"""Jev 迷宫第五轮（补测：只删踩坑记录，2026-09-27）：exp_icl_maze3.py 的多局组 reason_plan
（失败历史 + 程序把已知陷阱当墙重算距离）第 1–5 局通关 0,0,24,24,24，合计 72/120。
回头核对结论时的推断：
这组"跨局学习"其实是程序重算距离在起作用——Jev 95% 的步都照最小距离走，失败历史文字本身
多半是多余的——但没做过"只删掉历史、其余全同"的对照，不能实测坐实这个推断。
（实测结果：删掉记录、其余不变，通关从 72/120 掉到 60/120，记录并非多余，只是出力远小于程序。）

本脚本补这组对照：plan_nohist 条件与 exp_icl_maze3.plan 完全一致（同 12 图种子 100–111、
同 2 次、连打 5 局、步数上限 40、已知陷阱由程序维护并当墙算距离），唯一差别是 state 里
不写 previous_episodes（不给失败历史文字）。已知陷阱集合仍按实际踩到的结果由程序维护、
仍用于重算距离——这部分是"程序在学"，不是"喂历史文字"，予以保留，才是干净的单变量对照。

因为两组第 1 局的 state 完全相同（都没有历史可写），第 1 局的选择应该一致；
从第 2 局起若两组仍然一致，说明历史文字确实是多余的；一旦分叉，则历史文字确有作用。
report 里按局号配对、逐步比较两组在相同局面下选的方向，直到分叉为止，把这一点实测出来。

用法：python3 exp_icl_maze5.py run | report
日志 icl_maze5_log.json（被 .gitignore 排除），断点续跑；report 会只读引用同目录第三轮的日志
icl_maze3_log.json（先跑 exp_icl_maze3.py 才有）做 PLAN 对照，不修改它。
"""
# 让本脚本从任意目录都能找到仓库根部的 jevkit.py 和同目录的其他 exp_icl_*.py
import sys as _sys, pathlib as _pathlib
_sys.path[:0] = [str(_pathlib.Path(__file__).resolve().parent), str(_pathlib.Path(__file__).resolve().parent.parent)]
import json, os, sys, threading
from concurrent.futures import ThreadPoolExecutor

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from exp_icl_maze3 import (SEED0, MAPS, REPS, EPISODES, STEP_LIMIT, DIRS, Q, ACTS,
                            plan_state, make_map, fmt_p, by_map_ci)

LOG = os.path.join(HERE, 'icl_maze5_log.json')
# 第三轮（exp_icl_maze3.py）的日志，只读引用
LOG3 = os.path.join(HERE, 'icl_maze3_log.json')
LOCK = threading.Lock()


def plan_nohist_series(mi, rep, log):
    import jevkit as jev
    key = 'PLANNH|%d|%d' % (mi, rep)
    if key in log and all(e['result'] != 'api_error' for e in log[key]):
        return
    m = make_map(SEED0 + mi)
    traps, walls = set(m['traps']), set(m['walls'])
    known, eps = [], []
    for _ in range(EPISODES):
        pos, visits, recent, steps = m['start'], {m['start']: 1}, [], []
        ep = None
        for _ in range(STEP_LIMIT):
            # 与 exp_icl_maze3.plan_series 唯一的差别：past 恒为 []，state 里不写 previous_episodes
            r = jev.call(plan_state(m, pos, visits, recent, known, []), {'move': jev.choice(Q, ACTS)})
            if '_error' in r:
                ep = {'result': 'api_error', 'steps': steps, 'why': 'api'}; break
            a = r['answers']['move']
            mv = a['choice']
            n = (pos[0] + DIRS[mv][0], pos[1] + DIRS[mv][1])
            rec = {'pos': list(pos), 'move': mv, 'p': a['probabilities'], 'cost': r.get('usage', {}).get('cost', 0.0), 'model': r.get('model')}
            if not (0 <= n[0] < 6) or not (0 <= n[1] < 6) or n in walls:
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
        if ep['result'] == 'trap' and tuple(ep['trap']) not in known:
            known.append(tuple(ep['trap']))
        # 注意：不 append 到任何 past 列表——下一局 state 依旧不带历史文字
    with LOCK:
        log[key] = eps
        save(log)


def load():
    return json.load(open(LOG)) if os.path.exists(LOG) else {}


def save(log):
    tmp = LOG + '.tmp'
    json.dump(log, open(tmp, 'w'), ensure_ascii=False)
    os.replace(tmp, LOG)


def compare_with_plan():
    """逐局、逐步对照 plan_nohist 与第三轮 PLAN：相同局号下从第 1 步开始比较选择的方向，
    直到某一步方向不一致（分叉）为止；分叉之后局面已经不同，不再继续比。"""
    nh = load()
    if not os.path.exists(LOG3):
        print('  （找不到第三轮日志 %s，跳过对照；先跑 exp_icl_maze3.py）' % LOG3)
        return
    plan = json.load(open(LOG3))
    agree = total = 0
    ep_full_match = ep_total = 0
    diverge_at_ep = {}
    for key, eps_nh in nh.items():
        if not key.startswith('PLANNH|'):
            continue
        mi, rep = key.split('|')[1:]
        pkey = 'PLAN|%s|%s' % (mi, rep)
        if pkey not in plan:
            continue
        eps_p = plan[pkey]
        for ei in range(min(len(eps_nh), len(eps_p))):
            steps_nh = eps_nh[ei]['steps']
            steps_p = eps_p[ei]['steps']
            ep_total += 1
            matched_fully = True
            for si in range(min(len(steps_nh), len(steps_p))):
                total += 1
                if steps_nh[si]['move'] == steps_p[si]['move']:
                    agree += 1
                else:
                    matched_fully = False
                    diverge_at_ep[ei + 1] = diverge_at_ep.get(ei + 1, 0) + 1
                    break
            else:
                if len(steps_nh) != len(steps_p):
                    matched_fully = False
            ep_full_match += matched_fully
    if total:
        print('  逐步方向一致率（按局号配对、遇分叉即停）：%d/%d=%.0f%%；整局从头到尾未分叉 %d/%d' % (
            agree, total, 100 * agree / total, ep_full_match, ep_total))
        if diverge_at_ep:
            print('  首次分叉发生在第几局：%s' % dict(sorted(diverge_at_ep.items())))
    else:
        print('  （PLANNH 与 PLAN 无可配对的局，跳过对照）')


def report():
    log = load()
    series = {k: v for k, v in log.items() if k.startswith('PLANNH|')}
    steps_all = [s for v in series.values() for e in v for s in e['steps']]
    print('日志 %d 条，请求 %d 次，花费 $%.4f，模型 %s' % (
        len(log), len(steps_all), sum(s.get('cost', 0) for s in steps_all), {s.get('model') for s in steps_all}))
    if not series:
        print('（还没有数据，先 run）'); return
    print('\n多局 plan_nohist（12 图 × 2 次 × 5 局，无失败历史 + 已知陷阱当墙算距离）：')
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
    print('\n与第三轮 PLAN（含历史文字）的逐步方向对照：')
    compare_with_plan()


def main():
    if len(sys.argv) < 2 or sys.argv[1] not in ('run', 'report'):
        print(__doc__); return
    if sys.argv[1] == 'run':
        import jevkit as jev
        log = load()
        jobs = [(mi, rep) for mi in range(MAPS) for rep in range(REPS)]
        with ThreadPoolExecutor(max_workers=12) as ex:
            list(ex.map(lambda j: plan_nohist_series(j[0], j[1], log), jobs))
        print(jev.spend())
    report()


if __name__ == '__main__':
    main()
