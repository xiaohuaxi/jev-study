"""Jev 跨局学习续测：把"距离提示"单独摘出来，看它对躲陷阱这件事到底帮了多少。

exp_icl_maze.py 里 reason 写法本身就带一个"距离提示"字段 steps_to_goal_after_move（每个能走的
方向离终点还有几步），这个距离只按墙算、完全不管已知陷阱，个别时候甚至会把 Jev 指向陷阱方向——
分不清"从失败历史里学会躲陷阱"和"跟着距离提示抄近路"到底谁的功劳更大。这一版把距离字段单独做
成开关，另外试一种"重算距离但不点破陷阱位置"的折中写法（reason_redist）。

六个条件（局内信息除下面这个距离字段外完全一样；有历史的都用 reason 写法——只把上一局怎么结束的
原样写一句，不做任何归纳，跨局记忆见 exp_icl_maze.py 的 docstring）：
  none_dist         无跨局历史 + 原距离提示（忽略已知陷阱，等价旧实验的 none）
  none_nodist       无跨局历史 + 不给距离提示（其余字段照旧：to、cell 类型、times_already_visited、
                     goal 坐标、墙列表都还在）
  reason_dist       失败历史 + 原距离提示（等价旧实验的 reason，只是步数上限从 24 提到 40）
  reason_dist_note  同 reason_dist，但 state 里多一句大白话提醒："steps_to_goal_after_move 按墙
                     计算，没有考虑陷阱，可能穿过已知陷阱"——距离数字不变，只是附一句说明
  reason_nodist     失败历史 + 不给距离提示
  reason_redist     失败历史 + 重算距离：每个邻格 n 的距离 = 从 n 出发、避开"除 n 自身以外的已知
                     陷阱"的最短路。这样陷阱格本身不会显示"到不了"（仍要靠记忆去躲，不能靠距离
                     数字反推出陷阱在哪），但路过其它已知陷阱的路线会被绕开，不再把 Jev 往坑边引。
                     邻格类型（cell）在六个条件里都不标 trap，是否躲全靠历史文字里记的坐标。

跨局历史里的用词严格对齐设计口径："第 k 局：走到 (r,c) 踩到隐藏陷阱，失败" / "第 k 局：走了 40
步还没到终点，超时"（成功局照旧记"走到终点，本局成功"，同一份 reason 历史三种结果都会出现，
不是只挑失败句子）。

地图复用 exp_icl_maze.py 的 make_map（同一套 BFS 造图逻辑，"陷阱卡在最短路上"的构造方式不变），
但种子换成 100–111（12 张），故意跟旧实验的 0–7 错开——避免眼熟的地图让人下意识拿这次和上次的
结果直接比对（步数上限、条件定义都变了，本就不适合逐图对比）。每张图重复 2 次，每次独立"连打
5 局"（known 已知陷阱清空重来）；步数上限从旧实验的 24 提到 40——地图是 6×6，安全最短路一般
10 步出头，40 步给"绕远路但还在摸索"留够余量，尽量别把"没学会躲陷阱"和"步数太紧被判超时"这两种
失败混在一起统计。

用法：python3 exp_icl_maze2.py run | report
结果写同目录 icl_maze2_log.json（已被 .gitignore 的 *_log.json 排除）；断点续跑以"轮"（一张图
一次的 5 局连打）为单位，跳过已成功的轮、失败的整轮重发；每轮跑完立即落盘，防中途崩溃全丢。
每一步都把 jev 的完整回包存进日志（含 usage.cost），report 只读日志汇总请求数与花费，不依赖
本次进程的实时统计。
"""
# 让本脚本从任意目录都能找到仓库根部的 jevkit.py 和同目录的其他 exp_icl_*.py
import sys as _sys, pathlib as _pathlib
_sys.path[:0] = [str(_pathlib.Path(__file__).resolve().parent), str(_pathlib.Path(__file__).resolve().parent.parent)]
import json, math, os, statistics, sys, threading
from concurrent.futures import ThreadPoolExecutor

from exp_icl_maze import DIRS, ACTS, OBJ, Q, N, dist_map, make_map, fmt_p

HERE = os.path.dirname(os.path.abspath(__file__))
LOG = os.path.join(HERE, 'icl_maze2_log.json')
LOCK = threading.Lock()

SEED0 = 100  # 地图种子 100..111（12 张），跟旧实验的 0..7 错开
MAPS, REPS, EPISODES, STEP_LIMIT = 12, 2, 5, 40
CONDS = ['none_dist', 'none_nodist', 'reason_dist', 'reason_dist_note', 'reason_nodist', 'reason_redist']
DIST_NOTE = 'steps_to_goal_after_move 按墙计算，没有考虑陷阱，可能穿过已知陷阱'


def build_state(m, pos, visits, recent, cond, known, past):
    """局内 state：邻格类型六个条件里都不标 trap；距离字段按 cond 三选一（原距离/无/重算）。"""
    walls = set(m['walls'])
    goal = m['goal']
    d_plain = dist_map(walls, goal)  # 忽略已知陷阱，六个条件公用的"原距离"
    give_dist = not cond.endswith('nodist')
    redist = cond == 'reason_redist'
    nb = {}
    for a, (dr, dc) in DIRS.items():
        n = (pos[0] + dr, pos[1] + dc)
        info = {'to': list(n)}
        if not (0 <= n[0] < N and 0 <= n[1] < N):
            info['cell'] = 'out_of_bounds'
        elif n in walls:
            info['cell'] = 'wall'
        elif n == goal:
            info['cell'] = 'goal'
        else:
            info['cell'] = 'clear'  # 已知陷阱格也是 clear，六个条件都不点破
        if info['cell'] in ('clear', 'goal'):
            if give_dist:
                if redist and known:
                    block = set(known) - {n}  # 避开除 n 自身以外的已知陷阱
                    info['steps_to_goal_after_move'] = dist_map(walls, goal, block).get(n, 'unreachable')
                else:
                    info['steps_to_goal_after_move'] = d_plain.get(n, 'unreachable')
            info['times_already_visited'] = visits.get(n, 0)
        nb[a] = info
    st = {'objective': OBJ, 'grid_size': [N, N], 'player': list(pos), 'goal': list(goal),
          'walls': [list(w) for w in m['walls']], 'neighbors': nb, 'recent_moves_this_episode': recent[-4:]}
    if cond == 'reason_dist_note':
        st['steps_to_goal_note'] = DIST_NOTE
    if cond.startswith('reason') and past:
        st['previous_episodes'] = '\n'.join('第 %d 局：%s' % (k + 1, ep['why']) for k, ep in enumerate(past))
    return st


def play_episode(m, cond, past, known):
    import jevkit as jev
    pos, visits, recent, steps = m['start'], {m['start']: 1}, [], []
    traps, walls = set(m['traps']), set(m['walls'])
    for _ in range(STEP_LIMIT):
        st = build_state(m, pos, visits, recent, cond, known, past)
        r = jev.call(st, {'move': jev.choice(Q, ACTS)})
        if '_error' in r:
            return {'result': 'api_error', 'steps': steps, 'why': 'api', 'err': r['_error']}
        a = r['answers']['move']
        mv = a['choice']
        n = (pos[0] + DIRS[mv][0], pos[1] + DIRS[mv][1])
        rec = {'pos': pos, 'move': mv, 'p': a['probabilities'], 'resp': r}
        if not (0 <= n[0] < N and 0 <= n[1] < N) or n in walls:
            rec['to'] = pos; steps.append(rec); recent.append(mv + '(撞墙,未移动)'); continue
        rec['to'] = n; steps.append(rec)
        pos = n; recent.append(mv); visits[pos] = visits.get(pos, 0) + 1
        if pos in traps:
            return {'result': 'trap', 'trap': pos, 'known_before': pos in known, 'steps': steps,
                    'why': '走到 %s 踩到隐藏陷阱，失败' % fmt_p(pos)}
        if pos == m['goal']:
            return {'result': 'win', 'steps': steps, 'why': '走到终点，本局成功'}
    return {'result': 'timeout', 'steps': steps, 'why': '走了 %d 步还没到终点，超时' % STEP_LIMIT}


def load():
    return json.load(open(LOG)) if os.path.exists(LOG) else {}


def save(log):
    tmp = LOG + '.tmp'
    json.dump(log, open(tmp, 'w'), ensure_ascii=False)
    os.replace(tmp, LOG)


def run_series(mi, rep, cond, log):
    """跑一"轮"：一张图一次的 5 局连打。跳过已成功的轮，失败（含 api_error）的整轮重发。"""
    key = '%d|%d|%s' % (mi, rep, cond)
    if key in log and all(e['result'] != 'api_error' for e in log[key]):
        return
    m = make_map(SEED0 + mi)
    past, known, eps = [], [], []
    for e in range(EPISODES):
        ep = play_episode(m, cond, past, known)
        eps.append(ep)
        if ep['result'] == 'api_error':
            break
        past.append(ep)
        if ep['result'] == 'trap' and ep['trap'] not in known:
            known.append(ep['trap'])
    with LOCK:
        log[key] = json.loads(json.dumps(eps))  # tuple -> list for json
        save(log)  # 每轮跑完立即落盘


# ---------------- 报告 ----------------
def wilson(k, n, z=1.96):
    if n == 0:
        return None
    p = k / n
    denom = 1 + z * z / n
    center = p + z * z / (2 * n)
    margin = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return max(0.0, (center - margin) / denom), min(1.0, (center + margin) / denom)


def pct_ci(k, n):
    if n == 0:
        return 'n=0'
    lo, hi = wilson(k, n)
    return '%d/%d=%.0f%%[%.0f-%.0f]' % (k, n, 100 * k / n, 100 * lo, 100 * hi)


def pct_map(per_map):
    """per_map：{图号: (k, n)}。总比例照常算；区间按图聚类（同一张图的两次连打、同一轮的前后局互相牵连，
    不能当独立试验算 Wilson，否则偏窄）：比率估计 p=Σk/Σn，se=√(m/(m-1)·Σ(k_i-p·n_i)²)/Σn，±1.96se。"""
    items = [(k, n) for k, n in per_map.values() if n]
    K = sum(k for k, _ in items)
    Nn = sum(n for _, n in items)
    if Nn == 0:
        return 'n=0'
    p = K / Nn
    m = len(items)
    if m < 2:
        return '%d/%d=%.0f%%' % (K, Nn, 100 * p)
    se = math.sqrt(m / (m - 1) * sum((k - p * n) ** 2 for k, n in items)) / Nn
    return '%d/%d=%.0f%%[按图%.0f-%.0f]' % (K, Nn, 100 * p, 100 * max(0.0, p - 1.96 * se), 100 * min(1.0, p + 1.96 * se))


def add(acc, mi, k, n=1):
    a = acc.setdefault(mi, [0, 0])
    a[0] += k; a[1] += n


def report():
    log = load()
    maps = {mi: make_map(SEED0 + mi) for mi in range(MAPS)}
    print('地图（种子 %d-%d，12 张；安全最短路(避两陷阱)=opt / 无视陷阱最短路=naive）：' % (SEED0, SEED0 + MAPS - 1))
    for mi in range(MAPS):
        mm = maps[mi]
        print('  #%d(seed=%d) opt=%d naive=%d' % (mi, SEED0 + mi, mm['opt'], mm['naive']))

    calls = sum(len(e['steps']) for v in log.values() for e in v)
    cost = sum(s.get('resp', {}).get('usage', {}).get('cost', 0.0) for v in log.values() for e in v for s in e.get('steps', []))
    n_err = sum(e['result'] == 'api_error' for v in log.values() for e in v)
    print('\n日志 %d/%d 轮，请求 %d 次，花费 $%.4f；api_error 局 %d' % (
        len(log), MAPS * REPS * len(CONDS), calls, cost, n_err))

    print('\n成功局数（每格 %d 轮 = %d 图 x %d 次）；第 k 列 = 第 k 局（k/n）' % (MAPS * REPS, MAPS, REPS))
    print('%-18s %s | %-16s %-16s %-14s %s' % (
        '条件', '  '.join('局%d' % (k + 1) for k in range(EPISODES)),
        '合计成功', '第2局起重踩已知陷阱', '超时', '成功局均步数'))
    for cond in CONDS:
        series = [v for k, v in log.items() if k.endswith('|' + cond)]
        cols = []
        for k in range(EPISODES):
            eps = [s[k] for s in series if len(s) > k]
            cols.append('%2d/%-2d' % (sum(e['result'] == 'win' for e in eps), len(eps)))
        win_m, rep_m, to_m = {}, {}, {}
        for k, s in log.items():
            if not k.endswith('|' + cond):
                continue
            mi = int(k.split('|')[0])
            for i, e in enumerate(s):
                add(win_m, mi, e['result'] == 'win')
                add(to_m, mi, e['result'] == 'timeout')
                if i >= 1:
                    add(rep_m, mi, e['result'] == 'trap' and e['known_before'])
        all_eps = [e for s in series for e in s]
        wins_steps = [len(e['steps']) for e in all_eps if e['result'] == 'win']
        print('%-18s %s | %-16s %-16s %-14s %.1f' % (
            cond, '  '.join(cols), pct_map(win_m), pct_map(rep_m), pct_map(to_m),
            statistics.mean(wins_steps) if wins_steps else 0))

    print('\n第 1 局单独统计（此时 known 必空，条件间差异只来自距离字段本身，不含历史影响）：')
    for cond in CONDS:
        eps1 = [v[0] for k, v in log.items() if k.endswith('|' + cond) and len(v) > 0]
        trap_n = sum(e['result'] == 'trap' for e in eps1)
        win_n = sum(e['result'] == 'win' for e in eps1)
        to_n = sum(e['result'] == 'timeout' for e in eps1)
        print('  %-18s 踩坑 %-14s 通关 %-14s 超时 %s（Wilson，每图 2 局，只作参考）' % (
            cond, pct_ci(trap_n, len(eps1)), pct_ci(win_n, len(eps1)), pct_ci(to_n, len(eps1))))

    print('\n已知陷阱在隔壁：按局计"第一次遇到时是否避开" | 按步计"走进去的比例"（均从 known 非空起算）')
    for cond in CONDS:
        step_m, ep_m = {}, {}
        for k, series in log.items():
            if not k.endswith('|' + cond):
                continue
            mi = int(k.split('|')[0])
            known = []
            for ep in series:
                if known:
                    first = None
                    for s in ep['steps']:
                        pos = tuple(s['pos'])
                        adj_dirs = [a for a, (dr, dc) in DIRS.items() if (pos[0] + dr, pos[1] + dc) in known]
                        if adj_dirs:
                            first = (s, adj_dirs); break
                    if first:
                        s, adj_dirs = first
                        add(ep_m, mi, s['move'] not in adj_dirs)
                for s in ep['steps']:
                    pos = tuple(s['pos'])
                    for a, (dr, dc) in DIRS.items():
                        if (pos[0] + dr, pos[1] + dc) in known:
                            add(step_m, mi, s['move'] == a)
                if ep['result'] == 'trap' and tuple(ep['trap']) not in known:
                    known.append(tuple(ep['trap']))
        print('  %-18s 首次隔壁即避开 %-16s 逐步走进去(步数口径) %s' % (
            cond, pct_map(ep_m), pct_map(step_m)))

    print('\n已知陷阱在隔壁时，陷阱方向显示的距离是不是各方向里最小（只看给距离的有历史组；按"机会"=每步×每个相邻已知陷阱计）')
    for cond in ('reason_dist', 'reason_dist_note', 'reason_redist'):
        opp = at_min = strict = rep = rep_min = 0
        for k, series in log.items():
            if not k.endswith('|' + cond):
                continue
            m = make_map(SEED0 + int(k.split('|')[0]))
            known = []
            for ep in series:
                for s in ep['steps']:
                    pos = tuple(s['pos'])
                    nb = build_state(m, pos, {}, [], cond, known, [])['neighbors']
                    d = {a: v['steps_to_goal_after_move'] for a, v in nb.items()
                         if isinstance(v.get('steps_to_goal_after_move'), int)}
                    tdirs = [a for a, (dr, dc) in DIRS.items() if (pos[0] + dr, pos[1] + dc) in known]
                    if not tdirs or not d:
                        continue
                    lo = min(d.values())
                    for a in tdirs:
                        opp += 1
                        at_min += d[a] == lo
                        strict += d[a] == lo and list(d.values()).count(lo) == 1
                    if s['move'] in tdirs:
                        rep += 1; rep_min += d[s['move']] == lo
                if ep['result'] == 'trap' and tuple(ep['trap']) not in known:
                    known.append(tuple(ep['trap']))
        print('  %-18s 机会 %d：陷阱方向距离=最小 %d，严格最小 %d | 走进已知陷阱的步 %d，其中陷阱方向是最小距离 %d' % (
            cond, opp, at_min, strict, rep, rep_min))

    print('\n超时局到过几个不同格子（中位；"落点"只数移动目的地，"含起点"再加上出发格）')
    for cond in CONDS:
        tos = [e for k, v in log.items() if k.endswith('|' + cond) for e in v if e['result'] == 'timeout']
        if not tos:
            continue
        dest = [len({tuple(s['to']) for s in e['steps'] if tuple(s['to']) != tuple(s['pos'])}) for e in tos]
        withstart = [len({tuple(s['to']) for s in e['steps']} | {tuple(e['steps'][0]['pos'])}) for e in tos]
        print('  %-18s 超时 %d 局：落点中位 %s，含起点中位 %s' % (
            cond, len(tos), statistics.median(dest), statistics.median(withstart)))


def main():
    if len(sys.argv) < 2 or sys.argv[1] not in ('run', 'report'):
        print(__doc__); return
    if sys.argv[1] == 'run':
        import jevkit as jev
        log = load()
        jobs = [(mi, rep, c) for mi in range(MAPS) for rep in range(REPS) for c in CONDS]
        with ThreadPoolExecutor(max_workers=8) as ex:
            list(ex.map(lambda j: run_series(j[0], j[1], j[2], log), jobs))
        print(jev.spend())
    report()


if __name__ == '__main__':
    main()
