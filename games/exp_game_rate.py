"""实时性实测：串行游戏循环能跑多少 Hz，要跑到 10 Hz 必须怎么做，决策有多旧。

文献版调研（未收录本仓库） 说官方 Doom 约 10 query/s。本脚本量三件事：
  1) 串行 while 循环（收到答案再发下一帧）实际能到几 Hz；
  2) 按 100ms 固定节拍发请求（重叠飞行）能不能撑住 10 Hz、要多少并发；
  3) 一次决策回来时已经过了几个 tick —— 也就是决策有多旧。
顺带用实测 input token 数核对 文献版调研（未收录本仓库） 里的成本表。
"""
# 让本脚本从任意目录都能找到仓库根部的 jevkit.py / corpus.py
import sys as _sys, pathlib as _pathlib
_sys.path.insert(0, str(_pathlib.Path(__file__).resolve().parent.parent))
import json, os, statistics, threading, time
from concurrent.futures import ThreadPoolExecutor
import jevkit as jev

STATE = {
    'tick': 0, 'health': 62, 'ammo': 18, 'objective': 'reach_exit',
    'visible_enemies': [{'type': 'imp', 'bearing_deg': 17, 'distance': 6.5},
                        {'type': 'shotgun_guy', 'bearing_deg': 295, 'distance': 11.0}],
    'navigation': {'forward_clearance': 5.2, 'left_clearance': 4.8, 'right_clearance': 5.0,
                   'back_clearance': 7.7},
    'recent_events': ['took damage from front_right', 'enemy became visible'],
    'recent_damage_direction': 'front_right', 'exit_distance': 27.4, 'exit_bearing_deg': 5,
    'visited_cells': [[3, 4], [3, 5], [4, 5], [4, 6]],
}
ACTS = {'shoot': '朝可见敌人射击', 'forward': '向前推进', 'turn_left': '向左转向',
        'turn_right': '向右转向', 'strafe_left': '向左横移', 'strafe_right': '向右横移',
        'retreat': '后撤脱离接触', 'noop': '原地不动'}
QS = {'action': jev.choice('根据当前状态选择这一帧要执行的动作。', ACTS),
      'threat': jev.score('评估即时威胁。', ['安全', '有一定威胁', '高威胁', '极度危险']),
      'retreat': jev.noul('现在是否应该优先后撤？')}

def pct(xs, q):
    xs = sorted(xs)
    return xs[min(len(xs) - 1, int(len(xs) * q))]

def serial(n=15):
    lat = []
    t0 = time.time()
    for i in range(n):
        st = dict(STATE, tick=i)
        r = jev.call(st, QS)
        if '_error' in r: print('串行失败', r['_error']); continue
        lat.append(r['_elapsed'])
    wall = time.time() - t0
    tok = r['usage']['input_tokens']
    print('== 串行循环（收到再发下一帧）==')
    print('%d 帧用时 %.1fs → %.2f 决策/秒；单次延迟 中位 %.2fs p90 %.2fs 最大 %.2fs' % (
        n, wall, n / wall, statistics.median(lat), pct(lat, .9), max(lat)))
    print('每帧输入 %d token（三个问题一起问）' % tok)
    return lat, tok

def paced(hz=10, seconds=5.0, workers=24):
    """固定节拍发，不等上一帧回来。记录每帧发出与返回的时刻。"""
    n = int(hz * seconds)
    interval = 1.0 / hz
    inflight = {'now': 0, 'max': 0}
    lock = threading.Lock()
    rec = []
    t0 = time.time()

    def one(i):
        with lock:
            inflight['now'] += 1
            inflight['max'] = max(inflight['max'], inflight['now'])
        sent = time.time()
        r = jev.call(dict(STATE, tick=i), QS, retries=1)
        got = time.time()
        with lock:
            inflight['now'] -= 1
        rec.append({'i': i, 'sent': sent - t0, 'got': got - t0,
                    'lat': got - sent, 'ok': '_error' not in r,
                    'err': r.get('_error')})

    with ThreadPoolExecutor(max_workers=workers) as ex:
        for i in range(n):
            due = t0 + i * interval
            slack = due - time.time()
            if slack > 0: time.sleep(slack)
            ex.submit(one, i)
        send_span = time.time() - t0
    wall = time.time() - t0
    ok = [x for x in rec if x['ok']]
    lat = [x['lat'] for x in ok]
    print('\n== 固定 %d Hz 发送、请求重叠飞行 ==' % hz)
    print('计划 %d 帧 / %.1fs；实际发完用时 %.2fs（发送节拍达成 %.2f Hz）' % (
        n, seconds, send_span, n / send_span))
    print('成功 %d / %d；全部收完 %.2fs；最高同时在飞 %d 个' % (
        len(ok), n, wall, inflight['max']))
    if lat:
        print('延迟 中位 %.2fs p90 %.2fs 最大 %.2fs' % (
            statistics.median(lat), pct(lat, .9), max(lat)))
        st = [l / (1.0 / hz) for l in lat]
        print('决策回来时已经过了 中位 %.1f 个 tick、最多 %.1f 个 tick（%d Hz 下）' % (
            statistics.median(st), max(st), hz))
    bad = [x for x in rec if not x['ok']]
    if bad: print('失败样本:', bad[:3])
    return rec

def jitter(n=10):
    """同一个 state 连发 n 次（字节完全相同），看动作和概率抖多少。"""
    rs = [jev.call(STATE, QS) for _ in range(n)]
    ok = [r for r in rs if '_error' not in r]
    picks = [r['answers']['action']['choice'] for r in ok]
    keys = sorted(ok[0]['answers']['action']['probabilities'])
    print('\n== 同一状态连发 %d 次（完全相同的请求体）==' % n)
    print('动作: %s' % ','.join(picks))
    print('%-13s %6s %6s %6s' % ('动作', '最小', '最大', '极差'))
    for k in keys:
        vs = [r['answers']['action']['probabilities'][k] for r in ok]
        if max(vs) < 0.02: continue
        print('%-13s %6.2f %6.2f %6.2f' % (k, min(vs), max(vs), max(vs) - min(vs)))
    for label, path in (('threat 分数', lambda r: r['answers']['threat']['score']),
                        ('retreat 概率', lambda r: r['answers']['retreat']['noul'])):
        vs = [path(r) for r in ok]
        print('%-13s %6.2f %6.2f %6.2f' % (label, min(vs), max(vs), max(vs) - min(vs)))
    return picks


def cost_table(tok):
    print('\n== 用实测 token 数核对成本表（$0.042 / 1M input，output 免费）==')
    for hz in (1, 5, 10):
        print('%2d Hz × %d tok = %.2fM input/小时 → $%.4f/小时' % (
            hz, tok, hz * 3600 * tok / 1e6, hz * 3600 * tok * 0.042 / 1e6))
    doom = 7.0 / (10 * 3600 * 0.042 / 1e6)
    print('反推：若 10 Hz 真花 $7/小时，则每帧输入约 %.0f token（本脚本的状态才 %d token）' % (doom, tok))

def main():
    lat, tok = serial()
    jitter()
    rec = paced()
    cost_table(tok)
    p = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'game_rate_log.json')
    json.dump({'serial_lat': lat, 'in_tok': tok, 'paced': rec}, open(p, 'w'), indent=1)
    print('\n明细:', p)
    print(jev.spend())

main()
