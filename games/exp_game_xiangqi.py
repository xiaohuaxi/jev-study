"""中国象棋初探：把国际象棋那套「棋库枚举合法着法 → Jev 在清单里挑」原样换成中国象棋。

需要 cchess 与 python-chess：pip install cchess chess
（本文件用 Python 3.13 + cchess 1.25.5 + chess 1.11 跑过）。

  A 看盘：同一局面问六个客观是非题（谁还有车、黑方是否被将军……），真值由棋库给；
  B 规则：B1 不给棋盘，只问规则本身（中国象棋 6 题、国际象棋 3 题）；
          B2 两个棋种的开局局面，各 4 步合法 + 4 步违规；
          B3 中国象棋细则摆进同一个局面：蹇马腿、炮架、兵过河、对脸将、塞象眼、士走斜线；
  C 一步杀：C1 四个「只有一步能杀」的局面，着法写成中文记谱 vs 坐标；
            C2 两个教科书杀型（双车错、马后炮），state 给 FEN vs 给子力清单，各两次。

cchess 有两处坑，都在下面处理了：
  - is_valid_move 只查每个子自己的走法，不查走完后自己的帅会不会被将（对脸将也在这一类），
    完整合法性要再过一道 is_checked_move；判将死那部分是查全的。
  - 它用「帅直接吃将」这种伪着法表示对脸将，列候选时要剔掉。
着法描述只说「某子从哪走到哪」，不写犯了哪条规则——题干里带结论，测的就不是它了。
"""
# 让本脚本从任意目录都能找到仓库根部的 jevkit.py / corpus.py
import sys as _sys, pathlib as _pathlib
_sys.path.insert(0, str(_pathlib.Path(__file__).resolve().parent.parent))
import json, os
import chess, cchess
import jevkit as jev

FILE = 'abcdefghi'
NAME = {'K': '帅', 'A': '仕', 'B': '相', 'N': '马', 'R': '车', 'C': '炮', 'P': '兵',
        'k': '将', 'a': '士', 'b': '象', 'n': '马', 'r': '车', 'c': '炮', 'p': '卒'}
COORDS = '坐标用 ICCS 记法：纵线 a 到 i 从红方左手边数起，横线 0 到 9 从红方底线数起'
HINTS = ('挡', '隔', '过河', '九宫', '直线', '越过', '照面', '中心', '腿', '炮架', '斜')
ASK = '你在下中国象棋，执红。从合法着法里选一步最好的。注意：这里存在一步将死的机会。'
LOG = {}

def sq(p): return '%s%d' % (FILE[p[0]], p[1])

def fen_of(pc, turn='w'):
    rows = []
    for y in range(9, -1, -1):
        row, blank = '', 0
        for x in range(9):
            f = pc.get((x, y))
            if f is None:
                blank += 1
            else:
                if blank: row += str(blank); blank = 0
                row += f
        if blank: row += str(blank)
        rows.append(row)
    return '/'.join(rows) + ' ' + turn

def legal(b, pf, pt):
    """完整合法：单子走法合法，且走完自己不被将（含对脸将）。"""
    return bool(b.is_valid_move(pf, pt)) and not b.is_checked_move(pf, pt)

def red_in_check(fen):
    b = cchess.ChessBoard(fen).copy()
    b.move_player.next()
    return b.is_checking()

def legal_moves(fen):
    """[(iccs, 中文记谱, 起点, 终点, 起点棋子, 终点棋子, 是否一步杀)]"""
    b = cchess.ChessBoard(fen)
    out = []
    for pf, pt in list(b.create_moves()):
        if b.get_fench(pt) == 'k' or not legal(b, pf, pt):
            continue
        mv = cchess.ChessBoard(fen).move(pf, pt)
        out.append((mv.to_iccs(), mv.to_text(), pf, pt, b.get_fench(pf), b.get_fench(pt),
                    bool(mv.is_checking and mv.is_checkmate)))
    return out

def assert_clean(descs):
    for d in descs:
        assert not any(h in d for h in HINTS), '描述里带了规则提示：' + d

def yesno(tag, state, items, truth):
    """items: [(key, 问题)]；truth: {key: bool}。打印逐题并返回答错数。"""
    r = jev.call(state, {k: jev.noul(q) for k, q in items})
    if '_error' in r:
        print('  失败', r['_error']); return None
    wrong, rows = 0, []
    for k, q in items:
        p = r['answers'][k]['noul']; got = p >= 0.5; want = truth[k]
        wrong += got != want
        rows.append({'q': q, 'truth': want, 'p': p})
        print('  %-40s 真值 %-4s 它答 %-4s p=%.2f %s' % (
            q[-40:], '是' if want else '否', '是' if got else '否', p, '✓' if got == want else '✗'))
    print('  → %s 答错 %d/%d\n' % (tag, wrong, len(items)))
    LOG[tag] = rows
    return wrong

# ---------------------------------------------------------------- 局面
PUZZLES = [   # 随机搜出来的「只有一步能杀」局面（搜索时 random.seed(7)），运行时会重新断言
    ('9/9/4ka3/2C4R1/9/8N/9/3K5/7c1/9 w', 'h6e6'),
    ('3cak3/9/8C/3R5/9/9/3N5/9/9/4K4 w', 'd6f6'),
    ('2N6/5a3/5k3/9/9/9/9/1c1K3C1/9/2R6 w', 'c0c7'),
    ('5k3/5a3/9/9/9/9/9/2R6/3c3CN/4K4 w', 'h1f1'),
]
CLASSIC = [   # 帅放在 d0，避开和黑将同线对脸
    ('双车错', '4k4/R8/8R/9/9/9/9/9/9/3K5 w', 'i7i9'),
    ('马后炮', '4k4/9/9/9/5N3/4C4/9/9/9/3K5 w', 'f5e7'),
]

def check_puzzle(fen, want):
    b = cchess.ChessBoard(fen)
    assert not b.is_checking() and not red_in_check(fen), ('起始就在将军', fen)
    ms = legal_moves(fen)
    mates = [m[0] for m in ms if m[6]]
    assert mates == [want], (fen, mates)
    return ms

# ---------------------------------------------------------------- A 看盘
def part_a():
    print('== A 看盘：客观是非题，真值由棋库给 ==')
    fen = PUZZLES[0][0]
    b = cchess.ChessBoard(fen)
    cnt = {f: 0 for f in NAME}
    king = None
    for x in range(9):
        for y in range(10):
            f = b.get_fench((x, y))
            if f: cnt[f] += 1
            if f == 'k': king = (x, y)
    truth = {'check': b.is_checking(), 'red_r': cnt['R'] > 0, 'black_r': cnt['r'] > 0,
             'horse': cnt['N'] > cnt['n'], 'king_e': king[0] == 4, 'two_a': cnt['a'] == 2}
    items = [('check', '黑方此刻是否正被将军？'), ('red_r', '红方盘面上是否还有车？'),
             ('black_r', '黑方盘面上是否还有车？'), ('horse', '红方的马是否比黑方多？'),
             ('king_e', '黑将是否在中路（e 线）上？'), ('two_a', '黑方是否还有两个士？')]
    yesno('A 看盘', {'fen': fen, 'side_to_move': '红方', 'coords': COORDS}, items, truth)

# ---------------------------------------------------------------- B 规则
def part_b():
    print('== B1 不给棋盘，只问规则本身 ==')
    rules = [
        ('xq1', True,  '中国象棋里，马走日字时，如果「马腿」那一格被任何棋子占住，这一步就不能走。这个说法对吗？'),
        ('xq2', True,  '中国象棋里，炮要吃掉对方的子，中间必须正好隔着一个棋子。这个说法对吗？'),
        ('xq3', True,  '中国象棋里，兵（卒）过河之后才可以横着走一格，过河之前只能向前。这个说法对吗？'),
        ('xq4', False, '中国象棋里，士（仕）可以在九宫内横着或竖着走一格。这个说法对吗？'),
        ('xq5', True,  '中国象棋里，相（象）走田字，田字中心那一格有子时就走不过去。这个说法对吗？'),
        ('xq6', False, '中国象棋里，帅和将允许在同一条竖线上直接照面、中间不隔任何棋子。这个说法对吗？'),
        ('ch1', False, '国际象棋里，王车易位时，王可以经过正被对方攻击的格子。这个说法对吗？'),
        ('ch2', True,  '国际象棋里，兵走到对方底线时必须升变成后、车、象或马之一。这个说法对吗？'),
        ('ch3', True,  '国际象棋里，吃过路兵只能在对方兵刚刚一次走两格之后的那一步立刻进行。这个说法对吗？'),
    ]
    yesno('B1 纯规则', {'topic': '棋类规则常识判断'},
          [(k, q) for k, _, q in rules], {k: t for k, t, _ in rules})

    print('== B2 开局局面，4 步合法 + 4 步违规 ==')
    xb = cchess.ChessBoard(cchess.FULL_INIT_FEN)
    xq = [((7, 2), (4, 2)), ((7, 0), (6, 2)), ((4, 3), (4, 4)), ((0, 0), (0, 1)),
          ((7, 0), (7, 1)), ((0, 0), (0, 4)), ((2, 0), (2, 5)), ((4, 0), (6, 0))]
    items, truth = [], {}
    for i, (pf, pt) in enumerate(xq):
        d = '%s从 %s 走到 %s' % (NAME[xb.get_fench(pf)], sq(pf), sq(pt))
        items.append(('x%d' % i, '在当前局面下，这一步是否符合中国象棋规则？' + d))
        truth['x%d' % i] = legal(xb, pf, pt)
    assert sum(truth.values()) == 4
    assert_clean(q for _, q in items)
    yesno('B2 中国象棋开局', {'fen': cchess.FULL_INIT_FEN, 'side_to_move': '红方', 'coords': COORDS},
          items, truth)

    cb = chess.Board()
    ok = {m.uci() for m in cb.legal_moves}
    ch = [('e2 的兵走到 e4', 'e2e4'), ('g1 的马走到 f3', 'g1f3'), ('b1 的马走到 c3', 'b1c3'),
          ('a2 的兵走到 a3', 'a2a3'), ('b1 的马走到 b3', 'b1b3'), ('c1 的象走到 c3', 'c1c3'),
          ('a1 的车走到 a4', 'a1a4'), ('e1 的王走到 e3', 'e1e3')]
    items = [('c%d' % i, '在当前局面下，这一步是否符合国际象棋规则？' + d) for i, (d, _) in enumerate(ch)]
    truth = {'c%d' % i: u in ok for i, (_, u) in enumerate(ch)}
    assert sum(truth.values()) == 4
    yesno('B2 国际象棋开局', {'fen': cb.fen(), 'side_to_move': 'white'}, items, truth)

    print('== B3 中国象棋细则，摆进同一个局面 ==')
    pc = {(4, 9): 'k', (2, 6): 'p', (0, 6): 'p',
          (4, 0): 'K', (5, 0): 'A', (2, 0): 'B', (3, 1): 'P',   # 相 c0 的田字中心 d1 有兵；仕 f0 前面 f1 是空格
          (6, 2): 'N', (6, 3): 'P',                              # 马 g2 的马腿 g3 有兵
          (2, 2): 'C', (0, 2): 'C', (0, 4): 'P',                 # 炮 c2 无炮架；炮 a2 隔兵 a4
          (1, 3): 'P', (7, 5): 'P',                              # 兵 b3 未过河；兵 h5 已过河
          (4, 4): 'N'}                                           # 马 e4 是帅将之间唯一的子
    fen = fen_of(pc)
    assert not cchess.ChessBoard(fen).is_checking() and not red_in_check(fen)
    b = cchess.ChessBoard(fen)
    cases = [((6, 2), (5, 4)), ((2, 2), (2, 6)), ((0, 2), (0, 6)), ((1, 3), (0, 3)),
             ((7, 5), (6, 5)), ((4, 4), (3, 6)), ((2, 0), (4, 2)), ((5, 0), (5, 1))]
    items, truth = [], {}
    for i, (pf, pt) in enumerate(cases):
        eat = '，吃掉对方的%s' % NAME[b.get_fench(pt)] if b.get_fench(pt) else ''
        d = '%s从 %s 走到 %s%s' % (NAME[b.get_fench(pf)], sq(pf), sq(pt), eat)
        items.append(('f%d' % i, '在当前局面下，这一步是否符合中国象棋规则？' + d))
        truth['f%d' % i] = legal(b, pf, pt)
    assert [truth['f%d' % i] for i in range(8)] == [False, False, True, False, True, False, False, False]
    assert_clean(q for _, q in items)
    yesno('B3 中国象棋细则', {'fen': fen, 'side_to_move': '红方', 'coords': COORDS}, items, truth)

# ---------------------------------------------------------------- C 一步杀
def pick(state, crit, want, tag):
    r = jev.call(state, {'move': jev.choice(ASK, crit)})
    if '_error' in r:
        print('  失败', r['_error']); return None
    a = r['answers']['move']
    ok = a['choice'] == want
    print('  [%s] 候选 %2d  正解 %s（%s） 选了 %s（%s） p(正解)=%.2f conf=%.2f %s' % (
        tag, len(crit), want, crit[want], a['choice'], crit.get(a['choice'], '?'),
        a['probabilities'].get(want, 0), a.get('confidence', 0), '✓' if ok else '✗'))
    LOG.setdefault('C', []).append({'tag': tag, 'want': want, 'choice': a['choice'],
                                    'p_want': a['probabilities'].get(want, 0),
                                    'conf': a.get('confidence', 0)})
    return ok

def board_list(fen):
    b = cchess.ChessBoard(fen); red, black = {}, {}
    for x in range(9):
        for y in range(10):
            f = b.get_fench((x, y))
            if f: (red if f.isupper() else black).setdefault(NAME[f], []).append(sq((x, y)))
    return {'coords': COORDS, '红方子力': red, '黑方子力': black, '轮到': '红方'}

def part_c():
    print('== C1 一步杀：着法写成中文记谱 vs 坐标 ==')
    score = {'中文记谱': 0, '坐标': 0}
    for fen, want in PUZZLES:
        ms = check_puzzle(fen, want)
        st = {'fen': fen, 'side_to_move': '红方', 'coords': COORDS,
              'legal_moves_iccs': sorted(m[0] for m in ms)}
        cn = {m[0]: m[1] for m in ms}
        xy = {m[0]: '%s从 %s 走到 %s%s' % (NAME[m[4]], sq(m[2]), sq(m[3]),
                                         '，吃掉对方的%s' % NAME[m[5]] if m[5] else '') for m in ms}
        assert_clean(xy.values())
        score['中文记谱'] += bool(pick(st, cn, want, '中文记谱'))
        score['坐标'] += bool(pick(st, xy, want, '坐标    '))
    print('  → 中文记谱 %d/4，坐标 %d/4\n' % (score['中文记谱'], score['坐标']))

    print('== C2 教科书杀型：state 给 FEN vs 给子力清单，各两次 ==')
    for name, fen, want in CLASSIC:
        ms = check_puzzle(fen, want)
        crit = {m[0]: m[1] for m in ms}
        moves = sorted(crit)
        fen_state = {'fen': fen, 'side_to_move': '红方', 'coords': COORDS, 'legal_moves_iccs': moves}
        list_state = dict(board_list(fen), legal_moves_iccs=moves)
        print('  %s  %s' % (name, fen))
        for label, st in (('FEN    ', fen_state), ('子力清单', list_state)):
            for _ in range(2):
                pick(st, crit, want, '%s·%s' % (name, label))
    print()

def main():
    part_a()
    part_b()
    part_c()
    p = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'game_xiangqi_log.json')
    json.dump(LOG, open(p, 'w'), ensure_ascii=False, indent=1)
    print('明细:', p)
    print(jev.spend())

main()
