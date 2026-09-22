# -*- coding: utf-8 -*-
"""发现线索的小对照（66 次请求）：国际象棋 SAN 里的 # / + 是不是初探一步杀 10/10 的来源。

    python exp_xiangqi_probe.py        # 发 66 次请求（约 $0.003），原始回包写 exp_xiangqi_probe_log.json（不入库）

这是研究开头的第一眼，沿用初探的旧格式（选项键是坐标、state 带合法着法清单），每题两次：
  - 国际象棋：games/exp_game_chess.py 的 5 个一步杀局面（都是有效题），选项描述三种——原样 SAN / # 换成 + / 去掉 + 和 #。
    本目录 README.md（中国象棋实测报告）第一节只引用这一半，而且只当线索；正式结论以 exp_xiangqi_mate.py 的 48 个局面为准。
  - 中国象棋：初探 games/exp_game_xiangqi.py 的 6 个旧局面，其中 5 个后来证实无效（摆法不合法 / 另有一步困毙，
    见 boards.audit_mate），所以这一半的数字不用；判合法用的是当时的 cchess 写法，也没过 boards 的核对。
需要 cchess 与 python-chess（python3 -m pip install cchess chess）。
"""
# 让本脚本从任意目录都能找到仓库根部的 jevkit.py
import sys as _sys, pathlib as _pathlib
_sys.path.insert(0, str(_pathlib.Path(__file__).resolve().parent.parent))
import sys, os, json
import chess, cchess
import jevkit as jev

MATES = ['6k1/5ppp/8/8/8/8/8/R5K1 w - - 0 1', '3r3k/6pp/8/8/8/8/5PPP/3R2K1 w - - 0 1',
         'q5k1/5ppp/8/8/8/8/5PPP/R5K1 w - - 0 1', 'k7/8/1K6/8/8/8/8/7R w - - 0 1',
         '6k1/4Rppp/8/8/8/8/5PPP/6K1 w - - 0 1']
ASK_C = '你在下国际象棋，执白。从合法着法里选一步最好的。注意：这里存在一步将死的机会。'


def is_mate(b, m):
    b.push(m)
    r = b.is_checkmate()
    b.pop()
    return r


jobs, meta = [], {}
for i, fen in enumerate(MATES):
    b = chess.Board(fen)
    wants = [m.uci() for m in b.legal_moves if is_mate(b, m)]
    assert len(wants) == 1
    want = wants[0]
    san = {m.uci(): b.san(m) for m in b.legal_moves}
    arms = {'orig': san,
            'mate_as_check': {k: v.replace('#', '+') for k, v in san.items()},
            'stripped': {k: v.rstrip('+#') for k, v in san.items()}}
    st = {'fen': fen, 'side_to_move': 'white', 'legal_moves_uci': sorted(san)}
    for arm, crit in arms.items():
        for rep in range(2):
            k = ('chess', i, arm, rep)
            meta[k] = want
            jobs.append((k, st, {'move': jev.choice(ASK_C, crit)}))

XQ = [('9/9/4ka3/2C4R1/9/8N/9/3K5/7c1/9 w', 'h6e6'), ('3cak3/9/8C/3R5/9/9/3N5/9/9/4K4 w', 'd6f6'),
      ('2N6/5a3/5k3/9/9/9/9/1c1K3C1/9/2R6 w', 'c0c7'), ('5k3/5a3/9/9/9/9/9/2R6/3c3CN/4K4 w', 'h1f1'),
      ('4k4/R8/8R/9/9/9/9/9/9/3K5 w', 'i7i9'), ('4k4/9/9/9/5N3/4C4/9/9/9/3K5 w', 'f5e7')]
COORDS = '坐标用 ICCS 记法：纵线 a 到 i 从红方左手边数起，横线 0 到 9 从红方底线数起'
ASK_X = '你在下中国象棋，执红。从合法着法里选一步最好的。注意：这里存在一步将死的机会。'
for i, (fen, want) in enumerate(XQ):
    b = cchess.ChessBoard(fen)
    ms = []
    for pf, pt in list(b.create_moves()):
        if b.get_fench(pt) == 'k' or not b.is_valid_move(pf, pt) or b.is_checked_move(pf, pt):
            continue
        mv = cchess.ChessBoard(fen).move(pf, pt)
        ms.append((mv.to_iccs(), mv.to_text(), bool(mv.is_checking),
                   bool(mv.is_checking and mv.is_checkmate)))
    assert [m[0] for m in ms if m[3]] == [want], (fen, [m[0] for m in ms if m[3]])
    arms = {'orig': {m[0]: m[1] for m in ms},
            'check_marked': {m[0]: m[1] + ('（将军）' if m[2] else '') for m in ms},
            'mate_marked': {m[0]: m[1] + ('（将死）' if m[3] else '（将军）' if m[2] else '') for m in ms}}
    st = {'fen': fen, 'side_to_move': '红方', 'coords': COORDS,
          'legal_moves_iccs': sorted(m[0] for m in ms)}
    for arm, crit in arms.items():
        for rep in range(2):
            k = ('xq', i, arm, rep)
            meta[k] = want
            jobs.append((k, st, {'move': jev.choice(ASK_X, crit)}))
    print('xq', i, 'legal', len(ms), 'checking moves', sum(m[2] for m in ms))

res = jev.fan(jobs, workers=8)
agg = {}
for k, r in res.items():
    if '_error' in r:
        print('ERR', k, r['_error'])
        continue
    a = r['answers']['move']
    want = meta[k]
    g = agg.setdefault((k[0], k[2]), [0, 0, []])
    g[0] += a['choice'] == want
    g[1] += 1
    g[2].append(round(a['probabilities'].get(want, 0), 2))
for (game, arm), (h, n, ps) in sorted(agg.items()):
    print('%-5s %-14s %d/%d  p(正解)=%s' % (game, arm, h, n, ps))
json.dump({str(k): v for k, v in res.items()}, open(__file__.replace('.py', '_log.json'), 'w'),
          ensure_ascii=False)
print(jev.spend())
