"""GridWorld 实测：把 文献版调研（未收录本仓库） 推荐的第一个 MVP 真跑起来。

两个变量：
  state 形态  —— 结构化 JSON（适配器把几何算好）vs 纯 ASCII 地图（让模型自己看图）
  同一张图重复跑 —— 看动作稳不稳

每一步只问一个 choice，五个动作恒定给全（含非法方向），
这样「会不会挑非法动作」是可测的，而不是被 criteria 挡掉。
"""
# 让本脚本从任意目录都能找到仓库根部的 jevkit.py / corpus.py
import sys as _sys, pathlib as _pathlib
_sys.path.insert(0, str(_pathlib.Path(__file__).resolve().parent.parent))
import json, os, statistics, sys, threading, time
from collections import deque
from concurrent.futures import ThreadPoolExecutor
import jevkit as jev

LOCK = threading.Lock()
WORKERS = 6   # 各局互不相关，并发跑只为省墙上时间；单步延迟以 exp_game_rate.py 为准

N = 5
ACTS = {'up': '向上移动一格', 'down': '向下移动一格', 'left': '向左移动一格',
        'right': '向右移动一格', 'wait': '原地等待一回合'}
DELTA = {'up': (-1, 0), 'down': (1, 0), 'left': (0, -1), 'right': (0, 1), 'wait': (0, 0)}
OBJ = '在不踩到敌人所在格子的前提下，用尽量少的步数走到终点。'
OBJ_V = OBJ + '不要在两个格子之间来回绕圈；尽量不要回到已经走过多次的格子。'
ARMS = ('json', 'ascii', 'json_visits')
STEP_LIMIT = 18
REPEATS = 2

MAPS = [
    {'name': 'm1', 'start': (0, 0), 'goal': (4, 4), 'enemy': (2, 2), 'walls': [(0, 3), (1, 1), (3, 1)]},
    {'name': 'm2', 'start': (0, 0), 'goal': (0, 4), 'enemy': (0, 2), 'walls': [(1, 1), (1, 3), (2, 2)]},
    {'name': 'm3', 'start': (4, 0), 'goal': (0, 4), 'enemy': (2, 2), 'walls': [(3, 1), (2, 1), (1, 3)]},
    {'name': 'm4', 'start': (2, 0), 'goal': (2, 4), 'enemy': (2, 2), 'walls': [(1, 2), (3, 2), (0, 3)]},
    {'name': 'm5', 'start': (0, 0), 'goal': (4, 4), 'enemy': (3, 3), 'walls': [(1, 0), (1, 1), (1, 2), (1, 3)]},
    {'name': 'm6', 'start': (4, 4), 'goal': (0, 0), 'enemy': (1, 1), 'walls': [(3, 3), (2, 4), (0, 1)]},
]

def blocked(m, p):
    r, c = p
    return not (0 <= r < N and 0 <= c < N) or tuple(p) in [tuple(w) for w in m['walls']]

def bfs(m):
    """最短安全路径长度；敌人格子视为不可走。用来给「步数是否接近最优」当基准。"""
    bad = set(tuple(w) for w in m['walls']) | {tuple(m['enemy'])}
    q, seen = deque([(tuple(m['start']), 0)]), {tuple(m['start'])}
    while q:
        p, d = q.popleft()
        if p == tuple(m['goal']):
            return d
        for dr, dc in list(DELTA.values())[:4]:
            np_ = (p[0] + dr, p[1] + dc)
            if 0 <= np_[0] < N and 0 <= np_[1] < N and np_ not in bad and np_ not in seen:
                seen.add(np_); q.append((np_, d + 1))
    return None

def cell(m, p):
    if tuple(p) == tuple(m['goal']): return 'G'
    if tuple(p) == tuple(m['enemy']): return 'E'
    if tuple(p) in [tuple(w) for w in m['walls']]: return '#'
    return '.'

def ascii_map(m, pos):
    rows = []
    for r in range(N):
        row = []
        for c in range(N):
            row.append('S' if (r, c) == tuple(pos) else cell(m, (r, c)))
        rows.append(' '.join(row))
    return '\n'.join(rows)

def state_json(m, pos, hist, visits=None):
    nb = {}
    for a, (dr, dc) in DELTA.items():
        if a == 'wait': continue
        np_ = (pos[0] + dr, pos[1] + dc)
        if not (0 <= np_[0] < N and 0 <= np_[1] < N): tag = 'out_of_bounds'
        elif np_ in [tuple(w) for w in m['walls']]: tag = 'wall'
        elif np_ == tuple(m['enemy']): tag = 'enemy'
        elif np_ == tuple(m['goal']): tag = 'goal'
        else: tag = 'clear'
        nb[a] = tag if visits is None else {'cell': tag, 'times_already_visited': visits.get(np_, 0)}
    st = {'grid_size': [N, N], 'player': list(pos), 'goal': list(m['goal']),
          'enemy': list(m['enemy']), 'walls': [list(w) for w in m['walls']],
          'neighbors': nb, 'recent_moves': hist[-4:],
          'objective': OBJ if visits is None else OBJ_V}
    if visits is not None:
        st['times_already_visited_here'] = visits.get(tuple(pos), 0)
    return st

def state_ascii(m, pos, hist):
    return {'map': ascii_map(m, pos),
            'legend': 'S=你 G=终点 E=敌人 #=墙 .=空地；地图第一行在最上方，'
                      'up 表示向上一行、down 向下一行、left 向左一列、right 向右一列。',
            'recent_moves': hist[-4:], 'objective': OBJ}

def episode(m, arm, rep, log):
    pos, hist = tuple(m['start']), []
    illegal = ticks = 0
    lat = []
    visits = {tuple(m['start']): 1}
    for _ in range(STEP_LIMIT):
        if arm == 'ascii': st = state_ascii(m, pos, hist)
        elif arm == 'json_visits': st = state_json(m, pos, hist, visits)
        else: st = state_json(m, pos, hist)
        r = jev.call(st, {'action': jev.choice('根据当前状态选择下一步动作。', ACTS)})
        ticks += 1
        if '_error' in r:
            return {'result': 'api_error', 'steps': ticks, 'illegal': illegal, 'lat': lat}
        a = r['answers']['action']
        lat.append(r['_elapsed'])
        mv = a['choice']
        dr, dc = DELTA[mv]
        np_ = (pos[0] + dr, pos[1] + dc)
        bad = mv != 'wait' and blocked(m, np_)
        with LOCK:
            log.write(json.dumps({'map': m['name'], 'arm': arm, 'rep': rep, 'pos': list(pos), 'move': mv,
                                  'p': a['probabilities'], 'conf': a.get('confidence'),
                                  'illegal': bad, 'elapsed': r['_elapsed'],
                                  'in_tok': r['usage']['input_tokens']}, ensure_ascii=False) + '\n')
        if bad:
            illegal += 1; hist.append(mv + '(撞墙,未移动)'); continue
        pos = np_; hist.append(mv); visits[pos] = visits.get(pos, 0) + 1
        if pos == tuple(m['enemy']):
            return {'result': 'dead', 'steps': ticks, 'illegal': illegal, 'lat': lat}
        if pos == tuple(m['goal']):
            return {'result': 'win', 'steps': ticks, 'illegal': illegal, 'lat': lat}
    return {'result': 'timeout', 'steps': ticks, 'illegal': illegal, 'lat': lat}

def main():
    out = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'game_grid_log.jsonl')
    log = open(out, 'w')
    print('地图基准（BFS 最短安全路径）:', {m['name']: bfs(m) for m in MAPS})
    jobs = [(m, arm, rep) for m in MAPS for arm in ARMS for rep in range(REPEATS)]
    for m in MAPS:
        assert bfs(m) is not None, m['name']
    with ThreadPoolExecutor(max_workers=WORKERS) as ex:
        res = list(ex.map(lambda j: episode(j[0], j[1], j[2], log), jobs))
    log.close()
    agg = {}
    for (m, arm, rep), e in zip(jobs, res):
        agg.setdefault((m['name'], arm), []).append(e)
        print('%-3s %-11s rep%d -> %-9s 步数 %2d (最优 %d) 非法 %d' % (
            m['name'], arm, rep, e['result'], e['steps'], bfs(m), e['illegal']))
    print('\n== 汇总 ==')
    for arm in ARMS:
        eps = [e for (n, a), v in agg.items() if a == arm for e in v]
        wins = sum(1 for e in eps if e['result'] == 'win')
        dead = sum(1 for e in eps if e['result'] == 'dead')
        to = sum(1 for e in eps if e['result'] == 'timeout')
        ill = sum(e['illegal'] for e in eps)
        steps = sum(e['steps'] for e in eps)
        opt = sum(bfs(m) * REPEATS for m in MAPS)
        lats = [x for e in eps for x in e['lat']]
        print('%-11s 局数 %d | 到终点 %d | 踩敌人 %d | 超步数 %d | 非法动作 %d/%d | '
              '总步数 %d(最优 %d) | 单步延迟 中位 %.2fs p90 %.2fs' % (
                  arm, len(eps), wins, dead, to, ill, steps, steps, opt,
                  statistics.median(lats), sorted(lats)[int(len(lats) * 0.9) - 1]))
    print('日志:', out)
    print(jev.spend())

if __name__ == '__main__':   # exp_game_objective.py 会 import 本文件复用地图
    main()
