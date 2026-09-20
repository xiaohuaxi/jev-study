"""自然语言改目标，行为会不会真的跟着变？

官方 Doom demo 的看点之一是「用自然语言指令改变行为」。这里在同一张地图、
同一套五个动作、同一份状态字段上，只换 objective 那一句话，跑完整回合看结果。
四个目标互相矛盾（去终点 / 远离敌人 / 主动撞敌人 / 去左下角），
所以只要行为真的跟着变，指标上一眼能看出来。
复用 exp_game_grid.py 的地图与状态构造。
"""
# 让本脚本从任意目录都能找到仓库根部的 jevkit.py / corpus.py
import sys as _sys, pathlib as _pathlib
_sys.path.insert(0, str(_pathlib.Path(__file__).resolve().parent.parent))
import json, os, statistics
from concurrent.futures import ThreadPoolExecutor
import exp_game_grid as G
import jevkit as jev

OBJS = {
    'goal': '尽快走到终点（goal 坐标），不要踩到敌人所在的格子。',
    'flee': '不要去终点。你唯一的目标是尽可能远离敌人，并一直保持最大距离。',
    'hunt': '不要去终点。你唯一的目标是走到敌人所在的那一格上，越快越好。',
    'corner': '不要去终点。你唯一的目标是走到地图的左下角（第 4 行第 0 列）并停在那里。',
}
LIMIT = 12
REPS = 3
MAP = G.MAPS[0]   # 玩家 (0,0)、终点 (4,4)、敌人 (2,2)

def dist(a, b):
    return abs(a[0] - b[0]) + abs(a[1] - b[1])

def run(key, rep):
    m, pos, hist = MAP, tuple(MAP['start']), []
    ds, path = [], [pos]
    for _ in range(LIMIT):
        st = G.state_json(m, pos, hist)
        st['objective'] = OBJS[key]
        r = jev.call(st, {'action': jev.choice('根据当前状态和目标选择下一步动作。', G.ACTS)})
        if '_error' in r: break
        mv = r['answers']['action']['choice']
        dr, dc = G.DELTA[mv]
        np_ = (pos[0] + dr, pos[1] + dc)
        if mv != 'wait' and G.blocked(m, np_):
            hist.append(mv + '(撞墙,未移动)')
        else:
            pos = np_; hist.append(mv)
        path.append(pos)
        ds.append(dist(pos, m['enemy']))
        if key == 'goal' and pos == tuple(m['goal']): break
        if key == 'hunt' and pos == tuple(m['enemy']): break
        if key == 'corner' and pos == (4, 0): break
    return {'obj': key, 'rep': rep, 'end': list(pos), 'steps': len(path) - 1,
            'path': [list(p) for p in path],
            'reached_goal': pos == tuple(m['goal']), 'on_enemy': pos == tuple(m['enemy']),
            'at_corner': pos == (4, 0),
            'd_end': dist(pos, m['enemy']), 'd_min': min(ds) if ds else None,
            'd_mean': statistics.mean(ds) if ds else None}

def main():
    jobs = [(k, r) for k in OBJS for r in range(REPS)]
    with ThreadPoolExecutor(max_workers=6) as ex:
        res = list(ex.map(lambda j: run(*j), jobs))
    print('地图：玩家(0,0) 终点(4,4) 敌人(2,2) 墙 %s；起点到敌人距离 4' % MAP['walls'])
    print('%-7s %-5s %-6s %-8s %-6s %-6s %-6s %s' % (
        '目标', '步数', '终点位置', '到终点?', '踩敌人?', '左下角?', '末距敌', '轨迹'))
    for r in res:
        print('%-7s %-5d %-6s %-8s %-6s %-6s %-6d %s' % (
            r['obj'], r['steps'], r['end'], r['reached_goal'], r['on_enemy'],
            r['at_corner'], r['d_end'], '→'.join('%d%d' % (p[0], p[1]) for p in r['path'])))
    print('\n== 达成率 ==')
    for k in OBJS:
        g = [r for r in res if r['obj'] == k]
        hit = {'goal': sum(r['reached_goal'] for r in g),
               'hunt': sum(r['on_enemy'] for r in g),
               'corner': sum(r['at_corner'] for r in g),
               'flee': sum(r['d_end'] >= 4 for r in g)}[k]
        print('%-7s %d/%d 达成 | 平均步数 %.1f | 与敌人距离 末 %.1f 均 %.1f' % (
            k, hit, len(g), statistics.mean([r['steps'] for r in g]),
            statistics.mean([r['d_end'] for r in g]),
            statistics.mean([r['d_mean'] for r in g])))
    p = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'game_objective_log.json')
    json.dump(res, open(p, 'w'), ensure_ascii=False, indent=1)
    print('\n明细:', p)
    print(jev.spend())

main()
