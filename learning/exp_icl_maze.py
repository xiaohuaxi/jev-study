"""Jev 跨局学习：带隐藏陷阱的迷宫，多局连打，上一局的失败写进下一局 state，看成功率升不升。

地图 6×6，墙可见；两个陷阱看不见（state 里显示成空地），踩到本局失败。陷阱按"卡在最短路上"放：
去掉第一个陷阱绕开后，新的最短路上又卡着第二个，两个都绕开才有路。适配器每步给四个方向
走过去是哪一格、是什么（墙 / 出界 / 空地 / 终点）、按已知地图走过去后离终点还有几步、那格来过几次
（沿用 GridWorld 里 10/12 通关的写法，先把"打转"压下去，失败主要来自陷阱）。

每轮连打 5 局，跨局记忆的六种写法（局内信息完全一样，只差跨局那部分）：
  none    不给跨局记忆（基线：每局都是第一次）
  raw     前几局的完整轨迹：每一步从哪格往哪走到哪格，最后怎么结束
  reason  只写前几局怎么失败的："第 k 局走到 (r,c) 踩到隐藏陷阱，失败"（环境原样反馈，不归纳）
  lesson  程序汇总成一句："已知 (r,c)、(r,c) 有陷阱，别走进去"（外部代码整理成规则，Jev 还得自己
          把坐标对到方向上）
  mark    程序把已知陷阱直接标到方向上：该方向的格子写成 trap（Jev 只需避开写着 trap 的方向）
  plan    在 mark 基础上，"离终点几步"也按避开已知陷阱重算（学习全由适配器完成，Jev 只需贪心）

用法：python3 exp_icl_maze.py run | report   结果写 icl_maze_log.json，断点续跑按"轮"为单位
"""
# 让本脚本从任意目录都能找到仓库根部的 jevkit.py 和同目录的其他 exp_icl_*.py
import sys as _sys, pathlib as _pathlib
_sys.path[:0] = [str(_pathlib.Path(__file__).resolve().parent), str(_pathlib.Path(__file__).resolve().parent.parent)]
import json, os, random, statistics, sys, threading
from collections import deque
from concurrent.futures import ThreadPoolExecutor

HERE = os.path.dirname(os.path.abspath(__file__))
LOG = os.path.join(HERE, 'icl_maze_log.json')
LOCK = threading.Lock()
N = 6
DIRS = {'up': (-1, 0), 'down': (1, 0), 'left': (0, -1), 'right': (0, 1)}
ACTS = {'up': '向上移动一格', 'down': '向下移动一格', 'left': '向左移动一格', 'right': '向右移动一格'}
CONDS = ['none', 'raw', 'reason', 'lesson', 'mark', 'plan']
MAPS, REPS, EPISODES, STEP_LIMIT = 8, 3, 5, 24
OBJ = ('走到终点 goal。地图上有看不见的陷阱（在 state 里看起来和空地一样），踩到陷阱本局立即失败。'
       '你会连续玩好几局，地图和陷阱位置每局都一样。')
Q = '根据 state 选下一步往哪个方向走。'


def dist_map(walls, goal, block=()):
    bad = set(walls) | set(block)
    d = {goal: 0}
    q = deque([goal])
    while q:
        p = q.popleft()
        for dr, dc in DIRS.values():
            n = (p[0] + dr, p[1] + dc)
            if 0 <= n[0] < N and 0 <= n[1] < N and n not in bad and n not in d:
                d[n] = d[p] + 1; q.append(n)
    return d


def make_map(seed):
    rng = random.Random('maze|%d' % seed)
    while True:
        start, goal = (rng.randrange(N), 0), (rng.randrange(N), N - 1)
        walls = set()
        while len(walls) < 8:
            w = (rng.randrange(N), rng.randrange(N))
            if w not in (start, goal):
                walls.add(w)
        d0 = dist_map(walls, goal)
        if start not in d0:
            continue
        cand1 = [c for c in d0 if c not in (start, goal) and 99 > dist_map(walls, goal, [c]).get(start, 99) > d0[start]
                 and abs(c[0] - start[0]) + abs(c[1] - start[1]) > 1]
        if not cand1:
            continue
        t1 = rng.choice(cand1)
        d1 = dist_map(walls, goal, [t1])
        cand2 = [c for c in d1 if c not in (start, goal, t1) and dist_map(walls, goal, [t1, c]).get(start, 99) > d1[start]
                 and dist_map(walls, goal, [t1, c]).get(start, 99) < 99 and abs(c[0] - start[0]) + abs(c[1] - start[1]) > 1]
        if not cand2:
            continue
        t2 = rng.choice(cand2)
        return {'start': start, 'goal': goal, 'walls': sorted(walls), 'traps': [t1, t2],
                'opt': dist_map(walls, goal, [t1, t2])[start], 'naive': d0[start]}


def fmt_p(p):
    return '(%d,%d)' % p


def build_state(m, pos, visits, recent, cond, known, past):
    walls = set(m['walls'])
    d_plain = dist_map(walls, m['goal'])
    d_plan = dist_map(walls, m['goal'], known) if cond == 'plan' else d_plain
    nb = {}
    for a, (dr, dc) in DIRS.items():
        n = (pos[0] + dr, pos[1] + dc)
        info = {'to': list(n)}
        if not (0 <= n[0] < N and 0 <= n[1] < N):
            info['cell'] = 'out_of_bounds'
        elif n in walls:
            info['cell'] = 'wall'
        elif n == m['goal']:
            info['cell'] = 'goal'
        elif cond in ('mark', 'plan') and n in known:
            info['cell'] = 'trap'
        else:
            info['cell'] = 'clear'
        if info['cell'] in ('clear', 'goal'):
            info['steps_to_goal_after_move'] = d_plan.get(n, 'unreachable')
            info['times_already_visited'] = visits.get(n, 0)
        nb[a] = info
    st = {'objective': OBJ, 'grid_size': [N, N], 'player': list(pos), 'goal': list(m['goal']),
          'walls': [list(w) for w in m['walls']], 'neighbors': nb, 'recent_moves_this_episode': recent[-4:]}
    if cond == 'raw' and past:
        lines = []
        for k, ep in enumerate(past):
            path = ' '.join('%s-%s→%s' % (fmt_p(s['pos']), s['move'], fmt_p(s['to'])) for s in ep['steps'])
            lines.append('第 %d 局：%s。结果：%s' % (k + 1, path, ep['why']))
        st['previous_episodes'] = '\n'.join(lines)
    elif cond == 'reason' and past:
        st['previous_episodes'] = '\n'.join('第 %d 局：%s' % (k + 1, ep['why']) for k, ep in enumerate(past))
    elif cond == 'lesson' and known:
        st['lesson'] = '经验：已知 %s 有陷阱，别走进这些格子。' % '、'.join(fmt_p(t) for t in known)
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
        rec = {'pos': pos, 'move': mv, 'p': a['probabilities']}
        if not (0 <= n[0] < N and 0 <= n[1] < N) or n in walls:
            rec['to'] = pos; steps.append(rec); recent.append(mv + '(撞墙,未移动)'); continue
        rec['to'] = n; steps.append(rec)
        pos = n; recent.append(mv); visits[pos] = visits.get(pos, 0) + 1
        if pos in traps:
            return {'result': 'trap', 'trap': pos, 'known_before': pos in known, 'steps': steps,
                    'why': '走到 %s 时踩到隐藏陷阱，本局失败' % fmt_p(pos)}
        if pos == m['goal']:
            return {'result': 'win', 'steps': steps, 'why': '走到终点，本局成功'}
    return {'result': 'timeout', 'steps': steps, 'why': '走了 %d 步还没到终点，本局超时' % STEP_LIMIT}


def run_series(mi, rep, cond, log):
    key = '%d|%d|%s' % (mi, rep, cond)
    if key in log and all(e['result'] != 'api_error' for e in log[key]):
        return
    m = make_map(mi)
    past, known, eps = [], [], []
    for e in range(EPISODES):
        ep = play_episode(m, cond, past, known)
        eps.append(ep)
        if ep['result'] == 'api_error':
            break
        past.append(ep)
        if ep['result'] == 'trap' and ep['trap'] not in known:
            known.append(ep['trap'])
    # tuple -> list for json
    with LOCK:
        log[key] = json.loads(json.dumps(eps))


def report():
    log = json.load(open(LOG))
    print('地图（最短路：无视陷阱 / 避开两陷阱）：', {i: (make_map(i)['naive'], make_map(i)['opt']) for i in range(MAPS)})
    calls = sum(len(e['steps']) for v in log.values() for e in v)
    print('日志 %d 轮，请求 %d 次；api_error 局 %d' % (len(log), calls, sum(e['result'] == 'api_error' for v in log.values() for e in v)))
    print('\n成功局数（每格 %d 轮 = %d 图 × %d 次）；第 k 列 = 第 k 局' % (MAPS * REPS, MAPS, REPS))
    print('%-7s %s | %-9s %-12s %-10s %s' % ('写法', '  '.join('局%d  ' % (k + 1) for k in range(EPISODES)),
                                          '合计成功', '踩已知陷阱', '超时', '成功局平均步数'))
    for cond in CONDS:
        series = [v for k, v in log.items() if k.endswith('|' + cond)]
        cols = []
        for k in range(EPISODES):
            eps = [s[k] for s in series if len(s) > k]
            cols.append('%2d/%d' % (sum(e['result'] == 'win' for e in eps), len(eps)))
        all_eps = [e for s in series for e in s]
        later = [e for s in series for e in s[1:]]
        wins = [len(e['steps']) for e in all_eps if e['result'] == 'win']
        rep_trap = sum(e['result'] == 'trap' and e['known_before'] for e in later)
        print('%-7s %s | %3d/%-5d %3d/%-8d %3d/%-6d %.1f' % (
            cond, '  '.join(cols), len(wins), len(all_eps), rep_trap, len(later),
            sum(e['result'] == 'timeout' for e in all_eps), len(all_eps), statistics.mean(wins) if wins else 0))
    # 已知陷阱就在隔壁时，往那边走的概率
    print('\n已知陷阱就在隔壁的那些步：往陷阱方向走的比例 / 平均概率（只算第 2 局起）')
    for cond in CONDS:
        n = hit = 0; ps = []
        for k, series in log.items():
            if not k.endswith('|' + cond):
                continue
            m = make_map(int(k.split('|')[0]))
            known = []
            for ep in series:
                for s in ep['steps']:
                    pos = tuple(s['pos'])
                    for a, (dr, dc) in DIRS.items():
                        if (pos[0] + dr, pos[1] + dc) in known:
                            n += 1; hit += s['move'] == a; ps.append(s['p'][a])
                if ep['result'] == 'trap' and tuple(ep['trap']) not in known:
                    known.append(tuple(ep['trap']))
        if n:
            print('  %-7s %d/%d 步走进去，平均概率 %.2f' % (cond, hit, n, statistics.mean(ps)))


def main():
    if len(sys.argv) < 2 or sys.argv[1] not in ('run', 'report'):
        print(__doc__); return
    if sys.argv[1] == 'run':
        import jevkit as jev
        log = json.load(open(LOG)) if os.path.exists(LOG) else {}
        jobs = [(mi, rep, c) for mi in range(MAPS) for rep in range(REPS) for c in CONDS]
        with ThreadPoolExecutor(max_workers=12) as ex:
            list(ex.map(lambda j: run_series(j[0], j[1], j[2], log), jobs))
        json.dump(log, open(LOG, 'w'), ensure_ascii=False)
        print(jev.spend())
    report()


if __name__ == '__main__':
    main()
