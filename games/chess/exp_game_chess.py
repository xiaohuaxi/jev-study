"""国际象棋实测：文献版调研（未收录本仓库） 说这是最容易完整复现的 Jev 游戏案例，这里真跑一遍。

需要 python-chess：python3 -m pip install chess（本文件用 Python 3.13 + chess 1.11 跑过）。
三组：
  A 杀棋一步：每个局面都用 python-chess 断言「只有一步能将死」，看 Jev 找不找到；
  B 两层物质搜索给出的最佳着法：看 Jev 选中率、以及平均亏多少子；
  C 真对局：Jev 执白 vs 随机走子，测结果、每步延迟、每局成本。
合法着法一律由棋库枚举后作为 choice 候选，criteria 里带 SAN，与原报告描述一致。
"""
# 让本脚本从任意目录都能找到仓库根部的 jevkit.py / corpus.py
import sys as _sys, pathlib as _pathlib
_sys.path.insert(0, str(_pathlib.Path(__file__).resolve().parent.parent.parent))
import json, os, random, statistics, sys, time
from concurrent.futures import ThreadPoolExecutor
import chess
import jevkit as jev

VAL = {chess.PAWN: 1, chess.KNIGHT: 3, chess.BISHOP: 3, chess.ROOK: 5, chess.QUEEN: 9, chess.KING: 0}

def material(b, color):
    s = 0
    for pt, v in VAL.items():
        s += v * (len(b.pieces(pt, color)) - len(b.pieces(pt, not color)))
    return s

def best_material(b, depth=2):
    """两层物质搜索：我走一步，对手用最好的一步回吃。返回 {move: 分数}。"""
    me = b.turn
    out = {}
    for m in b.legal_moves:
        b.push(m)
        if b.is_checkmate():
            out[m] = 999
        else:
            worst = material(b, me)
            for r in b.legal_moves:
                b.push(r)
                worst = min(worst, material(b, me))
                b.pop()
            out[m] = worst
        b.pop()
    return out

def ask(b, extra=''):
    crit = {}
    for m in b.legal_moves:
        crit[m.uci()] = b.san(m)
    st = {'fen': b.fen(), 'side_to_move': 'white' if b.turn else 'black',
          'legal_moves_uci': sorted(crit.keys())}
    q = {'move': jev.choice(
        '你在下国际象棋，执%s。从合法着法里选一步最好的。%s' % (
            '白' if b.turn else '黑', extra), crit)}
    return jev.call(st, q)

MATES = [
    '6k1/5ppp/8/8/8/8/8/R5K1 w - - 0 1',
    '3r3k/6pp/8/8/8/8/5PPP/3R2K1 w - - 0 1',
    'q5k1/5ppp/8/8/8/8/5PPP/R5K1 w - - 0 1',
    'k7/8/1K6/8/8/8/8/7R w - - 0 1',
    '6k1/4Rppp/8/8/8/8/5PPP/6K1 w - - 0 1',
]

def part_a():
    print('== A 杀棋一步（每个局面都只有一步能将死）==')
    hit = tot = 0
    for fen in MATES:
        b = chess.Board(fen)
        mates = [m for m in b.legal_moves if _is_mate(b, m)]
        assert len(mates) == 1, (fen, [b.san(m) for m in mates])
        want = mates[0]
        for _ in range(2):
            r = ask(b, '注意：这里存在一步将死的机会。')
            if '_error' in r:
                print('  失败', r['_error']); continue
            a = r['answers']['move']
            ok = a['choice'] == want.uci()
            hit += ok; tot += 1
            print('  %-42s 正解 %-6s 选了 %-6s p=%.2f conf=%.2f %s' % (
                fen, b.san(want), a['choice'], a['probabilities'].get(want.uci(), 0),
                a.get('confidence', 0), '✓' if ok else '✗'))
    print('  找到杀棋 %d/%d' % (hit, tot))

def _is_mate(b, m):
    b.push(m); r = b.is_checkmate(); b.pop(); return r

TACTICS = [
    ('开局吃兵', 'r1bqkbnr/pppp1ppp/2n5/4p3/3PP3/5N2/PPP2PPP/RNBQKB1R w - - 0 1'),
    ('中局对峙', 'r2q1rk1/ppp2ppp/2n1bn2/3p4/3P4/2N1BN2/PPP2PPP/R2Q1RK1 w - - 0 1'),
    ('可白吃一个后', 'rnb1kbnr/pppp1ppp/8/4p3/6Q1/5q2/PPPPPPPP/RNB1KBNR w - - 0 1'),
    ('后对后', 'r3k2r/ppp2ppp/2n5/3q4/3Q4/2N5/PPP2PPP/R3K2R w - - 0 1'),
    ('王兵残局', '8/8/4k3/8/8/4K3/4P3/8 w - - 0 1'),
    ('可以升变', '8/4P1k1/8/8/8/8/5K2/8 w - - 0 1'),
]

def part_b():
    print('\n== B 两层物质搜索的最佳着法，Jev 选中率 ==')
    tot = hit = 0
    loss = []
    for name, fen in TACTICS:
        b = chess.Board(fen)
        sc = best_material(b)
        top = max(sc.values())
        bests = [m.uci() for m, v in sc.items() if v == top]
        for _ in range(2):
            r = ask(b)
            if '_error' in r: print('  失败', r['_error']); continue
            a = r['answers']['move']
            got = a['choice']
            gv = [v for m, v in sc.items() if m.uci() == got][0]
            hit += got in bests; tot += 1; loss.append(top - gv)
            print('  %-12s 最佳(%d 步并列) 分 %+d | 选 %-6s 分 %+d | 亏 %d | conf %.2f' % (
                name, len(bests), top, got, gv, top - gv, a.get('confidence', 0)))
    print('  选中最佳 %d/%d，平均亏 %.2f 个子（1=一个兵）' % (hit, tot, statistics.mean(loss)))

def one_game(seed):
    random.seed(seed)
    b = chess.Board()
    lat, toks, plies = [], [], 0
    while not b.is_game_over() and plies < 60:
        if b.turn == chess.WHITE:
            r = ask(b)
            if '_error' in r: return {'err': r['_error']}
            lat.append(r['_elapsed']); toks.append(r['usage']['input_tokens'])
            mv = chess.Move.from_uci(r['answers']['move']['choice'])
        else:
            mv = random.choice(list(b.legal_moves))
        b.push(mv); plies += 1
    return {'result': b.result(claim_draw=True), 'over': b.is_game_over(),
            'plies': plies, 'material': material(b, chess.WHITE),
            'lat': lat, 'toks': toks, 'fen': b.fen()}

def part_c(n=4):
    print('\n== C Jev(白) vs 随机走子(黑)，最多 60 手 ==')
    with ThreadPoolExecutor(max_workers=n) as ex:
        gs = list(ex.map(one_game, range(n)))
    for i, g in enumerate(gs):
        if 'err' in g: print('  第%d局失败 %s' % (i, g['err'])); continue
        print('  第%d局 %s%s 共 %d 手，白方净子 %+d，Jev 走了 %d 步，'
              '每步延迟中位 %.2fs，每步输入 %d tok，本局 Jev 成本 $%.5f' % (
                  i, g['result'], '' if g['over'] else '（未终局，按净子看）',
                  g['plies'], g['material'], len(g['lat']),
                  statistics.median(g['lat']), int(statistics.mean(g['toks'])),
                  sum(g['toks']) * 0.042 / 1e6))
    ok = [g for g in gs if 'err' not in g]
    allm = [g['material'] for g in ok]
    alll = [x for g in ok for x in g['lat']]
    print('  %d 局：净子 %s，平均 %+.1f；全部 Jev 步延迟中位 %.2fs；'
          '平均每局 Jev 成本 $%.5f、纯等待 %.0f 秒' % (
              len(ok), allm, statistics.mean(allm), statistics.median(alll),
              statistics.mean([sum(g['toks']) * 0.042 / 1e6 for g in ok]),
              statistics.mean([sum(g['lat']) for g in ok])))
    p = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'game_chess_log.json')
    json.dump(ok, open(p, 'w'), indent=1)
    print('  明细:', p)

def main():
    part_a(); part_b(); part_c()
    print('\n' + jev.spend())

main()
