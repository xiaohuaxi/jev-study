"""中国象棋 / 国际象棋研究的公共底座：规则、着法描述、state 渲染、选项键、局面特征、两层物质、引擎封装。

给中国象棋实测的三个实验（A 一步杀、B 看盘、C 适配器阶梯）共用；本文件不调 Jev、不花钱。
局面集由 make_positions.py 生成，存在旁边的 xiangqi_positions.json（两棋种都在里面）。

依赖（本文件用 Python 3.13 跑过）：
  python3 -m pip install pyffish==0.0.90 cchess==1.25.5 chess==1.11.2
  引擎 Fairy-Stockfish 14.0.1（brew install fairy-stockfish）；路径可用环境变量 FAIRY_STOCKFISH 指定。

约定（实验脚本都按这个来）：
  - game 取 'xiangqi' 或 'chess'。
  - 着法、格子对外一律用 ICCS：纵线 a–i 从红方左手数起，横线 0–9 从红方底线数起；国际象棋就是 UCI（e2e4、e7e8q，
    易位写王的走法 e1g1）。Fairy-Stockfish 的中国象棋横线是 1–10，换算只在本文件内部做（to_fsf / from_fsf）。
  - 规则权威是 pyffish：合法着法、将军、将死（受将且无着）、困毙（未受将且无着）都以它为准。
    cchess 只出中文记谱，python-chess 只出 SAN；crosscheck() 逐局面比对两边的合法着法、将军、将死、困毙和记谱。
  - FEN 一律用 pyffish 规范化后的完整 FEN（norm()）。中国象棋 FEN 第一段从横线 9（黑方底线）写起，w = 红方走。
  - 局面特征、两层物质都从「行棋方」视角算（正数 = 行棋方占优）。

按实验找接口：
  A 一步杀     describe_all(风格, 语言) / options(键与打乱，键只随局面和 rep 变、与臂无关) / state(四种形态)
               / features / mate_moves / audit_mate
  B 看盘       parse（格子真值）/ pseudo_moves + violation（违规着法按类型出题）/ capturable（对方能否吃掉某子）
  C 适配器     facts（L1：吃什么、将军、将死）/ safety（L2：走完哪些子会被吃、对方最多吃回多少）/ two_ply（L3）
               baseline（random / greedy1 / greedy2）/ Engine.analyse、score_moves + losses（厘兵损失，可 cap 封顶）
               / is_mate_score（杀棋分不当普通厘兵用）
  局面集       load_positions / select（默认不含无效旧局面）/ verify_position

修订 1（独立审查后）：选项键改成纯辅音、跨臂同键；select 默认排除无效旧局面；middle / gain 排除强制杀。

用法：
  python3 games/xiangqi/boards.py selftest           跑全部断言：规则细则、记谱、描述泄露、渲染、选项键、违规分类、两层物质、引擎可复现、局面集逐个复核
  python3 games/xiangqi/boards.py selftest --quick   同上，但随机对局交叉比对只跑少量
  python3 games/xiangqi/boards.py show GAME FEN      打印一个局面的特征与各档描述（调试用）

cchess 的坑（读 1.25.5 源码核实，下面的包装都处理了）：
  - is_valid_move 不查走完后自己被将（含对脸将），完整合法要再过 is_checked_move；
  - 对脸将用「帅将互吃」的伪着表示，过滤要写成目标子 .lower() == 'k'（红黑都要滤）；
  - is_checkmate() 只判「对方无合法着」，会把困毙也算成将死；本文件的将死 / 困毙一律用 pyffish 判；
  - 中文记谱：同一纵线两子的前 / 后正确；多路兵（两条纵线各有两个以上兵）会给出重复的「前兵进一」，
    三子同线源码留了 TODO。cn_ok() 把这两种局面标出来，局面集里不收；其余局面用 cn_text() 独立实现逐步核对。
pyffish 的坑：WXF 记谱在「炮隔着同线的另一个炮吃子」时省掉前 / 后前缀（给 'C8+5'），所以只拿它核对后半截。
"""
import hashlib, json, os, random, re, shutil, subprocess, sys
import pyffish as sf
import cchess
import chess

XQ, CH = 'xiangqi', 'chess'
GAMES = (XQ, CH)
FILES = {XQ: 'abcdefghi', CH: 'abcdefgh'}
TOP = {XQ: 9, CH: 8}          # FEN 第一行对应的横线号
BOTTOM = {XQ: 0, CH: 1}
START = {g: sf.start_fen(g) for g in GAMES}
HERE = os.path.dirname(os.path.abspath(__file__))
POSITIONS = os.path.join(HERE, 'xiangqi_positions.json')

# ---------------------------------------------------------------- 坐标
_ICCS = re.compile(r'^([a-i])(\d)([a-i])(\d)$')
_FSF = re.compile(r'^([a-i])(\d+)([a-i])(\d+)$')


def to_fsf(game, mv):
    """ICCS/UCI -> Fairy-Stockfish 着法。中国象棋横线 +1，国际象棋原样。"""
    if game == CH:
        return mv
    m = _ICCS.match(mv)
    assert m, ('不是 ICCS 着法', mv)
    return '%s%d%s%d' % (m[1], int(m[2]) + 1, m[3], int(m[4]) + 1)


def from_fsf(game, mv):
    """Fairy-Stockfish 着法 -> ICCS/UCI。"""
    if game == CH:
        return mv
    m = _FSF.match(mv)
    assert m, ('不是 Fairy-Stockfish 中国象棋着法', mv)
    y1, y2 = int(m[2]) - 1, int(m[4]) - 1
    assert 0 <= y1 <= 9 and 0 <= y2 <= 9, mv
    return '%s%d%s%d' % (m[1], y1, m[3], y2)


def split_move(mv):
    """'e7e8q' -> ('e7', 'e8', 'q')；没有升变时第三项是 None。两棋种的格子都是「字母 + 一位数字」。"""
    return mv[:2], mv[2:4], (mv[4:] or None)


def xy(sq):
    """'e5' -> (4, 5)：纵线下标从 0 起，横线就是坐标里的数字（中国象棋 0–9，国际象棋 1–8）。"""
    return 'abcdefghi'.index(sq[0]), int(sq[1:])


def sq_of(x, y):
    return 'abcdefghi'[x] + str(y)


# ---------------------------------------------------------------- FEN
def parse(game, fen):
    """FEN -> ({格: 棋子字母}, 行棋方 'w'/'b')。大写 = 红 / 白。"""
    parts = fen.split()
    rows = parts[0].split('/')
    assert len(rows) == TOP[game] - BOTTOM[game] + 1, ('FEN 横线数不对', fen)
    board = {}
    for i, row in enumerate(rows):
        y, x, num = TOP[game] - i, 0, ''
        for ch in row:
            if ch.isdigit():
                num += ch
                continue
            if num:
                x += int(num)
                num = ''
            assert ch.isalpha(), ('FEN 里有不认识的字符', fen)
            board[sq_of(x, y)] = ch
            x += 1
        if num:
            x += int(num)
        assert x == len(FILES[game]), ('FEN 某一行格数不对', fen, row)
    return board, (parts[1] if len(parts) > 1 else 'w')


def board_fen(game, board):
    """{格: 棋子} -> FEN 第一段（parse 的逆运算，自检用）。"""
    rows = []
    for y in range(TOP[game], BOTTOM[game] - 1, -1):
        row, blank = '', 0
        for x in range(len(FILES[game])):
            p = board.get(sq_of(x, y))
            if p is None:
                blank += 1
            else:
                if blank:
                    row += str(blank)
                    blank = 0
                row += p
        rows.append(row + (str(blank) if blank else ''))
    return '/'.join(rows)


def norm(game, fen):
    """校验并返回 pyffish 规范化的完整 FEN（短 FEN 如 '... w' 会补全成 '... w - - 0 1'）。"""
    assert sf.validate_fen(fen, game) == sf.FEN_OK, ('pyffish 不认这个 FEN', game, fen)
    return sf.get_fen(game, fen, [])


def reset_clock(fen):
    """把 FEN 末尾的半回合计数与回合数改成 '0 1'。局面集一律这样存：计数对局面判断无关，却会向模型透露对局阶段，
    还会让引擎评估随计数浮动（实测同一局面计数 0 / 23 / 60 时评估 197 / 250 / 184 厘兵，国际象棋最佳着也变了）。"""
    parts = fen.split()
    assert len(parts) == 6, ('要完整 FEN', fen)
    return ' '.join(parts[:4] + ['0', '1'])


def key_of(fen):
    """去重用：只看棋盘、行棋方（国际象棋再加易位权与过路兵格），忽略步数计数。"""
    return ' '.join(fen.split()[:4])


def is_red(piece):
    return piece.isupper()


# ---------------------------------------------------------------- 规则（pyffish 为准）
def legal(game, fen):
    """全部合法着法（ICCS/UCI），排好序。"""
    return sorted(from_fsf(game, m) for m in sf.legal_moves(game, fen, []))


def play(game, fen, mv, check=True):
    """走一步，返回新 FEN。check=True 时先断言这步合法（pyffish 对非法着法不报错）。"""
    f = to_fsf(game, mv)
    if check:
        assert f in sf.legal_moves(game, fen, []), ('非法着法', game, fen, mv)
    return sf.get_fen(game, fen, [f])


def in_check(game, fen):
    """行棋方此刻是否正被将军。"""
    return sf.gives_check(game, fen, [])


def status(game, fen):
    """'mate'（受将且无着）/ 'stalemate'（困毙：未受将且无着）/ 'check' / 'ok'。
    中国象棋困毙判负、国际象棋困毙（逼和）判和，这里只报事实，胜负由调用方按棋种解释。"""
    moves = sf.legal_moves(game, fen, [])
    chk = sf.gives_check(game, fen, [])
    if not moves:
        return 'mate' if chk else 'stalemate'
    return 'check' if chk else 'ok'


def facts(game, fen, mv, board=None):
    """一步棋的客观事实：走哪个子、吃什么（含过路兵）、是否将军 / 将死 / 困毙、升变、易位时车怎么走。"""
    if board is None:
        board = parse(game, fen)[0]
    fr, to, promo = split_move(mv)
    piece = board[fr]
    cap, cap_sq, ep, castle = board.get(to), to, False, None
    if game == CH and piece in 'Pp' and fr[0] != to[0] and cap is None:
        cap_sq, ep = to[0] + fr[1], True                      # 过路兵：被吃的兵在起点那条横线上
        cap = board.get(cap_sq)
        assert cap is not None and cap in 'Pp', ('过路兵但那格没有兵', fen, mv)
    if game == CH and piece in 'Kk' and abs(xy(fr)[0] - xy(to)[0]) == 2:
        r = fr[1]
        castle = ('h' + r, 'f' + r) if to[0] == 'g' else ('a' + r, 'd' + r)
        assert board.get(castle[0], '').lower() == 'r', ('易位但角上没有车', fen, mv)
    f = to_fsf(game, mv)
    check = sf.gives_check(game, fen, [f])
    replies = sf.legal_moves(game, fen, [f])
    return {'move': mv, 'piece': piece, 'from': fr, 'to': to, 'captured': cap,
            'cap_sq': cap_sq if cap else None, 'ep': ep, 'promo': promo, 'castle': castle,
            'check': check, 'mate': check and not replies, 'stalemate': (not check) and not replies}


def all_facts(game, fen):
    board = parse(game, fen)[0]
    return {m: facts(game, fen, m, board) for m in legal(game, fen)}


def mate_moves(game, fen):
    """一步就能将死对方的全部着法。"""
    out = []
    for m in sf.legal_moves(game, fen, []):
        if sf.gives_check(game, fen, [m]) and not sf.legal_moves(game, fen, [m]):
            out.append(from_fsf(game, m))
    return sorted(out)


def stalemate_moves(game, fen):
    """一步让对方困毙（未受将且无着）的全部着法。中国象棋里这也是赢棋，一步杀局面集要排除它。"""
    out = []
    for m in sf.legal_moves(game, fen, []):
        if not sf.gives_check(game, fen, [m]) and not sf.legal_moves(game, fen, [m]):
            out.append(from_fsf(game, m))
    return sorted(out)


# ---------------------------------------------------------------- 另一个库（交叉比对用）
def _iccs(pf, pt):
    return sq_of(*pf) + sq_of(*pt)


def cchess_legal(fen):
    """cchess 给出的中国象棋合法着法（ICCS 集合）：单子走法 + 走完不自将，并滤掉帅将互吃的伪着（红黑都滤）。"""
    b = cchess.ChessBoard(fen)
    out = set()
    for pf, pt in b.create_moves():
        tgt = b.get_fench(pt)
        if tgt and tgt.lower() == 'k':
            continue
        if not b.is_valid_move(pf, pt) or b.is_checked_move(pf, pt):
            continue
        out.add(_iccs(pf, pt))
    return out


def _cchess_after(b, pf, pt):
    """cchess 里走一步后：(是否将军, 对方是否无合法着)。"""
    b2 = b.copy()
    b2._move_piece(pf, pt)
    chk = b2.is_checking()              # 走子方是否攻击到对方的将
    b2.move_player.next()
    return chk, b2.no_moves()


def _cchess_in_check(b):
    b2 = b.copy()
    b2.move_player.next()
    return b2.is_checking()


CN_NAME = {'K': '帅', 'A': '仕', 'B': '相', 'N': '马', 'R': '车', 'C': '炮', 'P': '兵',
           'k': '将', 'a': '士', 'b': '象', 'n': '马', 'r': '车', 'c': '炮', 'p': '卒'}
_RED_NUM = '零一二三四五六七八九'
_BLACK_NUM = '０１２３４５６７８９'


def wxf(fen, mv):
    """pyffish 给的 WXF 记谱（如 'C2=5'、'R++1'）。"""
    return sf.get_san(XQ, fen, to_fsf(XQ, mv), False, sf.NOTATION_XIANGQI_WXF)


def wxf_tail(w, red):
    """WXF 的最后两位（进 / 退 / 平 + 步数或落点）换成中文，用来核对 cchess 记谱的后半截。
    只核后半截：pyffish 在「炮隔着同线的另一个炮吃子」时会省掉前 / 后前缀（如给 'C8+5' 而不是 'C-+5'），
    按中文记谱规范同线两子一律写前 / 后，所以前半截改由 cn_text() 独立核对。"""
    num = _RED_NUM if red else _BLACK_NUM
    return {'+': '进', '-': '退', '=': '平'}[w[-2]] + num[int(w[-1])]


def cn_notation(fen, mv):
    """cchess 的中文记谱（如 '炮二平五'；黑方用全角数字 '炮８平５'）。实验里 N0 臂用的就是它。"""
    fr, to, _ = split_move(mv)
    m = cchess.ChessBoard(fen).move(xy(fr), xy(to))
    assert m is not None, ('cchess 不认这步', fen, mv)
    return m.to_text()


def cn_text(fen, mv):
    """不经 cchess、按规范独立写出的中文记谱，只用来交叉核对 cn_notation()。
    规范：红方中文数字、黑方全角数字，纵线从各自右手数起；车炮兵帅进退写步数、平写落点纵线，马相仕写落点纵线；
    车马炮兵同一纵线两个时写前 / 后（不写纵线号），仕相不用前后。
    同一纵线三个以上同种子，或两条以上纵线各有两个以上兵，规范写法本文件不实现，返回 None。"""
    board, _ = parse(XQ, fen)
    fr, to, _ = split_move(mv)
    p = board[fr]
    red, kind = is_red(p), p.lower()
    (x1, y1), (x2, y2) = xy(fr), xy(to)
    num = _RED_NUM if red else _BLACK_NUM
    fnum = (lambda x: 9 - x) if red else (lambda x: x + 1)
    name = CN_NAME[p]
    head = name + num[fnum(x1)]
    if kind in 'rncp':
        same = [s for s, q in board.items() if q == p and s[0] == fr[0]]
        if len(same) >= 3:
            return None
        if kind == 'p':
            per_file = {}
            for s, q in board.items():
                if q == p:
                    per_file[s[0]] = per_file.get(s[0], 0) + 1
            if sum(v >= 2 for v in per_file.values()) >= 2:
                return None
        if len(same) == 2:
            oy = xy([s for s in same if s != fr][0])[1]
            head = ('前' if (y1 > oy if red else y1 < oy) else '后') + name
    dy = (y2 - y1) * (1 if red else -1)
    op = '平' if dy == 0 else ('进' if dy > 0 else '退')
    dest = abs(dy) if (kind in 'rcpk' and dy != 0) else fnum(x2)
    return head + op + num[dest]


def cn_ok(fen):
    """这个局面的行棋方全部着法能否用中文记谱规范、无歧义地写出：独立实现都能写（见 cn_text），且 cchess 的写法两两不同。
    局面集里只收 cn_ok 的中国象棋局面。"""
    moves = legal(XQ, fen)
    if any(cn_text(fen, m) is None for m in moves):
        return False
    texts = [cn_notation(fen, m) for m in moves]
    return len(set(texts)) == len(texts)


def crosscheck(game, fen):
    """pyffish 与另一个库逐项比对，返回不一致清单（空列表 = 完全一致）。
    比对：合法着法集合；行棋方是否被将；每步是否将军 / 将死 / 困毙；
    记谱（中国象棋 cchess 中文记谱 vs pyffish WXF 换算；国际象棋 python-chess SAN vs pyffish SAN）。"""
    bad = []
    mine = set(legal(game, fen))
    fx = all_facts(game, fen)
    if game == XQ:
        b = cchess.ChessBoard(fen)
        other = cchess_legal(fen)
        if _cchess_in_check(b) != in_check(game, fen):
            bad.append(('行棋方受将不一致', in_check(game, fen)))
        red = parse(game, fen)[1] == 'w'
        for m in sorted(mine & other):
            fr, to, _ = split_move(m)
            chk, nomv = _cchess_after(b, xy(fr), xy(to))
            f = fx[m]
            if (chk, chk and nomv, (not chk) and nomv) != (f['check'], f['mate'], f['stalemate']):
                bad.append(('将军/将死/困毙不一致', m, (chk, nomv), f))
            c, mine_cn, w = cn_notation(fen, m), cn_text(fen, m), wxf(fen, m)
            if mine_cn is not None and mine_cn != c:
                bad.append(('cchess 中文记谱与独立实现不一致', m, c, mine_cn))
            if not w[0].isdigit() and c[-2:] != wxf_tail(w, red):
                bad.append(('cchess 中文记谱后半截与 WXF 不一致', m, c, w))
    else:
        b = chess.Board(fen)
        other = {m.uci() for m in b.legal_moves}
        if b.is_check() != in_check(game, fen):
            bad.append(('行棋方受将不一致', in_check(game, fen)))
        for m in sorted(mine & other):
            mv = chess.Move.from_uci(m)
            san = b.san(mv)
            b.push(mv)
            got = (b.is_check(), b.is_checkmate(), b.is_stalemate())
            b.pop()
            f = fx[m]
            if got != (f['check'], f['mate'], f['stalemate']):
                bad.append(('将军/将死/困毙不一致', m, got, f))
            if san != sf.get_san(CH, fen, m):
                bad.append(('SAN 不一致', m, san, sf.get_san(CH, fen, m)))
    if mine != other:
        bad.append(('合法着法集合不一致', sorted(mine - other), sorted(other - mine)))
    return bad


# ---------------------------------------------------------------- 着法描述
NAME = {
    (XQ, 'zh'): CN_NAME,
    (XQ, 'en'): {'k': 'King', 'a': 'Advisor', 'b': 'Elephant', 'n': 'Horse', 'r': 'Rook', 'c': 'Cannon', 'p': 'Pawn'},
    (CH, 'zh'): {'k': '王', 'q': '后', 'r': '车', 'b': '象', 'n': '马', 'p': '兵'},
    (CH, 'en'): {'k': 'King', 'q': 'Queen', 'r': 'Rook', 'b': 'Bishop', 'n': 'Knight', 'p': 'Pawn'},
}
STYLES = ('U0', 'U1', 'U2', 'U3', 'coord', 'N0', 'N3')
UNMARKED = ('U0', 'coord', 'N0')     # 无标记臂：不许出现吃子 / 将军 / 将死 / 规则提示
ZH_HINTS = ('挡', '隔', '过河', '九宫', '直线', '越过', '照面', '中心', '腿', '炮架', '斜',
            '牵制', '威胁', '保护', '攻击', '安全', '危险', '逃')
EN_HINTS = ('block', 'jump', 'river', 'palace', 'pin', 'attack', 'threat', 'safe', 'protect', 'defend', 'escape')


def piece_name(game, piece, lang='zh'):
    tab = NAME[(game, lang)]
    if game == XQ and lang == 'zh':
        return tab[piece]
    return tab[piece.lower()]


def describe(game, fen, mv, style, lang='zh', fx=None):
    """一步棋的文字描述。style：
      U0    '车从 h6 走到 e6'
      U1    U0 + '，吃掉对方的马'（吃子时）
      U2    U1 + '，将军'（杀着也只写将军）
      U3    U2，但杀着写 '，将死'
      coord '从 h6 走到 e6'（不含棋子名）
      N0    原生写法、不带标记：国际象棋 SAN 去掉 x + #；中国象棋 cchess 中文记谱
      N3    原生写法原样：国际象棋 SAN（仅国际象棋）
    lang='en' 只用于 U0–U3 与 coord（'Rook from h6 to e6'）。
    国际象棋升变写 '，升变为后'，易位写 '，车从 h1 走到 f1'——这两样不写就会有两步描述相同或描述不全。"""
    f = fx or facts(game, fen, mv)
    if style in ('N0', 'N3'):
        if game == XQ:
            assert style == 'N0', '中国象棋没有 N3'
            return cn_notation(fen, mv)
        san = chess.Board(fen).san(chess.Move.from_uci(mv))
        return san if style == 'N3' else san.replace('x', '').replace('+', '').replace('#', '')
    zh = lang == 'zh'
    if style == 'coord':
        s = ('从 %s 走到 %s' if zh else 'from %s to %s') % (f['from'], f['to'])
    else:
        s = ('%s从 %s 走到 %s' if zh else '%s from %s to %s') % (
            piece_name(game, f['piece'], lang), f['from'], f['to'])
    if f['castle']:
        s += ('，车从 %s 走到 %s' if zh else ', Rook from %s to %s') % f['castle']
    if f['promo']:
        s += ('，升变为%s' if zh else ', promoting to %s') % piece_name(game, f['promo'], lang)
    lvl = int(style[1]) if style[0] == 'U' else 0
    if lvl >= 1 and f['captured']:
        s += ('，吃掉对方的%s' if zh else ", capturing the opponent's %s") % piece_name(game, f['captured'], lang)
    if lvl >= 2 and f['check']:
        if lvl == 3 and f['mate']:
            s += '，将死' if zh else ', checkmate'
        else:
            s += '，将军' if zh else ', check'
    return s


def tags(text, lang):
    """从描述文字里找出泄露标记：{'capture', 'check', 'mate', 'hint'}。lang 取 'zh' / 'en' / 'san'。
    中文里「将」开头时当棋子名（黑将）处理，不算将军标记。"""
    t = set()
    if lang == 'san':
        if 'x' in text: t.add('capture')
        if '+' in text: t.add('check')
        if '#' in text: t.add('mate')
        return t
    if lang == 'zh':
        s = text[1:] if text.startswith('将') else text
        if '吃' in s or '捉' in s: t.add('capture')
        if '将' in s or '照' in s or '军' in s: t.add('check')
        if '杀' in s or '死' in s: t.add('mate')
        if any(h in s for h in ZH_HINTS): t.add('hint')
        return t
    s = text.lower()
    if re.search(r'captur|\btakes?\b', s): t.add('capture')
    if 'check' in s: t.add('check')
    if 'mate' in s: t.add('mate')
    if any(h in s for h in EN_HINTS): t.add('hint')
    return t


def text_lang(game, style, lang):
    if style in ('N0', 'N3'):
        return 'san' if game == CH else 'zh'
    return lang


def assert_marks(game, style, lang, texts, fxs):
    """断言每条描述的标记和这一档应有的完全一致：无标记臂一个都不许有；U1 恰在吃子时写吃；
    U2 恰在将军（含杀着）时写将军、不写将死；U3 恰在杀着时写将死。任何档都不许出现规则提示字眼。"""
    tl = text_lang(game, style, lang)
    for mv, text in texts.items():
        f = fxs[mv]
        got = tags(text, tl)
        cap, chk, mate = f['captured'] is not None, f['check'], f['mate']
        if style in UNMARKED:
            want = set()
        elif style == 'N3':
            want = {'capture'} if cap else set()
            want |= {'mate'} if mate else ({'check'} if chk else set())
        else:
            lvl = int(style[1])
            want = set()
            if lvl >= 1 and cap: want.add('capture')
            if lvl >= 2 and chk: want.add('check')
            if lvl == 3 and mate: want.add('mate')
            if lvl == 3 and mate and tl in ('zh', 'en'):
                got = got - {'check'}      # '将死' / 'checkmate' 本身含「将」/ check，不另算
                want = want - {'check'}
        assert got == want, ('描述标记与档位不符', game, style, lang, mv, text, sorted(got), sorted(want))


def assert_distinct(texts):
    """同一局面里每步描述两两不同。"""
    seen = {}
    for mv, t in texts.items():
        assert t not in seen, ('两步描述相同', seen.get(t), mv, t)
        seen[t] = mv


def describe_all(game, fen, style, lang='zh', fxs=None):
    """{着法: 描述}，全部合法着法；自动断言两两不同、标记与档位一致。"""
    fxs = fxs or all_facts(game, fen)
    texts = {m: describe(game, fen, m, style, lang, fxs[m]) for m in sorted(fxs)}
    assert_distinct(texts)
    assert_marks(game, style, lang, texts, fxs)
    return texts


# ---------------------------------------------------------------- state 渲染
COORDS = {
    (XQ, 'zh'): '坐标用 ICCS 记法：纵线 a 到 i 从红方左手边数起，横线 0 到 9 从红方底线数起',
    (XQ, 'en'): "Coordinates use ICCS notation: files a to i counted from Red's left, ranks 0 to 9 counted from Red's back rank",
    (CH, 'zh'): '坐标用代数记法：纵线 a 到 h 从白方左手边数起，横线 1 到 8 从白方底线数起',
    (CH, 'en'): "Coordinates use algebraic notation: files a to h counted from White's left, ranks 1 to 8 counted from White's back rank",
}
SIDE = {(XQ, 'zh'): ('红方', '黑方'), (XQ, 'en'): ('Red', 'Black'),
        (CH, 'zh'): ('白方', '黑方'), (CH, 'en'): ('White', 'Black')}
LEGEND = {
    (XQ, 'zh'): '大写字母是红方，小写字母是黑方；K 帅/将，A 仕/士，B 相/象，N 马，R 车，C 炮，P 兵/卒；点是空格',
    (XQ, 'en'): 'Uppercase is Red, lowercase is Black; K King, A Advisor, B Elephant, N Horse, R Rook, C Cannon, P Pawn; a dot is an empty point',
    (CH, 'zh'): '大写字母是白方，小写字母是黑方；K 王，Q 后，R 车，B 象，N 马，P 兵；点是空格',
    (CH, 'en'): 'Uppercase is White, lowercase is Black; K King, Q Queen, R Rook, B Bishop, N Knight, P Pawn; a dot is an empty square',
}
ORDER = {XQ: 'KABNRCP', CH: 'KQRBNP'}
FORMS = ('fen', 'cells', 'pieces', 'board')


def _square_order(game):
    return [sq_of(x, y) for y in range(TOP[game], BOTTOM[game] - 1, -1) for x in range(len(FILES[game]))]


def label(game, piece, lang='zh'):
    """'红马' / 'Red Horse' / '白后' / 'White Queen'。"""
    side = SIDE[(game, lang)][0 if is_red(piece) else 1]
    name = piece_name(game, piece, lang)
    return side[0] + name if lang == 'zh' else side + ' ' + name


def char_board(game, board):
    """带坐标的字符棋盘：每行开头是横线号，最后一行是纵线字母。"""
    rows = []
    for y in range(TOP[game], BOTTOM[game] - 1, -1):
        cells = [board.get(sq_of(x, y), '.') for x in range(len(FILES[game]))]
        rows.append('%d %s' % (y, ' '.join(cells)))
    rows.append('  ' + ' '.join(FILES[game]))
    return '\n'.join(rows)


def state(game, fen, form='fen', lang='zh'):
    """给 Jev 的 state。四种形态（都附行棋方与坐标约定一句，不放合法着法清单）：
      fen    {'fen': 完整 FEN}
      cells  {'cells': {'e5': '红马', ...}}（只列有子的格，按横线从上到下、纵线从左到右）
      pieces {'pieces': {'红方': {'车': ['a8', 'i7'], ...}, '黑方': {...}}}
      board  {'board': 带坐标字符棋盘, 'legend': 字母图例}"""
    board, stm = parse(game, fen)
    red, black = SIDE[(game, lang)]
    st = {'side_to_move': red if stm == 'w' else black, 'coords': COORDS[(game, lang)]}
    if form == 'fen':
        st['fen'] = fen
    elif form == 'cells':
        st['cells'] = {s: label(game, board[s], lang) for s in _square_order(game) if s in board}
    elif form == 'pieces':
        out = {red: {}, black: {}}
        for letter in ORDER[game]:
            for side, p in ((red, letter), (black, letter.lower())):
                sqs = sorted((s for s in board if board[s] == p), key=lambda s: (xy(s)[0], xy(s)[1]))
                if sqs:
                    out[side][piece_name(game, p, lang)] = sqs
        st['pieces'] = out
    elif form == 'board':
        st['board'] = char_board(game, board)
        st['legend'] = LEGEND[(game, lang)]
    else:
        raise ValueError(form)
    return st


# ---------------------------------------------------------------- 选项键
# 键 = 4 个互不相同的辅音字母。字母表去掉了元音和 y（拼不出英文词、拼音音节）、x（SAN 的吃子符号）、
# 两棋种的棋子字母 k q r b n p c a，所以只剩下面 12 个；不含数字，也就不会像坐标。
KEY_LETTERS = 'dfghjlmstvwz'
# 排除表：键里含有下面任何一串就不用。收的是只由上面字母能拼出的常见缩写、语气词、网络用语（含拼音首字母缩写），
# 以及几个和棋局沾边的拼音首字母（js 将死 / 绝杀，zj 照将，gm / fm 国际象棋称号）。另外排除键盘上连着的三个字母（sdf、fgh…）。
KEY_BLOCK = ('hm', 'vs', 'md', 'js', 'zj', 'gm', 'fm',
             'wtf', 'smh', 'fml', 'ftw', 'fwd', 'ltd', 'gmt', 'gfw', 'mtv', 'gsm', 'dms', 'jdm', 'sfw', 'wfh', 'dtf',
             'tmd', 'zsm', 'jms', 'dvd', 'hdd', 'ssd', 'sms', 'hdtv', 'html', 'glhf', 'hmm', 'shh', 'zzz')
_KB_ROW = 'sdfghj'                     # 键盘中排里本字母表连续的一段（字母表里其余字母在键盘上不相邻）
KEY_RUNS = tuple(_KB_ROW[i:i + 3] for i in range(len(_KB_ROW) - 2)) + \
    tuple(_KB_ROW[::-1][i:i + 3] for i in range(len(_KB_ROW) - 2))


def seed_of(*parts):
    """由若干部分算出稳定的整数种子（与 Python 的 hash 随机化无关）。"""
    return int.from_bytes(hashlib.sha256('|'.join(map(str, parts)).encode()).digest()[:8], 'big')


def key_ok(k):
    """一个键是否合格：4 个互不相同的 KEY_LETTERS 字母，不含 KEY_BLOCK / KEY_RUNS 里的任何一串。"""
    return (len(k) == 4 and len(set(k)) == 4 and all(c in KEY_LETTERS for c in k)
            and not any(b in k for b in KEY_BLOCK + KEY_RUNS))


def _key_pool():
    if not _POOL:
        import itertools
        _POOL.extend(k for k in (''.join(t) for t in itertools.permutations(KEY_LETTERS, 4)) if key_ok(k))
    return _POOL


_POOL = []
_MOVE_SPACE = 8100 + 216               # 所有可能的着法写法数：格 a–i × 0–9 两两组合 + 国际象棋升变


def _move_index(mv):
    """着法写法 → 0.._MOVE_SPACE-1 的固定编号（两棋种共用一套，不看局面）。"""
    m = re.fullmatch(r'([a-i])(\d)([a-i])(\d)([qrbn]?)', mv)
    assert m, ('不是 ICCS / UCI 着法', mv)
    ff, fr, tf, tr, pr = 'abcdefghi'.index(m[1]), int(m[2]), 'abcdefghi'.index(m[3]), int(m[4]), m[5]
    if not pr:
        return (ff * 10 + fr) * 90 + tf * 10 + tr
    assert abs(tf - ff) <= 1 and tr in (1, 8), ('升变写法不对', mv)
    return 8100 + ((ff * 3 + tf - ff + 1) * 2 + (tr == 8)) * 4 + 'qrbn'.index(pr)


def option_keys(n, *seed_parts):
    """n 个两两不同的无意义键（如 'dvlz'），由 seed_parts 固定种子从键池里抽。键的规则见 key_ok。"""
    return random.Random(seed_of('keys', *seed_parts)).sample(_key_pool(), n)


def options(texts, pos_id, arm=None, rep=0):
    """texts: {着法: 描述}。返回 (criteria, key_to_move)：criteria = {键: 描述}（已打乱），key_to_move = {键: 着法}。
    - 键 ↔ 着法：只由 (局面, rep) 决定，与臂无关，也与 texts 里有哪些着法无关——同一局面同一 rep 下，
      各臂（各描述档、各 state 形态、中英文）里同一步着法永远是同一个键，臂间差异里不混进键名。
      做法：每个 (局面, rep) 把键池整体打乱一次，着法按固定编号取第几个键，所以不同着法必然不同键。
    - 顺序：也只由 (局面, rep) 决定，同一局面同一 rep 下各臂的选项顺序相同，只有描述文字不同。
    - 换 rep：映射和顺序都换，重复请求取平均时用。
    - arm 参数保留只为兼容旧调用，不再影响任何东西（修订 1 之前键和顺序按臂换）。"""
    pool = _key_pool()
    assert len(pool) >= _MOVE_SPACE, '键池比着法编号空间小，不能保证不同着法不同键'
    perm = pool[:]
    random.Random(seed_of('keymap', pos_id, rep)).shuffle(perm)
    moves = sorted(texts)
    random.Random(seed_of('order', pos_id, rep)).shuffle(moves)
    crit, k2m = {}, {}
    for mv in moves:
        k = perm[_move_index(mv)]
        crit[k] = texts[mv]
        k2m[k] = mv
    assert len(crit) == len(texts)
    return crit, k2m


# ---------------------------------------------------------------- 子力与局面特征
XQ_VAL = {'r': 9, 'n': 4, 'c': 4.5, 'a': 2, 'b': 2, 'p': 1, 'k': 0}
CH_VAL = {'p': 1, 'n': 3, 'b': 3, 'r': 5, 'q': 9, 'k': 0}
MATE_SCORE = 1000      # 两层物质里「一步杀」的分值


def value(game, piece, sq):
    """子值：中国象棋车 9、马 4、炮 4.5、仕相 2、兵 1（过河 2）；国际象棋 1/3/3/5/9，王 0。"""
    p = piece.lower()
    if game == CH:
        return CH_VAL[p]
    if p == 'p':
        y = xy(sq)[1]
        return 2 if (y >= 5 if is_red(piece) else y <= 4) else 1
    return XQ_VAL[p]


def material(game, board):
    """红（白）减黑的子力差。"""
    return sum(value(game, p, s) * (1 if is_red(p) else -1) for s, p in board.items())


def escapes(game, fen):
    """对方将 / 王此刻的逃格数：把行棋权交给对方（空着），数它的王一步能合法走到的格（国际象棋不含易位）。
    行棋方正被将时空着不合法，返回 None。"""
    if in_check(game, fen):
        return None
    board, stm = parse(game, fen)
    parts = fen.split()
    parts[1] = 'b' if stm == 'w' else 'w'
    if game == CH:
        parts[3] = '-'
    nf = ' '.join(parts)
    king = 'k' if stm == 'w' else 'K'
    ksq = [s for s, p in board.items() if p == king]
    assert len(ksq) == 1, fen
    kx, ky = xy(ksq[0])
    n = 0
    for m in legal(game, nf):
        fr, to, _ = split_move(m)
        if fr == ksq[0] and max(abs(xy(to)[0] - kx), abs(xy(to)[1] - ky)) == 1:
            n += 1
    return n


def features(game, fen):
    """局面特征（行棋方视角）：合法着法数、将军着法数、吃子着法数、一步杀数、一步困毙数、子力数（含将帅）、
    物质差、对方将 / 王逃格数；恰有一步杀时再给杀着、走杀着的子、杀着是否吃子。"""
    board, stm = parse(game, fen)
    fxs = all_facts(game, fen)
    sign = 1 if stm == 'w' else -1
    mates = [f for f in fxs.values() if f['mate']]
    ft = {'legal': len(fxs),
          'checks': sum(f['check'] for f in fxs.values()),
          'captures': sum(f['captured'] is not None for f in fxs.values()),
          'mates': len(mates),
          'stalemates': sum(f['stalemate'] for f in fxs.values()),
          'pieces': len(board),
          'material': sign * material(game, board),
          'in_check': in_check(game, fen),
          'escapes': escapes(game, fen)}
    if len(mates) == 1:
        f = mates[0]
        ft.update(mate_move=f['move'], mate_piece=f['piece'].upper(),
                  mate_capture=f['captured'] is not None,
                  mate_captured=f['captured'].upper() if f['captured'] else None)
    return ft


# ---------------------------------------------------------------- 两层物质与安全事实
def _gain_of(game, board, mv):
    """在 board 上走 mv，走子方净增的物质：吃到的子值 + 自己这个子的升值（中国象棋兵过河、国际象棋升变）。"""
    fr, to, promo = split_move(mv)
    piece = board[fr]
    cap_sq = to
    cap = board.get(to)
    if game == CH and piece in 'Pp' and fr[0] != to[0] and cap is None:
        cap_sq = to[0] + fr[1]
        cap = board.get(cap_sq)
    g = value(game, cap, cap_sq) if cap else 0
    newp = (promo.upper() if is_red(piece) else promo) if promo else piece
    return g + value(game, newp, to) - value(game, piece, fr), (cap, cap_sq)


def safety(game, fen, mv):
    """走完 mv 之后的 L2 安全事实（行棋方视角）：
      threatened    对方下一步能吃掉的我方子 [{'square', 'piece', 'value'}]，按子值从大到小
      max_recapture 对方吃子回应里最多能吃回多少（被吃子的子值）
      best_reply    对方让我方物质降得最多的那步（含兵过河、升变），reply_gain 是降了多少；降 0 时 best_reply 为 None
      after         走完 mv 时的物质差；two_ply = after - reply_gain（两层物质值）；gain = two_ply - 走之前的物质差
    我方一步杀：two_ply = MATE_SCORE；让对方困毙：中国象棋同样记 MATE_SCORE（困毙判负），国际象棋记 0（逼和）。"""
    board, stm = parse(game, fen)
    sign = 1 if stm == 'w' else -1
    base = sign * material(game, board)
    f = to_fsf(game, mv)
    fen1 = sf.get_fen(game, fen, [f])
    b1 = parse(game, fen1)[0]
    after = sign * material(game, b1)
    replies = [from_fsf(game, r) for r in sf.legal_moves(game, fen1, [])]
    out = {'after': after, 'threatened': [], 'max_recapture': 0, 'best_reply': None, 'reply_gain': 0}
    if not replies:
        mated = sf.gives_check(game, fen1, [])
        out['two_ply'] = MATE_SCORE if (mated or game == XQ) else 0
        out['gain'] = out['two_ply'] - base
        out['end'] = 'mate' if mated else 'stalemate'
        return out
    threat = {}
    best, best_gain = None, None
    for r in replies:
        g, (cap, cap_sq) = _gain_of(game, b1, r)
        if cap:
            v = value(game, cap, cap_sq)
            threat[cap_sq] = {'square': cap_sq, 'piece': cap, 'value': v}
            out['max_recapture'] = max(out['max_recapture'], v)
        if best_gain is None or g > best_gain:
            best, best_gain = r, g
    out['threatened'] = sorted(threat.values(), key=lambda d: (-d['value'], d['square']))
    out['best_reply'], out['reply_gain'] = (best if best_gain > 0 else None), best_gain
    out['two_ply'] = after - best_gain
    out['gain'] = out['two_ply'] - base
    return out


def two_ply(game, fen):
    """{着法: 两层物质净得}（= safety()['gain']）：我走一步，对方用对它最有利的一步应对后，物质差比现在多了多少。"""
    return {m: safety(game, fen, m)['gain'] for m in legal(game, fen)}


def two_ply_slow(game, fen):
    """两层物质的笨办法：每个应对都真走出来再数子。只给自检用，核对 two_ply() 的快算法。"""
    board, stm = parse(game, fen)
    sign = 1 if stm == 'w' else -1
    base = sign * material(game, board)
    out = {}
    for m in legal(game, fen):
        fen1 = play(game, fen, m)
        rs = legal(game, fen1)
        if not rs:
            v = MATE_SCORE if (in_check(game, fen1) or game == XQ) else 0
        else:
            v = min(sign * material(game, parse(game, play(game, fen1, r, check=False))[0]) for r in rs)
        out[m] = v - base
    return out


# ---------------------------------------------------------------- 摆法核对
_ADVISOR_PTS = {'A': {'d0', 'f0', 'e1', 'd2', 'f2'}, 'a': {'d9', 'f9', 'e8', 'd7', 'f7'}}
_ELEPHANT_PTS = {'B': {'c0', 'g0', 'a2', 'e2', 'i2', 'c4', 'g4'}, 'b': {'c9', 'g9', 'a7', 'e7', 'i7', 'c5', 'g5'}}
_MAX_COUNT = {XQ: {'k': 1, 'a': 2, 'b': 2, 'n': 2, 'r': 2, 'c': 2, 'p': 5}, CH: {'k': 1, 'p': 8}}


def placement_issues(game, fen):
    """棋子摆在正常对局到不了的位置的清单（空 = 没发现）。中国象棋：仕士只能在各自 5 个点、相象 7 个点、
    将帅在九宫、未过河的兵卒只能在原来的五条纵线且不在起始横线之后、各子数量不超编；国际象棋：兵不在底线、各一个王。
    这类局面上 cchess 与 pyffish 的判断会分歧（例如 cchess 认为不在 5 个点上的士动不了，pyffish 认为它能在九宫里斜走）。"""
    board, _ = parse(game, fen)
    out, cnt = [], {}
    for sq, p in sorted(board.items()):
        cnt[p] = cnt.get(p, 0) + 1
        x, y = xy(sq)
        if game == XQ:
            k = p.lower()
            if k == 'a' and sq not in _ADVISOR_PTS[p]:
                out.append('%s在 %s（只能在 %s）' % (CN_NAME[p], sq, '/'.join(sorted(_ADVISOR_PTS[p]))))
            if k == 'b' and sq not in _ELEPHANT_PTS[p]:
                out.append('%s在 %s（只能在 %s）' % (CN_NAME[p], sq, '/'.join(sorted(_ELEPHANT_PTS[p]))))
            if k == 'k' and not (3 <= x <= 5 and (y <= 2 if is_red(p) else y >= 7)):
                out.append('%s在九宫外 %s' % (CN_NAME[p], sq))
            if k == 'p':
                crossed = y >= 5 if is_red(p) else y <= 4
                behind = y < 3 if is_red(p) else y > 6
                if behind or (not crossed and sq[0] not in 'acegi'):
                    out.append('未过河的%s在 %s（到不了）' % (CN_NAME[p], sq))
        elif p in 'Pp' and y in (1, 8):
            out.append('兵在底线 %s' % sq)
    for p, c in cnt.items():
        lim = _MAX_COUNT[game].get(p.lower())
        if lim and c > lim:
            out.append('%s有 %d 个' % (piece_name(game, p), c))
    for k in ('K', 'k'):
        if cnt.get(k, 0) != 1:
            out.append('%s不是正好一个' % piece_name(game, k))
    return out


def audit_mate(game, fen, answer):
    """核对一道「一步杀」题，返回问题清单（空 = 干净）：摆法到不了、起始受将、answer 按 pyffish 不是杀、另有杀着、
    中国象棋另有一步困毙（也判胜）、两库判断不一致。旧局面入库时用它把问题原样记下来。"""
    issues = ['摆法：' + s for s in placement_issues(game, fen)]
    if in_check(game, fen):
        issues.append('起始局面行棋方正被将')
    mm = mate_moves(game, fen)
    if answer not in mm:
        issues.append('按 pyffish 这步不是杀：%s 之后对方还能走 %s' % (answer, ' '.join(legal(game, play(game, fen, answer)))))
    if [m for m in mm if m != answer]:
        issues.append('另有杀着 %s' % ' '.join(m for m in mm if m != answer))
    if game == XQ and stalemate_moves(game, fen):
        issues.append('另有一步困毙 %s（中国象棋困毙也判胜）' % ' '.join(stalemate_moves(game, fen)))
    for b in crosscheck(game, fen):
        issues.append('两库不一致：%s %s' % (b[0], b[1]))
    return issues


# ---------------------------------------------------------------- 违规分类（实验 B2 出题用）
VIOLATIONS = {
    'own': '目标格有己方子', 'shape': '不合这个子的走法', 'palace': '出九宫', 'river': '相过河',
    'eye': '塞象眼', 'leg': '蹩马腿', 'jump': '越子', 'screen0': '炮吃子没有炮架', 'screen2': '炮隔两个以上的子吃子',
    'pawn_side': '兵未过河就横走', 'pawn_back': '兵后退', 'facing': '走完帅将照面', 'self_check': '走完自己被将',
    'pawn_block': '兵前方有子', 'castle': '不满足易位条件', 'pin': '被牵制的子离开牵制线', 'king_attacked': '王走进被攻击的格',
}


def _between(a, b):
    """同一横线 / 纵线 / 斜线上 a、b 之间的格（不含两端）；不共线返回 None。"""
    (x1, y1), (x2, y2) = xy(a), xy(b)
    dx, dy = x2 - x1, y2 - y1
    if not (dx == 0 or dy == 0 or abs(dx) == abs(dy)):
        return None
    n = max(abs(dx), abs(dy))
    sx, sy = (dx > 0) - (dx < 0), (dy > 0) - (dy < 0)
    return [sq_of(x1 + sx * i, y1 + sy * i) for i in range(1, n)]


def _in_palace(sq, red):
    x, y = xy(sq)
    return 3 <= x <= 5 and (y <= 2 if red else y >= 7)


def violation(game, fen, mv):
    """行棋方走 mv 犯了哪条规则：返回 VIOLATIONS 里的键，合法返回 None。
    先按棋子走法查几何（走形、九宫、过河、象眼、马腿、越子、炮架、兵的方向），几何没问题再看走完是否照面 / 自将。
    结论与 pyffish 的合法着法集合逐一对得上（selftest 在随机局面的全部「起点有己方子」的着法上核对）。"""
    board, stm = parse(game, fen)
    fr, to, promo = split_move(mv)
    p = board.get(fr)
    assert p is not None and is_red(p) == (stm == 'w'), ('起点不是行棋方的子', fen, mv)
    red, kind = is_red(p), p.lower()
    tgt = board.get(to)
    if tgt is not None and is_red(tgt) == red:
        return 'own'
    (x1, y1), (x2, y2) = xy(fr), xy(to)
    dx, dy = x2 - x1, y2 - y1
    adx, ady = abs(dx), abs(dy)
    fwd = dy if red else -dy
    path = _between(fr, to)
    if game == XQ:
        if kind == 'k':
            if adx + ady != 1:
                return 'shape'
            if not _in_palace(to, red):
                return 'palace'
        elif kind == 'a':
            if (adx, ady) != (1, 1):
                return 'shape'
            if not _in_palace(to, red):
                return 'palace'
        elif kind == 'b':
            if (adx, ady) != (2, 2):
                return 'shape'
            if (y2 >= 5) if red else (y2 <= 4):
                return 'river'
            if board.get(sq_of(x1 + dx // 2, y1 + dy // 2)):
                return 'eye'
        elif kind == 'n':
            if sorted((adx, ady)) != [1, 2]:
                return 'shape'
            leg = sq_of(x1 + (dx // 2 if adx == 2 else 0), y1 + (dy // 2 if ady == 2 else 0))
            if board.get(leg):
                return 'leg'
        elif kind == 'r':
            if dx and dy:
                return 'shape'
            if any(board.get(s) for s in path):
                return 'jump'
        elif kind == 'c':
            if dx and dy:
                return 'shape'
            n = sum(1 for s in path if board.get(s))
            if tgt is None and n:
                return 'jump'
            if tgt is not None and n == 0:
                return 'screen0'
            if tgt is not None and n >= 2:
                return 'screen2'
        elif kind == 'p':
            crossed = (y1 >= 5) if red else (y1 <= 4)
            if adx + ady != 1:
                return 'shape'
            if fwd < 0:
                return 'pawn_back'
            if dy == 0 and not crossed:
                return 'pawn_side'
        after = dict(board)
        del after[fr]
        after[to] = p
        ks = {q: s for s, q in after.items() if q in 'Kk'}
        if ks['K'][0] == ks['k'][0] and not any(after.get(s) for s in _between(ks['K'], ks['k'])):
            return 'facing'
        return None if mv in legal(game, fen) else 'self_check'
    # 国际象棋
    if kind == 'n':
        if sorted((adx, ady)) != [1, 2]:
            return 'shape'
    elif kind in 'brq':
        ok = {'b': adx == ady, 'r': dx == 0 or dy == 0, 'q': adx == ady or dx == 0 or dy == 0}[kind]
        if not ok or (adx == 0 and ady == 0):
            return 'shape'
        if any(board.get(s) for s in path):
            return 'jump'
    elif kind == 'k':
        if adx == 2 and dy == 0 and y1 == (1 if red else 8) and x1 == 4:
            return None if mv in legal(game, fen) else 'castle'
        if max(adx, ady) != 1:
            return 'shape'
    elif kind == 'p':
        start = 2 if red else 7
        if dx == 0 and fwd == 1:
            if tgt is not None:
                return 'pawn_block'
        elif dx == 0 and fwd == 2 and y1 == start:
            if tgt is not None or board.get(sq_of(x1, y1 + (1 if red else -1))):
                return 'pawn_block'
        elif adx == 1 and fwd == 1:
            parts = fen.split()
            if tgt is None and parts[3] != to:
                return 'shape'
        else:
            return 'shape'
        if (y2 == (8 if red else 1)) != bool(promo):
            return 'shape'
    if mv in legal(game, fen):
        return None
    if kind == 'k':
        return 'king_attacked'
    b = chess.Board(fen)
    if b.is_pinned(b.turn, chess.parse_square(fr)) and not b.is_check():
        return 'pin'
    return 'self_check'


def pseudo_moves(game, fen):
    """行棋方每个子到棋盘上每一格（不含原地）的全部「着法」，附 violation() 结论：{着法: None 或违规键}。
    国际象棋兵走到底线时只列升变成后的写法。实验 B2 从这里按违规类型平衡抽题。"""
    board, stm = parse(game, fen)
    sqs = [sq_of(x, y) for x in range(len(FILES[game])) for y in range(BOTTOM[game], TOP[game] + 1)]
    out = {}
    for fr, p in board.items():
        if is_red(p) != (stm == 'w'):
            continue
        for to in sqs:
            if to == fr:
                continue
            mv = fr + to
            if game == CH and p in 'Pp' and to[1] in '18':
                mv += 'q'
            out[mv] = violation(game, fen, mv)
    return out


def capturable(game, fen, sq):
    """假如轮到对方走，对方能否合法吃掉 sq 上的行棋方棋子（空着法，含牵制、自将等限制）。实验 B3 的真值。
    行棋方正被将时空着不合法，报错。"""
    assert not in_check(game, fen), '行棋方正被将，不能用空着判断'
    board, stm = parse(game, fen)
    assert sq in board and is_red(board[sq]) == (stm == 'w'), ('那格不是行棋方的子', sq)
    parts = fen.split()
    parts[1] = 'b' if stm == 'w' else 'w'
    if game == CH:
        parts[3] = '-'
    return any(m[2:4] == sq for m in legal(game, ' '.join(parts)))


# ---------------------------------------------------------------- 确定性基线（实验 C，不花钱）
BASELINES = ('random', 'greedy1', 'greedy2')


def baseline(game, fen, kind, rng):
    """免费基线挑一步。rng 是 random.Random（调用方按局面 / 对局固定种子）。并列时一律在并列者里随机。
      random   合法着法里均匀随机
      greedy1  贪心-L1：能杀就杀 > 吃子值最大的 > 将军 > 随机（只用 L1 事实：吃什么、是否将军、是否将死）
      greedy2  贪心-L2：两层物质净得最大（two_ply；一步杀记 MATE_SCORE 自然排第一）"""
    moves = legal(game, fen)
    if kind == 'random':
        return rng.choice(moves)
    if kind == 'greedy1':
        board = parse(game, fen)[0]
        fxs = {m: facts(game, fen, m, board) for m in moves}
        mates = [m for m in moves if fxs[m]['mate']]
        if mates:
            return rng.choice(mates)
        caps = {m: value(game, fxs[m]['captured'], fxs[m]['cap_sq']) for m in moves if fxs[m]['captured']}
        if caps:
            top = max(caps.values())
            return rng.choice([m for m in moves if caps.get(m) == top])
        checks = [m for m in moves if fxs[m]['check']]
        return rng.choice(checks or moves)
    if kind == 'greedy2':
        g = two_ply(game, fen)
        top = max(g.values())
        return rng.choice([m for m in moves if g[m] == top])
    raise ValueError(kind)


# ---------------------------------------------------------------- 引擎
MATE_CP = 32000      # 杀棋分：「N 步杀」记 ±(MATE_CP - N)
MATE_BOUND = MATE_CP - 1000    # 绝对值 ≥ 它的都是杀棋分（is_mate_score）
DEPTH = 12
HASH_MB = 16


def engine_path():
    return os.environ.get('FAIRY_STOCKFISH') or shutil.which('fairy-stockfish') or '/opt/homebrew/bin/fairy-stockfish'


class Engine:
    """Fairy-Stockfish 常驻进程：固定深度、Threads=1、固定 Hash。评估一律是行棋方视角的厘兵，杀棋分见 MATE_CP。
    可复现：每次搜索前先重设 Threads=1（重建搜索线程）再 ucinewgame。只发 ucinewgame 不够——实测中国象棋里
    同一局面先搜过别的局面再搜，分数会差几到二十几厘兵、主变也不同（国际象棋没有这个问题），推测是每线程的缓存表
    ucinewgame 不清；重建线程后结果只取决于局面和深度，与调用顺序、进程无关（selftest 打乱顺序、穿插别的搜索来验证）。
    两棋种都是 classical 评估（本机没有 NNUE 网络文件，引擎自报 classical evaluation enabled），口径一致。
    弱档对手别用 Skill Level：实测 Skill 0 同局面同深度、10 个新进程给出 4 种着法，不可复现；
    改用 top(fen, k, depth) + 按对局固定种子的随机数挑（make_positions.py 的自对弈就是这么做的）。
    用法：with Engine('xiangqi') as e: e.analyse(fen)"""

    def __init__(self, game, depth=DEPTH, hash_mb=HASH_MB, path=None):
        self.game, self.depth, self.hash_mb = game, depth, hash_mb
        self.p = subprocess.Popen([path or engine_path()], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                  stderr=subprocess.DEVNULL, text=True, bufsize=1)
        self._send('uci')
        head = self._until('uciok')
        self.id = next((l[8:] for l in head if l.startswith('id name ')), '?')
        for k, v in (('UCI_Variant', game), ('Threads', 1), ('Hash', hash_mb), ('MultiPV', 1)):
            self._send('setoption name %s value %s' % (k, v))
        self.multipv = 1
        self._send('isready')
        self._until('readyok')

    def _send(self, s):
        self.p.stdin.write(s + '\n')
        self.p.stdin.flush()

    def _until(self, prefix):
        lines = []
        while True:
            line = self.p.stdout.readline()
            if not line:
                raise RuntimeError('引擎进程意外退出')
            line = line.strip()
            lines.append(line)
            if line.startswith(prefix):
                return lines

    def _go(self, fen, depth, searchmoves=None, multipv=1):
        if multipv != self.multipv:
            self._send('setoption name MultiPV value %d' % multipv)
            self.multipv = multipv
        self._send('setoption name Threads value 1')   # 重建线程：连带清掉每线程的缓存表（ucinewgame 清不干净，见类说明）
        self._send('ucinewgame')
        self._send('isready')
        self._until('readyok')
        self._send('position fen ' + fen)
        cmd = 'go depth %d' % depth
        if searchmoves:
            cmd += ' searchmoves ' + ' '.join(to_fsf(self.game, m) for m in searchmoves)
        self._send(cmd)
        return self._until('bestmove')

    def _infos(self, lines):
        out = []
        for l in lines:
            t = l.split()
            if not t or t[0] != 'info' or 'score' not in t or 'pv' not in t:
                continue
            if 'lowerbound' in t or 'upperbound' in t:
                continue
            i = t.index('score')
            kind, val = t[i + 1], int(t[i + 2])
            cp = val if kind == 'cp' else (MATE_CP - val if val > 0 else -MATE_CP - val)
            out.append({'depth': int(t[t.index('depth') + 1]),
                        'multipv': int(t[t.index('multipv') + 1]) if 'multipv' in t else 1,
                        'cp': cp, 'mate': val if kind == 'mate' else None,
                        'pv': [from_fsf(self.game, m) for m in t[t.index('pv') + 1:]]})
        return out

    def _terminal(self, fen):
        chk = in_check(self.game, fen)
        cp = -MATE_CP if (chk or self.game == XQ) else 0
        return {'best': None, 'cp': cp, 'mate': 0 if chk else None, 'depth': 0, 'pv': []}

    def analyse(self, fen, depth=None):
        """{'best': 最佳着, 'cp': 评估, 'mate': N 步杀（没有则 None）, 'depth', 'pv'}。无着可走时直接按规则给分。"""
        depth = depth or self.depth
        if not sf.legal_moves(self.game, fen, []):
            return self._terminal(fen)
        lines = self._go(fen, depth)
        info = [i for i in self._infos(lines) if i['multipv'] == 1][-1]
        best = from_fsf(self.game, lines[-1].split()[1])
        assert info['pv'][0] == best, ('bestmove 与主变不符', fen, lines[-3:])
        return {'best': best, 'cp': info['cp'], 'mate': info['mate'], 'depth': info['depth'], 'pv': info['pv']}

    def top(self, fen, k, depth=None):
        """MultiPV：前 k 名 [(着法, 评估)]，自对弈造局面用。"""
        depth = depth or self.depth
        lines = self._go(fen, depth, multipv=k)
        last = {}
        for i in self._infos(lines):
            last[i['multipv']] = i
        return [(last[j]['pv'][0], last[j]['cp']) for j in sorted(last)]

    def score_moves(self, fen, moves=None, depth=None):
        """{着法: 评估}：每步用 searchmoves 在根节点单独搜到同一深度，行棋方视角。
        注意它和 analyse() 不完全同口径：只搜一步时剪枝不同，最佳着的分数可能和 analyse 的 cp 差十几厘兵。
        所以厘兵损失一律用本函数内部比较：losses(score_moves(fen))。"""
        depth = depth or self.depth
        out = {}
        for m in (moves or legal(self.game, fen)):
            lines = self._go(fen, depth, searchmoves=[m])
            info = [i for i in self._infos(lines) if i['multipv'] == 1][-1]
            assert info['pv'][0] == m, ('searchmoves 没按要求搜', fen, m, lines[-2:])
            out[m] = info['cp']
        return out

    def close(self):
        if self.p.poll() is None:
            try:
                self._send('quit')
                self.p.wait(timeout=5)
            except Exception:
                self.p.kill()

    def __enter__(self):
        return self

    def __exit__(self, *a):
        self.close()


def is_mate_score(cp):
    """这个分数是不是杀棋分（N 步杀 / 被 N 步杀），而不是普通厘兵。"""
    return abs(cp) >= MATE_BOUND


def losses(scores, cap=None):
    """{着法: 厘兵损失}：同一批 score_moves 结果里，最高分减该步得分（≥0）。
    cap=None（默认，与修订前相同）：杀棋分原样参与比较——「3 步杀 vs 2 步杀」只差 1，「送杀」差三万多；
    判「失误（损失 ≥200）」这类阈值没问题，但求平均损失会被杀棋分冲掉。
    cap=数值：先把每步分数截到 [-cap, +cap] 再比，算平均损失时建议 cap=1000。
    杀棋分不要当普通厘兵拿去和阈值比（局面集生成时 middle / gain 已排除最高分或答案是杀棋分的局面）。"""
    if cap is not None:
        scores = {m: max(-cap, min(cap, v)) for m, v in scores.items()}
    top = max(scores.values())
    return {m: top - v for m, v in scores.items()}


# ---------------------------------------------------------------- 局面集读取
def load_positions(path=POSITIONS):
    """读入库的局面集：返回 {'meta': ..., 'positions': [...]}。"""
    with open(path, encoding='utf-8') as f:
        return json.load(f)


def select(data, game=None, set_=None, stratum=None, include_invalid_legacy=False):
    """按棋种 / 集 / 分层过滤局面。默认**不返回无效旧局面**（legacy_ok = false：按真实规则没有唯一一步杀的
    初探旧局面，目前是 xq-mate-old-02…06），所以 select(set_='mate') 拿到的都是有唯一正解的题。
    只有「旧格式复现」这类要原样重放全部旧局面的场合才传 include_invalid_legacy=True（修订 1 起的语义）。"""
    return [p for p in data['positions'] if (game is None or p['game'] == game)
            and (set_ is None or p['set'] == set_) and (stratum is None or p['stratum'] == stratum)
            and (include_invalid_legacy or p.get('legacy_ok', True))]


# ---------------------------------------------------------------- 自检
def _ok(cond, msg):
    if not cond:
        raise AssertionError(msg)


class _T:
    """计数器：每条断言记一笔，最后打印分子分母。"""
    def __init__(self):
        self.n = 0
        self.sec = {}

    def __call__(self, sec, cond, msg=''):
        self.n += 1
        self.sec[sec] = self.sec.get(sec, 0) + 1
        _ok(cond, '[%s] %s' % (sec, msg))


def _xq(rows, stm='w'):
    """用 {格: 子} 摆中国象棋局面，返回规范化 FEN。"""
    return norm(XQ, board_fen(XQ, rows) + ' ' + stm)


def _moves_from(game, fen, sq):
    return {m for m in legal(game, fen) if m.startswith(sq)}


def _both(T, sec, fen, mv, want):
    """pyffish 与 cchess 对同一步的合法性判断都要等于 want。"""
    a = mv in legal(XQ, fen)
    b = mv in cchess_legal(fen)
    T(sec, a == want and b == want, '%s %s 期望 %s，pyffish %s，cchess %s' % (fen, mv, want, a, b))


def selftest_rules(T):
    K = {'d0': 'K', 'e9': 'k'}      # 帅将不同线，免得摆出对脸的非法局面
    # 坐标换算
    for x in range(9):
        for y in range(10):
            for x2, y2 in ((x, 9 - y), (8 - x, y)):
                mv = sq_of(x, y) + sq_of(x2, y2)
                T('坐标', from_fsf(XQ, to_fsf(XQ, mv)) == mv, mv)
    T('坐标', to_fsf(XQ, 'f5e7') == 'f6e8' and from_fsf(XQ, 'b3b10') == 'b2b9', '冒烟样例')
    for g in GAMES:
        f = START[g]
        T('FEN', board_fen(g, parse(g, f)[0]) == f.split()[0], g)
    T('FEN', norm(XQ, '4k4/9/9/9/5N3/4C4/9/9/9/3K5 w') == '4k4/9/9/9/5N3/4C4/9/9/9/3K5 w - - 0 1', '短 FEN 补全')

    # 马腿：开局 b0 马 → a2、c2 可走，→ d1 被 c0 相蹩腿
    f = START[XQ]
    _both(T, '马腿', f, 'b0c2', True)
    _both(T, '马腿', f, 'b0a2', True)
    _both(T, '马腿', f, 'b0d1', False)
    f = _xq({**K, 'd4': 'N', 'd5': 'P', 'c4': 'P'})         # d5 挡住向上两格；c4 挡住向左两格
    for mv, want in (('d4c6', False), ('d4e6', False), ('d4b5', False), ('d4b3', False),
                     ('d4f5', True), ('d4f3', True), ('d4c2', True), ('d4e2', True)):
        _both(T, '马腿', f, mv, want)
    # 塞象眼 + 相不过河
    f = _xq({**K, 'c0': 'B', 'd1': 'N'})
    _both(T, '塞象眼', f, 'c0e2', False)
    _both(T, '塞象眼', f, 'c0a2', True)
    f = _xq({**K, 'c4': 'B'})
    _both(T, '相不过河', f, 'c4e6', False)
    _both(T, '相不过河', f, 'c4a2', True)
    # 炮架：同一局面里无架 / 一架 / 两架吃子，以及炮不吃子时不能越子
    f = _xq({**K, 'a2': 'C', 'a6': 'r',                    # a 线：炮与车之间无子 → 不能吃
             'b2': 'C', 'b4': 'P', 'b7': 'r',              # b 线：隔一个兵 → 能吃
             'c2': 'C', 'c4': 'P', 'c5': 'p', 'c8': 'r'})  # c 线：隔两个 → 不能吃
    _both(T, '炮架', f, 'a2a6', False)
    _both(T, '炮架', f, 'a2a5', True)
    _both(T, '炮架', f, 'b2b7', True)
    _both(T, '炮架', f, 'b2b6', False)                     # 不吃子时不能越过 b4
    _both(T, '炮架', f, 'c2c8', False)
    _both(T, '炮架', f, 'c2c5', True)                      # 隔 c4 吃 c5
    # 车越子
    f = _xq({**K, 'a0': 'R', 'a3': 'P', 'a7': 'r'})
    _both(T, '车越子', f, 'a0a2', True)
    _both(T, '车越子', f, 'a0a4', False)
    _both(T, '车越子', f, 'a0a7', False)
    # 九宫：帅、仕出不了九宫，仕不能直走
    f = _xq({'d2': 'K', 'e9': 'k', 'e1': 'A', 'f0': 'A'})
    _both(T, '九宫', f, 'd2c2', False)
    _both(T, '九宫', f, 'd2d3', False)
    _both(T, '九宫', f, 'd2d1', True)
    _both(T, '九宫', f, 'e1f2', True)
    _both(T, '九宫', f, 'f0f1', False)                     # 仕直走（目标格空）
    _both(T, '九宫', f, 'f0g1', False)
    # 兵：过河前只能向前，过河后可以横走，永远不能后退
    f = _xq({**K, 'c3': 'P', 'g5': 'P', 'a6': 'p', 'i4': 'p'})
    _both(T, '兵过河', f, 'c3c4', True)
    _both(T, '兵过河', f, 'c3b3', False)
    _both(T, '兵过河', f, 'c3d3', False)
    _both(T, '兵过河', f, 'g5f5', True)
    _both(T, '兵过河', f, 'g5h5', True)
    _both(T, '兵过河', f, 'g5g6', True)
    _both(T, '兵过河', f, 'g5g4', False)
    fb = _xq({**K, 'c3': 'P', 'g5': 'P', 'a6': 'p', 'i4': 'p'}, 'b')
    _both(T, '兵过河', fb, 'a6b6', False)                  # 黑卒未过河不能横走
    _both(T, '兵过河', fb, 'a6a5', True)
    _both(T, '兵过河', fb, 'i4h4', True)                   # 黑卒过河后可横走
    _both(T, '兵过河', fb, 'i4i5', False)                  # 不能后退
    # 对脸将：帅将之间唯一的子离开纵线 → 自将；帅走到将所在的纵线且中间无子 → 不合法
    f = _xq({'e0': 'K', 'e9': 'k', 'e4': 'N', 'd9': 'a'})
    _both(T, '对脸将', f, 'e4c5', False)
    _both(T, '对脸将', f, 'e4c3', False)
    f = _xq({'d0': 'K', 'e9': 'k', 'd4': 'N'})
    _both(T, '对脸将', f, 'd0e0', False)
    _both(T, '对脸将', f, 'd0d1', True)
    # 自将：被牵制的车不能离开车线；帅不能走进被攻击的格
    f = _xq({'e0': 'K', 'e9': 'k', 'e3': 'R', 'e7': 'r', 'f9': 'a'})
    _both(T, '自将', f, 'e3d3', False)
    _both(T, '自将', f, 'e3e5', True)
    _both(T, '自将', f, 'e3e7', True)
    f = _xq({'e0': 'K', 'e9': 'k', 'd8': 'r', 'e4': 'P'})
    _both(T, '自将', f, 'e0d0', False)
    # 困毙 vs 将死
    stale = _xq({'f9': 'k', 'e0': 'K', 'g8': 'R'}, 'b')    # 黑将 f9：f8 被车控，e9 会和帅照面，自己没受将
    T('困毙', status(XQ, stale) == 'stalemate' and not in_check(XQ, stale), stale)
    T('困毙', cchess.ChessBoard(stale).is_checkmate() is False, 'cchess 判断的是「对方」，换行棋方后才会判')
    b = cchess.ChessBoard(stale)
    b.move_player.next()                                                # 让红方为「走完一步」的一方
    T('困毙', b.is_checkmate() is True and not b.is_checking(),
      'cchess.is_checkmate 把困毙也当将死（坑，所以不用它判终局）')
    mate = _xq({'f9': 'k', 'e0': 'K', 'f2': 'R', 'g8': 'R'}, 'b')
    T('将死', status(XQ, mate) == 'mate', mate)
    pre = _xq({'f9': 'k', 'e0': 'K', 'g2': 'R'})           # 车 g2→g8 困毙黑将；g2→f2 借帅照面成杀
    T('困毙', stalemate_moves(XQ, pre) == ['g2g8'] and mate_moves(XQ, pre) == ['g2f2'], '一步困毙与一步杀分开记')
    fx = facts(XQ, pre, 'g2g8')
    T('困毙', fx['stalemate'] and not fx['mate'] and not fx['check'], fx)
    T('困毙', safety(XQ, pre, 'g2g8')['two_ply'] == MATE_SCORE, '中国象棋困毙判负，两层物质记赢')
    # 吃帅伪着：帅将照面的（非法）局面里，cchess 会生成互吃的伪着，红黑都要滤掉
    for stm, bad in (('w', 'e0e9'), ('b', 'e9e0')):
        f = board_fen(XQ, {'e0': 'K', 'e9': 'k', 'a0': 'R', 'a9': 'r'}) + ' ' + stm
        raw = {_iccs(a, c) for a, c in cchess.ChessBoard(f).create_moves()}
        T('吃帅伪着', bad in raw and bad not in cchess_legal(f), (stm, '伪着应被过滤'))
    # 中文记谱：同线双车、双兵前后，红黑各一；多路兵的歧义要被 cn_ok 抓住
    f = _xq({'d0': 'K', 'e9': 'k', 'a2': 'R', 'a1': 'R', 'e5': 'P', 'e6': 'P'})
    T('记谱', cn_notation(f, 'a2a5') == '前车进三' and cn_notation(f, 'a1b1') == '后车平八', '红双车')
    T('记谱', cn_notation(f, 'e6e7') == '前兵进一' and cn_notation(f, 'e5d5') == '后兵平六', '红双兵')
    T('记谱', cn_ok(f), '单线双子无歧义')
    fb = _xq({'d0': 'K', 'e9': 'k', 'a6': 'r', 'a8': 'r', 'e4': 'p', 'e3': 'p'}, 'b')
    T('记谱', cn_notation(fb, 'a6a4') == '前车进２' and cn_notation(fb, 'a8b8') == '后车平２', '黑双车')
    T('记谱', cn_notation(fb, 'e3e2') == '前卒进１' and cn_notation(fb, 'e4d4') == '后卒平４', '黑双卒')
    f2 = _xq({'d0': 'K', 'e9': 'k', 'c5': 'P', 'c6': 'P', 'g5': 'P', 'g6': 'P'})
    T('记谱', not cn_ok(f2), '两路各有双兵：cchess 会重复写「前兵进一」，必须被标出来')
    try:
        describe_all(XQ, f2, 'N0')
        T('记谱', False, 'describe_all 应该在重复描述上报错')
    except AssertionError as e:
        T('记谱', '两步描述相同' in str(e), str(e))
    f3 = _xq({'d0': 'K', 'e9': 'k', 'a5': 'P', 'a6': 'P', 'a7': 'P'})
    T('记谱', not cn_ok(f3), '三兵同线：规范写法不实现，标出来不收')
    f4 = 'r1bakabn1/7c1/nc6r/p1p1p1p1p/1C7/9/P1P1P1P1P/1C7/4A4/RNBAK1BNR w - - 6 4'   # 随机对局里撞到的
    T('记谱', cn_notation(f4, 'b2b7') == cn_text(f4, 'b2b7') == '后炮进五' and wxf(f4, 'b2b7') == 'C8+5',
      'pyffish WXF 在炮隔同线炮吃子时省掉前后前缀；cchess 与独立实现都写「后炮进五」')

    # 摆法核对：初探随机局面 2 把士摆在 e9（士到不了的点），两个库在这种局面上分歧
    old2 = norm(XQ, '3cak3/9/8C/3R5/9/9/3N5/9/9/4K4 w')
    T('摆法', placement_issues(XQ, old2) != [] and placement_issues(XQ, START[XQ]) == [] and
      placement_issues(CH, START[CH]) == [], placement_issues(XQ, old2))
    T('摆法', mate_moves(XQ, old2) == [] and 'e9f8' in legal(XQ, play(XQ, old2, 'd6f6')) and
      any('两库不一致' in s for s in audit_mate(XQ, old2, 'd6f6')),
      '初探认定的杀着 d6f6：pyffish 认为士能 e9→f8 解将，cchess 认为不在 5 个点上的士动不了')

    # ---- 国际象棋：易位、过路兵、升变、牵制
    f = 'r3k2r/8/8/8/8/8/8/R3K2R w KQkq - 0 1'
    T('易位', {'e1g1', 'e1c1'} <= set(legal(CH, f)), '通路干净时两边都能易位')
    f = 'r3k2r/8/8/8/8/8/5r2/R3K2R w KQkq - 0 1'   # f2 车攻击 f1：短易位经过被攻击格
    T('易位', 'e1g1' not in legal(CH, f) and 'e1c1' in legal(CH, f), '不能经过被攻击的格')
    f = 'r3k2r/8/8/8/8/8/4r3/R3K2R w KQkq - 0 1'   # 被将时不能易位
    T('易位', 'e1g1' not in legal(CH, f) and 'e1c1' not in legal(CH, f), '被将时不能易位')
    fx = facts(CH, 'r3k2r/8/8/8/8/8/8/R3K2R w KQkq - 0 1', 'e1g1')
    T('易位', fx['castle'] == ('h1', 'f1'), fx)
    T('易位', describe(CH, 'r3k2r/8/8/8/8/8/8/R3K2R w KQkq - 0 1', 'e1c1', 'U0') == '王从 e1 走到 c1，车从 a1 走到 d1', '描述')
    ep = 'rnbqkbnr/ppp1p1pp/8/3pPp2/8/8/PPPP1PPP/RNBQKBNR w KQkq f6 0 3'
    T('过路兵', 'e5f6' in legal(CH, ep) and 'e5d6' not in legal(CH, ep), '只有刚走两格的 f 兵能被吃过路兵')
    fx = facts(CH, ep, 'e5f6')
    T('过路兵', fx['ep'] and fx['captured'] == 'p' and fx['cap_sq'] == 'f5', fx)
    T('过路兵', describe(CH, ep, 'e5f6', 'U1') == '兵从 e5 走到 f6，吃掉对方的兵', '描述')
    T('过路兵', describe(CH, ep, 'e5f6', 'N0') == 'ef6' and describe(CH, ep, 'e5f6', 'N3') == 'exf6', 'SAN')
    pr = '8/4P1k1/8/8/8/8/5K2/8 w - - 0 1'
    T('升变', {'e7e8q', 'e7e8r', 'e7e8b', 'e7e8n'} <= set(legal(CH, pr)), '四种升变')
    d = describe_all(CH, pr, 'U0')
    T('升变', d['e7e8q'] == '兵从 e7 走到 e8，升变为后' and d['e7e8n'] == '兵从 e7 走到 e8，升变为马', d)
    T('升变', describe(CH, pr, 'e7e8n', 'N3') == 'e8=N+' and describe(CH, pr, 'e7e8n', 'N0') == 'e8=N', '升变带将军')
    pin ='4k3/4r3/8/8/8/8/4N3/4K3 w - - 0 1'      # e2 马被 e7 车牵制
    T('牵制', _moves_from(CH, pin, 'e2') == set() and chess.Board(pin).is_pinned(chess.WHITE, chess.E2), '被牵制的马无着')
    pin2 = '4k3/8/8/8/1b6/8/3R4/4K3 w - - 0 1'     # d2 车被 b4 象斜线牵制，只能… 一步也不能走（车不走斜线）
    T('牵制', _moves_from(CH, pin2, 'd2') == set(), '斜线牵制的车无着')
    pin3 = '4k3/8/8/8/8/8/1q1R1K2/8 w - - 0 1'     # d2 车在横线上被牵制，只能沿横线走（含吃掉后）
    T('牵制', _moves_from(CH, pin3, 'd2') == {'d2c2', 'd2b2', 'd2e2'}, sorted(_moves_from(CH, pin3, 'd2')))
    st = '7k/5Q2/6K1/8/8/8/8/8 b - - 0 1'
    T('困毙', status(CH, st) == 'stalemate', '国际象棋逼和局面')
    T('将死', status(CH, '7k/6Q1/6K1/8/8/8/8/8 b - - 0 1') == 'mate', '国际象棋将死')


def selftest_desc(T):
    f = '9/9/4ka3/2C4R1/9/8N/9/3K5/7c1/9 w - - 0 1'      # 初探局面 1：h6e6 是唯一杀着
    fxs = all_facts(XQ, f)
    T('描述', describe(XQ, f, 'h6e6', 'U0') == '车从 h6 走到 e6', 'U0')
    T('描述', describe(XQ, f, 'h6e6', 'U2') == '车从 h6 走到 e6，将军', 'U2 杀着只写将军')
    T('描述', describe(XQ, f, 'h6e6', 'U3') == '车从 h6 走到 e6，将死', 'U3')
    T('描述', describe(XQ, f, 'h6e6', 'coord') == '从 h6 走到 e6', 'coord')
    T('描述', describe(XQ, f, 'h6e6', 'U0', 'en') == 'Rook from h6 to e6', 'en')
    T('描述', describe(XQ, f, 'h6e6', 'U3', 'en') == 'Rook from h6 to e6, checkmate', 'en U3')
    cap = [m for m, x in fxs.items() if x['captured']]
    T('描述', cap and '吃掉对方的' in describe(XQ, f, cap[0], 'U1'), 'U1 吃子')
    for style in STYLES[:-1]:
        for lang in ('zh', 'en'):
            if style == 'N0' and lang == 'en':
                continue
            describe_all(XQ, f, style, lang, fxs)
            T('描述', True)
    # 泄露检测本身的对照：带标记的句子必须被抓出来，干净的句子不能误报
    for text, lang, want in (('车从 h6 走到 e6，将军', 'zh', {'check'}), ('车从 h6 走到 e6，吃掉对方的马', 'zh', {'capture'}),
                             ('车从 h6 走到 e6，将死', 'zh', {'check', 'mate'}), ('马从 d4 走到 c6（马腿被挡）', 'zh', {'hint'}),
                             ('将从 e9 走到 e8', 'zh', set()), ('将５平６', 'zh', set()), ('炮二平五', 'zh', set()),
                             ('Rook from h6 to e6, check', 'en', {'check'}), ('Rook from h6 to e6', 'en', set()),
                             ('Nxe5+', 'san', {'capture', 'check'}), ('Qf7#', 'san', {'mate'}), ('Ne5', 'san', set())):
        T('泄露检测', tags(text, lang) == want, (text, tags(text, lang), want))
    try:
        assert_marks(XQ, 'U0', 'zh', {'h6e6': '车从 h6 走到 e6，将军'}, fxs)
        T('泄露检测', False, '无标记臂里混进「将军」必须报错')
    except AssertionError as e:
        T('泄露检测', '描述标记与档位不符' in str(e), str(e))
    try:
        assert_marks(XQ, 'U2', 'zh', {'h6e6': '车从 h6 走到 e6，将死'}, fxs)
        T('泄露检测', False, 'U2 写了将死必须报错')
    except AssertionError as e:
        T('泄露检测', '描述标记与档位不符' in str(e), str(e))
    # 国际象棋：原样 SAN 的杀着带 #，N0 去掉
    m = 'r1bqkb1r/pppp1ppp/2n2n2/4p2Q/2B1P3/8/PPPP1PPP/RNB1K1NR w KQkq - 4 4'
    T('描述', describe(CH, m, 'h5f7', 'N3') == 'Qxf7#' and describe(CH, m, 'h5f7', 'N0') == 'Qf7', 'SAN')
    T('描述', describe(CH, m, 'h5f7', 'U3') == '后从 h5 走到 f7，吃掉对方的兵，将死', 'U3')
    T('描述', describe(CH, m, 'h5f7', 'U3', 'en') == "Queen from h5 to f7, capturing the opponent's Pawn, checkmate", 'en')
    for style in STYLES:
        describe_all(CH, m, style)
        T('描述', True)


def selftest_render(T):
    for game, fen in ((XQ, '9/9/4ka3/2C4R1/9/8N/9/3K5/7c1/9 w - - 0 1'), (XQ, START[XQ]),
                      (CH, START[CH]), (CH, 'r1bqkb1r/pppp1ppp/2n2n2/4p2Q/2B1P3/8/PPPP1PPP/RNB1K1NR w KQkq - 4 4')):
        board, stm = parse(game, fen)
        for lang in ('zh', 'en'):
            inv = {label(game, p, lang): p for p in set(board.values())}
            T('渲染', len(inv) == len(set(board.values())), '标签两两不同')
            st = state(game, fen, 'cells', lang)
            T('渲染', {s: inv[v] for s, v in st['cells'].items()} == board, '格子表还原棋盘')
            st = state(game, fen, 'pieces', lang)
            back = {}
            red, black = SIDE[(game, lang)]
            for side, d in st['pieces'].items():
                for nm, sqs in d.items():
                    cand = [p for p in set(board.values()) if piece_name(game, p, lang) == nm and is_red(p) == (side == red)]
                    T('渲染', len(cand) == 1, (side, nm))
                    for s in sqs:
                        back[s] = cand[0]
            T('渲染', back == board, '子力清单还原棋盘')
            st = state(game, fen, 'board', lang)
            rows = st['board'].split('\n')
            T('渲染', len(rows) == TOP[game] - BOTTOM[game] + 2, '字符棋盘行数')
            back = {}
            for r in rows[:-1]:
                y, cells = int(r.split()[0]), r.split()[1:]
                T('渲染', len(cells) == len(FILES[game]), r)
                for x, c in enumerate(cells):
                    if c != '.':
                        back[sq_of(x, y)] = c
            T('渲染', back == board, '字符棋盘还原棋盘')
            st = state(game, fen, 'fen', lang)
            T('渲染', st['fen'] == fen and st['side_to_move'] == (red if stm == 'w' else black), 'FEN 形态')
            for form in FORMS:
                T('渲染', 'legal' not in json.dumps(state(game, fen, form, lang)), 'state 里不放着法清单')


def selftest_keys(T):
    import itertools
    pool = _key_pool()
    T('选项键', len(pool) == len(set(pool)) >= _MOVE_SPACE, '键池两两不同，且不小于着法编号空间')
    T('选项键', all(key_ok(k) for k in pool), '键池里每个键都合格')
    # 排除表：键里不含任何排除串；键里没有元音 / y / x / 棋子字母 / 数字，所以拼不出英文词和拼音音节
    T('选项键', not any(b in k for k in pool for b in KEY_BLOCK + KEY_RUNS), '键不含排除表里的串')
    T('选项键', not set(''.join(pool)) & set('aeiouyxkqrbnpc0123456789'), '键里没有元音、y、x、棋子字母、数字')
    for w in ('move', 'game', 'fire', 'rule', 'five', 'zero', 'mate', 'best', 'html', 'wtfs', 'sdfg', 'djsl', 'hmzt'):
        T('选项键', w not in pool, ('真词 / 排除串不该在键池里', w))
    # 着法编号：两棋种所有可能写法一一对应
    sq = [f + str(r) for f in 'abcdefghi' for r in range(10)]
    idx = [_move_index(a + b) for a, b in itertools.product(sq, sq)]
    T('选项键', len(set(idx)) == len(idx) and max(idx) < 8100, '着法编号不重（中国象棋 / 普通着法）')
    promo = [_move_index(f + r1 + g + r2 + p) for f in 'abcdefgh' for g in 'abcdefgh' if abs(ord(f) - ord(g)) <= 1
             for r1, r2 in (('7', '8'), ('2', '1')) for p in 'qrbn']
    T('选项键', len(set(promo)) == len(promo) and 8100 <= min(promo) and max(promo) < _MOVE_SPACE, '升变编号不重')
    ks = option_keys(255, 'p1', 0)
    T('选项键', len(set(ks)) == 255 and option_keys(40, 'p1', 0) == option_keys(40, 'p1', 0), 'option_keys 不重、可复现')
    # options：真实局面上、全部描述档之间
    for game, fen, pid in ((XQ, '9/9/4ka3/2C4R1/9/8N/9/3K5/7c1/9 w - - 0 1', 'xq-t'),
                           (CH, 'r1bqkb1r/pppp1ppp/2n2n2/4p2Q/2B1P3/8/PPPP1PPP/RNB1K1NR w KQkq - 4 4', 'ch-t')):
        fxs = all_facts(game, fen)
        arms = [(s, l) for s in STYLES for l in ('zh', 'en')
                if not (s in ('N0', 'N3') and l == 'en') and not (s == 'N3' and game == XQ)]
        outs = {a: options(describe_all(game, fen, a[0], a[1], fxs), pid, '%s-%s' % a, 0) for a in arms}
        c0, k0 = outs[arms[0]]
        for a, (c, k) in outs.items():
            T('选项键', k == k0 and list(k) == list(k0), ('同 (局面, rep) 下跨臂同着法同键、同顺序', game, a))
            T('选项键', all(c[x] == describe(game, fen, k[x], a[0], a[1], fxs[k[x]]) for x in c), ('键 → 着法 → 描述', a))
            T('选项键', all(key_ok(x) for x in c), ('键不在排除表里', a))
        again = options(describe_all(game, fen, 'U0', 'zh', fxs), pid, 'U0', 0)
        T('选项键', list(again[0].items()) == list(outs[('U0', 'zh')][0].items()), '同 (局面, rep) 可复现')
        sub = {m: 't' for m in list(k0.values())[:5]}
        T('选项键', {m: x for x, m in options(sub, pid, 'any', 0)[1].items()} == {m: x for x, m in k0.items() if m in sub},
          '只给部分着法时，这些着法的键不变')
        c1, k1 = options(describe_all(game, fen, 'U0', 'zh', fxs), pid, 'U0', 1)
        inv0, inv1 = {m: x for x, m in k0.items()}, {m: x for x, m in k1.items()}
        same = sum(inv0[m] == inv1[m] for m in inv0)
        T('选项键', same <= len(inv0) // 10 and list(k1.values()) != list(k0.values()), ('换 rep 映射和顺序都换', same))
        T('选项键', options(describe_all(game, fen, 'U0', 'zh', fxs), 'other', 'U0', 0)[1] != k0, '换局面换映射')


def selftest_violation(T, quick):
    """违规分类：每一类各举一例（与规则细则同样的摆法），再在随机局面的全部「起点有己方子」着法上与 pyffish 逐一核对。"""
    K = {'d0': 'K', 'e9': 'k'}
    cases = [
        (XQ, _xq({**K, 'd4': 'N', 'd5': 'P', 'c4': 'P'}), [('d4c6', 'leg'), ('d4b5', 'leg'), ('d4f5', None), ('d4d6', 'shape')]),
        (XQ, _xq({**K, 'c0': 'B', 'd1': 'N', 'c4': 'B'}), [('c0e2', 'eye'), ('c0a2', None), ('c4e6', 'river'), ('c4c3', 'shape')]),
        (XQ, _xq({**K, 'a2': 'C', 'a6': 'r', 'b2': 'C', 'b4': 'P', 'b7': 'r', 'c2': 'C', 'c4': 'P', 'c5': 'p', 'c8': 'r'}),
         [('a2a6', 'screen0'), ('b2b7', None), ('b2b6', 'jump'), ('c2c8', 'screen2'), ('c2c5', None), ('a2b3', 'shape')]),
        (XQ, _xq({**K, 'a0': 'R', 'a3': 'P', 'a7': 'r'}), [('a0a4', 'jump'), ('a0a7', 'jump'), ('a0a3', 'own'), ('a0b1', 'shape')]),
        (XQ, _xq({'d2': 'K', 'e9': 'k', 'e1': 'A', 'f0': 'A'}), [('d2c2', 'palace'), ('d2d3', 'palace'), ('f0f1', 'shape'),
                                                                ('f0g1', 'palace'), ('e1d0', None)]),
        (XQ, _xq({**K, 'c3': 'P', 'g5': 'P'}), [('c3b3', 'pawn_side'), ('g5g4', 'pawn_back'), ('g5f5', None), ('c3c5', 'shape')]),
        (XQ, _xq({'e0': 'K', 'e9': 'k', 'e4': 'N', 'd9': 'a'}), [('e4c5', 'facing'), ('e4d6', 'facing')]),
        (XQ, _xq({'e0': 'K', 'e9': 'k', 'e3': 'R', 'e7': 'r', 'f9': 'a'}), [('e3d3', 'self_check'), ('e3e5', None)]),
        (CH, '4k3/8/8/8/8/8/1P6/B3K3 w - - 0 1', [('a1c3', 'jump'), ('b2b4', None), ('a1a3', 'shape')]),
        (CH, '4k3/4r3/8/8/8/8/4N3/4K3 w - - 0 1', [('e2c3', 'pin'), ('e2e4', 'shape'), ('e1d1', None)]),
        (CH, '4k3/8/8/8/8/8/3r4/4K3 w - - 0 1', [('e1e2', 'king_attacked'), ('e1d2', None), ('e1f1', None)]),
        (CH, 'r3k2r/8/8/8/8/8/5r2/R3K2R w KQkq - 0 1', [('e1g1', 'castle'), ('e1c1', None)]),
        (CH, '4k3/8/8/8/8/4p3/4P3/4K3 w - - 0 1', [('e2e3', 'pawn_block'), ('e2d3', 'shape')]),
    ]
    for game, fen, items in cases:
        for mv, want in items:
            got = violation(game, fen, mv)
            T('违规分类', got == want, (game, fen, mv, got, want))
    # 对方能否吃掉某子（空着法）：马腿、被牵制的攻击者
    f = _xq({'d0': 'K', 'e9': 'k', 'e5': 'R', 'c7': 'n'})
    T('受攻判断', capturable(XQ, f, 'e5') is False, 'c7 马吃不到 e5（不是日字）')
    f = _xq({'d0': 'K', 'e9': 'k', 'e5': 'R', 'd7': 'n'})
    T('受攻判断', capturable(XQ, f, 'e5') is True, 'd7 马能吃 e5')
    f = _xq({'d0': 'K', 'e9': 'k', 'e5': 'R', 'd7': 'n', 'd6': 'P'})
    T('受攻判断', capturable(XQ, f, 'e5') is False, 'd6 蹩住马腿')
    f = _xq({'d0': 'K', 'e9': 'k', 'e7': 'n', 'e2': 'R', 'd5': 'C'})
    T('受攻判断', capturable(XQ, f, 'd5') is False and capturable(XQ, f, 'e2') is False, 'e7 马被 e2 车牵制，吃不了 d5')
    T('受攻判断', capturable(CH, '4k3/4r3/8/8/8/8/4N3/4K3 w - - 0 1', 'e2') is True, 'e7 车能吃 e2 马')
    T('受攻判断', capturable(CH, '4k3/4n3/8/3B4/8/8/8/4RK2 w - - 0 1', 'd5') is False, 'e7 马被 e1 车牵制，吃不了 d5 象')
    # 与 pyffish 逐一核对
    n = 1 if quick else 4
    for game in GAMES:
        fens = [f for f in _random_positions(game, n, 5, plies=120) if legal(game, f)]
        for fen in fens:
            pm = pseudo_moves(game, fen)
            lg = {m for m in legal(game, fen) if len(m) == 4 or m[4] == 'q'}
            T('违规分类与 pyffish 一致', {m for m, v in pm.items() if v is None} == lg, (game, fen))
        print('  %s 随机局面 %d 个：违规分类判为合法的着法 = pyffish 合法着法' % (game, len(fens)))


def _random_positions(game, n_games, seed, plies=160):
    rng = random.Random(seed_of('rand', game, seed))
    out = []
    for _ in range(n_games):
        fen = START[game]
        for _ in range(plies):
            ms = legal(game, fen)
            if not ms:
                break
            out.append(fen)
            fen = play(game, fen, rng.choice(ms), check=False)
        out.append(fen)
    return out


def selftest_random(T, quick):
    """随机对局的全部局面（红黑双方行棋都有）上交叉比对两个库；抽样核对两层物质快慢两种算法。"""
    n = 2 if quick else 12
    for game in GAMES:
        fens = _random_positions(game, n, 1)
        for i, fen in enumerate(fens):
            bad = crosscheck(game, fen)
            T('随机局面交叉比对', not bad, (game, fen, bad[:3]))
            if i % 25 == 0:
                T('两层物质快慢一致', two_ply(game, fen) == two_ply_slow(game, fen), (game, fen))
        print('  %s 随机局面 %d 个：两库合法着法 / 将军 / 将死 / 困毙 / 记谱全一致' % (game, len(fens)))


def selftest_engine(T):
    # 顺序无关：同一批局面，一个进程按顺序搜，另一个进程倒序并穿插 MultiPV / searchmoves 搜索，结果必须逐项相同
    for game in GAMES:
        fens = _random_positions(game, 2, 7, plies=50)[20::6]
        with Engine(game) as e1:
            base = [e1.analyse(f) for f in fens]
        with Engine(game) as e2:
            got = []
            for i, f in reversed(list(enumerate(fens))):
                e2.top(fens[i - 1], 3, 4)
                e2.score_moves(fens[i - 2], legal(game, fens[i - 2])[:3])
                got.append(e2.analyse(f))
            got.reverse()
        T('引擎可复现', base == got, (game, [(a['cp'], b['cp']) for a, b in zip(base, got) if a != b]))
        print('  %s %d 个局面：换进程、倒序、穿插别的搜索，结果逐项相同' % (game, len(fens)))
    for game, fen in ((XQ, '9/9/4ka3/2C4R1/9/8N/9/3K5/7c1/9 w - - 0 1'),
                      (XQ, 'r1bakab1r/9/1cn3nc1/p1p1p1p1p/9/2P6/P3P1P1P/1CN3NC1/9/R1BAKAB1R w - - 0 1'),
                      (CH, 'r1bqkb1r/pppp1ppp/2n2n2/4p2Q/2B1P3/8/PPPP1PPP/RNB1K1NR w KQkq - 4 4'),
                      (CH, 'r1bqkbnr/pppp1ppp/2n5/4p3/3PP3/5N2/PPP2PPP/RNBQKB1R w KQkq - 0 1')):
        with Engine(game) as e1, Engine(game) as e2:
            a = e1.analyse(fen)
            b = e1.analyse(START[game])
            c = e1.analyse(fen)
            d = e2.analyse(fen)
            T('引擎可复现', a == c == d, (game, fen, a, c, d))
            s1 = e1.score_moves(fen, legal(game, fen)[:6] + [a['best']])
            s2 = e2.score_moves(fen, legal(game, fen)[:6] + [a['best']])
            T('引擎可复现', s1 == s2, (game, fen))
            if s1[a['best']] != a['cp']:
                print('  注意：%s 整体搜索给最佳着 %s 打 %d，只搜这一步（searchmoves）打 %d——两种搜索剪枝不同，'
                      '厘兵损失要统一用 score_moves 口径' % (game, a['best'], a['cp'], s1[a['best']]))
            mm = mate_moves(game, fen)
            if mm:
                T('引擎一步杀', a['mate'] == 1 and a['best'] == mm[0] and a['cp'] == MATE_CP - 1, (a, mm))
        print('  %s %s…：两个进程、前后两次结果一致，%s' % (game, fen[:30], a if not mm else '一步杀 %s' % a['best']))


def verify_position(p, eng=None, slow=True):
    """复核局面集里的一个局面，返回核对的断言条数；任何不符直接抛错。eng：{game: Engine} 时顺带核对引擎结论。"""
    game, fen, n = p['game'], p['fen'], 0

    def ok(cond, msg):
        nonlocal n
        n += 1
        _ok(cond, '[%s] %s' % (p['id'], msg))
    ok(norm(game, fen) == fen and fen.endswith(' 0 1'), 'FEN 应是规范化的，计数重置为 0 1')
    ok(parse(game, fen)[1] == 'w', '一律红 / 白先走')
    ok(not in_check(game, fen), '起始未被将')
    ft = features(game, fen)
    ok(ft == p['features'], ('特征与重算不符', ft, p['features']))
    if p['stratum'] == 'legacy':
        # 旧局面原样保留，只核对记下的问题清单与重算一致
        iss = audit_mate(game, fen, p['answer'])
        ok(iss == p['issues'], ('旧局面问题清单与重算不符', iss, p['issues']))
        ok(p['legacy_ok'] == (not iss), 'legacy_ok 与问题清单一致')
        return n
    ok(not placement_issues(game, fen), ('摆法到不了', placement_issues(game, fen)))
    bad = crosscheck(game, fen)
    ok(not bad, ('两库不一致', bad[:3]))
    fxs = all_facts(game, fen)
    langs = {'U0': ('zh', 'en'), 'U1': ('zh', 'en'), 'U2': ('zh', 'en'), 'U3': ('zh', 'en'), 'coord': ('zh', 'en'),
             'N0': ('zh',), 'N3': ('zh',)}
    for style, ls in langs.items():
        if style == 'N3' and game == XQ:
            continue
        for lang in ls:
            describe_all(game, fen, style, lang, fxs)
            ok(True, '')
    if game == XQ:
        ok(cn_ok(fen), '中文记谱无歧义')
    if p['set'] == 'mate':
        ok(audit_mate(game, fen, p['answer']) == [], ('一步杀题有问题', audit_mate(game, fen, p['answer'])))
        ok(mate_moves(game, fen) == [p['answer']], '恰好一步杀，且就是 answer')
        if game == XQ:
            ok(stalemate_moves(game, fen) == [], '中国象棋一步杀局面里不能另有一步困毙（也是赢）')
        rng = random.Random(0)
        ok(baseline(game, fen, 'greedy1', rng) == p['answer'] and baseline(game, fen, 'greedy2', rng) == p['answer'],
           '两个贪心基线都应走出唯一杀着')
        if eng:
            a = eng[game].analyse(fen)
            ok(a['best'] == p['answer'] and a['mate'] == 1, ('引擎应找到这步杀', a))
    else:
        ok(mate_moves(game, fen) == [], '中局 / 得子局面里没有一步杀')
        if game == XQ:
            ok(stalemate_moves(game, fen) == [], '也没有一步困毙')
    if p['set'] == 'middle':
        ok(20 <= p['source']['ply'] <= 60, '第 20–60 半回合')
        ok(ft['pieces'] >= 20, '子力 ≥20')
        ok(abs(p['engine']['cp']) <= 300 and p['engine']['mate'] is None, '评估在 ±300 内、没有杀棋分')
    if p['set'] == 'gain':
        g = two_ply(game, fen)
        ok(g == p['gains'], '两层物质与重算一致')
        if slow:
            ok(g == two_ply_slow(game, fen), '两层物质快慢一致')
        top = [m for m, v in g.items() if v >= p['rule']['min_gain']]
        ok(top == [p['answer']], '恰好一步净得子')
        ok(sorted(v for m, v in g.items() if m != p['answer'])[-1] <= p['rule']['max_other'], '其余着法都不净得子')
        baits = sorted(m for m in g if fxs[m]['captured'] and g[m] < 0)
        ok(baits == p['baits'] and baits, '有会被吃回的诱饵吃子')
        ok(baseline(game, fen, 'greedy2', random.Random(0)) == p['answer'], '贪心-L2 应走出得子着')
        ok(not is_mate_score(p['move_scores'][p['answer']]), '得子着的分数不是杀棋分')
        ok(losses(p['move_scores'])[p['answer']] <= p['rule']['max_engine_loss'], '引擎认可这步得子')
    if p['set'] in ('middle', 'gain'):
        ok(p['engine']['mate'] is None, ('中局 / 得子局面不许有强制杀', p['engine']))
        ok(not is_mate_score(max(p['move_scores'].values())), '逐步分数的最高分不是杀棋分（否则厘兵损失没有意义）')
    if eng and p['set'] in ('middle', 'gain'):
        a = eng[game].analyse(fen, p['engine']['search_depth'])
        ok({k: a[k] for k in ('best', 'cp', 'mate', 'depth', 'pv')} ==
           {k: p['engine'][k] for k in ('best', 'cp', 'mate', 'depth', 'pv')}, ('引擎复算不一致', a, p['engine']))
        ok(sorted(p['move_scores']) == legal(game, fen), 'move_scores 覆盖全部合法着法')
        if slow and p['id'][-3:] in ('-01', '-02'):          # 抽样重算逐步分数（全算太慢）
            ok(eng[game].score_moves(fen) == p['move_scores'], '逐步分数复算不一致')
    return n


def selftest_positions(T, quick):
    if not os.path.exists(POSITIONS):
        print('  （还没有 %s，跳过局面集复核；先跑 make_positions.py build）' % os.path.basename(POSITIONS))
        return
    data = load_positions()
    ids = [p['id'] for p in data['positions']]
    T('局面集', len(ids) == len(set(ids)), 'id 两两不同')
    bad = {p['id'] for p in data['positions'] if p.get('legacy_ok') is False}
    T('局面集', not bad & {p['id'] for p in select(data)} and not bad & {p['id'] for p in select(data, set_='mate')},
      'select 默认不返回无效旧局面')
    T('局面集', len(select(data, include_invalid_legacy=True)) == len(ids) and
      {p['id'] for p in select(data, set_='mate', stratum='legacy', include_invalid_legacy=True)} >= bad,
      '显式 include_invalid_legacy=True 才返回')
    keys = {}
    for p in data['positions']:
        k = (p['game'], key_of(p['fen']))
        T('局面集', k not in keys, ('局面重复', p['id'], keys.get(k)))
        keys[k] = p['id']
    engs = {g: Engine(g) for g in GAMES}
    try:
        cnt = {}
        for p in data['positions']:
            n = verify_position(p, engs, slow=not quick or p['id'].endswith('-01'))
            T.n += n
            T.sec['局面集逐个复核'] = T.sec.get('局面集逐个复核', 0) + n
            cnt[(p['game'], p['set'], p['stratum'])] = cnt.get((p['game'], p['set'], p['stratum']), 0) + 1
    finally:
        for e in engs.values():
            e.close()
    for k in sorted(cnt):
        print('  %-8s %-6s %-9s %3d 个' % (k[0], k[1], k[2], cnt[k]))


def selftest(quick=False):
    T = _T()
    for name, fn in (('规则细则', selftest_rules), ('描述', selftest_desc), ('渲染', selftest_render),
                     ('选项键', selftest_keys)):
        fn(T)
        print('%s：通过' % name)
    print('违规分类 / 受攻判断：')
    selftest_violation(T, quick)
    print('随机局面交叉比对：')
    selftest_random(T, quick)
    print('引擎：')
    selftest_engine(T)
    print('局面集：')
    selftest_positions(T, quick)
    print('\n全部通过，共 %d 条断言：' % T.n)
    for k, v in T.sec.items():
        print('  %-16s %5d' % (k, v))


def show(game, fen):
    fen = norm(game, fen)
    print(fen)
    print(char_board(game, parse(game, fen)[0]))
    print(json.dumps(features(game, fen), ensure_ascii=False))
    fxs = all_facts(game, fen)
    for m in sorted(fxs):
        row = [describe(game, fen, m, s, 'zh', fxs[m]) for s in ('U3', 'N0')]
        if game == CH:
            row.append(describe(game, fen, m, 'N3', 'zh', fxs[m]))
        print(' ', m, ' | '.join(row))
    bad = crosscheck(game, fen)
    print('交叉比对：', '一致' if not bad else bad)


if __name__ == '__main__':
    args = sys.argv[1:]
    if args[:1] == ['selftest']:
        selftest(quick='--quick' in args)
    elif args[:1] == ['show'] and len(args) >= 3:
        show(args[1], ' '.join(args[2:]))
    else:
        print(__doc__)
