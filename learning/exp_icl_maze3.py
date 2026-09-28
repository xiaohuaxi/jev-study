"""Jev 迷宫第三轮（补漏对照，2026-09-26）：不给距离时通关起不来，是"找不出绕路"还是"没距离就不会导航"？
再补一组"程序把已知陷阱当墙算距离"的干净对照。

背景见 exp_icl_maze2.py：同一批 12 张图（种子 100–111），失败历史 + 不给距离 4/120，重算距离 38/120；
但 maze2 的"重算距离"故意让陷阱格自己仍显示到终点的真实步数（往往最小），不是干净的规划对照；
也没测过没有陷阱时，只靠坐标和墙能不能走到终点。

单局导航（每张图 10 个起点：原起点 + 9 个随机空格，离终点按墙算 ≥6 步；5 个条件共用同一批起点，每起点 1 局，
每格 120 局；Jev 回包基本确定，同一 state 重复跑几乎同一条路，所以用多起点而不是重复跑）：
  nav_nodist        去掉陷阱，只有墙；不给距离（其余字段同 maze2：邻格类型、来过几次、终点坐标、墙列表、最近 4 步）；
                    objective 只写"走到终点 goal"
  nav_nodist_obj    同上，但 objective 沿用 maze2 原文（说有看不见的陷阱、会连玩几局），地图里其实没有陷阱：
                    看"提防陷阱"这句话本身会不会让它更爱打转
  nav_dist          去掉陷阱，给按墙算的正确距离（对照：跟着距离走的上限）
  wall_nodist       两个陷阱改成看得见的墙（写进墙列表、邻格显示 wall），不给距离：障碍全知道，只差自己找绕路
  wall_dist         同上，给正确距离（把陷阱当墙算）
多局（同 maze2：12 图 × 2 次 × 连打 5 局，失败历史写法，步数上限 40，陷阱看不见）：
  reason_plan       失败历史 + 程序按已知陷阱重算距离，且已知陷阱格自己也显示 unreachable（邻格类型仍写 clear，不标 trap）
                    ——即"程序把已知坑当墙算路"的干净版；与 maze2 reason_redist（陷阱格显示真实步数）对照

用法：python3 exp_icl_maze3.py run | report
日志 icl_maze3_log.json（被 .gitignore 排除），每局 / 每轮跑完即落盘，断点续跑。
"""
# 让本脚本从任意目录都能找到仓库根部的 jevkit.py 和同目录的其他 exp_icl_*.py
import sys as _sys, pathlib as _pathlib
_sys.path[:0] = [str(_pathlib.Path(__file__).resolve().parent), str(_pathlib.Path(__file__).resolve().parent.parent)]
import json, os, random, statistics, sys, threading
from concurrent.futures import ThreadPoolExecutor

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from exp_icl_maze import DIRS, ACTS, OBJ, Q, N, dist_map, make_map, fmt_p

HERE = os.path.dirname(os.path.abspath(__file__))
LOG = os.path.join(HERE, 'icl_maze3_log.json')
LOCK = threading.Lock()

SEED0, MAPS, STARTS, STEP_LIMIT = 100, 12, 10, 40
REPS, EPISODES = 2, 5
NAV_CONDS = ['nav_nodist', 'nav_nodist_obj', 'nav_dist', 'wall_nodist', 'wall_dist']
OBJ_NAV = '走到终点 goal。'


def starts_for(mi):
    m = make_map(SEED0 + mi)
    blocked = set(m['walls']) | set(m['traps'])
    d = dist_map(blocked, m['goal'])
    cand = sorted(c for c, v in d.items() if v >= 6 and c != m['start'] and c not in blocked)
    rng = random.Random('maze3starts|%d' % mi)
    rng.shuffle(cand)
    return [m['start']] + cand[:STARTS - 1]


def nav_state(m, pos, visits, recent, cond):
    walls = set(m['walls'])
    if cond.startswith('wall'):
        walls |= set(m['traps'])
    goal = m['goal']
    d = dist_map(walls, goal)
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
            info['cell'] = 'clear'
        if info['cell'] in ('clear', 'goal'):
            if cond.endswith('_dist'):
                info['steps_to_goal_after_move'] = d.get(n, 'unreachable')
            info['times_already_visited'] = visits.get(n, 0)
        nb[a] = info
    obj = OBJ if cond == 'nav_nodist_obj' else OBJ_NAV
    return {'objective': obj, 'grid_size': [N, N], 'player': list(pos), 'goal': list(goal),
            'walls': [list(w) for w in sorted(walls)], 'neighbors': nb, 'recent_moves_this_episode': recent[-4:]}


def nav_episode(mi, si, cond, log):
    import jevkit as jev
    key = 'NAV|%d|%d|%s' % (mi, si, cond)
    if key in log and log[key]['result'] != 'api_error':
        return
    m = make_map(SEED0 + mi)
    start = starts_for(mi)[si]
    walls = set(m['walls']) | (set(m['traps']) if cond.startswith('wall') else set())
    pos, visits, recent, steps = start, {start: 1}, [], []
    result = 'timeout'
    for _ in range(STEP_LIMIT):
        r = jev.call(nav_state(m, pos, visits, recent, cond), {'move': jev.choice(Q, ACTS)})
        if '_error' in r:
            result = 'api_error'; break
        a = r['answers']['move']
        mv = a['choice']
        n = (pos[0] + DIRS[mv][0], pos[1] + DIRS[mv][1])
        rec = {'pos': list(pos), 'move': mv, 'p': a['probabilities'], 'cost': r.get('usage', {}).get('cost', 0.0), 'model': r.get('model')}
        if not (0 <= n[0] < N and 0 <= n[1] < N) or n in walls:
            rec['to'] = list(pos); steps.append(rec); recent.append(mv + '(撞墙,未移动)'); continue
        rec['to'] = list(n); steps.append(rec)
        pos = n; recent.append(mv); visits[pos] = visits.get(pos, 0) + 1
        if pos == m['goal']:
            result = 'win'; break
    opt = dist_map(walls, m['goal']).get(start)
    with LOCK:
        log[key] = {'result': result, 'start': list(start), 'opt': opt, 'steps': steps}
        save(log)


def plan_state(m, pos, visits, recent, known, past):
    walls = set(m['walls'])
    goal = m['goal']
    d = dist_map(walls, goal, known)  # 已知陷阱一律当墙：陷阱格自己不在表里 -> unreachable
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
            info['cell'] = 'clear'
        if info['cell'] in ('clear', 'goal'):
            info['steps_to_goal_after_move'] = d.get(n, 'unreachable')
            info['times_already_visited'] = visits.get(n, 0)
        nb[a] = info
    st = {'objective': OBJ, 'grid_size': [N, N], 'player': list(pos), 'goal': list(goal),
          'walls': [list(w) for w in m['walls']], 'neighbors': nb, 'recent_moves_this_episode': recent[-4:]}
    if past:
        st['previous_episodes'] = '\n'.join('第 %d 局：%s' % (k + 1, ep['why']) for k, ep in enumerate(past))
    return st


def plan_series(mi, rep, log):
    import jevkit as jev
    key = 'PLAN|%d|%d' % (mi, rep)
    if key in log and all(e['result'] != 'api_error' for e in log[key]):
        return
    m = make_map(SEED0 + mi)
    traps, walls = set(m['traps']), set(m['walls'])
    past, known, eps = [], [], []
    for _ in range(EPISODES):
        pos, visits, recent, steps = m['start'], {m['start']: 1}, [], []
        ep = None
        for _ in range(STEP_LIMIT):
            r = jev.call(plan_state(m, pos, visits, recent, known, past), {'move': jev.choice(Q, ACTS)})
            if '_error' in r:
                ep = {'result': 'api_error', 'steps': steps, 'why': 'api'}; break
            a = r['answers']['move']
            mv = a['choice']
            n = (pos[0] + DIRS[mv][0], pos[1] + DIRS[mv][1])
            rec = {'pos': list(pos), 'move': mv, 'p': a['probabilities'], 'cost': r.get('usage', {}).get('cost', 0.0), 'model': r.get('model')}
            if not (0 <= n[0] < N and 0 <= n[1] < N) or n in walls:
                rec['to'] = list(pos); steps.append(rec); recent.append(mv + '(撞墙,未移动)'); continue
            rec['to'] = list(n); steps.append(rec)
            pos = n; recent.append(mv); visits[pos] = visits.get(pos, 0) + 1
            if pos in traps:
                ep = {'result': 'trap', 'trap': list(pos), 'known_before': pos in known, 'steps': steps,
                      'why': '走到 %s 踩到隐藏陷阱，失败' % fmt_p(pos)}; break
            if pos == m['goal']:
                ep = {'result': 'win', 'steps': steps, 'why': '走到终点，本局成功'}; break
        if ep is None:
            ep = {'result': 'timeout', 'steps': steps, 'why': '走了 %d 步还没到终点，超时' % STEP_LIMIT}
        eps.append(ep)
        if ep['result'] == 'api_error':
            break
        past.append(ep)
        if ep['result'] == 'trap' and tuple(ep['trap']) not in known:
            known.append(tuple(ep['trap']))
    with LOCK:
        log[key] = eps
        save(log)


def load():
    return json.load(open(LOG)) if os.path.exists(LOG) else {}


def save(log):
    tmp = LOG + '.tmp'
    json.dump(log, open(tmp, 'w'), ensure_ascii=False)
    os.replace(tmp, LOG)


def by_map_ci(per_map):
    import math
    items = [(k, n) for k, n in per_map.values() if n]
    K = sum(k for k, _ in items); Nn = sum(n for _, n in items)
    p = K / Nn
    m = len(items)
    if m < 2:
        return '%d/%d=%.0f%%' % (K, Nn, 100 * p)
    se =math.sqrt(m / (m - 1) * sum((k - p * n) ** 2 for k, n in items)) / Nn
    return '%d/%d=%.0f%%[按图 %.0f-%.0f]' % (K, Nn, 100 * p, 100 * max(0, p - 1.96 * se), 100 * min(1, p + 1.96 * se))


def report():
    log = load()
    steps_all = [s for k, v in log.items() for e in ([v] if k.startswith('NAV') else v) for s in e['steps']]
    print('日志 %d 条，请求 %d 次，花费 $%.4f，模型 %s' % (
        len(log), len(steps_all), sum(s.get('cost', 0) for s in steps_all), {s.get('model') for s in steps_all}))
    print('\n单局导航（12 图 × 10 起点，步数上限 %d）：' % STEP_LIMIT)
    for cond in NAV_CONDS:
        eps = {k: v for k, v in log.items() if k.startswith('NAV|') and k.endswith('|' + cond)}
        if not eps:
            continue
        per_map = {}
        for k, v in eps.items():
            mi = int(k.split('|')[1])
            a = per_map.setdefault(mi, [0, 0]); a[0] += v['result'] == 'win'; a[1] += 1
        orig = [v for k, v in eps.items() if k.split('|')[2] == '0']
        wins = [v for v in eps.values() if v['result'] == 'win']
        extra = [len(v['steps']) - v['opt'] for v in wins]
        tos = [v for v in eps.values() if v['result'] == 'timeout']
        cells = [len({tuple(s['to']) for s in v['steps']} | {tuple(v['start'])}) for v in tos]
        bumps = sum(s['to'] == s['pos'] for v in eps.values() for s in v['steps'])
        nsteps = sum(len(v['steps']) for v in eps.values())
        print('  %-15s 通关 %s | 原起点 %d/%d | 通关局多走步数中位 %s | 超时 %d 局、到过格子中位（含起点）%s | 撞墙步 %d/%d' % (
            cond, by_map_ci(per_map), sum(v['result'] == 'win' for v in orig), len(orig),
            statistics.median(extra) if extra else '-', len(tos), statistics.median(cells) if cells else '-', bumps, nsteps))
    print('\n按"必须多绕几步"分组（绕路步数 = 真实最短路 − 起点到终点的横竖格数；0 表示可以一路朝终点走）：')
    for cond in NAV_CONDS:
        agg = {}
        for k, v in log.items():
            if not (k.startswith('NAV|') and k.endswith('|' + cond)):
                continue
            g = make_map(SEED0 + int(k.split('|')[1]))['goal']
            s = v['start']
            det = v['opt'] - (abs(s[0] - g[0]) + abs(s[1] - g[1]))
            b = agg.setdefault('0' if det == 0 else ('2' if det == 2 else '4+'), [0, 0])
            b[0] += v['result'] == 'win'; b[1] += 1
        if agg:
            print('  %-15s %s' % (cond, '  '.join('绕 %s 步：%d/%d' % (b, *agg[b]) for b in sorted(agg))))
    series = {k: v for k, v in log.items() if k.startswith('PLAN|')}
    if series:
        print('\n多局 reason_plan（12 图 × 2 次 × 5 局，失败历史 + 已知陷阱当墙算距离）：')
        cols = []
        for e in range(EPISODES):
            xs = [s[e] for s in series.values() if len(s) > e]
            cols.append('%d/%d' % (sum(x['result'] == 'win' for x in xs), len(xs)))
        per_map, rep_m = {}, {}
        to = 0
        for k, s in series.items():
            mi = int(k.split('|')[1])
            for i, e in enumerate(s):
                a = per_map.setdefault(mi, [0, 0]); a[0] += e['result'] == 'win'; a[1] += 1
                to += e['result'] == 'timeout'
                if i >= 1:
                    b = rep_m.setdefault(mi, [0, 0]); b[0] += e['result'] == 'trap' and e['known_before']; b[1] += 1
        print('  第 1–5 局通关 %s | 合计 %s | 第 2 局起重踩已知陷阱 %s | 超时 %d' % (
            ', '.join(cols), by_map_ci(per_map), by_map_ci(rep_m), to))


def main():
    if len(sys.argv) < 2 or sys.argv[1] not in ('run', 'report'):
        print(__doc__); return
    if sys.argv[1] == 'run':
        import jevkit as jev
        log = load()
        jobs = [('plan', mi, rep) for mi in range(MAPS) for rep in range(REPS)]
        jobs += [('nav', mi, si, c) for c in NAV_CONDS for mi in range(MAPS) for si in range(len(starts_for(mi)))]
        with ThreadPoolExecutor(max_workers=12) as ex:
            list(ex.map(lambda j: plan_series(j[1], j[2], log) if j[0] == 'plan' else nav_episode(j[1], j[2], j[3], log), jobs))
        print(jev.spend())
    report()


if __name__ == '__main__':
    main()
