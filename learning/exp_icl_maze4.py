"""Jev 迷宫第四轮（贪心对照，2026-09-27）：把提示的距离换成"直线距离"，看要绕路的起点会不会崩。

假设：Jev 每步挑"眼前看起来最好"的方向；眼前最好和真正最好一致时走得远，不一致时就栽。
第三轮已有：不给距离 98/120（绕 0/2/4+ 步：66/69、27/32、5/19），给按墙算的正确距离 120/120。
本轮只换距离这一个字段：给曼哈顿直线距离（|行差|+|列差|，不考虑墙和坑）。
预测：绕 0 步的起点接近满分（直线距离和真实一致）；要绕路的起点显著低于"不给距离"组（直线距离把它往墙边引）。

复用 exp_icl_maze3.py 的 12 张图、每图 10 个起点、步数上限 40、提问方式、state 其余字段，每起点 1 局，每格 120 局：
  nav_manh        无坑、只有墙；steps_to_goal_after_move 填直线距离（字段名与第三轮 nav_dist 完全相同，只换数值）
  nav_manh_named  同上，但字段改名为 straight_line_distance_to_goal_ignoring_walls（如实告诉它这是直线距离）：
                  区分"被错标的数误导"和"如实给的启发式也会把它往墙边引"
  wall_manh       两个坑画成墙（同第三轮 wall_*），字段同 nav_manh，填直线距离
绕路步数 = 按墙算的真实最短路 − 起点到终点的直线距离，分 0 / 2 / 4+ 三档（同第三轮）。

零请求基线（baseline 子命令）：把 Jev 换成纯程序"每步走所给距离最小的可走方向"，并列按方向优先顺序打破，
遍历四个方向的全部 24 种顺序；另一版并列时先挑来过次数少的（相当于也读 times_already_visited）。
同一套也跑在第三轮 nav_dist / wall_dist（正确距离）和第二轮 reason_dist（失败历史 + 只按墙算的距离、
坑看不见，12 图 × 5 局连打；程序不读历史，距离也不随踩坑更新，所以 5 局完全相同，2 次重复也相同）。

用法：python3 exp_icl_maze4.py run [冒烟局数] | report | baseline
日志 icl_maze4_log.json（被 .gitignore 排除），每局跑完即落盘，断点续跑。report 同时读第三轮日志做三组对比。
"""
# 让本脚本从任意目录都能找到仓库根部的 jevkit.py 和同目录的其他 exp_icl_*.py
import sys as _sys, pathlib as _pathlib
_sys.path[:0] = [str(_pathlib.Path(__file__).resolve().parent), str(_pathlib.Path(__file__).resolve().parent.parent)]
import json, os, statistics, sys, threading
from concurrent.futures import ThreadPoolExecutor

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from exp_icl_maze import DIRS, ACTS, Q, N, dist_map, make_map
from exp_icl_maze3 import SEED0, MAPS, STEP_LIMIT, OBJ_NAV, starts_for, by_map_ci

HERE = os.path.dirname(os.path.abspath(__file__))
LOG = os.path.join(HERE, 'icl_maze4_log.json')
LOG3 = os.path.join(HERE, 'icl_maze3_log.json')
LOCK = threading.Lock()
CONDS = ['nav_manh', 'nav_manh_named', 'wall_manh']
FIELD = {'nav_manh': 'steps_to_goal_after_move', 'wall_manh': 'steps_to_goal_after_move',
         'nav_manh_named': 'straight_line_distance_to_goal_ignoring_walls'}


def manh(a, b):
    return abs(a[0] - b[0]) + abs(a[1] - b[1])


def state(m, pos, visits, recent, cond):
    walls = set(m['walls'])
    if cond.startswith('wall'):
        walls |= set(m['traps'])
    goal = m['goal']
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
            info[FIELD[cond]] = manh(n, goal)
            info['times_already_visited'] = visits.get(n, 0)
        nb[a] = info
    return {'objective': OBJ_NAV, 'grid_size': [N, N], 'player': list(pos), 'goal': list(goal),
            'walls': [list(w) for w in sorted(walls)], 'neighbors': nb, 'recent_moves_this_episode': recent[-4:]}


def episode(mi, si, cond, log):
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
        r = jev.call(state(m, pos, visits, recent, cond), {'move': jev.choice(Q, ACTS)})
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


def load(path=LOG):
    return json.load(open(path)) if os.path.exists(path) else {}


def save(log):
    tmp = LOG + '.tmp'
    json.dump(log, open(tmp, 'w'), ensure_ascii=False)
    os.replace(tmp, LOG)


def bucket(k, v):
    g = make_map(SEED0 + int(k.split('|')[1]))['goal']
    det = v['opt'] - manh(v['start'], g)
    return '0' if det == 0 else ('2' if det == 2 else '4+')


def greedy_stats(k, v):
    """每一步：可走方向里直线距离最小的是哪些；Jev 是否选了其中之一；直线最小的方向是不是也是真实最短方向。"""
    m = make_map(SEED0 + int(k.split('|')[1]))
    cond = k.split('|')[3]
    walls = set(m['walls']) | (set(m['traps']) if cond.startswith('wall') else set())
    d = dist_map(walls, m['goal'])
    out = []
    for s in v['steps']:
        pos = tuple(s['pos'])
        legal = {}
        for a, (dr, dc) in DIRS.items():
            n = (pos[0] + dr, pos[1] + dc)
            if 0 <= n[0] < N and 0 <= n[1] < N and n not in walls:
                legal[a] = n
        if not legal:
            continue
        mh = min(manh(n, m['goal']) for n in legal.values())
        best_m = {a for a, n in legal.items() if manh(n, m['goal']) == mh}
        tr = min(d.get(n, 99) for n in legal.values())
        best_t = {a for a, n in legal.items() if d.get(n, 99) == tr}
        out.append((s['move'] in best_m, bool(best_m & best_t), s['move'] in best_t))
    return out


def table(log, conds, tag):
    for cond in conds:
        eps = {k: v for k, v in log.items() if k.startswith('NAV|') and k.endswith('|' + cond)}
        if not eps:
            continue
        per_map, agg = {}, {}
        for k, v in eps.items():
            mi = int(k.split('|')[1])
            a = per_map.setdefault(mi, [0, 0]); a[0] += v['result'] == 'win'; a[1] += 1
            b = agg.setdefault(bucket(k, v), [0, 0]); b[0] += v['result'] == 'win'; b[1] += 1
        wins = [v for v in eps.values() if v['result'] == 'win']
        extra = [len(v['steps']) - v['opt'] for v in wins]
        bumps = sum(s['to'] == s['pos'] for v in eps.values() for s in v['steps'])
        nsteps = sum(len(v['steps']) for v in eps.values())
        print('  %-15s[%s] 通关 %s | %s | 通关多走中位 %s | 撞墙步 %d/%d' % (
            cond, tag, by_map_ci(per_map), '  '.join('绕 %s 步：%d/%d' % (b, *agg[b]) for b in sorted(agg)),
            statistics.median(extra) if extra else '-', bumps, nsteps))


def report():
    log, log3 = load(), load(LOG3)
    steps_all = [s for v in log.values() for s in v['steps']]
    print('第四轮日志 %d 局，请求 %d 次，花费 $%.4f，模型 %s，api_error %d 局' % (
        len(log), len(steps_all), sum(s.get('cost', 0) for s in steps_all), {s.get('model') for s in steps_all},
        sum(v['result'] == 'api_error' for v in log.values())))
    print('\n无坑（绕路步数 = 真实最短路 − 直线距离）：')
    table(log3, ['nav_nodist', 'nav_dist'], '三')
    table(log, ['nav_manh', 'nav_manh_named'], '四')
    print('\n坑画成墙：')
    table(log3, ['wall_nodist', 'wall_dist'], '三')
    table(log, ['wall_manh'], '四')
    print('\n逐步贪心（第三轮组作参照：不给距离时它也常自己往直线最近的方向走）：选了直线距离最小方向的比例 | 直线最小方向与真实最短方向不重合的步里，它选直线最小的比例：')
    for cond in ['nav_nodist', 'wall_nodist', 'nav_dist', 'wall_dist'] + CONDS:
        src = log3 if cond in ('nav_nodist', 'wall_nodist', 'nav_dist', 'wall_dist') else log
        rows = [r for k, v in src.items() if k.startswith('NAV|') and k.endswith('|' + cond) for r in greedy_stats(k, v)]
        if not rows:
            continue
        conflict = [r for r in rows if not r[1]]
        print('  %-15s %d/%d=%.0f%% | 冲突步 %d，跟直线 %d、跟真实 %d' % (
            cond, sum(r[0] for r in rows), len(rows), 100 * sum(r[0] for r in rows) / len(rows),
            len(conflict), sum(r[0] for r in conflict), sum(r[2] for r in conflict)))
    print('\n同一起点配对：不给距离 vs 直线距离（p 为配对符号检验双侧）')
    for c4 in CONDS:
        c3 = 'wall_nodist' if c4.startswith('wall') else 'nav_nodist'
        for b, bs in (('0', {'0'}), ('2', {'2'}), ('4+', {'4+'}), ('2/4+', {'2', '4+'})):
            both = [(log3.get(k.replace(c4, c3)), v) for k, v in log.items() if k.endswith('|' + c4) and bucket(k, v) in bs]
            both = [(x, y) for x, y in both if x]
            w3 = sum(x['result'] == 'win' for x, _ in both); w4 = sum(y['result'] == 'win' for _, y in both)
            only3 = sum(x['result'] == 'win' and y['result'] != 'win' for x, y in both)
            only4 = sum(y['result'] == 'win' and x['result'] != 'win' for x, y in both)
            nd = only3 + only4
            pv = min(1.0, 2 * sum(__import__('math').comb(nd, i) for i in range(min(only3, only4) + 1)) / 2 ** nd) if nd else 1.0
            print('  %-15s 绕 %-4s 步：不给距离 %d/%d，直线 %d/%d；只有不给距离赢 %d，只有直线赢 %d，p=%.3g' % (c4, b, w3, len(both), w4, len(both), only3, only4, pv))


ORDERS = list(__import__('itertools').permutations(['up', 'down', 'left', 'right']))


def greedy_walk(m, start, walls, traps, distf, order, use_visits):
    """纯程序：每步在可走方向（界内且不是墙）里挑所给距离最小的；返回 win / trap / timeout。"""
    pos, visits = start, {start: 1}
    for _ in range(STEP_LIMIT):
        cands = []
        for a in order:
            n = (pos[0] + DIRS[a][0], pos[1] + DIRS[a][1])
            if 0 <= n[0] < N and 0 <= n[1] < N and n not in walls:
                d = distf(n)
                cands.append((99 if d is None else d, visits.get(n, 0) if use_visits else 0, order.index(a), n))
        pos = min(cands)[3]
        visits[pos] = visits.get(pos, 0) + 1
        if pos in traps:
            return 'trap'
        if pos == m['goal']:
            return 'win'
    return 'timeout'


def first_trap(m, walls, traps, d, order, use_visits):
    pos, visits = m['start'], {m['start']: 1}
    for _ in range(STEP_LIMIT):
        cands = []
        for a in order:
            n = (pos[0] + DIRS[a][0], pos[1] + DIRS[a][1])
            if 0 <= n[0] < N and 0 <= n[1] < N and n not in walls:
                x = d.get(n)
                cands.append((99 if x is None else x, visits.get(n, 0) if use_visits else 0, order.index(a), n))
        pos = min(cands)[3]
        visits[pos] = visits.get(pos, 0) + 1
        if pos in traps:
            return pos


def baseline():
    print('零请求纯程序基线：每步走所给距离最小的方向；并列按方向顺序打破，24 种顺序全遍历（汇总 = 24 × 局数）')
    log3 = load(LOG3)
    for use_visits in (False, True):
        print('\n并列规则：%s' % ('先挑来过次数少的，再按方向顺序' if use_visits else '只按方向顺序'))
        for cond in ('nav_manh', 'nav_dist', 'wall_manh', 'wall_dist'):
            agg, per_order = {}, []
            for order in ORDERS:
                w = 0
                for mi in range(MAPS):
                    m = make_map(SEED0 + mi)
                    walls = set(m['walls']) | (set(m['traps']) if cond.startswith('wall') else set())
                    d = dist_map(walls, m['goal'])
                    distf = (lambda n, g=m['goal']: manh(n, g)) if cond.endswith('manh') else (lambda n, d=d: d.get(n))
                    for start in starts_for(mi):
                        r = greedy_walk(m, start, walls, set(), distf, order, use_visits)
                        det = d[start] - manh(start, m['goal'])
                        b = agg.setdefault('0' if det == 0 else ('2' if det == 2 else '4+'), [0, 0])
                        b[0] += r == 'win'; b[1] += 1; w += r == 'win'
                per_order.append(w)
            print('  %-10s 通关 %d/%d（单一顺序 %d–%d/120）| %s' % (
                cond, sum(per_order), 120 * len(ORDERS), min(per_order), max(per_order),
                '  '.join('绕 %s 步：%d/%d' % (b, *agg[b]) for b in sorted(agg))))
        # 第二轮 reason_dist：坑看不见、距离只按墙算、程序不读历史 -> 5 局相同
        res, per_order = {}, []
        for order in ORDERS:
            w = 0
            for mi in range(MAPS):
                m = make_map(SEED0 + mi)
                d = dist_map(set(m['walls']), m['goal'])
                r = greedy_walk(m, m['start'], set(m['walls']), set(m['traps']), lambda n, d=d: d.get(n), order, use_visits)
                res[r] = res.get(r, 0) + 1; w += r == 'win'
            per_order.append(w)
        # 第三轮 reason_plan：已知坑当墙算距离（踩坑后程序更新 known），程序不读历史
        curve, po2 = [0] * 5, []
        for order in ORDERS:
            w = 0
            for mi in range(MAPS):
                m = make_map(SEED0 + mi)
                known = []
                for e in range(5):
                    d = dist_map(set(m['walls']), m['goal'], known)
                    pos = m['start']; r = greedy_walk(m, pos, set(m['walls']), set(m['traps']), lambda n, d=d: d.get(n), order, use_visits)
                    if r == 'trap':
                        # 找出踩到的那个坑：重走一遍记录终点
                        known.append(first_trap(m, set(m['walls']), set(m['traps']), d, order, use_visits))
                    curve[e] += r == 'win'; w += r == 'win'
            po2.append(w)
        print('  第三轮 reason_plan（已知坑当墙算距离，每图 1 串 5 局，每顺序 ×2 次 = 120 局）：第 1–5 局通关（24 顺序 × 12 图）%s | 单一顺序 %d–%d/120' % (
            curve, 2 * min(po2), 2 * max(po2)))
        print('  第二轮 reason_dist（12 图 × 2 次 × 5 局 = 120 局/顺序；5 局相同）：每顺序通关 %s/120（单一顺序 %d–%d）| 结局分布 %s' % (
            '、'.join(sorted({str(10 * x) for x in per_order})), 10 * min(per_order), 10 * max(per_order), res))


def main():
    if len(sys.argv) > 1 and sys.argv[1] == 'baseline':
        baseline(); return
    if len(sys.argv) < 2 or sys.argv[1] not in ('run', 'report'):
        print(__doc__); return
    if sys.argv[1] == 'run':
        import jevkit as jev
        log = load()
        jobs = [(mi, si, c) for c in CONDS for mi in range(MAPS) for si in range(len(starts_for(mi)))]
        if len(sys.argv) > 2:  # 冒烟：每个条件只跑前 n 局
            n = int(sys.argv[2])
            jobs = [j for c in CONDS for j in [x for x in jobs if x[2] == c][:n]]
        with ThreadPoolExecutor(max_workers=12) as ex:
            list(ex.map(lambda j: episode(*j, log), jobs))
        print(jev.spend())
    report()


if __name__ == '__main__':
    main()
