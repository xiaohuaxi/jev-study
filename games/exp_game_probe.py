"""按 文献版调研（未收录本仓库） 建议的「第一轮测试集」逐项实测（Doom 式结构化状态）。

七种固定状态，每种重复 5 次：看动作概率、威胁分数、是否撤退这三项判断
会不会按预期随状态变化；顺带量一次同状态的重复稳定性。
最后一小节比较「一次问 1 个问题」和「一次问 3 个问题」的延迟与计费。
"""
# 让本脚本从任意目录都能找到仓库根部的 jevkit.py / corpus.py
import sys as _sys, pathlib as _pathlib
_sys.path.insert(0, str(_pathlib.Path(__file__).resolve().parent.parent))
import json, math, os, statistics
import jevkit as jev

ACTS = {
    'shoot': '朝可见敌人射击',
    'forward': '向前推进',
    'turn_left': '向左转向',
    'turn_right': '向右转向',
    'strafe_left': '向左横移',
    'strafe_right': '向右横移',
    'retreat': '后撤脱离接触',
    'noop': '原地不动',
}
Q3 = {
    'action': jev.choice('根据当前状态选择这一帧要执行的动作。', ACTS),
    'threat': jev.score('评估玩家当前面临的即时威胁程度。', ['安全', '有一定威胁', '高威胁', '极度危险']),
    'retreat': jev.noul('现在是否应该优先后撤脱离接触？'),
}
Q1 = {'action': Q3['action']}

BASE = {
    'health': 62, 'ammo': 18, 'objective': 'reach_exit',
    'visible_enemies': [{'type': 'imp', 'bearing_deg': 17, 'distance': 6.5}],
    'navigation': {'forward_clearance': 5.2, 'left_clearance': 4.8, 'right_clearance': 5.0},
    'recent_damage_direction': None, 'exit_distance': 27.4, 'exit_bearing_deg': 5,
}

def var(**kw):
    s = json.loads(json.dumps(BASE))
    for k, v in kw.items():
        if k == 'nav': s['navigation'] = v
        elif k == 'enemy': s['visible_enemies'] = v
        else: s[k] = v
    return s

CASES = [
    ('基线', var()),
    ('明显危险', var(health=8, ammo=2, enemy=[{'type': 'imp', 'bearing_deg': 350, 'distance': 1.2}],
                 recent_damage_direction='front_right')),
    ('明显攻击机会', var(health=95, ammo=40, enemy=[{'type': 'imp', 'bearing_deg': 3, 'distance': 2.5}])),
    ('正前方封死', var(nav={'forward_clearance': 0.2, 'left_clearance': 6.0, 'right_clearance': 5.5})),
    ('目标=reach_exit', var(objective='reach_exit')),
    ('目标=kill_all', var(objective='kill_all')),
    ('左右信息近似', var(enemy=[], exit_bearing_deg=None, exit_distance=None,
                    nav={'forward_clearance': 0.3, 'left_clearance': 5.0, 'right_clearance': 4.9})),
    ('删掉敌人距离', var(enemy=[{'type': 'imp', 'bearing_deg': 17}])),
]
REPS = 5

def ent(p):
    return -sum(v * math.log(v, 2) for v in p.values() if v > 0)

def main():
    rows = []
    jobs = [((name, i), st, Q3) for name, st in CASES for i in range(REPS)]
    res = jev.fan(jobs, workers=8)
    out = {}
    for (name, i), r in res.items():
        if '_error' in r:
            print('失败', name, r['_error']); continue
        a = r['answers']
        out.setdefault(name, []).append({
            'choice': a['action']['choice'], 'p': a['action']['probabilities'],
            'conf': a['action'].get('confidence'), 'ent': ent(a['action']['probabilities']),
            'top': max(a['action']['probabilities'].values()),
            'threat': a['threat']['score'], 'tconf': a['threat'].get('confidence'),
            'retreat': a['retreat']['noul'], 'in_tok': r['usage']['input_tokens'],
        })
    print('%-14s %-12s %6s %6s %6s %6s %6s  %s' % (
        '场景', '动作(众数)', 'p(该动作)', '熵', '置信', '威胁分', '撤退', '五次动作'))
    for name, _ in CASES:
        v = out.get(name, [])
        if not v: continue
        picks = [x['choice'] for x in v]
        mode = max(set(picks), key=picks.count)
        pm = statistics.mean([x['p'][mode] for x in v])
        print('%-14s %-12s %6.2f %6.2f %6.2f %6.2f %6.2f  %s' % (
            name, mode, pm, statistics.mean([x['ent'] for x in v]),
            statistics.mean([x['conf'] for x in v]),
            statistics.mean([x['threat'] for x in v]),
            statistics.mean([x['retreat'] for x in v]), ','.join(picks)))
        rows.append({'case': name, 'picks': picks, 'mean': {
            'p_mode': pm, 'ent': statistics.mean([x['ent'] for x in v]),
            'conf': statistics.mean([x['conf'] for x in v]),
            'threat': statistics.mean([x['threat'] for x in v]),
            'tconf': statistics.mean([x['tconf'] for x in v]),
            'retreat': statistics.mean([x['retreat'] for x in v])},
            'p_all': v[0]['p'], 'in_tok': v[0]['in_tok']})

    print('\n-- 关键单项概率（取五次均值）--')
    for name, _ in CASES:
        v = out.get(name, [])
        if not v: continue
        keys = ['shoot', 'forward', 'retreat']
        print('%-14s ' % name + '  '.join(
            '%s=%.2f' % (k, statistics.mean([x['p'].get(k, 0) for x in v])) for k in keys))

    print('\n-- 一次问 1 个 vs 一次问 3 个（同一基线状态，各 5 次）--')
    for label, q in (('1 个问题', Q1), ('3 个问题', Q3)):
        rs = jev.fan([((label, i), BASE, q) for i in range(5)], workers=1)
        ok = [r for r in rs.values() if '_error' not in r]
        print('%-8s 延迟中位 %.2fs | 输入 %d tok | 输出 %d tok | 单次花费 $%.7f' % (
            label, statistics.median([r['_elapsed'] for r in ok]),
            ok[0]['usage']['input_tokens'], ok[0]['usage']['output_tokens'],
            statistics.mean([r['usage']['cost'] for r in ok])))

    p = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'game_probe_log.json')
    json.dump(rows, open(p, 'w'), ensure_ascii=False, indent=1)
    print('\n明细:', p)
    print(jev.spend())

main()
