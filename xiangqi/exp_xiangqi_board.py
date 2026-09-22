# -*- coding: utf-8 -*-
"""实验 B：看盘与关系判断。Jev 下中国象棋不行，是读不准盘面（H2：哪格有什么子都读不准），
还是读得到子、却算不出子与子的关系（H3：马腿、炮架、谁能吃谁）？国际象棋同题做对照。

    python exp_xiangqi_board.py check                 # 只出题、跑断言、打印题目分布与请求量估计，不发请求、不需要 key
    python exp_xiangqi_board.py run [--only=B0,B1] [--expect=指纹] [--workers=6]   # 发请求，原始回包写 xiangqi_board_log.json；已成功的跳过（断点续跑）；
                                                      # 给了 --expect 时题目指纹不符就不发；跑的途中底座 / 局面文件一改就重算指纹，变了即停
    python exp_xiangqi_board.py fingerprint           # 只打印题目指纹
    python exp_xiangqi_board.py b2c-extra             # 用引擎重下补测 B2C 的自对弈，核对脚本里的 B2C_EXTRA（不发请求）
    python exp_xiangqi_board.py b2p-gen               # 用引擎重下补测 B2P 的自对弈，核对脚本里的 B2P_BASE（不发请求，约 5 分钟）
    python exp_xiangqi_board.py void-b3               # 把日志里第一版 B3 的条目挪进作废日志（只挪与第一版逐字相同的；可重复执行）
    python exp_xiangqi_board.py report [--only=B2C,B2P,B3v1]   # 只读日志出表，不发请求；--only 只出列出的补测小节

判别逻辑：B1 识子好、B2 / B3 差才支持 H3；B1 就差则是 H2。cells（格子表）形态下识子只是查表，是阳性对照：
若 cells 下 B1 近满分而 B2 / B3 仍差，读盘就不是瓶颈。

各部分（局面 = 局面集 set='middle'，两棋种各 30 个，B0 不用局面）：
  B0 纯规则：不给棋盘，两棋种各 12 条规则陈述（真假各半，覆盖各子种走法、吃法和特殊规则；
     初探的 6+3 条原样保留），一棋种一次请求问完，同一请求体重复 3 次看抖动。
  B1 识子：每局面 12 格（6 有子，双方各 3 格、子种尽量不重复；6 空格），choice「X 格上是什么」，
     候选 = 空 + 双方各子种（中国象棋 15 项、国际象棋 13 项；键就是「红马」这类子名，每题独立打乱顺序）。
     四种 state 形态 fen / cells / pieces / board，题目与选项顺序在各形态间完全相同，只换 state。
  B2 规则落盘：每局面 12 步（6 合法、6 违规），noul「在当前局面下，这一步是否符合规则？」，
     描述只写「某子从 X 走到 Y」（U0，不写吃子，不写犯了哪条）。违规按类型全局平衡抽题：
     每局面每类至多 1 步，优先抽全局还少的类型；每步违规只犯一条（own 类要求「目标格换成对方子就合法」，
     shape 类只取两格以内的走错形）；国际象棋不出易位题（cells 形态里没有易位权，判不了）。
     合法步按违规步的棋子种类配对抽（有马的违规就配一步合法的马），防止「看子种猜」。形态 fen / cells。
  B3 受攻判断：每局面 8 个红 / 白方的子（不含帅 / 王），真值 boards.capturable（黑方走一步能否合法吃掉它）。
     能被吃的取 min(4, 实有数)，其余是不能被吃的（局面集里多数局面凑不满 4 个能被吃的，见 check 输出）；
     不能被吃的里尽量一半取「差一点」的（对方有子够得着、但被马腿 / 炮架 / 越子 / 牵制等挡住）。形态 fen / cells。
     第二版（现行）：state 用同一盘面、行棋方改成黑方（FEN 第二段 b，side_to_move「黑方」），
     题目「黑方现在能否吃掉 e5 上的红马？」。黑方此刻被将的局面会让「能否吃」受应将限制，自检断言没有这种局面
     （局面集都是黑方刚走完一步合法着、轮到红方走，黑方不可能正被将；万一出现就报错停下，不跳过）。
     第一版（作废）：state 写红 / 白方走，题目却问「假设现在轮到黑方走：黑方下一步能否吃掉……」，两处互相矛盾。
     第一版的 160 条回包由 void-b3 挪进作废日志 xiangqi_board_void_log.json，不进分析，只在 B3v1 小节做新旧对比；
     build_b3_v1 能逐字重建第一版请求，selfcheck 断言它与 B0–B2 合起来的指纹仍是原批次的 54ddf0d8213128c0。
  抖动：前 10 个局面的 B1 / B2 / B3（fen 形态）同一请求体再发 2 次（r1、r2）。
  同请求多题是否互相影响：前 5 个局面的 B1、B2（fen）拆成一题一请求，与多题一请求（r0，另有 r1 / r2 看抖动）对比。
  B2C 炮架配对（补测）：B2 里合法的炮吃子只有 2 步，分不清「数炮架」与「见炮吃子就判违规」。30 组，每组取一个自对弈局面里的
     一步合法炮吃子（中间恰好一个子），再各改一个子造出三个相近局面：拿掉炮架（无架吃子）、在路径空格加一个兵卒（两架吃子）、
     拿掉目标子（不吃子却越子）。同组四道题文字一字不差（B2 的问法与 U0 描述），只能靠读盘分辨；形态 cells 与 fen，一题一请求。
     底局面先取局面集（每盘自对弈一组，只凑得出 17 组），其余 13 组来自按同一对弈法多下的自对弈（B2C_EXTRA）。
     所有局面 placement_issues 为空、没有同一方两个未过河兵同线、双方都未被将、帅将不照面。
  B2P 规则落盘配对题（补测 2）：B2 的违规类型只是 violation 返回的第一条，合法对照也没完全按子种配平，逐类型结论不够硬。
     五类各 30 组，每组题只差造成违规的那一个条件（着法一律走到空格，免得「目标格有子」这条线索掺进来）：
       leg     蹩马腿：同一匹马、同一步，马腿格有子（自对弈原局面） vs 把马腿上的子拿掉（合法）
       eye     塞象眼：同一只相、同一步，象眼有子（原局面） vs 把象眼上的子拿掉（合法）
       palace  出九宫：同一个仕 / 帅、同一格出发，走出九宫的一步 vs 九宫内的合法一步（同一局面，两步文字不同）
       pawn    兵未过河横走：河口（横线 4）的兵横走 vs 同一个兵前进一步（合法，同一局面）
               vs 把这个兵挪到过河后的横线 5、再往同一方向横走（合法，已过河兵横走作对照）
       facing  帅将照面：帅将同线、中间恰好两个子，其中一个红子走离这条线（原局面，合法） vs 拿掉另一个子后同一步（照面）
     每道违规题只犯这一条：leg / eye / facing 的合法对照就是「修掉该条件」的局面，同一步在 pyffish 下合法；
     palace / pawn 的区域规则改不了盘面，改为断言「去掉区域规则就合法」：走完不照面、己方帅不被将（legal_but_region）。
     底局面来自按局面集同一对弈法多下的自对弈（make_positions.selfplay，每类一段局序号，见 B2P_GAME0），
     每盘在第 20–100 半回合、轮红走、未被将、摆法合法的局面里收集能造的配对，按 seed_of('B2P', 类, 局序号) 挑一组；
     每盘至多一组，五类局序号不重叠，所以 150 组来自 150 盘不同的对局，按组聚类就是按对局聚类。
     B2P_BASE 存挑出的 (局序号, 半回合, FEN, 着法)，b2p-gen 重下核对。问法同 B2（U0 描述），一题一请求；
     形态 cells 全部组，fen 对照只做每类前 15 组。

请求量：B0 6 + B1 240 + B2 120 + B3 120 + 抖动 120 + 单题 240 = 846 次（原批次，题目指纹 54ddf0d8213128c0，$0.0615）；
补测 B2C 30 组 × 4 类 × 2 形态 = 240 次（$0.0053）。
补测 2：B3 第二版 160 次（B3 120 + 抖动 40，替换作废的第一版 160 次）；B2P cells 330 次 + fen 165 次 = 495 次。
统计：noul 报 AUC（与阈值无关）与 p≥0.5 判「是」的准确率；choice 报准确率、p(正解)、p(正解)×候选数、
正解排名的归一化位置（0 = 排第一）；区间一律按局面聚类 bootstrap（每个中局局面来自不同的自对弈对局，
所以局面聚类就是对局聚类）；形态之间按局面配对，两棋种之间是不同局面、独立重抽。B0 没有局面，按陈述给 Wilson 区间。

题目自检（check / run / report 都会先跑）：B1 真值用 boards.parse，且 cells 形态的 state 里确实查得到；
B2 每步的「合法」与 pyffish 合法着法集合一致、违规类型与 boards.violation 一致，合法步的描述与 boards.describe(U0) 逐字相同，
全部描述不含 boards.ZH_HINTS、不带吃子 / 将军标记、同局面两两不同；B3 真值用 boards.capturable，
并与「黑方走的那个局面里有没有吃这一格的合法着」复算一致。
每条回包检查模型串必须是 typesafe/jev-1.13-20260917，不是就立即停。
report 核对：日志里的条目与当前出题一一对应、state 与题目逐字相同、没有计划外条目；作废日志与 build_b3_v1 逐字相同。
日志 xiangqi_board_log.json、作废日志 xiangqi_board_void_log.json 都被 .gitignore 排除，不入库。
"""
# 让本脚本从任意目录都能找到仓库根部的 jevkit.py
import sys as _sys, pathlib as _pathlib
_sys.path.insert(0, str(_pathlib.Path(__file__).resolve().parent.parent))
import collections, json, math, os, random, sys, time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import boards as B

LOG = os.environ.get('XQB_LOG') or os.path.join(HERE, 'xiangqi_board_log.json')   # XQB_LOG 只给离线测报告用
VOID = os.environ.get('XQB_VOID') or os.path.join(HERE, 'xiangqi_board_void_log.json')   # 作废的第一版 B3
B_V1_FP = '54ddf0d8213128c0'      # 原批次 846 个请求（B0–B3，B3 为第一版）的题目指纹
MODEL = 'typesafe/jev-1.13-20260917'
XQ, CH = B.XQ, B.CH
FORMS_B1 = ('fen', 'cells', 'pieces', 'board')
FORMS_B23 = ('fen', 'cells')
N_JIT, N_SGL, JIT_REPS = 10, 5, (1, 2)
WORKERS = 6
BOOT = 4000
GNAME = {XQ: '中国象棋', CH: '国际象棋'}

# ---------------------------------------------------------------- B0 规则陈述
# 前 6 条中国象棋、前 3 条国际象棋是初探（games/exp_game_xiangqi.py）的原句
B0 = {
    XQ: [
        ('xq_n', True, '中国象棋里，马走日字时，如果「马腿」那一格被任何棋子占住，这一步就不能走。'),
        ('xq_c1', True, '中国象棋里，炮要吃掉对方的子，中间必须正好隔着一个棋子。'),
        ('xq_p', True, '中国象棋里，兵（卒）过河之后才可以横着走一格，过河之前只能向前。'),
        ('xq_a1', False, '中国象棋里，士（仕）可以在九宫内横着或竖着走一格。'),
        ('xq_b1', True, '中国象棋里，相（象）走田字，田字中心那一格有子时就走不过去。'),
        ('xq_k2', False, '中国象棋里，帅和将允许在同一条竖线上直接照面、中间不隔任何棋子。'),
        ('xq_r', True, '中国象棋里，车沿横线或竖线走，格数不限，但不能越过中间的棋子。'),
        ('xq_a2', True, '中国象棋里，士（仕）每步沿斜线走一格，而且不能走出九宫。'),
        ('xq_k1', False, '中国象棋里，帅（将）每步走一格，可以走到九宫外面去。'),
        ('xq_b2', False, '中国象棋里，相（象）可以过河，走到对方那一半棋盘上。'),
        ('xq_c2', False, '中国象棋里，炮不吃子、只是移动时，也可以跳过中间的一个棋子。'),
        ('xq_s', False, '中国象棋里，轮到走棋的一方没有任何合法着法、但并没有被将军时，算作和棋。'),
    ],
    CH: [
        ('ch_c', False, '国际象棋里，王车易位时，王可以经过正被对方攻击的格子。'),
        ('ch_pr', True, '国际象棋里，兵走到对方底线时必须升变成后、车、象或马之一。'),
        ('ch_ep', True, '国际象棋里，吃过路兵只能在对方兵刚刚一次走两格之后的那一步立刻进行。'),
        ('ch_k1', True, '国际象棋里，王不能走到正被对方棋子攻击的格子上。'),
        ('ch_k2', False, '国际象棋里，王每步可以沿任意方向走两格。'),
        ('ch_q', True, '国际象棋里，后可以沿横线、竖线或斜线走任意格，但不能越过其他棋子。'),
        ('ch_r', False, '国际象棋里，车既可以沿横线、竖线走，也可以沿斜线走。'),
        ('ch_b', True, '国际象棋里，象只沿斜线走，所以一个象始终停在同一种颜色的格子上。'),
        ('ch_n', True, '国际象棋里，马走「L」形（沿一个方向走两格再横走一格），可以越过中间的棋子。'),
        ('ch_p1', False, '国际象棋里，兵可以后退一格。'),
        ('ch_p2', False, '国际象棋里，兵在任何位置都可以一次向前走两格。'),
        ('ch_s', False, '国际象棋里，轮到走棋的一方没有任何合法着法、但并没有被将军时，这一方判负。'),
    ],
}
B0_STATE = {'topic': '棋类规则常识判断'}   # 与初探相同

# B2 违规类型：列表顺序只用于全局计数打平时的先后（稀有、设计文档点名的在前）
B2_TYPES = {
    XQ: ['facing', 'river', 'eye', 'self_check', 'screen2', 'screen0', 'leg', 'palace', 'jump_r', 'jump_c',
         'pawn_side', 'pawn_back', 'own', 'shape'],
    CH: ['pin', 'king_attacked', 'self_check', 'pawn_block', 'jump', 'shape_n', 'shape_p', 'shape_s', 'shape_k', 'own'],
}
TYPE_ZH = {
    'facing': '走完帅将照面', 'river': '相过河', 'eye': '塞象眼', 'self_check': '走完自己被将', 'screen2': '炮隔两子以上吃子',
    'screen0': '炮无架吃子', 'leg': '蹩马腿', 'palace': '出九宫', 'jump_r': '车越子', 'jump_c': '炮不吃子却越子',
    'pawn_side': '兵未过河横走', 'pawn_back': '兵后退', 'own': '目标格有己方子', 'shape': '走错形（两格内）',
    'pin': '被牵制子离线', 'king_attacked': '王走进被攻击格', 'pawn_block': '兵前方有子', 'jump': '滑子越子',
    'shape_n': '马走错形', 'shape_p': '兵走错形', 'shape_s': '象车后走错线', 'shape_k': '王走两格',
}
# 「只看这个子自己和格子位置就能判」vs「要看别的子」
LOCAL = {'river', 'palace', 'pawn_side', 'pawn_back', 'shape', 'shape_n', 'shape_p', 'shape_s', 'shape_k', 'own'}


# ---------------------------------------------------------------- 局面
_DATA = None


def positions(game):
    global _DATA
    if _DATA is None:
        _DATA = B.load_positions()
    ps = sorted(B.select(_DATA, game=game, set_='middle'), key=lambda p: p['id'])
    assert len(ps) == 30, (game, len(ps))
    return ps


def side_names(game):
    return B.SIDE[(game, 'zh')]


# ---------------------------------------------------------------- B1 识子
def b1_labels(game):
    """候选：空 + 双方各子种。{键: 描述}（未打乱）。"""
    red, black = side_names(game)
    out = {'空': '这一格没有棋子'}
    for letters, side in ((B.ORDER[game], red), (B.ORDER[game].lower(), black)):
        for L in letters:
            out[B.label(game, L)] = '%s的%s' % (side, B.piece_name(game, L))
    assert len(out) == (15 if game == XQ else 13), len(out)
    return out


def b1_items(game, p):
    """-> [(题名, 格, 真值键)]，12 题，已打乱。"""
    board, stm = B.parse(game, p['fen'])
    rng = random.Random(B.seed_of('B1', p['id']))
    occ = {True: [], False: []}
    for s in sorted(board):
        occ[B.is_red(board[s])].append(s)
    for v in occ.values():
        rng.shuffle(v)
    chosen, kinds = [], set()
    for side in (True, False, True, False, True, False):
        cand = [s for s in occ[side] if s not in chosen and board[s] not in kinds] or \
               [s for s in occ[side] if s not in chosen]
        s = cand[0]
        chosen.append(s)
        kinds.add(board[s])
    allsq = [B.sq_of(x, y) for x in range(len(B.FILES[game])) for y in range(B.BOTTOM[game], B.TOP[game] + 1)]
    empty = sorted(s for s in allsq if s not in board)
    rng.shuffle(empty)
    chosen += empty[:6]
    rng.shuffle(chosen)
    items = []
    for i, s in enumerate(chosen):
        truth = B.label(game, board[s]) if s in board else '空'
        items.append(('q%02d' % (i + 1), s, truth))
    return items


def b1_question(game, pid, sq):
    labels = b1_labels(game)
    keys = list(labels)
    random.Random(B.seed_of('B1opt', pid, sq)).shuffle(keys)
    return {'type': 'choice', 'instructions': '%s 这一格上现在是什么？选出这一格上的棋子；没有棋子就选「空」。' % sq,
            'criteria': {k: labels[k] for k in keys}}


# ---------------------------------------------------------------- B2 规则落盘
def u0(game, board, mv):
    """U0 写法，合法着法与 boards.describe(U0) 逐字相同（check 里断言）；违规着法照同一格式写。"""
    fr, to, promo = B.split_move(mv)
    s = '%s从 %s 走到 %s' % (B.piece_name(game, board[fr]), fr, to)
    if promo:
        s += '，升变为%s' % B.piece_name(game, promo)
    return s


def only_own(game, fen, board, mv):
    """目标格是己方子这步，若把那格换成对方子是否就合法——是，才算「只犯 own 一条」。"""
    fr, to, _ = B.split_move(mv)
    if board[to].lower() == 'k':
        return False
    red = B.is_red(board[fr])
    enemy = 'p' if red else 'P'
    if game == CH and to[1] in '18':
        enemy = 'n' if red else 'N'
    b2 = dict(board)
    b2[to] = enemy
    parts = fen.split()
    if game == CH:
        parts[2] = '-'      # 只看吃子几何；易位本来就不出题，去掉易位权免得换掉角上的车后 FEN 不合法
    f2 = B.board_fen(game, b2) + ' ' + ' '.join(parts[1:])
    try:
        f2 = B.norm(game, f2)
    except AssertionError:
        return False
    if B.in_check(game, f2):
        return False
    return B.violation(game, f2, mv) is None


def b2_subtype(game, fen, board, mv, v):
    """violation 键 -> 抽题类型；None = 不出这道题。"""
    fr, to, _ = B.split_move(mv)
    kind = board[fr].lower()
    (x1, y1), (x2, y2) = B.xy(fr), B.xy(to)
    near = max(abs(x2 - x1), abs(y2 - y1)) <= 2
    if v == 'castle':
        return None
    if v == 'own':
        return 'own' if only_own(game, fen, board, mv) else None
    if game == XQ:
        if v == 'shape':
            return 'shape' if near else None
        if v == 'jump':
            return 'jump_r' if kind == 'r' else 'jump_c'
        return v
    if v == 'shape':
        if not near:
            return None
        return {'n': 'shape_n', 'p': 'shape_p', 'k': 'shape_k'}.get(kind, 'shape_s')
    return v


def b2_legal_pool(game, fen, board):
    out = []
    for m in B.legal(game, fen):
        fr, to, promo = B.split_move(m)
        if game == CH:
            if board[fr] in 'Kk' and abs(B.xy(fr)[0] - B.xy(to)[0]) == 2:
                continue        # 易位：cells 形态里看不到易位权
            if promo and promo != 'q':
                continue        # 与 pseudo_moves 一致，只出升后
            if board[fr] in 'Pp' and fr[0] != to[0] and to not in board:
                continue        # 过路兵（局面集里没有，保险）
        out.append(m)
    return out


_B2_PLAN = {}


def b2_plan(game):
    """全局平衡抽题。-> {局面 id: [(题名, 着法, 合法?, 类型或 None)]}"""
    if game in _B2_PLAN:
        return _B2_PLAN[game]
    types = B2_TYPES[game]
    count = collections.Counter()
    plan = {}
    for p in positions(game):
        fen = p['fen']
        board, _ = B.parse(game, fen)
        rng = random.Random(B.seed_of('B2', p['id']))
        pools = collections.defaultdict(list)
        for mv, v in sorted(B.pseudo_moves(game, fen).items()):
            if v is None:
                continue
            t = b2_subtype(game, fen, board, mv, v)
            if t is not None:
                assert t in types, (game, mv, v, t)
                pools[t].append(mv)
        chosen, used = [], set()
        while len(chosen) < 6:
            avail = [t for t in types if pools[t] and t not in used] or [t for t in types if pools[t]]
            t = min(avail, key=lambda t: (count[t], types.index(t)))
            mv = rng.choice(pools[t])
            pools[t].remove(mv)
            chosen.append((mv, t))
            used.add(t)
            count[t] += 1
        lp = b2_legal_pool(game, fen, board)
        legal_chosen = []
        for mv, t in chosen:
            kind = board[mv[:2]].lower()
            cands = [m for m in lp if board[m[:2]].lower() == kind and m not in legal_chosen] or \
                    [m for m in lp if m not in legal_chosen]
            legal_chosen.append(rng.choice(cands))
        rows = [(m, True, None) for m in legal_chosen] + [(m, False, t) for m, t in chosen]
        rng.shuffle(rows)
        plan[p['id']] = [('q%02d' % (i + 1),) + r for i, r in enumerate(rows)]
    _B2_PLAN[game] = plan
    return plan


def b2_question(game, board, mv):
    return {'type': 'noul', 'instructions': '在当前局面下，这一步是否符合%s规则？着法：%s' % (GNAME[game], u0(game, board, mv))}


# ---------------------------------------------------------------- B3 受攻判断
def flipped(game, fen):
    parts = fen.split()
    parts[1] = 'b' if parts[1] == 'w' else 'w'
    if game == CH:
        parts[3] = '-'
    return ' '.join(parts)


def near_types(game, fen, sq):
    """对方有哪些子「够得着」sq 却吃不了：返回对方走到 sq 的伪着法里除走错形以外的违规类型集合。"""
    board, stm = B.parse(game, fen)
    f2 = flipped(game, fen)
    out = set()
    for fr, q in board.items():
        if B.is_red(q) == (stm == 'w'):
            continue
        mv = fr + sq
        if game == CH and q in 'Pp' and sq[1] in '18':
            mv += 'q'
        v = B.violation(game, f2, mv)
        assert v is None or v != 'own'
        if v is not None and v != 'shape':
            out.add(v)
    return sorted(out)


def attackers(game, fen, sq):
    """对方哪些子能合法吃 sq（子的字母）。"""
    board, _ = B.parse(game, fen)
    f2 = flipped(game, fen)
    return sorted({board[m[:2]] for m in B.legal(game, f2) if m[2:4] == sq})


def b3_items(game, p):
    """-> [(题名, 格, 能被吃?, 类别)]；类别：cap / near / far。"""
    fen = p['fen']
    board, stm = B.parse(game, fen)
    own = sorted(s for s, q in board.items() if B.is_red(q) == (stm == 'w') and q not in 'Kk')
    assert len(own) >= 8, (p['id'], len(own))
    cap = [s for s in own if B.capturable(game, fen, s)]
    non = [s for s in own if s not in cap]
    rng = random.Random(B.seed_of('B3', p['id']))
    k = min(4, len(cap))
    capc = rng.sample(cap, k)
    near = [s for s in non if near_types(game, fen, s)]
    far = [s for s in non if s not in near]
    m = 8 - k
    nn = min(len(near), m // 2)
    pick_near = rng.sample(near, nn)
    pick_far = rng.sample(far, min(len(far), m - nn))
    rest = [s for s in near if s not in pick_near]
    pick_near += rng.sample(rest, m - nn - len(pick_far))
    rows = [(s, True, 'cap') for s in capc] + [(s, False, 'near') for s in pick_near] + [(s, False, 'far') for s in pick_far]
    assert len(rows) == 8
    rng.shuffle(rows)
    return [('q%02d' % (i + 1),) + r for i, r in enumerate(rows)]


def b3_truth(game, fen, board, items):
    return {n: {'sq': s, 'truth': ok, 'cat': c, 'kind': board[s].lower(),
                'near': near_types(game, fen, s) if c == 'near' else [],
                'att': attackers(game, fen, s) if ok else []} for n, s, ok, c in items}


def b3_fen(game, fen):
    """第二版 B3 的 state 局面：同一盘面，轮到黑方走（国际象棋去掉过路兵格，与 capturable 同口径；易位权原样，吃子用不到）。"""
    return B.norm(game, flipped(game, fen))


def b3_question(game, board, sq):
    """第二版：state 里就是黑方走，直接问黑方现在能否吃。"""
    red, black = side_names(game)
    assert B.is_red(board[sq])
    return {'type': 'noul', 'instructions': '%s现在能否吃掉 %s 上的%s？' % (black, sq, B.label(game, board[sq]))}


def b3_question_v1(game, board, sq):
    """第一版（作废）：state 写红 / 白方走，题目却假设轮到黑方走。只用来核对作废日志、做新旧对比。"""
    red, black = side_names(game)
    opp = black if B.is_red(board[sq]) else red
    return {'type': 'noul', 'instructions': '假设现在轮到%s走：%s下一步能否吃掉 %s 上的%s？' % (opp, opp, sq, B.label(game, board[sq]))}


# ---------------------------------------------------------------- B2C 炮架配对（补测）
# B2 里合法的炮吃子只抽到 2 步，分不清 Jev 是在数炮架还是「见炮吃子就判违规」。这里每组（family）固定
# 一个自然局面里的一步合法炮吃子（中间恰好一个子），再各改一个子造出三个「相近局面」，着法文字一字不差：
#   legal    原局面：中间恰好一个子，目标格是对方子（合法）
#   screen0  拿掉炮架：中间没有子（违规：炮吃子没有炮架）
#   screen2  在炮与目标之间的空格里加一个兵 / 卒：中间两个子（违规：隔两个子吃子）
#   jump     拿掉目标子：炮不吃子却越过一个子（违规）
# 所以同一组四道题只差「炮架数」或「目标格有没有子」，文字相同，答案只能靠读盘。
B2C_N = 30
B2C_CLASSES = ('legal', 'screen0', 'screen2', 'jump')
B2C_ZH = {'legal': '合法炮吃子（中间恰好一个子）', 'screen0': '违规：炮吃子、中间没有子',
          'screen2': '违规：炮吃子、中间两个子', 'jump': '违规：炮不吃子却越子'}
B2C_VIOL = {'legal': None, 'screen0': 'screen0', 'screen2': 'screen2', 'jump': 'jump'}
B2C_SCREENS = {'legal': 1, 'screen0': 0, 'screen2': 2, 'jump': 1}
FORMS_B2C = ('cells', 'fen')
# 局面集里能造出四个合法相近局面的自对弈对局只有 17 盘，不够 30 组。其余 13 组来自多下的自对弈：
# make_positions.selfplay(XQ, 局序号)（与局面集同一对弈法、同一套种子规则），局序号从 10000 起；每盘在第 20–100 半回合、
# 轮红走、未被将、摆法合法的局面里找能造出四个局面的合法炮吃子，按 seed_of('B2Cextra', 局序号) 挑一步。
# 重新生成并比对：python exp_xiangqi_board.py b2c-extra（gen_b2c_extra，连跑两次输出逐字相同）。(局序号, 半回合, FEN, 着法)
B2C_EXTRA = [
    (10000, 22, 'rnbak1br1/4a4/6n2/p1p1p1p1p/9/6P1P/c1P1P2c1/N3B1N1C/4A4/R3KABR1 w - - 0 1', 'i2i6'),
    (10001, 74, '2bk1a3/4a2R1/4b4/8p/1Rp3nC1/4P4/8P/2N1B1r2/2crA4/4KAB2 w - - 0 1', 'h5c5'),
    (10002, 76, '9/4a3R/2n1kr3/p1pCp1p2/8p/2PR2P2/4N1c1P/4BAN2/1r7/3A1KB2 w - - 0 1', 'd6g6'),
    (10003, 58, '4k1b2/1C5C1/4ba1r1/pcp5p/9/P1PR5/4P3P/4Bp3/8N/3NKABc1 w - - 0 1', 'h8h0'),
    (10004, 64, '3rkab2/7c1/3a3C1/2pn1C3/3R4N/2P1P4/P7P/2N1BA3/4A4/2B1KR3 w - - 0 1', 'f6c6'),
    (10005, 20, 'rn2kabnr/4a4/2c1b4/pCp5p/3Rp4/6B2/P1P1P2cP/2N3NC1/4A4/4KAB1R w - - 0 1', 'b6i6'),
    (10006, 34, '2b1kab1r/4a4/6n2/4p1p1p/9/p1p3P1P/P3P4/2N1BRn2/5C3/1rBAKA3 w - - 0 1', 'f1f9'),
    (10007, 22, 'r3kabr1/4a4/c1n1b3n/p3p1p1p/2p2N3/9/P1P1Pc2P/2N1B1C2/4A4/1R2KAB1R w - - 0 1', 'g2g9'),
    (10008, 74, '4ka3/4aR3/8b/P4C3/3r4P/4p3C/2Pc2P2/2N1B1n2/4A4/2BAK4 w - - 0 1', 'f6f9'),
    (10009, 64, 'C3ka3/4a4/3rbc1rb/R1p1p2cp/7R1/2P1Cp1n1/P3P1P1P/2N1B4/4A4/2BAK2N1 w - - 0 1', 'e4h4'),
    (10010, 30, 'r1b1ka3/4a3r/n3b4/p3pR2p/1n4c2/9/P1P3P1P/4C1N2/3RA4/1NB1K1B2 w - - 0 1', 'e2e7'),
    (10011, 22, '4kab1r/4a4/r1n1b1n2/1c2p1p2/p7p/2B6/P1C1P1PcP/2N3NC1/4A4/3RKAB1R w - - 0 1', 'c3c7'),
    (10012, 88, 'C4ab2/4a4/3k2n2/p1R6/2b6/1CB1p2rP/P3P1P2/1c7/4A4/2BAK4 w - - 0 1', 'a9g9'),
]


def b2c_positions():
    """底局面：局面集里全部自对弈出来的中国象棋局面（middle、gain、mate 的 natural 层），不用教科书和旧局面。"""
    global _DATA
    if _DATA is None:
        _DATA = B.load_positions()
    return sorted((p for p in B.select(_DATA, game=XQ) if p['stratum'] in ('selfplay', 'natural')),
                  key=lambda p: p['id'])


def b2c_extra():
    """-> [(局面 dict, 着法)]，多下的自对弈局面，格式与局面集一致。"""
    return [({'id': 'xq-sp%d-p%03d' % (idx, ply), 'fen': fen, 'source': {'selfplay': idx, 'ply': ply}}, mv)
            for idx, ply, fen, mv in B2C_EXTRA]


def facing(board):
    ks = {q: s for s, q in board.items() if q in 'Kk'}
    return ks['K'][0] == ks['k'][0] and not any(board.get(s) for s in B._between(ks['K'], ks['k']))


def xq_fen(board):
    return B.norm(XQ, B.board_fen(XQ, board) + ' w - - 0 1')


def pawn_stack(board):
    """同一方两个未过河的兵（卒）在同一条纵线上：兵过河前只能直走，这种摆法到不了（placement_issues 不查这一条，这里补上）。"""
    files = collections.Counter()
    for s, q in board.items():
        if q in 'Pp' and ((B.xy(s)[1] <= 4) if q == 'P' else (B.xy(s)[1] >= 5)):
            files[(q, s[0])] += 1
    return any(v > 1 for v in files.values())


def legal_position(board):
    """摆法到得了（placement_issues 为空，且没有同一方两个未过河兵同线）、红方先走且未被将、黑方也不在被将状态
    （否则轮红走的局面不合法）、帅将不照面。返回规范化 FEN；不合法返回 None。"""
    if facing(board) or pawn_stack(board):
        return None
    try:
        fen = xq_fen(board)
    except AssertionError:
        return None
    if B.placement_issues(XQ, fen) or B.in_check(XQ, fen) or B.in_check(XQ, flipped(XQ, fen)):
        return None
    return fen


def n_screens(board, mv):
    return sum(1 for s in B._between(mv[:2], mv[2:4]) if s in board)


def b2c_family(p, mv, rng):
    """一步合法炮吃子 -> {类: FEN} 与改动说明；造不出合法的四个局面返回 None。"""
    fen = p['fen']
    board, stm = B.parse(XQ, fen)
    fr, to, _ = B.split_move(mv)
    path = B._between(fr, to)
    scr = [s for s in path if s in board]
    empty = [s for s in path if s not in board]
    if board[fr] != 'C' or to not in board or B.is_red(board[to]) or len(scr) != 1 or not empty:
        return None
    if board[scr[0]] in 'Kk' or legal_position(board) != fen:
        return None
    out = {'legal': fen}
    b0 = dict(board)
    del b0[scr[0]]
    out['screen0'] = legal_position(b0)
    bj = dict(board)
    del bj[to]
    out['jump'] = legal_position(bj)
    added = None
    tries = [(s, q) for s in empty for q in 'pP']
    rng.shuffle(tries)
    for s, q in tries:
        b2 = dict(board)
        b2[s] = q
        f2 = legal_position(b2)
        if f2:
            out['screen2'], added = f2, (s, q)
            break
    if any(out.get(c) is None for c in B2C_CLASSES):
        return None
    return {'fens': out, 'screen': scr[0], 'screen_piece': board[scr[0]], 'target': to, 'target_piece': board[to],
            'added': added}


_B2C = None


def _b2c_pick(pairs, cap):
    """按顺序挑：每盘自对弈至多一组，造不出四个合法局面的跳过，挑满 cap 组为止。"""
    fams, games = [], set()
    for p, mv in pairs:
        g = p['source']['selfplay']
        if g in games:
            continue
        f = b2c_family(p, mv, random.Random(B.seed_of('B2Cadd', p['id'], mv)))
        if f is None:
            continue
        games.add(g)
        f.update(pid=p['id'], selfplay=g, move=mv, extra=g >= 10000)
        fams.append(f)
        if len(fams) == cap:
            break
    return fams


def b2c_natural_cands():
    """局面集里全部合法炮吃子，按固定种子打乱。"""
    cands = []
    for p in b2c_positions():
        board, _ = B.parse(XQ, p['fen'])
        for mv in B.legal(XQ, p['fen']):
            if board[mv[:2]] == 'C' and mv[2:4] in board:
                cands.append((p, mv))
    random.Random(B.seed_of('B2C')).shuffle(cands)
    return cands


def b2c_plan():
    """-> [family]，B2C_N 组，每盘自对弈至多一组（组间独立，按组聚类就是按对局聚类）。
    先用局面集（候选按固定种子打乱，每盘取第一个造得出的），不够再按顺序用 B2C_EXTRA。"""
    global _B2C
    if _B2C is not None:
        return _B2C
    fams = _b2c_pick(b2c_natural_cands() + b2c_extra(), B2C_N)
    assert len(fams) == B2C_N, ('合法的炮架配对不够', len(fams))
    fams.sort(key=lambda f: (f['pid'], f['move']))
    for i, f in enumerate(fams):
        f['fid'] = 'c%02d' % (i + 1)
    _B2C = fams
    return fams


def gen_b2c_extra():
    """重新生成 B2C_EXTRA（要引擎，约 15 秒）并与脚本里的常量比对：局面集凑出几组，就从局序号 10000 起多下几盘补足。
    每盘在第 20–100 半回合、轮红走、未被将、摆法合法的局面里收集造得出四个局面的合法炮吃子，按 seed_of('B2Cextra', 局序号) 挑一步。"""
    import make_positions as MP
    need = B2C_N - len(_b2c_pick(b2c_natural_cands(), B2C_N))
    eng = B.Engine(XQ)
    out, idx = [], 10000
    while len(out) < need:
        cands = []
        for ply, fen in enumerate(MP.selfplay(XQ, idx, eng)):
            if ply % 2 or ply < 20 or ply > 100:
                continue
            fen = B.reset_clock(B.norm(XQ, fen))
            board, stm = B.parse(XQ, fen)
            if stm != 'w' or B.status(XQ, fen) != 'ok' or B.placement_issues(XQ, fen):
                continue
            pid = 'xq-sp%d-p%03d' % (idx, ply)
            for mv in B.legal(XQ, fen):
                if board[mv[:2]] == 'C' and mv[2:4] in board and \
                        b2c_family({'fen': fen, 'id': pid}, mv, random.Random(B.seed_of('B2Cadd', pid, mv))):
                    cands.append((ply, fen, mv))
        if cands:
            ply, fen, mv = random.Random(B.seed_of('B2Cextra', idx)).choice(cands)
            out.append((idx, ply, fen, mv))
        idx += 1
    for row in out:
        print('    (%d, %d, %r, %r),' % row)
    print('局面集凑出 %d 组，补 %d 盘；与脚本里的 B2C_EXTRA %s' % (B2C_N - need, need, '一致' if out == B2C_EXTRA else '不一致'))
    return out == B2C_EXTRA


# ---------------------------------------------------------------- B2P 规则落盘配对题（补测 2）
# 每组题只差造成违规的那一个条件。类（cls）：viol = 违规题；legal = 合法对照；crossed = 已过河兵横走（只有 pawn 有）。
B2P_TYPES = ('leg', 'eye', 'palace', 'pawn', 'facing')
B2P_N = 30
B2P_FEN_N = 15                      # fen 对照只做每类前 15 组
FORMS_B2P = ('cells', 'fen')
B2P_GAME0 = {'leg': 20000, 'eye': 21000, 'palace': 22000, 'pawn': 23000, 'facing': 24000}   # 每类自对弈的起始局序号
B2P_CLASSES = {'leg': ('viol', 'legal'), 'eye': ('viol', 'legal'), 'palace': ('viol', 'legal'),
               'pawn': ('viol', 'legal', 'crossed'), 'facing': ('viol', 'legal')}
B2P_VIOL = {'leg': 'leg', 'eye': 'eye', 'palace': 'palace', 'pawn': 'pawn_side', 'facing': 'facing'}
B2P_ZH = {'leg': '蹩马腿', 'eye': '塞象眼', 'palace': '出九宫', 'pawn': '兵未过河横走', 'facing': '走完帅将照面'}
B2P_CLS_ZH = {
    'leg': {'viol': '违规：马腿格有子（原局面）', 'legal': '合法：马腿上的子拿掉'},
    'eye': {'viol': '违规：象眼有子（原局面）', 'legal': '合法：象眼上的子拿掉'},
    'palace': {'viol': '违规：走出九宫', 'legal': '合法：同一个子在九宫内走一步'},
    'pawn': {'viol': '违规：河口的兵横走', 'legal': '合法：同一个兵前进', 'crossed': '合法：这个兵挪过河后横走'},
    'facing': {'viol': '违规：拿掉另一个子后，走完帅将照面', 'legal': '合法：原局面（帅将之间还有另一个子）'},
}
B2P_PIECE = {'leg': 'N', 'eye': 'B', 'palace': 'AK', 'pawn': 'P', 'facing': 'RNBACP'}


def legal_but_region(board, mv):
    """红方走 mv，若不管九宫 / 河界这类区域规则，是否合法：走完帅将不照面、红帅不被将（pyffish 判将，与帅在哪一格无关）。
    palace / pawn 两类的「只犯这一条」用它断言：违规题除了区域规则，别的都合法。自检里拿 B2 局面的全部合法着和自将、照面着核对过它。"""
    after = dict(board)
    after[mv[2:4]] = after.pop(mv[:2])
    if facing(after):
        return False
    return not B.in_check(XQ, B.board_fen(XQ, after) + ' w - - 0 1')


def block_sq(t, mv):
    """马腿 / 象眼那一格。"""
    (x1, y1), (x2, y2) = B.xy(mv[:2]), B.xy(mv[2:4])
    dx, dy = x2 - x1, y2 - y1
    if t == 'eye':
        return B.sq_of(x1 + dx // 2, y1 + dy // 2)
    return B.sq_of(x1 + (dx // 2 if abs(dx) == 2 else 0), y1 + (dy // 2 if abs(dy) == 2 else 0))


def king_file_between(board):
    """帅将同线时返回两者之间的格（不含两端），否则 None。"""
    ks = {q: s for s, q in board.items() if q in 'Kk'}
    return B._between(ks['K'], ks['k']) if ks['K'][0] == ks['k'][0] else None


def b2p_family(t, fen, spec):
    """底局面 + spec -> {'fens': {类: FEN}, 'moves': {类: 着法}, 'edit', 'piece', 'natural'}；造不出合法的一组返回 None。
    spec：palace 是 (出九宫的着法, 九宫内的着法)，其余是一步着法（pawn 是横走那步，facing 是走离帅将线那步）。"""
    board, stm = B.parse(XQ, fen)
    if stm != 'w' or legal_position(board) != fen:
        return None
    mv = spec[0] if t == 'palace' else spec
    fr, to = mv[:2], mv[2:4]
    if board.get(fr) is None or board[fr] not in B2P_PIECE[t] or to in board:
        return None
    if t in ('leg', 'eye'):
        if B.violation(XQ, fen, mv) != t:
            return None
        blk = block_sq(t, mv)
        if board[blk] in 'Kk':
            return None
        b2 = dict(board)
        del b2[blk]
        f2 = legal_position(b2)
        if not f2 or mv not in B.legal(XQ, f2):
            return None
        return {'fens': {'viol': fen, 'legal': f2}, 'moves': {'viol': mv, 'legal': mv}, 'edit': ('拿掉', blk, board[blk]),
                'piece': board[fr], 'natural': 'viol'}
    if t == 'palace':
        mv_in = spec[1]
        if mv_in[:2] != fr or mv_in[2:4] in board or mv_in == mv:
            return None
        if B.violation(XQ, fen, mv) != 'palace' or not legal_but_region(board, mv) or mv_in not in B.legal(XQ, fen):
            return None
        return {'fens': {'viol': fen, 'legal': fen}, 'moves': {'viol': mv, 'legal': mv_in}, 'edit': None,
                'piece': board[fr], 'natural': 'both'}
    if t == 'pawn':
        x, y = B.xy(fr)
        if y != 4 or B.violation(XQ, fen, mv) != 'pawn_side' or not legal_but_region(board, mv):
            return None
        fwd, side2 = B.sq_of(x, 5), B.sq_of(B.xy(to)[0], 5)
        if fwd in board or side2 in board or fr + fwd not in B.legal(XQ, fen):
            return None
        b2 = dict(board)
        b2[fwd] = b2.pop(fr)
        f2 = legal_position(b2)
        if not f2 or fwd + side2 not in B.legal(XQ, f2):
            return None
        return {'fens': {'viol': fen, 'legal': fen, 'crossed': f2}, 'moves': {'viol': mv, 'legal': fr + fwd, 'crossed': fwd + side2},
                'edit': ('挪兵', fr, fwd), 'piece': 'P', 'natural': 'viol+legal'}
    # facing：原局面帅将同线、中间恰好两个子；红子 X 走离这条线合法；拿掉另一个子 Y 后同一步就照面
    between = king_file_between(board)
    if between is None:
        return None
    occ = [s for s in between if s in board]
    if len(occ) != 2 or fr not in occ or B.xy(to)[0] == B.xy(fr)[0] or mv not in B.legal(XQ, fen):
        return None
    y_sq = [s for s in occ if s != fr][0]
    b2 = dict(board)
    del b2[y_sq]
    f2 = legal_position(b2)
    if not f2 or B.violation(XQ, f2, mv) != 'facing':
        return None
    return {'fens': {'viol': f2, 'legal': fen}, 'moves': {'viol': mv, 'legal': mv}, 'edit': ('拿掉', y_sq, board[y_sq]),
            'piece': board[fr], 'natural': 'legal'}


def b2p_cands(t, fen):
    """一个局面里 t 类能造的全部 spec（顺序固定）。"""
    board, _ = B.parse(XQ, fen)
    out = []
    if t == 'palace':
        legal = B.legal(XQ, fen)
        for mv, v in sorted(B.pseudo_moves(XQ, fen).items()):
            if v == 'palace':
                for mi in legal:
                    if mi[:2] == mv[:2] and b2p_family(t, fen, (mv, mi)):
                        out.append((mv, mi))
        return out
    if t == 'facing':
        if king_file_between(board) is None:
            return out
        return [mv for mv in B.legal(XQ, fen) if b2p_family(t, fen, mv)]
    for mv, v in sorted(B.pseudo_moves(XQ, fen).items()):
        if v == B2P_VIOL[t] and b2p_family(t, fen, mv):
            out.append(mv)
    return out


# (局序号, 半回合, FEN, spec)，由 b2p-gen 生成并核对
B2P_BASE = {
    'leg': [   # 下了 30 盘
        (20000, 38, '2bak2rR/4a4/9/p3p4/2b3pP1/7c1/P3n1P2/4B1C2/4A4/1N1AK1BN1 w - - 0 1', 'h0f1'),
        (20001, 78, '2c1k2r1/4a4/4bC1n1/3PC4/4c4/4N1p2/P7p/5R3/4A4/2BK1ABN1 w - - 0 1', 'h0f1'),
        (20002, 22, '4kab1r/1c1ra4/2n1b2c1/p1P1p3p/5n3/6p1P/P3P4/3C2NC1/4N4/1RBAKAB1R w - - 0 1', 'g2i1'),
        (20003, 32, '3akab2/3n2r2/5Cc1n/p1p1p3p/9/6p2/P1P1P3P/2NABCN2/9/3K1AB1R w - - 0 1', 'c2e1'),
        (20004, 42, '2b1kab2/4a3n/5c2r/p1p1n1p2/9/P1P1P1P1P/9/2N1B1Nr1/4A4/3AK2CR w - - 0 1', 'g2i1'),
        (20005, 34, '4ka1c1/n3a4/4b1nr1/p1p1p1p2/2b6/8P/PR2P1P1N/2NAC4/9/2B1KAB2 w - - 0 1', 'i3h5'),
        (20006, 22, 'r1bak3r/1c2an3/2n1b4/2p1p1p1p/p8/5N2P/P1c1P4/1CN2C3/9/R1BAKABR1 w - - 0 1', 'c2b4'),
        (20007, 22, 'rcbakab2/9/2n3n2/2p5p/p3C4/6p2/PcP1P3P/R1N1B3N/4A2r1/2BAK3R w - - 0 1', 'c2d4'),
        (20008, 42, '2bakr3/4a4/2n1b4/rC1c4p/p3p2n1/1NB4R1/P3P3P/1C4N2/3cA4/2B1KA3 w - - 0 1', 'b4d5'),
        (20009, 24, '2b1kabn1/4a1C2/2n1c1c2/p3C1p1r/2p5p/9/P3P1P1P/B1r3N2/4A4/2R1KABR1 w - - 0 1', 'g2h4'),
        (20010, 24, 'rn2kab2/4a2c1/bRc3n2/p3p4/2p3P1r/5C2p/P1P1P3P/2N1C4/4A4/2B1KABNR w - - 0 1', 'c2d4'),
        (20011, 22, 'r1bak3r/4a4/3cb1n2/p3p1p1p/1n7/P1p6/2P1P1PcP/1C4C2/4A4/1NB1KABNR w - - 0 1', 'b0d1'),
        (20012, 22, 'rn2kab2/4a2r1/2c3n2/p1p1p2cp/6b2/5N3/P1P1P3P/2N1C4/C3A4/R1BA1KBR1 w - - 0 1', 'c2b4'),
        (20013, 74, '2b1k1b2/4a3n/9/p1n3pPp/4P4/Pr2N1P2/5c3/4B4/4A4/3CKAB2 w - - 0 1', 'e4f6'),
        (20014, 32, '2rakc3/3na4/b7b/p3p1p2/5R2p/P5C2/2P1P3P/Nc2B1N2/4A4/R2AK1B2 w - - 0 1', 'a2c1'),
        (20015, 34, 'rnbak4/4a4/4brnR1/p3p4/2p3P2/8p/P1PNP3P/C1N2C3/4A4/1RBAK1B2 w - - 0 1', 'd3f4'),
        (20016, 20, 'r1bak2r1/1c2a4/2n3n2/pCp1p1p1p/2b6/2P3C2/P3P1c1P/2N1B1N2/4A4/3RKAB1R w - - 0 1', 'g2f4'),
        (20017, 54, '4kab2/4a4/4br3/C3p4/2c6/2CnP1B1P/P1n5R/2N6/1r2A4/2BAKN3 w - - 0 1', 'c2b4'),
        (20018, 20, '1nRakabnr/1r7/4c4/p3p1pcp/9/8P/P2pP1PC1/4C1N2/9/1NBAKAB1R w - - 0 1', 'b0d1'),
        (20019, 38, '3nka3/4ar3/4c3b/4R1p1p/2p3b2/2P1P4/4N1P1P/1cN1B4/r3A4/3AK1B1R w - - 0 1', 'e3f1'),
        (20020, 38, '4kab1r/4a4/b3n1n2/p1P1N1pCp/7c1/P3P4/1r6P/1cC1B4/3NA4/R3KABR1 w - - 0 1', 'e6d8'),
        (20021, 42, '2b1ka3/4a4/c1n1b1n1r/p1Cr4p/4p4/P7P/4P1p2/3A2NC1/7R1/2B1KAB2 w - - 0 1', 'g2h4'),
        (20022, 72, 'R2aka1r1/9/3c5/8p/1Pb6/2B3R1P/3nr4/4NA3/4A4/4K4 w - - 0 1', 'e2g1'),
        (20023, 28, 'rn1akabr1/9/1C1cbcn2/2p1pRp1C/p8/2P6/P3P1P1P/2N1B1N2/9/R2AKAB2 w - - 0 1', 'g2f4'),
        (20024, 78, '3a2b2/4a4/5k3/2p3C1p/5Nn2/8P/6r2/B3B4/4A4/3AKn3 w - - 0 1', 'f5h6'),
        (20025, 28, 'r1b1ka3/3Ca1C2/n1ccb1n2/p1p1p2R1/6p2/9/P1P1P1P1P/2N1B1N2/4A4/R3KAB2 w - - 0 1', 'g2h4'),
        (20026, 70, '4kab2/4a4/9/9/4p4/2P1P4/8p/4r4/C2cN4/2BAKA3 w - - 0 1', 'e1f3'),
        (20027, 76, '3ak4/4a4/2R1b4/3Cp1C2/P1b6/8p/2NcP4/9/5p3/4KABr1 w - - 0 1', 'c3e4'),
        (20028, 48, '4kabr1/2n1a4/4b1R2/4R2cp/6P2/p1PN5/4P3P/C5N2/9/2BAKAB2 w - - 0 1', 'd4b3'),
        (20029, 22, 'r3kab1r/4a4/4b1n2/p1p3p1p/9/2P1Pn1c1/PR2N1P1P/4B1NC1/3cA4/4KAB1R w - - 0 1', 'e3f5'),
    ],
    'eye': [   # 下了 36 盘
        (21000, 26, '1Cbaka2r/r8/6nc1/p3p3p/6b2/2p5P/P1n1P2C1/4B1N2/Rc2A4/1NBAKR3 w - - 0 1', 'c0a2'),
        (21001, 70, '4k4/2r6/3Rn4/p5r1p/2b1p4/9/P2RP2cP/4B1N2/4N4/2BAKA3 w - - 0 1', 'e2c4'),
        (21002, 80, '2b1kab2/4a4/4r4/p6P1/9/P3p4/9/4B4/4A1rN1/4KAB2 w - - 0 1', 'g0i2'),
        (21003, 22, '2bakab1r/9/1cn3n2/rC2p2Rp/p1p3p2/P1P6/4P1PcP/2N1B1NCB/4A4/R2AK4 w - - 0 1', 'i2g4'),
        (21004, 34, '2bak2C1/4a4/n3b1n2/p1p1p1p1p/9/P1P1C4/4PrP1P/1RNcB1c1R/4A4/3K1AB2 w - - 0 1', 'e2g4'),
        (21005, 60, '2b1kab1r/4a4/6n2/p3p3p/9/4n4/P1p1N3P/6p2/1r1CA1cC1/1NBAK2R1 w - - 0 1', 'c0a2'),
        (21006, 74, '5k1C1/9/2n1ba1r1/p7p/4pRpP1/9/P1P1P4/9/3cK4/2B3r2 w - - 0 1', 'c0e2'),
        (21007, 100, '3ak1b2/4a4/7P1/5R3/1P4b2/6p2/9/B3B4/r2cAC3/3AK4 w - - 0 1', 'e2g0'),
        (21009, 30, 'r2akab2/9/c1n1b1n2/4p4/2p3p1C/5r3/PcP1P1P1P/BCN5N/4A4/R3KABR1 w - - 0 1', 'a2c4'),
        (21010, 36, 'r2ak1br1/4a4/1cn1b1n2/2PRp1C1p/9/1N2P3P/P5PcR/4B4/4AN3/2B1KA3 w - - 0 1', 'e2g0'),
        (21011, 24, 'r1b1kab2/4a4/3cn1n2/2p2C2p/p3p4/6P2/P1c1P3P/C1N1B4/4A2r1/3RKABNR w - - 0 1', 'g0i2'),
        (21012, 42, '2ba1kb2/3Ca2C1/2n6/p1p1p4/5n3/2P1c1B1r/P2rN4/6N2/4A2c1/R2A1KB2 w - - 0 1', 'g0i2'),
        (21014, 34, 'r3ka2r/4a4/3cb2cb/pC2p2Cp/2p4n1/P7P/4P2p1/4B1N2/3NA4/1R2KAB1R w - - 0 1', 'e2c0'),
        (21015, 28, '4kab1r/4a4/2n3n2/p1p1p4/6p2/P1P5p/1r2P1P1P/R1N1B1N2/4K2C1/3A1AB1R w - - 0 1', 'g0i2'),
        (21016, 36, '1r2kab2/4a4/2n1b4/p1p1p3p/2c4r1/P2n5/2P1PR2P/1CNCB2cB/4N4/R2AKA3 w - - 0 1', 'e2g4'),
        (21017, 54, '1n2kab2/4a4/4b2r1/4p4/r1p3pnp/2P5P/4P4/1cN1BA2B/4K2C1/5A2R w - - 0 1', 'i2g0'),
        (21018, 72, '3a1kbR1/4a1n2/4b4/p3C1P2/1P1c5/P8/3pP3P/4B1N2/3r5/4KAB2 w - - 0 1', 'e2c4'),
        (21019, 66, '4kab2/4a4/2n1b4/1c2p2P1/p1p1n4/9/P1P1PN2P/5C2B/3R5/2BAKA3 w - - 0 1', 'c0e2'),
        (21021, 44, '2b2kbr1/9/c5n2/2p6/p8/2P1r4/P3N1p2/4B4/3NA4/R3KAB2 w - - 0 1', 'e2c0'),
        (21022, 32, '2bakCb2/9/2n6/p1p1p1p1p/2P6/4P3P/P4rc1R/4B1r2/4A4/R3KAB2 w - - 0 1', 'e2g4'),
        (21023, 82, '4k4/3na4/4ba3/9/2p1p1b2/9/2P1P4/2N1B4/1R2Ar3/2B1KA3 w - - 0 1', 'c0a2'),
        (21024, 40, '3k1a1n1/3nac2r/b1r1b4/p1p3p2/9/4C3p/P1P1P4/9/3RA2R1/2BAK1BN1 w - - 0 1', 'g0i2'),
        (21025, 60, '2bak4/4r2c1/6n2/p1p3p1p/4N4/P3P1P1P/2n6/9/5N3/1rB1KAB1R w - - 0 1', 'g0e2'),
        (21027, 26, '3rkabr1/4a4/4n1c2/p1p1p1C2/1Rb4np/6P1P/P1P1P2c1/2C1B3R/3NK4/3A1ABN1 w - - 0 1', 'e2c0'),
        (21029, 24, '2b2ab1r/4k4/2n1canc1/2p1p1p1p/p2C5/9/P1P1P1P1P/2N1B1N2/1r2A4/RCBAKR3 w - - 0 1', 'c0a2'),
        (21031, 50, '4kab2/c3a4/2n1b1n2/4p1P2/3r5/p1B1P1PC1/1R2R4/1CN6/4A3N/2B1KA3 w - - 0 1', 'c4a2'),
        (21032, 34, '2b1k2r1/4a4/2nab2c1/2p1p1C2/7Rp/p8/4PNP2/1r2B4/4AN3/R1B1KA3 w - - 0 1', 'e2g4'),
        (21033, 100, '2ba1kn2/4ar3/4b4/5P3/p7p/9/P5N1P/4B4/4AN3/4KA3 w - - 0 1', 'e2g0'),
        (21034, 40, '2bk1a3/1Cn1a4/4b2cr/4nC2p/p1p3P2/9/P1P1Pp2P/3NB1N2/4A4/4KABR1 w - - 0 1', 'e2g4'),
        (21035, 64, '4kab2/4a4/2nrb4/4P4/9/1pP4p1/5n3/4B4/2N1A4/2B1KA2r w - - 0 1', 'e2g4'),
    ],
    'palace': [   # 下了 31 盘
        (22000, 56, '3ak4/3Ra4/2n1b4/p4R3/4p1b2/1rC1P1p1p/c1P6/B8/2N6/3AKABr1 w - - 0 1', ('f0g1', 'f0e1')),
        (22001, 98, '4kr3/R3a4/8N/9/9/1p2p4/9/C3BA3/9/4K1BCc w - - 0 1', ('f2e3', 'f2e1')),
        (22002, 30, 'r1bakab2/8r/2n3n2/p3p2Pp/1c7/2P3p1P/P3PN3/1C2C1N2/9/R1BAKAB1R w - - 0 1', ('f0g1', 'f0e1')),
        (22003, 92, '3RR4/5k3/b5n1b/p7p/1P7/6p2/P7P/9/3K5/2BA2B2 w - - 0 1', ('d0c1', 'd0e1')),
        (22004, 22, 'r1bakabc1/9/2n1r4/2p1p1p1p/p8/P1P5P/4PcP2/4C2R1/R8/1NBAKAB2 w - - 0 1', ('d0c1', 'd0e1')),
        (22005, 36, 'r1bak4/4a4/3c4b/pc1Cp1R1p/2pn2p2/P5P2/2P1P2NP/R1N1B4/1r4C2/2BAKA3 w - - 0 1', ('d0c1', 'd0e1')),
        (22006, 84, '2bakn3/1R2a4/4b4/8p/9/9/5p2P/3A2c2/9/rC2KA3 w - - 0 1', ('f0g1', 'f0e1')),
        (22008, 94, '3ak4/4cR3/3Rb2r1/9/9/1pP3P1P/4P4/2n1B4/1c7/2BAKA3 w - - 0 1', ('f0g1', 'f0e1')),
        (22009, 58, '2bakab2/6C2/9/pR2p4/c1PR5/5p2P/4P1n2/2NA2N2/9/2B1KABc1 w - - 0 1', ('d2c1', 'd2e1')),
        (22010, 96, '9/9/3aka3/6R2/4r1p1p/2B6/R3P3c/B4A3/5n3/3AK4 w - - 0 1', ('d0c1', 'd0e1')),
        (22011, 28, '1rbakr3/1C1can3/4b1c2/p3p1p2/2p5p/4P4/P1P3P1P/2N1B1nR1/4A4/1R1K1AB2 w - - 0 1', ('d0c0', 'd0d1')),
        (22012, 20, '1rbaka2r/9/2n1b1n2/p1p3C1p/4p4/4C4/c1P3P1P/Nc4N2/9/1RBAKABR1 w - - 0 1', ('f0g1', 'f0e1')),
        (22013, 94, '1r7/6R2/3aka3/2R1p4/3C5/4p4/5pp2/B2A1AN2/9/4K1B2 w - - 0 1', ('d2e3', 'd2e1')),
        (22014, 60, '1rb1k4/4a4/bCP6/4R4/6pnp/p3P4/5R3/5A3/3r2c2/2B1KA3 w - - 0 1', ('f2g3', 'f2e1')),
        (22015, 20, '1rbakab2/9/2n1c4/p1p1p1p1p/9/P8/2P1P1P1P/R1C1B4/8N/1cBAKA3 w - - 0 1', ('f0g1', 'f0e1')),
        (22016, 74, '2b6/3k5/nr1a2n1r/p3p4/2N3R2/6p1P/P3P4/2CABc3/9/2B1KA1N1 w - - 0 1', ('f0g1', 'f0e1')),
        (22017, 100, '4ka3/4a4/4b3b/9/p2n1nNr1/2B3P2/P8/4B4/9/3AKA3 w - - 0 1', ('d0c1', 'd0e1')),
        (22018, 50, '2bak1b2/1r2a2R1/c1C5n/4pP3/p7p/1N1R5/Pc2P4/6N2/3CA4/3K1AB2 w - - 0 1', ('d0c0', 'd0e0')),
        (22019, 24, '3akabr1/4n4/4b1n2/p1C1p1P1p/2P6/9/P1c1P2cP/1r3C2N/9/RNBAKAB1R w - - 0 1', ('d0c1', 'd0e1')),
        (22020, 20, '2bak3r/r3a4/2n1b1n2/p1p1p3p/6P2/5N1c1/P1c1P3P/1CNABC3/9/R2K1AB1R w - - 0 1', ('f0g1', 'f0e1')),
        (22021, 44, '1n1a1k2r/4a2R1/5r3/p1N1p4/8p/6p2/P3P1c1P/4B1N2/9/2BAKA3 w - - 0 1', ('f0g1', 'f0e1')),
        (22022, 34, '2b1kr3/4a4/r1nab1n2/pC2p1p1p/P2c3c1/2p3P2/4P3P/B1NAC4/8N/R2RKAB2 w - - 0 1', ('d2c3', 'd2e1')),
        (22023, 22, '1r1akr3/4a4/n3b1n1b/p1p1p1p1p/1c7/6P2/P1P1P2cP/2C1BAN2/9/RNBAKC2R w - - 0 1', ('d0c1', 'd0e1')),
        (22024, 26, 'r3ka2r/3n5/4b1n1b/pRp1pcp1p/9/2P6/P3P1P1P/2N2c3/3C4R/3AKABN1 w - - 0 1', ('d0c1', 'd0e1')),
        (22025, 62, '2b1ka3/4a2c1/7C1/2pr5/r5b1p/2P1p2NP/2R6/2NAB3R/2n6/1c1K1A3 w - - 0 1', ('d0c0', 'd0d1')),
        (22026, 66, '4kab1r/4a4/4b4/p3p3p/5P1P1/3r5/P8/3c2CcB/4A1n2/3K1A1NR w - - 0 1', ('d0c0', 'd0d1')),
        (22027, 82, '3k1a3/9/3Nban2/1P6p/9/1p2C3P/4P4/B2AB4/3KA4/9 w - - 0 1', ('d1c1', 'd1d0')),
        (22028, 80, '2ba1k3/2N1a4/5n3/6p2/8p/4P3P/2p2R3/2N1BA1r1/3c5/2B1KA3 w - - 0 1', ('f0g1', 'f0e1')),
        (22029, 74, '4ka1c1/2PRa4/4b1n2/9/4p3p/6B2/3CP4/p5N2/3NA2r1/3K1A3 w - - 0 1', ('d0c0', 'd0e0')),
        (22030, 76, '5ab2/7R1/C3kan2/2R6/P1N1P1b1p/2B3P2/9/6N2/9/3AKAB2 w - - 0 1', ('d0c1', 'd0e1')),
    ],
    'pawn': [   # 下了 32 盘
        (23000, 72, '2bak2n1/2r1a4/9/p5P1c/6r2/P2pp3P/4P4/R3B1N2/4A4/2BAK4 w - - 0 1', 'i4h4'),
        (23001, 92, '2ba4r/4k4/n4N3/p1p1p4/9/4P4/P1P2r1c1/R3C4/4K4/2BA5 w - - 0 1', 'e4f4'),
        (23002, 22, '3ak1b1r/1r2a4/2ncb1n2/p3p3p/2p3pc1/P6CP/2P1P1P2/2C1B1N2/R2NA4/4KAB1R w - - 0 1', 'a4b4'),
        (23003, 26, '3akabr1/3nr3n/4b2C1/p1p3p2/4C3p/P8/2P2cP1P/2N3N2/7R1/2BAKAB1R w - - 0 1', 'a4b4'),
        (23004, 92, '3ckab2/5R1r1/4b4/p3p4/1r3n3/2B2RP2/c3P4/4C4/4A4/4KA3 w - - 0 1', 'g4h4'),
        (23005, 74, '4kab2/4a4/4b4/p3c4/5n3/P1pr5/9/3CB1N2/4A4/3K1AB2 w - - 0 1', 'a4b4'),
        (23006, 96, '3ak1b2/4a4/4b1c2/9/4P4/1p4Pp1/5c3/8B/4K4/3A1A3 w - - 0 1', 'g4f4'),
        (23007, 80, '5ab2/2R6/3ak4/p2r5/9/P5P1p/2n1P4/3C2N2/4A4/4KAB2 w - - 0 1', 'a4b4'),
        (23008, 26, '1n2kab1C/4a2C1/r3bcn2/p1p1p1p1p/9/4P4/P1P3P1P/R1N1B1N2/4A4/4KA2R w - - 0 1', 'e4f4'),
        (23009, 36, '2b1kab1r/4a4/9/n1p1p3p/7c1/P1P1c4/4n1p1P/4B4/4A3R/3RKABC1 w - - 0 1', 'c4b4'),
        (23012, 60, '2c1k4/1c2a4/4b1n1r/2C1N4/8p/1pP3p2/P3P3P/2N1B4/4A3R/4KABC1 w - - 0 1', 'c4d4'),
        (23013, 36, '2baka1r1/2r6/2n6/2p1n3p/6b2/p3P4/1cP3p1P/1CN1B1N1c/3RA4/R1BAK4 w - - 0 1', 'e4d4'),
        (23014, 58, '2b1ka3/4a4/r3b1n2/p3p1p2/4P4/P2p2PR1/1c6r/2N1N4/R2KA4/2B2A3 w - - 0 1', 'g4f4'),
        (23015, 60, '1n1akr3/4a3R/b3b2P1/2R6/p5p2/2P1P1B2/P3N1P2/9/1c1KAN3/2B2A3 w - - 0 1', 'c4d4'),
        (23016, 20, 'rnbakabr1/9/4c1n2/p1p1p1p1p/5N3/2P6/P3P1PcP/3CB1C1R/5N3/1RBAKA3 w - - 0 1', 'c4d4'),
        (23017, 66, '4k4/4a4/2nab4/p3p3p/9/2P1Rn2P/P2r5/2c2AR2/4K4/1r3AB2 w - - 0 1', 'c4d4'),
        (23018, 48, '2b2a1r1/r2ka3n/2n1b4/4p1pCp/pc1c3P1/P3P1P2/3pN4/1C2BAN2/7R1/R1B1KA3 w - - 0 1', 'e4f4'),
        (23019, 28, '4kab2/4a4/2nrb1n2/p1p1p3p/6p2/1c1CP3C/P1c1N2rP/R3B3R/4A4/3NKAB2 w - - 0 1', 'e4f4'),
        (23020, 70, '2bak1bR1/4n2C1/5cr2/8p/p1P6/4P1P1P/1rP1N4/2N5B/4A4/2BAKR3 w - - 0 1', 'e4d4'),
        (23021, 26, 'rnbak3r/4a4/2c1b1n2/p3R4/6P2/P7p/2P1P2cP/2N1C1NCB/4A4/2BAK3R w - - 0 1', 'a4b4'),
        (23022, 42, '2bckabr1/4a4/2n3n2/p1C3p2/2p1P3p/P8/5rP1P/2N1KC3/3R1N3/3A1AR2 w - - 0 1', 'a4b4'),
        (23023, 42, 'r1bak4/4a4/2n1b1n1c/p1C5p/PCp3p2/4P3P/6P2/4B4/2NcAr3/R1BAK2R1 w - - 0 1', 'e4d4'),
        (23024, 100, '4kab1C/4aR3/9/2n1p4/9/P7P/4p1P2/9/9/2B1KA3 w - - 0 1', 'a4b4'),
        (23025, 78, '2b1k1b2/4a4/9/4r1p2/4C3p/n1P1p1B2/6P1P/r2RK1n2/4C4/9 w - - 0 1', 'c4d4'),
        (23026, 28, 'r2ak1b1r/3na4/4b1n2/p1p1p1C1p/6PP1/4P4/P1P1c2c1/2NC5/9/1RBAKABNR w - - 0 1', 'e4d4'),
        (23027, 54, '3k1ab1r/3C5/4b4/p8/5C2p/4P3P/P2n1p1cN/9/4A4/2B1KAB1R w - - 0 1', 'e4d4'),
        (23028, 94, '5a3/2R6/cC1k1a1R1/9/p4N2p/2P6/P3P3P/2N6/9/4K4 w - - 0 1', 'c4d4'),
        (23029, 74, '1Rb1k4/4a4/4c2C1/2r3p2/p7p/6P2/P7P/4B4/4A4/2BAK4 w - - 0 1', 'g4f4'),
        (23030, 24, '4kab1r/3na4/4b1n2/p1p1p1pC1/2c5p/3C2P2/P3P3P/N3B4/3rA4/R1B1KA1N1 w - - 0 1', 'g4h4'),
        (23031, 24, '2bakr3/4an3/r1n1b2c1/2p1p1p1p/p8/1NP1P4/P1C3P1P/4B4/1C2N4/R2AKAB1R w - - 0 1', 'e4d4'),
    ],
    'facing': [   # 下了 106 盘
        (24001, 38, '3ak1bnr/9/2n2ac2/5Cp1p/2p2Nb2/pcP6/P3P1P1P/6N2/4A4/1RBAK1BR1 w - - 0 1', 'e1f2'),
        (24004, 98, '3aka3/9/5n1cb/2R6/2bCp2P1/1p7/P2C5/B7B/4A4/1c2KA3 w - - 0 1', 'e1d2'),
        (24005, 64, '4ka3/4C4/b8/9/5nb2/2P1P4/5cn1P/p2A4B/6N2/3NKA2R w - - 0 1', 'e8i8'),
        (24006, 38, '2b1ka3/2R6/7C1/p1p1p1p1p/9/9/P2c2r1P/3R5/4A4/1NB1KAB2 w - - 0 1', 'e1d0'),
        (24008, 68, '1nc1k1bR1/1N7/r8/6p2/2p2P2p/9/p5N1P/3CB1n2/4A4/2B1KAC2 w - - 0 1', 'e2g4'),
        (24013, 100, '3R1a3/4k4/3R4n/4p2C1/2br5/3N4p/8P/6N2/4Ac3/2B1KAB2 w - - 0 1', 'e1f2'),
        (24021, 84, '2Rakabr1/9/9/4P1p2/p8/1n4P1p/P2n5/3N5/2R1A4/2B1KABrc w - - 0 1', 'e1d0'),
        (24022, 100, '2Raka3/9/9/9/9/P4N3/4p1r2/4B4/7c1/3AK4 w - - 0 1', 'e2c0'),
        (24025, 76, 'C3kab2/6C1r/4b4/2p2N3/p8/2P5p/P7P/2c6/4A2n1/1r1cK1B2 w - - 0 1', 'e1f2'),
        (24031, 86, '3akab2/2Nc5/1R7/8p/P5bR1/8P/9/4B4/4A4/2BAK4 w - - 0 1', 'e2c4'),
        (24032, 68, '5a3/8R/b2Nk4/3P1cR2/8p/P8/1p2P3P/4B1N2/5r3/3AK1B2 w - - 0 1', 'e2c4'),
        (24040, 98, 'n2ak1b2/2R6/3a4b/1PP2P1C1/3N2N2/8p/9/4B4/4A4/3AK1B2 w - - 0 1', 'e2g4'),
        (24041, 68, '3a1a3/3rkc3/b7r/2PC4p/p1bn1R3/2BN1pP2/P3P3P/3R4N/4A4/2B1K4 w - - 0 1', 'e1f0'),
        (24044, 20, 'rnba1abn1/4k4/6c1r/2p1C1p1p/p8/P1B5C/2P1P3P/6N2/3N5/R2AKAB1R w - - 0 1', 'e6d6'),
        (24047, 100, '4k1b2/4a4/3a5/p1N6/2b1P2P1/P8/9/4K4/8c/5r3 w - - 0 1', 'e5f5'),
        (24056, 100, '4ka3/1rcc5/b4a3/p5N1P/2b1C4/1NP6/P5n2/1R1Apr3/9/2B1K2R1 w - - 0 1', 'e5i5'),
        (24061, 70, '2bak4/9/3cban2/p4c2p/1R7/2B6/P1Pp2P1P/6n1N/4Ar3/4KABCR w - - 0 1', 'e1d0'),
        (24066, 96, '3rka3/4a4/8b/2R6/P7p/6BC1/2P4cP/8R/4A4/2B1K4 w - - 0 1', 'e1d2'),
        (24069, 56, '1r2kaR2/9/b1n2R3/p1p5p/9/4C4/P1P1P3P/3C5/9/2BAKAB2 w - - 0 1', 'e4c4'),
        (24074, 22, '2bakabn1/9/2n6/p1p3p1r/4C4/Pc6r/2P1c4/8B/8R/RNBAKA1N1 w - - 0 1', 'e5h5'),
        (24087, 92, '2ba1an2/1C7/3nk4/6p2/9/1pPR2Pp1/2r6/4B4/N3A4/3AK1B2 w - - 0 1', 'e1f0'),
        (24089, 50, '2b1kab2/9/2na2n2/6p1p/5c3/P1B1P1Pc1/1CP5P/9/4A4/R3KAB2 w - - 0 1', 'e1f2'),
        (24092, 60, 'C1Pakab2/9/b8/4p1p2/8p/3N5/P5P1c/2N1B4/1r3r3/2BAKA3 w - - 0 1', 'e2g4'),
        (24093, 46, '2b1kab1r/9/2n2a3/3C4p/r1pR5/2P2N1c1/p1c1P3P/2NAB2C1/9/4KAB1R w - - 0 1', 'e2g4'),
        (24094, 80, '2baka3/3C5/6R2/9/9/P8/6P2/4B4/4A4/2BCK3p w - - 0 1', 'e1f2'),
        (24098, 40, '1rba1ab2/4k4/2n6/pCp1p3p/2P3p2/8r/P2R2P2/B8/4A4/4K1BN1 w - - 0 1', 'e1f2'),
        (24099, 92, '1nb1k4/4a4/8R/9/p5P2/8P/P7c/r8/4A4/4KA3 w - - 0 1', 'e1d2'),
        (24102, 98, '4ka1R1/9/9/2p6/2b1C4/2P5P/P1r6/9/4c3C/3AKAB2 w - - 0 1', 'e5g5'),
        (24104, 100, '4k2C1/3R5/4b3b/9/P8/5nP1P/5p3/B1r1B4/9/4KA3 w - - 0 1', 'e2g0'),
        (24105, 20, 'r1b1kab1r/9/n3Can2/p1C1p3p/6p2/5c3/P1P3P1P/5AN1R/9/R1B1KABN1 w - - 0 1', 'e7b7'),
    ],
}


def _b2p_gen_type(t):
    """下自对弈，从 B2P_GAME0[t] 起逐盘找，凑满 B2P_N 组为止。要引擎。"""
    import make_positions as MP
    rows, idx = [], B2P_GAME0[t]
    with B.Engine(XQ) as eng:
        while len(rows) < B2P_N:
            cands = []
            for ply, fen in enumerate(MP.selfplay(XQ, idx, eng)):
                if ply % 2 or ply < 20 or ply > 100:
                    continue
                fen = B.reset_clock(B.norm(XQ, fen))
                board, stm = B.parse(XQ, fen)
                if stm != 'w' or B.status(XQ, fen) != 'ok' or legal_position(board) != fen:
                    continue
                cands += [(ply, fen, spec) for spec in b2p_cands(t, fen)]
            if cands:
                ply, fen, spec = random.Random(B.seed_of('B2P', t, idx)).choice(cands)
                rows.append((idx, ply, fen, spec))
            idx += 1
    return t, rows, idx - B2P_GAME0[t]


def gen_b2p(workers=5):
    """重新生成 B2P_BASE 并与脚本里的常量比对（五类并行，各用一个引擎进程）。"""
    from multiprocessing import Pool
    with Pool(min(workers, len(B2P_TYPES))) as pool:
        got = pool.map(_b2p_gen_type, B2P_TYPES)
    out = {}
    print('B2P_BASE = {')
    for t, rows, ngames in got:
        out[t] = rows
        print('    %r: [   # 下了 %d 盘' % (t, ngames))
        for row in rows:
            print('        (%d, %d, %r, %r),' % row)
        print('    ],')
    print('}')
    same = {t: out[t] == B2P_BASE.get(t) for t in B2P_TYPES}
    print('与脚本里的 B2P_BASE：%s' % same)
    return all(same.values())


_B2P = None


def b2p_plan():
    """-> {类型: [family]}，每类 B2P_N 组，按局序号排，组名 leg01…。"""
    global _B2P
    if _B2P is not None:
        return _B2P
    plan = {}
    for t in B2P_TYPES:
        rows = B2P_BASE[t]
        assert len(rows) == B2P_N, (t, len(rows))
        fams = []
        for i, (idx, ply, fen, spec) in enumerate(rows):
            f = b2p_family(t, fen, spec)
            assert f is not None, ('B2P 底局面造不出配对', t, idx)
            f.update(fid='%s%02d' % (t, i + 1), type=t, selfplay=idx, ply=ply, base=fen, spec=spec,
                     forms=FORMS_B2P if i < B2P_FEN_N else ('cells',))
            fams.append(f)
        plan[t] = fams
    _B2P = plan
    return plan


# ---------------------------------------------------------------- 出题
def jobkey(part, game, pid, form, mode, q, rep):
    return '|'.join([part, game, pid, form, mode, q, 'r%d' % rep])


def build():
    """-> OrderedDict: key -> {part, game, pos, form, mode, rep, state, questions, truth}。truth: 题名 -> 真值信息。"""
    jobs = collections.OrderedDict()

    def add(part, game, pid, form, mode, q, rep, st, qs, truth):
        k = jobkey(part, game, pid, form, mode, q, rep)
        assert k not in jobs, k
        jobs[k] = {'part': part, 'game': game, 'pos': pid, 'form': form, 'mode': mode, 'rep': rep,
                   'state': st, 'questions': qs, 'truth': truth}

    for game in (XQ, CH):
        # B0
        rows = list(B0[game])
        random.Random(B.seed_of('B0', game)).shuffle(rows)
        qs = collections.OrderedDict()
        truth = {}
        for i, (sid, t, text) in enumerate(rows):
            n = 'q%02d' % (i + 1)
            qs[n] = {'type': 'noul', 'instructions': text + '这个说法对吗？'}
            truth[n] = {'id': sid, 'truth': t}
        for rep in range(3):
            add('B0', game, '-', '-', 'multi', '-', rep, B0_STATE, qs, truth)

        ps = positions(game)
        plan2 = b2_plan(game)
        for idx, p in enumerate(ps):
            pid, fen = p['id'], p['fen']
            board, _ = B.parse(game, fen)
            # B1
            it1 = b1_items(game, p)
            q1 = collections.OrderedDict((n, b1_question(game, pid, s)) for n, s, _ in it1)
            t1 = {n: {'sq': s, 'truth': t} for n, s, t in it1}
            for form in FORMS_B1:
                add('B1', game, pid, form, 'multi', '-', 0, B.state(game, fen, form), q1, t1)
            # B2
            it2 = plan2[pid]
            q2 = collections.OrderedDict((n, b2_question(game, board, mv)) for n, mv, _, _ in it2)
            t2 = {n: {'move': mv, 'truth': ok, 'type': t, 'kind': board[mv[:2]].lower()} for n, mv, ok, t in it2}
            for form in FORMS_B23:
                add('B2', game, pid, form, 'multi', '-', 0, B.state(game, fen, form), q2, t2)
            # B3（第二版：state 轮到黑方走）
            it3 = b3_items(game, p)
            q3 = collections.OrderedDict((n, b3_question(game, board, s)) for n, s, _, _ in it3)
            t3 = b3_truth(game, fen, board, it3)
            f3 = b3_fen(game, fen)
            for form in FORMS_B23:
                add('B3', game, pid, form, 'multi', '-', 0, B.state(game, f3, form), q3, t3)
            # 抖动：同一请求体再发两次
            if idx < N_JIT:
                st = B.state(game, fen, 'fen')
                for rep in JIT_REPS:
                    add('B1', game, pid, 'fen', 'multi', '-', rep, st, q1, t1)
                    add('B2', game, pid, 'fen', 'multi', '-', rep, st, q2, t2)
                    add('B3', game, pid, 'fen', 'multi', '-', rep, B.state(game, f3, 'fen'), q3, t3)
            # 一题一请求
            if idx < N_SGL:
                st = B.state(game, fen, 'fen')
                for n in q1:
                    add('B1', game, pid, 'fen', 'single', n, 0, st, {n: q1[n]}, {n: t1[n]})
                for n in q2:
                    add('B2', game, pid, 'fen', 'single', n, 0, st, {n: q2[n]}, {n: t2[n]})
    # B2C 炮架配对（补测）：一局面一题一请求，同组四个局面的题目文字相同
    for f in b2c_plan():
        mv = f['move']
        for cls in B2C_CLASSES:
            fen = f['fens'][cls]
            board, _ = B.parse(XQ, fen)
            q = {'q01': b2_question(XQ, board, mv)}
            t = {'q01': {'move': mv, 'truth': cls == 'legal', 'type': cls, 'kind': 'c', 'fam': f['fid'],
                         'base': f['pid'], 'selfplay': f['selfplay'], 'screens': n_screens(board, mv)}}
            for form in FORMS_B2C:
                add('B2C', XQ, f['fid'], form, 'pair', cls, 0, B.state(XQ, fen, form), q, t)
    # B2P 规则落盘配对题（补测 2）：一局面一题一请求
    for t in B2P_TYPES:
        for f in b2p_plan()[t]:
            for cls in B2P_CLASSES[t]:
                fen, mv = f['fens'][cls], f['moves'][cls]
                board, _ = B.parse(XQ, fen)
                q = {'q01': b2_question(XQ, board, mv)}
                tr = {'q01': {'move': mv, 'truth': cls != 'viol', 'type': t, 'cls': cls, 'fam': f['fid'],
                              'selfplay': f['selfplay'], 'kind': board[mv[:2]].lower()}}
                for form in f['forms']:
                    add('B2P', XQ, f['fid'], form, 'pair', cls, 0, B.state(XQ, fen, form), q, tr)
    return jobs


def build_b3_v1():
    """第一版 B3 的请求（作废），键、题、真值与第二版相同，只有 state（红 / 白方走）和题目文字不同。"""
    jobs = collections.OrderedDict()
    for game in (XQ, CH):
        for idx, p in enumerate(positions(game)):
            pid, fen = p['id'], p['fen']
            board, _ = B.parse(game, fen)
            it3 = b3_items(game, p)
            q3 = collections.OrderedDict((n, b3_question_v1(game, board, s)) for n, s, _, _ in it3)
            t3 = b3_truth(game, fen, board, it3)
            runs = [(form, 0) for form in FORMS_B23] + ([('fen', r) for r in JIT_REPS] if idx < N_JIT else [])
            for form, rep in runs:
                jobs[jobkey('B3', game, pid, form, 'multi', '-', rep)] = {
                    'part': 'B3', 'game': game, 'pos': pid, 'form': form, 'mode': 'multi', 'rep': rep,
                    'state': B.state(game, fen, form), 'questions': q3, 'truth': t3}
    return jobs


def build_v1_batch(jobs):
    """原批次 846 个请求（B3 换回第一版，保持原来的顺序），用来核对指纹仍是 B_V1_FP。"""
    old = build_b3_v1()
    out = collections.OrderedDict()
    for k, j in jobs.items():
        if j['part'] in ('B2C', 'B2P'):
            continue
        out[k] = old[k] if j['part'] == 'B3' else j
    assert len(out) == 846
    return out


def fingerprint(jobs):
    import hashlib
    blob = json.dumps([[k, j['state'], j['questions'], j['truth']] for k, j in jobs.items()], ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(blob.encode()).hexdigest()[:16]


def base_mtimes():
    return [os.path.getmtime(os.path.join(HERE, f)) for f in ('boards.py', 'xiangqi_positions.json')]


def fresh_fingerprint():
    """新开进程重新出题算指纹（底座文件改过后，本进程里已 import 的 boards 不会更新）。"""
    import subprocess
    out = subprocess.run([sys.executable, os.path.abspath(__file__), 'fingerprint'], capture_output=True, text=True, cwd=HERE)
    return out.stdout.strip().splitlines()[-1] if out.stdout.strip() else 'ERR ' + out.stderr[-300:]


# ---------------------------------------------------------------- 自检
def selfcheck(jobs, verbose=False):
    n = 0

    def T(cond, msg):
        nonlocal n
        n += 1
        if not cond:
            raise AssertionError(msg)

    for game in (XQ, CH):
        rows = B0[game]
        T(len(rows) == 12 and sum(t for _, t, _ in rows) == 6, ('B0 真假各半', game))
        T(len({s for s, _, _ in rows}) == 12, 'B0 id 不重复')
        for p in positions(game):
            pid, fen = p['id'], p['fen']
            board, stm = B.parse(game, fen)
            T(stm == 'w' and not B.in_check(game, fen), ('红 / 白先走、未被将', pid))
            legal = set(B.legal(game, fen))
            # B1
            j = jobs[jobkey('B1', game, pid, 'cells', 'multi', '-', 0)]
            cells = j['state']['cells']
            tr = j['truth']
            T(len(tr) == 12, 'B1 12 题')
            occ = [v for v in tr.values() if v['truth'] != '空']
            T(len(occ) == 6, ('B1 6 有子', pid))
            T({B.is_red(board[v['sq']]) for v in occ} == {True, False} and
              sum(B.is_red(board[v['sq']]) for v in occ) == 3, ('B1 双方各 3', pid))
            T(len({v['sq'] for v in tr.values()}) == 12, 'B1 格子不重复')
            for name, v in tr.items():
                s = v['sq']
                want = B.label(game, board[s]) if s in board else '空'
                T(v['truth'] == want, ('B1 真值', pid, s))
                T(cells.get(s, '空') == want, ('B1 阳性对照：cells 里查得到', pid, s))
                crit = j['questions'][name]['criteria']
                T(want in crit and len(crit) == (15 if game == XQ else 13), ('B1 候选', pid, s))
                T(s in j['questions'][name]['instructions'], 'B1 题干含格名')
            for form in FORMS_B1:
                jf = jobs[jobkey('B1', game, pid, form, 'multi', '-', 0)]
                T(jf['questions'] == j['questions'], ('B1 各形态题目相同', pid, form))
                T(jf['state'] == B.state(game, fen, form), 'B1 state')
                T('legal' not in json.dumps(jf['state']) and 'moves' not in json.dumps(jf['state']), 'state 无着法清单')
            # B2
            j = jobs[jobkey('B2', game, pid, 'fen', 'multi', '-', 0)]
            tr = j['truth']
            T(len(tr) == 12 and sum(v['truth'] for v in tr.values()) == 6, ('B2 6 合法 6 违规', pid))
            descs = []
            for name, v in tr.items():
                mv = v['move']
                viol = B.violation(game, fen, mv)
                T((viol is None) == v['truth'] == (mv in legal), ('B2 合法性与 pyffish 一致', pid, mv, viol))
                if not v['truth']:
                    T(b2_subtype(game, fen, board, mv, viol) == v['type'], ('B2 违规类型', pid, mv))
                d = u0(game, board, mv)
                if v['truth']:
                    T(d == B.describe(game, fen, mv, 'U0'), ('B2 合法步描述与 describe(U0) 一致', pid, mv, d))
                T(not any(h in d for h in B.ZH_HINTS), ('B2 描述含规则提示', d))
                T(B.tags(d, 'zh') == set(), ('B2 描述带标记', d))
                T(j['questions'][name]['instructions'].endswith('着法：' + d), 'B2 题干')
                descs.append(d)
            T(len(set(descs)) == 12, ('B2 描述两两不同', pid))
            for form in FORMS_B23:
                T(jobs[jobkey('B2', game, pid, form, 'multi', '-', 0)]['questions'] == j['questions'], 'B2 各形态题目相同')
            # B3
            j = jobs[jobkey('B3', game, pid, 'fen', 'multi', '-', 0)]
            jcells = jobs[jobkey('B3', game, pid, 'cells', 'multi', '-', 0)]
            legal3 = B.legal(game, b3_fen(game, fen))
            tr = j['truth']
            T(len(tr) == 8 and len({v['sq'] for v in tr.values()}) == 8, ('B3 8 题', pid))
            ncap_all = sum(1 for s, q in board.items() if B.is_red(q) and q not in 'Kk' and B.capturable(game, fen, s))
            T(sum(v['truth'] for v in tr.values()) == min(4, ncap_all), ('B3 能被吃的取 min(4, 实有)', pid))
            for name, v in tr.items():
                s = v['sq']
                T(B.is_red(board[s]) and board[s] not in 'Kk', 'B3 是行棋方非帅子')
                T(B.capturable(game, fen, s) == v['truth'], ('B3 真值', pid, s))
                T((v['cat'] == 'cap') == v['truth'], 'B3 类别')
                if v['truth']:
                    T(len(v['att']) > 0, 'B3 能被吃就有吃它的子')
                if v['cat'] == 'near':
                    T(len(v['near']) > 0, 'B3 near 有挡住的子')
                if v['cat'] == 'far':
                    T(near_types(game, fen, s) == [], 'B3 far 没有够得着的子')
                qtext = j['questions'][name]['instructions']
                T(not any(h in qtext for h in B.ZH_HINTS), ('B3 题干含提示', qtext))
                # 第二版：题目直接问黑方现在能否吃；真值与「黑方走的局面里有吃这一格的合法着」一致
                T(qtext == '%s现在能否吃掉 %s 上的%s？' % (side_names(game)[1], s, B.label(game, board[s])), ('B3 题干', qtext))
                T(any(m[2:4] == s for m in legal3) == v['truth'], ('B3 真值与黑方走的局面复算一致', pid, s))
                T(jcells['state']['cells'][s] == B.label(game, board[s]), ('B3 题目里的子与 cells 一致', pid, s))
            # 第二版 state：同一盘面、轮到黑方走，局面合法（红方未被将 = 原局面行棋方未被将；黑方此刻也未被将）
            f3 = b3_fen(game, fen)
            T(B.parse(game, f3) == (board, 'b'), ('B3 局面只换行棋方', pid))
            T(not B.in_check(game, f3), ('B3 黑方此刻未被将（否则吃子要受应将限制）', pid))
            T(B.placement_issues(game, f3) == [] and len(legal3) > 0, ('B3 局面合法', pid))
            reps = [0] + (list(JIT_REPS) if pid in [x['id'] for x in positions(game)[:N_JIT]] else [])
            for form, rep in [(fm, 0) for fm in FORMS_B23] + [('fen', r) for r in reps[1:]]:
                jf = jobs[jobkey('B3', game, pid, form, 'multi', '-', rep)]
                T(jf['questions'] == j['questions'] and jf['truth'] == tr, 'B3 各形态 / 重复题目相同')
                T(jf['state'] == B.state(game, f3, form) and jf['state']['side_to_move'] == side_names(game)[1],
                  ('B3 state 轮到黑方走', pid, form, rep))
    # B2C 炮架配对
    fams = b2c_plan()
    T(len(fams) == B2C_N and len({f['selfplay'] for f in fams}) == B2C_N, 'B2C 组数、每盘自对弈至多一组')
    for f in fams:
        mv = f['move']
        fr, to, _ = B.split_move(mv)
        base_board, _ = B.parse(XQ, f['fens']['legal'])
        base_pos = [p for p in b2c_positions() + [p for p, _ in b2c_extra()] if p['id'] == f['pid']][0]
        T(f['fens']['legal'] == base_pos['fen'], ('B2C 合法那道就是局面集原局面', f['fid']))
        texts = set()
        for cls in B2C_CLASSES:
            fen = f['fens'][cls]
            board, stm = B.parse(XQ, fen)
            T(stm == 'w' and not B.in_check(XQ, fen) and not B.in_check(XQ, flipped(XQ, fen)), ('B2C 红先走、双方都未被将', f['fid'], cls))
            T(B.placement_issues(XQ, fen) == [] and not facing(board) and not pawn_stack(board),
              ('B2C 摆法合法、帅将不照面、未过河兵不同线', f['fid'], cls))
            T(B.norm(XQ, fen) == fen, 'B2C FEN 规范')
            T(board.get(fr) == 'C', ('B2C 起点是红炮', f['fid'], cls))
            T(n_screens(board, mv) == B2C_SCREENS[cls], ('B2C 炮架数', f['fid'], cls))
            T((to in board) == (cls != 'jump') and (cls == 'jump' or not B.is_red(board[to])), ('B2C 目标格', f['fid'], cls))
            T(B.violation(XQ, fen, mv) == B2C_VIOL[cls], ('B2C 违规类型', f['fid'], cls, B.violation(XQ, fen, mv)))
            T((mv in B.legal(XQ, fen)) == (cls == 'legal'), ('B2C 合法性与 pyffish 一致', f['fid'], cls))
            diff = {s for s in set(board) | set(base_board) if board.get(s) != base_board.get(s)}
            T(len(diff) == (0 if cls == 'legal' else 1), ('B2C 与原局面只差一个子', f['fid'], cls, diff))
            d = u0(XQ, board, mv)
            if cls == 'legal':
                T(d == B.describe(XQ, fen, mv, 'U0'), ('B2C 描述与 describe(U0) 一致', d))
            T(not any(h in d for h in B.ZH_HINTS) and B.tags(d, 'zh') == set(), ('B2C 描述含提示或标记', d))
            for form in FORMS_B2C:
                j = jobs[jobkey('B2C', XQ, f['fid'], form, 'pair', cls, 0)]
                T(j['state'] == B.state(XQ, fen, form), 'B2C state')
                T('legal' not in json.dumps(j['state']) and 'moves' not in json.dumps(j['state']), 'B2C state 无着法清单')
                texts.add(json.dumps(j['questions'], ensure_ascii=False))
                T(j['truth']['q01']['truth'] == (cls == 'legal') and j['truth']['q01']['type'] == cls, 'B2C 真值')
        T(len(texts) == 1, ('B2C 同组四道题文字相同', f['fid']))
    # B2P：先核对 legal_but_region 本身——在 B2 的中局局面上，合法着都判「合法」，自将、照面着都判「不合法」
    for p in positions(XQ):
        board, _ = B.parse(XQ, p['fen'])
        for mv, v in B.pseudo_moves(XQ, p['fen']).items():
            if v is None or v in ('self_check', 'facing'):
                T(legal_but_region(board, mv) == (v is None), ('legal_but_region 与 pyffish 不符', p['id'], mv, v))
    plan = b2p_plan()
    games = [f['selfplay'] for t in B2P_TYPES for f in plan[t]]
    T(len(games) == len(set(games)) == B2P_N * len(B2P_TYPES), 'B2P 每盘自对弈至多一组、五类不共用对局')
    for t in B2P_TYPES:
        fams = plan[t]
        T(len(fams) == B2P_N and sum('fen' in f['forms'] for f in fams) == B2P_FEN_N, ('B2P 组数', t))
        for f in fams:
            T(b2p_family(t, f['base'], f['spec']) is not None and f['base'] in f['fens'].values(), ('B2P 底局面', f['fid']))
            texts = {}
            for cls in B2P_CLASSES[t]:
                fen, mv = f['fens'][cls], f['moves'][cls]
                board, stm = B.parse(XQ, fen)
                fr, to = mv[:2], mv[2:4]
                # 局面合法：摆法到得了、未过河兵不同线、红先走、双方都未被将、帅将不照面
                T(legal_position(board) == fen and B.placement_issues(XQ, fen) == [], ('B2P 局面合法', f['fid'], cls))
                T(board.get(fr) is not None and board[fr] == f['piece'] and to not in board, ('B2P 同一个子、走到空格', f['fid'], cls))
                T((mv in B.legal(XQ, fen)) == (cls != 'viol'), ('B2P 合法性与 pyffish 一致', f['fid'], cls))
                T(B.violation(XQ, fen, mv) == (B2P_VIOL[t] if cls == 'viol' else None), ('B2P 违规类型', f['fid'], cls))
                d = u0(XQ, board, mv)
                if cls != 'viol':
                    T(d == B.describe(XQ, fen, mv, 'U0'), ('B2P 描述与 describe(U0) 一致', d))
                T(not any(h in d for h in B.ZH_HINTS) and B.tags(d, 'zh') == set(), ('B2P 描述含提示或标记', d))
                texts[cls] = d
                for form in f['forms']:
                    j = jobs[jobkey('B2P', XQ, f['fid'], form, 'pair', cls, 0)]
                    T(j['state'] == B.state(XQ, fen, form) and 'legal' not in json.dumps(j['state']), 'B2P state')
                    T(j['questions'] == {'q01': b2_question(XQ, board, mv)} and j['truth']['q01']['truth'] == (cls != 'viol'), 'B2P 题目与真值')
            # 违规题只犯这一条：修掉该条件后同一步合法
            vb, _ = B.parse(XQ, f['fens']['viol'])
            lb, _ = B.parse(XQ, f['fens']['legal'])
            diff = {s for s in set(vb) | set(lb) if vb.get(s) != lb.get(s)}
            if t in ('leg', 'eye', 'facing'):
                T(f['moves']['viol'] == f['moves']['legal'] and texts['viol'] == texts['legal'], ('B2P 同一步、题目文字相同', f['fid']))
                want = block_sq(t, f['moves']['viol']) if t != 'facing' else f['edit'][1]
                T(diff == {want}, ('B2P 两局面只差造成违规的那一格', f['fid'], diff))
                T((want in vb) == (t != 'facing'), ('B2P 马腿 / 象眼有子、照面那道少一个子', f['fid']))
                if t == 'facing':
                    T(king_file_between(vb) is not None and [s for s in king_file_between(vb) if s in vb] == [f['moves']['viol'][:2]],
                      ('B2P 照面：违规局面里帅将之间只剩走的那个子', f['fid']))
            else:
                T(diff == set() and f['moves']['viol'][:2] == f['moves']['legal'][:2], ('B2P 同一局面、同一个子', f['fid']))
                T(legal_but_region(vb, f['moves']['viol']), ('B2P 去掉区域规则就合法', f['fid']))
                if t == 'palace':
                    T(not B._in_palace(f['moves']['viol'][2:4], True) and B._in_palace(f['moves']['legal'][2:4], True), 'B2P 九宫')
                if t == 'pawn':
                    cb, _ = B.parse(XQ, f['fens']['crossed'])
                    fr, fwd = f['moves']['legal'][:2], f['moves']['legal'][2:4]
                    T(B.xy(fr)[1] == 4 and B.xy(fwd)[1] == 5 and f['moves']['crossed'][:2] == fwd, ('B2P 兵在河口、前进一步过河', f['fid']))
                    T({s for s in set(vb) | set(cb) if vb.get(s) != cb.get(s)} == {fr, fwd} and cb[fwd] == 'P', ('B2P 过河局面只挪了这个兵', f['fid']))
                    dx = B.xy(f['moves']['viol'][2:4])[0] - B.xy(fr)[0]
                    T(B.xy(f['moves']['crossed'][2:4]) == (B.xy(fwd)[0] + dx, 5), ('B2P 过河后往同一方向横走', f['fid']))
    # 原批次 846 个请求（B3 第一版）能逐字重建：指纹仍是 B_V1_FP
    T(fingerprint(build_v1_batch(jobs)) == B_V1_FP, '原批次指纹变了：B0–B2 或第一版 B3 的出题不再逐字相同')
    # 单题请求与多题请求的题目逐字相同
    for k, j in jobs.items():
        if j['mode'] == 'single':
            (qn,) = j['questions']
            mk = jobkey(j['part'], j['game'], j['pos'], 'fen', 'multi', '-', 0)
            T(jobs[mk]['questions'][qn] == j['questions'][qn] and jobs[mk]['state'] == j['state'], ('单题与多题一致', k))
    return n


def check():
    jobs = build()
    n = selfcheck(jobs)
    print('自检断言 %d 条全部通过' % n)
    cnt = collections.Counter((j['part'], j['mode'], j['rep'] > 0) for j in jobs.values())
    print('题目指纹 %s（底座改动后对比，变了就说明出的题变了）' % fingerprint(jobs))
    print('  其中 B0–B3 %s（B3 为第二版；换回第一版 B3 重建的原批次是 %s，与 %s %s），B2C %s，B2P %s' % (
        fingerprint({k: j for k, j in jobs.items() if j['part'] not in ('B2C', 'B2P')}),
        fingerprint(build_v1_batch(jobs)), B_V1_FP, '一致' if fingerprint(build_v1_batch(jobs)) == B_V1_FP else '不一致',
        fingerprint({k: j for k, j in jobs.items() if j['part'] == 'B2C'}),
        fingerprint({k: j for k, j in jobs.items() if j['part'] == 'B2P'})))
    print('请求数：%d' % len(jobs))
    for k in sorted(cnt):
        print('  %s %s %s %d' % (k[0], k[1], '重复' if k[2] else '', cnt[k]))
    chars = sum(len(json.dumps(j['state'], ensure_ascii=False)) + len(json.dumps(j['questions'], ensure_ascii=False))
                for j in jobs.values())
    print('state+questions 共 %d 字符（中文约一字一 token），按 $0.042/百万粗估 $%.3f' % (chars, chars * 0.042e-6))
    for game in (XQ, CH):
        plan = b2_plan(game)
        c = collections.Counter(t for rows in plan.values() for _, _, ok, t in rows if not ok)
        dup = sum(1 for rows in plan.values() for t, v in collections.Counter(t for _, _, ok, t in rows if not ok).items() if v > 1)
        print('%s B2 违规类型：%s；同局面同类型重复 %d 处' % (GNAME[game], dict(c), dup))
        lk = collections.Counter()
        for p in positions(game):
            board = B.parse(game, p['fen'])[0]
            for _, mv, ok, _ in plan[p['id']]:
                lk[(ok, board[mv[:2]].lower())] += 1
        print('  合法步子种：%s' % {k[1]: v for k, v in lk.items() if k[0]})
        print('  违规步子种：%s' % {k[1]: v for k, v in lk.items() if not k[0]})
        b3 = collections.Counter()
        for p in positions(game):
            for _, s, ok, c in b3_items(game, p):
                b3[c] += 1
        print('%s B3：能被吃 %d，差一点 %d，够不着 %d' % (GNAME[game], b3['cap'], b3['near'], b3['far']))
    fams = b2c_plan()
    print('B2C 炮架配对 %d 组（局面集 %d 组、补下的自对弈 %d 组），每组 4 个局面 × %d 种形态：' % (
        len(fams), sum(not f['extra'] for f in fams), sum(f['extra'] for f in fams), len(FORMS_B2C)))
    for f in fams:
        print('  %s %-16s %s 炮架 %s(%s) 目标 %s(%s) 加子 %s' % (f['fid'], f['pid'], f['move'], f['screen'], f['screen_piece'],
                                                         f['target'], f['target_piece'], '%s@%s' % (f['added'][1], f['added'][0])))
    plan = b2p_plan()
    print('B2P 配对题：每类 %d 组（fen 对照前 %d 组），请求 %d 次' % (B2P_N, B2P_FEN_N, sum(j['part'] == 'B2P' for j in jobs.values())))
    for t in B2P_TYPES:
        pieces = collections.Counter(f['piece'] for f in plan[t])
        print('  %s %s：局序号 %d–%d，子 %s' % (t, B2P_ZH[t], plan[t][0]['selfplay'], plan[t][-1]['selfplay'], dict(pieces)))
        for f in plan[t]:
            print('    %s 局 %d 半回合 %d  %s  %s' % (f['fid'], f['selfplay'], f['ply'],
                                             ' / '.join('%s %s' % (c, f['moves'][c]) for c in B2P_CLASSES[t]), f['edit'] or ''))
    return jobs


# ---------------------------------------------------------------- 日志与回包
def load():
    if os.path.exists(LOG):
        with open(LOG, encoding='utf-8') as f:
            return json.load(f)
    return {}


def save(log, path=LOG):
    tmp = path + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(log, f, ensure_ascii=False)
    os.replace(tmp, path)


def load_void():
    if os.path.exists(VOID):
        with open(VOID, encoding='utf-8') as f:
            return json.load(f)
    return {}


def void_b3():
    """把日志里第一版 B3 的条目（state 与题目和 build_b3_v1 逐字相同的）挪进作废日志；先写作废日志再改主日志，可重复执行。"""
    old = build_b3_v1()
    log, void = load(), load_void()
    moved = []
    for k, j in old.items():
        e = log.get(k)
        if e is not None and e['state'] == j['state'] and e['questions'] == j['questions']:
            assert k not in void or void[k] == e, ('作废日志里已有不同的条目', k)
            void[k] = e
            moved.append(k)
    if moved:
        save(void, VOID)
        for k in moved:
            del log[k]
        save(log)
    print('挪了 %d 条第一版 B3 进 %s；作废日志共 %d 条，主日志剩 %d 条' % (len(moved), VOID, len(void), len(log)))


def check_void(void, old):
    """作废日志与第一版出题一一对应、逐字相同，回包都成功、模型串对。"""
    assert set(void) == set(old), ('作废日志与第一版 B3 不一一对应', sorted(set(void) ^ set(old))[:3])
    for k, j in old.items():
        e = void[k]
        assert ok_entry(e) and e['state'] == j['state'] and e['questions'] == j['questions'], ('作废日志与第一版不一致', k)
        assert e['resp'].get('model') == MODEL


def ok_entry(e):
    return e is not None and '_error' not in e['resp']


def parse_resp(job, resp):
    """-> {题名: p（noul）或 {choice, p, conf}}；不符合断言就抛错。"""
    assert resp.get('model') == MODEL, ('模型串不对', resp.get('model'))
    ans = resp['answers']
    assert set(ans) == set(job['questions']), ('缺题或多题', sorted(ans))
    out = {}
    for n, q in job['questions'].items():
        a = ans[n]
        assert a['type'] == q['type'], (n, a['type'])
        if q['type'] == 'noul':
            v = float(a['noul'])
            assert 0 <= v <= 1
            out[n] = v
        else:
            p = {k: float(v) for k, v in a['probabilities'].items()}
            assert set(p) == set(q['criteria']) and a['choice'] in p, (n, 'choice 键')
            assert abs(sum(p.values()) - 1) <= 0.06, (n, '概率和', sum(p.values()))   # 两位小数显示，15 项舍入误差可累积
            out[n] = {'choice': a['choice'], 'p': p, 'conf': float(a['confidence'])}
    return out


def run(only=None, expect=None, workers=WORKERS):
    import jevkit as jev
    mt = base_mtimes()
    jobs = build()
    selfcheck(jobs)
    fp = fingerprint(jobs)
    print('题目指纹 %s' % fp)
    if expect and fp != expect:
        raise SystemExit('题目指纹 %s 与预期 %s 不同：底座或局面文件改了，停下' % (fp, expect))
    log = load()
    todo = []
    for k, j in jobs.items():
        if only and j['part'] not in only:
            continue
        e = log.get(k)
        if ok_entry(e):
            assert e['state'] == j['state'] and e['questions'] == j['questions'], '日志里的请求与当前出题不一致：%s' % k
            continue
        todo.append(k)
    print('需发起 %d 次请求（范围内已成功 %d 次）' % (len(todo), sum(1 for k, j in jobs.items()
                                                  if (not only or j['part'] in only) and ok_entry(log.get(k)))))
    CH_ = 60
    for i in range(0, len(todo), CH_):
        if base_mtimes() != mt:
            fp2 = fresh_fingerprint()
            if fp2 != fp:
                raise SystemExit('跑的过程中底座 / 局面文件改了，题目指纹 %s → %s，停下（已发的都在日志里）' % (fp, fp2))
            print('  底座文件改过，但题目指纹不变（%s），继续' % fp2)
            mt = base_mtimes()
        chunk = todo[i:i + CH_]
        res = jev.fan([(k, jobs[k]['state'], jobs[k]['questions']) for k in chunk], workers=workers)
        bad_model = []
        for k in chunk:
            d = res[k]
            j = jobs[k]
            log[k] = {'state': j['state'], 'questions': j['questions'], 'resp': d, 't': time.time()}
            if '_error' not in d and d.get('model') != MODEL:
                bad_model.append((k, d.get('model')))
        save(log)     # 先落盘再断言
        if bad_model:
            raise SystemExit('回包模型串不是 %s，立即停：%s' % (MODEL, bad_model[:3]))
        for k in chunk:
            if '_error' in res[k]:
                print('FAIL', k, res[k]['_error'])
            else:
                parse_resp(jobs[k], res[k])
        print('  %d/%d  %s' % (min(i + CH_, len(todo)), len(todo), jev.spend()))
    print(jev.spend())


# ---------------------------------------------------------------- 统计
def auc(pos, neg):
    """P(正例分 > 反例分) + 0.5 P(相等)，秩和法。任一侧为空返回 None。"""
    if not pos or not neg:
        return None
    allv = sorted([(v, 1) for v in pos] + [(v, 0) for v in neg])
    ranks, i = {}, 0
    rs = [0.0] * len(allv)
    while i < len(allv):
        j = i
        while j + 1 < len(allv) and allv[j + 1][0] == allv[i][0]:
            j += 1
        r = (i + j) / 2 + 1
        for k in range(i, j + 1):
            rs[k] = r
        i = j + 1
    rsum = sum(r for r, (v, lab) in zip(rs, allv) if lab == 1)
    n1, n0 = len(pos), len(neg)
    return (rsum - n1 * (n1 + 1) / 2) / (n1 * n0)


def pct(xs, lo=2.5, hi=97.5):
    xs = sorted(x for x in xs if x is not None)
    if not xs:
        return (None, None)
    def q(p):
        k = (len(xs) - 1) * p / 100
        f = math.floor(k)
        c = min(f + 1, len(xs) - 1)
        return xs[f] + (xs[c] - xs[f]) * (k - f)
    return (q(lo), q(hi))


def wilson(k, n, z=1.96):
    if n == 0:
        return (None, None)
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return (c - h, c + h)


def boot(groups, stat, n=BOOT, seed='boot'):
    """groups: {局面: [条目]}；stat(条目列表) -> 数。按局面有放回重抽。返回 (点估计, 下限, 上限)。"""
    keys = sorted(groups)
    rng = random.Random(B.seed_of(seed))
    est = stat([x for k in keys for x in groups[k]])
    vals = []
    for _ in range(n):
        items = []
        for _ in keys:
            items.extend(groups[keys[rng.randrange(len(keys))]])
        vals.append(stat(items))
    lo, hi = pct(vals)
    return est, lo, hi


def boot_paired(ga, gb, stat, n=BOOT, seed='bootp'):
    """同一批局面上两组条目之差（a − b），按局面配对重抽。"""
    keys = sorted(set(ga) & set(gb))
    rng = random.Random(B.seed_of(seed))
    est_a = stat([x for k in keys for x in ga[k]])
    est_b = stat([x for k in keys for x in gb[k]])
    vals = []
    for _ in range(n):
        ks = [keys[rng.randrange(len(keys))] for _ in keys]
        a = stat([x for k in ks for x in ga[k]])
        b = stat([x for k in ks for x in gb[k]])
        vals.append(None if a is None or b is None else a - b)
    lo, hi = pct(vals)
    return (None if est_a is None or est_b is None else est_a - est_b), lo, hi


def boot_indep(ga, gb, stat, n=BOOT, seed='booti'):
    """两批不同局面之差（a − b），各自独立重抽。"""
    ka, kb = sorted(ga), sorted(gb)
    rng = random.Random(B.seed_of(seed))
    est = stat([x for k in ka for x in ga[k]]) - stat([x for k in kb for x in gb[k]])
    vals = []
    for _ in range(n):
        a = stat([x for _ in ka for x in ga[ka[rng.randrange(len(ka))]]])
        b = stat([x for _ in kb for x in gb[kb[rng.randrange(len(kb))]]])
        vals.append(None if a is None or b is None else a - b)
    lo, hi = pct(vals)
    return est, lo, hi


# noul 条目：(p, 真值)
def s_auc(items):
    return auc([p for p, t in items if t], [p for p, t in items if not t])


def s_acc(items):
    return sum((p >= 0.5) == t for p, t in items) / len(items) if items else None


def s_bacc(items):
    pos = [p for p, t in items if t]
    neg = [p for p, t in items if not t]
    if not pos or not neg:
        return None
    return (sum(p >= 0.5 for p in pos) / len(pos) + sum(p < 0.5 for p in neg) / len(neg)) / 2


def s_tpr(items):
    pos = [p for p, t in items if t]
    return sum(p >= 0.5 for p in pos) / len(pos) if pos else None


def s_tnr(items):
    neg = [p for p, t in items if not t]
    return sum(p < 0.5 for p in neg) / len(neg) if neg else None


def s_meanp(items):
    return sum(p for p, _ in items) / len(items) if items else None


# choice 条目：dict(ok, pt, mult, rank)
def s_c(field):
    def f(items):
        return sum(x[field] for x in items) / len(items) if items else None
    return f


def choice_item(r, truth, n):
    p = r['p']
    pt = p[truth]
    higher = sum(1 for v in p.values() if v > pt)
    ties = sum(1 for v in p.values() if v == pt) - 1
    rank = higher + ties / 2          # 0 = 排第一；并列取平均名次
    return {'ok': r['choice'] == truth, 'pt': pt, 'mult': pt * n, 'rank': rank / (n - 1), 'choice': r['choice']}


def fmt(x, nd=2):
    return '—' if x is None else ('%.*f' % (nd, x))


def ci(t, nd=2):
    est, lo, hi = t
    return '%s [%s, %s]' % (fmt(est, nd), fmt(lo, nd), fmt(hi, nd))


# ---------------------------------------------------------------- 报告
def collect(jobs, log):
    """-> res[k] = 解析后的回包；缺条或失败直接报错。"""
    res = {}
    missing = [k for k in jobs if not ok_entry(log.get(k))]
    if missing:
        raise SystemExit('日志缺 %d 条（或失败），先跑 run。例：%s' % (len(missing), missing[:3]))
    extra = sorted(set(log) - set(jobs))
    if extra:
        raise SystemExit('日志里有 %d 条计划外条目（第一版 B3 要先 void-b3）。例：%s' % (len(extra), extra[:3]))
    for k, j in jobs.items():
        e = log[k]
        assert e['state'] == j['state'] and e['questions'] == j['questions'], '日志里的请求与当前出题不一致：%s' % k
        res[k] = parse_resp(j, e['resp'])
    return res


def noul_groups(jobs, res, part, game, form, mode='multi', rep=0, filt=None, pos_set=None):
    g = collections.defaultdict(list)
    for k, j in jobs.items():
        if (j['part'], j['game'], j['form'], j['mode'], j['rep']) != (part, game, form, mode, rep):
            continue
        if pos_set is not None and j['pos'] not in pos_set:
            continue
        for n, p in res[k].items():
            t = j['truth'][n]
            if filt is None or filt(t):
                g[j['pos']].append((p, t['truth']))
    return g


def choice_groups(jobs, res, game, form, mode='multi', rep=0, filt=None, pos_set=None):
    nopt = 15 if game == XQ else 13
    g = collections.defaultdict(list)
    for k, j in jobs.items():
        if (j['part'], j['game'], j['form'], j['mode'], j['rep']) != ('B1', game, form, mode, rep):
            continue
        if pos_set is not None and j['pos'] not in pos_set:
            continue
        for n, r in res[k].items():
            t = j['truth'][n]
            if filt is None or filt(t):
                x = choice_item(r, t['truth'], nopt)
                x['truth'] = t['truth']
                g[j['pos']].append(x)
    return g


def report_b2c(jobs, res, log, P):
    """B2C 炮架配对：各类判「违规」的比例；合法与各违规类之间的 AUC（按组重抽，同组的合法与违规一起抽，所以是配对区间）。"""
    fams = b2c_plan()
    ks = [k for k, j in jobs.items() if j['part'] == 'B2C']
    us = [log[k]['resp'].get('usage', {}) for k in ks]
    P('## B2C 炮架配对（补测：合法炮吃子 vs 三类违规，同组四个局面只差一个子、题目文字相同）\n')
    P('%d 组（局面集 %d 组、补下的自对弈 %d 组，每盘自对弈一组）× 4 类 × %d 种形态 = %d 次请求，一题一请求；输入 %d token，花费 $%.4f。'
      '区间：按组（= 按自对弈对局）bootstrap %d 次；比较合法与违规时同组一起抽，是配对区间。noul 以 p<0.5 判「违规」。\n' % (
          len(fams), sum(not f['extra'] for f in fams), sum(f['extra'] for f in fams), len(FORMS_B2C), len(ks),
          sum(u.get('input_tokens', 0) for u in us), sum(u.get('cost', 0) for u in us), BOOT))
    # p[form][fid][cls]
    p = {form: collections.defaultdict(dict) for form in FORMS_B2C}
    for k in ks:
        j = jobs[k]
        p[j['form']][j['pos']][j['truth']['q01']['type']] = res[k]['q01']
    fids = [f['fid'] for f in fams]

    def g1(form, cls):
        return {fid: [p[form][fid][cls]] for fid in fids}

    def frac_viol(items):
        return sum(x < 0.5 for x in items) / len(items)

    def meanv(items):
        return sum(items) / len(items)

    P('| 形态 | 类 | 题数 | 判「违规」 | 均 p（判合法的概率） |')
    P('|---|---|---:|---|---|')
    for form in FORMS_B2C:
        for cls in B2C_CLASSES:
            g = g1(form, cls)
            P('| %s | %s | %d | %s | %s |' % (form, B2C_ZH[cls], len(g), ci(boot(g, frac_viol, seed='c1' + form + cls)),
                                           ci(boot(g, meanv, seed='c2' + form + cls))))
    P('')
    P('合法 vs 违规（「组内排序对」= 同组里合法那道的 p 高于违规那道的比例，相等算一半；Δp = 同组 p(合法) − p(违规)）：\n')
    P('| 形态 | 对比 | AUC（全体题目） | 组内排序对 | 组内 Δp |')
    P('|---|---|---|---|---|')
    pairs = [(c, B2C_ZH[c]) for c in B2C_CLASSES[1:]] + [('all', '三类违规合并')]
    aucg = {}
    for form in FORMS_B2C:
        for cls, lab in pairs:
            viol = B2C_CLASSES[1:] if cls == 'all' else (cls,)
            ga = {fid: [(p[form][fid]['legal'], True)] + [(p[form][fid][c], False) for c in viol] for fid in fids}
            gd = {fid: [(p[form][fid]['legal'], p[form][fid][c]) for c in viol] for fid in fids}
            aucg[(form, cls)] = ga
            order = lambda items: sum(1.0 if a > b else 0.5 if a == b else 0.0 for a, b in items) / len(items)
            dp = lambda items: sum(a - b for a, b in items) / len(items)
            P('| %s | 合法 vs %s | %s | %s | %s |' % (form, lab, ci(boot(ga, s_auc, seed='c3' + form + cls)),
                                                    ci(boot(gd, order, seed='c4' + form + cls)),
                                                    ci(boot(gd, dp, seed='c5' + form + cls))))
    P('')
    P('格子表 − FEN（同一批组配对）：\n')
    P('| 指标 | 差 |')
    P('|---|---|')
    for cls in B2C_CLASSES:
        P('| %s 判「违规」 | %s |' % (B2C_ZH[cls], ci(boot_paired(g1('cells', cls), g1('fen', cls), frac_viol, seed='c6' + cls))))
    for cls, lab in pairs:
        P('| AUC 合法 vs %s | %s |' % (lab, ci(boot_paired(aucg[('cells', cls)], aucg[('fen', cls)], s_auc, seed='c7' + cls))))
    P('')
    P('逐组明细（格子表 / FEN 的 p；炮架与目标列的是原局面上的子，大写红方）：\n')
    P('| 组 | 底局面 | 着法 | 炮架 | 目标 | 加的子 | 合法 | 无架 | 两架 | 不吃越子 |')
    P('|---|---|---|---|---|---|---|---|---|---|')
    for f in fams:
        P('| %s | %s | %s | %s %s | %s %s | %s %s | %s |' % (
            f['fid'], f['pid'], f['move'], f['screen'], f['screen_piece'], f['target'], f['target_piece'],
            f['added'][0], f['added'][1],
            ' | '.join('%.2f / %.2f' % (p['cells'][f['fid']][c], p['fen'][f['fid']][c]) for c in B2C_CLASSES)))
    P('')


def report_b2p(jobs, res, log, P):
    """B2P 配对题：各类判「违规」的比例；合法对照 vs 违规题的 AUC、组内排序对、组内 Δp（按组重抽，同组一起抽 = 配对区间）。"""
    plan = b2p_plan()
    ks = [k for k, j in jobs.items() if j['part'] == 'B2P']
    us = [log[k]['resp'].get('usage', {}) for k in ks]
    P('## B2P 规则落盘配对题（补测 2：每组只差造成违规的那一个条件）\n')
    P('五类各 %d 组，每组来自一盘不同的自对弈（150 盘互不重复）；cells 全部组，fen 对照每类前 %d 组；一题一请求，共 %d 次，'
      '输入 %d token，花费 $%.4f。着法一律走到空格。区间：按组（= 按对局）bootstrap %d 次；比较合法与违规时同组一起抽，是配对区间。'
      'noul 以 p<0.5 判「违规」。逐类型归因以本节为准，B2 原批次的按类型表只作参考。\n' % (
          B2P_N, B2P_FEN_N, len(ks), sum(u.get('input_tokens', 0) for u in us), sum(u.get('cost', 0) for u in us), BOOT))
    p = {form: collections.defaultdict(dict) for form in FORMS_B2P}     # p[form][fid][cls]
    for k in ks:
        j = jobs[k]
        p[j['form']][j['pos']][j['truth']['q01']['cls']] = res[k]['q01']

    def frac_viol(items):
        return sum(x < 0.5 for x in items) / len(items)

    def meanv(items):
        return sum(items) / len(items)

    def order(items):
        return sum(1.0 if a > b else 0.5 if a == b else 0.0 for a, b in items) / len(items)

    def dp(items):
        return sum(a - b for a, b in items) / len(items)

    def fids(t, form):
        return [f['fid'] for f in plan[t] if form in f['forms']]

    def g1(t, form, cls, fs=None):
        return {fid: [p[form][fid][cls]] for fid in (fs or fids(t, form))}

    def pair_groups(t, form, pos, neg, fs=None):
        fs = fs or fids(t, form)
        ga = {fid: [(p[form][fid][pos], True), (p[form][fid][neg], False)] for fid in fs}
        gd = {fid: [(p[form][fid][pos], p[form][fid][neg])] for fid in fs}
        return ga, gd

    comps = {t: [('legal', 'viol')] + ([('crossed', 'viol')] if t == 'pawn' else []) for t in B2P_TYPES}
    P('### 总表：合法对照 vs 违规题\n')
    P('| 形态 | 类型 | 组数 | 违规题判「违规」 | 合法对照判「违规」 | 违规题均 p | 合法对照均 p | AUC（合法 vs 违规） | 组内排序对 | 组内 Δp（合法 − 违规） |')
    P('|---|---|---:|---|---|---|---|---|---|---|')
    for form in FORMS_B2P:
        for t in B2P_TYPES:
            for pos, neg in comps[t]:
                ga, gd = pair_groups(t, form, pos, neg)
                lab = B2P_ZH[t] + ('（对照：过河后横走）' if pos == 'crossed' else '')
                P('| %s | %s | %d | %s | %s | %s | %s | %s | %s | %s |' % (
                    form, lab, len(gd), ci(boot(g1(t, form, neg), frac_viol, seed='p1' + form + t + pos)),
                    ci(boot(g1(t, form, pos), frac_viol, seed='p2' + form + t + pos)),
                    ci(boot(g1(t, form, neg), meanv, seed='p3' + form + t + pos)),
                    ci(boot(g1(t, form, pos), meanv, seed='p4' + form + t + pos)),
                    ci(boot(ga, s_auc, seed='p5' + form + t + pos)), ci(boot(gd, order, seed='p6' + form + t + pos)),
                    ci(boot(gd, dp, seed='p7' + form + t + pos))))
    P('\n「组内排序对」= 同组里合法那道的 p 高于违规那道的比例，相等算一半，0.5 = 随机。AUC 用全体题目算（组间也比）。\n')
    P('### 格子表 − FEN（每类前 %d 组，同一批组配对）\n' % B2P_FEN_N)
    P('| 类型 | 违规题判「违规」差 | 合法对照判「违规」差 | AUC 差 | 组内 Δp 差 |')
    P('|---|---|---|---|---|')
    for t in B2P_TYPES:
        fs = fids(t, 'fen')
        for pos, neg in comps[t]:
            ga_c, gd_c = pair_groups(t, 'cells', pos, neg, fs)
            ga_f, gd_f = pair_groups(t, 'fen', pos, neg, fs)
            lab = B2P_ZH[t] + ('（对照：过河后横走）' if pos == 'crossed' else '')
            P('| %s | %s | %s | %s | %s |' % (
                lab, ci(boot_paired(g1(t, 'cells', neg, fs), g1(t, 'fen', neg, fs), frac_viol, seed='p8' + t + pos)),
                ci(boot_paired(g1(t, 'cells', pos, fs), g1(t, 'fen', pos, fs), frac_viol, seed='p9' + t + pos)),
                ci(boot_paired(ga_c, ga_f, s_auc, seed='pa' + t + pos)), ci(boot_paired(gd_c, gd_f, dp, seed='pb' + t + pos))))
    P('')
    P('### 按走的子细分（格子表）\n')
    for t in ('palace', 'facing'):
        byp = collections.defaultdict(list)
        for f in plan[t]:
            byp[f['piece']].append(f['fid'])
        P('- %s：%s' % (B2P_ZH[t], '；'.join('%s %d 组，违规题判「违规」%d，组内 Δp 均值 %+.3f' % (
            B.piece_name(XQ, pc), len(fs), sum(p['cells'][fid]['viol'] < 0.5 for fid in fs),
            sum(p['cells'][fid]['legal'] - p['cells'][fid]['viol'] for fid in fs) / len(fs)) for pc, fs in sorted(byp.items()))))
    P('')
    P('### 逐组明细（p = 判「合法」的概率，格子表 / FEN；FEN 只有前 %d 组；改动列是对原局面拿掉 / 挪动的子，大写红方）\n' % B2P_FEN_N)
    for t in B2P_TYPES:
        cl = B2P_CLASSES[t]
        P('#### %s\n' % B2P_ZH[t])
        P('| 组 | 自对弈 | 半回合 | 着法（%s） | 改动 | %s |' % (' / '.join(cl), ' | '.join(B2P_CLS_ZH[t][c] for c in cl)))
        P('|---|---|---|---|---|%s' % ('---|' * len(cl)))
        for f in plan[t]:
            edit = '%s %s %s' % (f['edit'][0], f['edit'][1], f['edit'][2]) if f['edit'] else '—'
            P('| %s | %d | %d | %s | %s | %s |' % (
                f['fid'], f['selfplay'], f['ply'], ' / '.join(f['moves'][c] for c in cl), edit,
                ' | '.join('%.2f / %s' % (p['cells'][f['fid']][c], '%.2f' % p['fen'][f['fid']][c] if 'fen' in f['forms'] else '—')
                           for c in cl)))
        P('')


def b3_subcases(jobs, res, game, form):
    """B3 里同一种子的「能吃 vs 差一点」：-> [(名称, 条目分组)]。"""
    cases = {
        XQ: [('炮能吃 vs 炮架不对（无架 / 两架）', lambda t: t['truth'] and 'c' in t['att'],
              lambda t: t['cat'] == 'near' and bool({'screen0', 'screen2'} & set(t['near']))),
             ('车能吃 vs 被隔住（越子）', lambda t: t['truth'] and 'r' in t['att'],
              lambda t: t['cat'] == 'near' and 'jump' in t['near'])],
        CH: [('后/车/象能吃 vs 被隔住（越子）', lambda t: t['truth'] and bool({'q', 'r', 'b'} & set(t['att'])),
              lambda t: t['cat'] == 'near' and 'jump' in t['near'])],
    }[game]
    out = []
    for name, fp, fn in cases:
        g = noul_groups(jobs, res, 'B3', game, form, filt=lambda t, fp=fp, fn=fn: fp(t) or fn(t))
        out.append((name, {k: [(p, t) for p, t in v] for k, v in g.items()}))
    return out


def report_b3v1(jobs, res, P):
    """第一版 B3（作废，行棋方矛盾）与第二版逐题对比。同一批局面、同一批题、同一真值，按局面配对重抽。"""
    old = build_b3_v1()
    void = load_void()
    check_void(void, old)
    rold = {k: parse_resp(old[k], void[k]['resp']) for k in old}
    us = [void[k]['resp'].get('usage', {}) for k in old]
    P('## B3 更正：第一版（作废）与第二版对比\n')
    P('第一版的 state 写红 / 白方走，题目却问「假设现在轮到黑方走：黑方下一步能否吃掉……」，同一请求里行棋方前后矛盾，已作废：'
      '%d 条挪进作废日志 %s（输入 %d token，花费 $%.4f），不进上面的 B3 表。第二版只改两处：state 的行棋方改成黑方（FEN 第二段 b），'
      '题目直接问「黑方现在能否吃掉 e5 上的红马？」；局面、题、真值、形态、抖动与第一版相同。差 = 第二版 − 第一版，按局面配对重抽。\n' % (
          len(old), os.path.basename(VOID), sum(u.get('input_tokens', 0) for u in us), sum(u.get('cost', 0) for u in us)))
    P('| 棋种 | 形态 | 第一版 AUC | 第二版 AUC | AUC 差 | 第一版平衡准确率 | 第二版平衡准确率 | 平衡准确率差 | 正例判是 一 → 二 | 反例判否 一 → 二 |')
    P('|---|---|---|---|---|---|---|---|---|---|')
    g_old, g_new = {}, {}
    for game in (XQ, CH):
        for form in FORMS_B23:
            go = noul_groups(old, rold, 'B3', game, form)
            gn = noul_groups(jobs, res, 'B3', game, form)
            g_old[(game, form)], g_new[(game, form)] = go, gn
            io = [x for v in go.values() for x in v]
            inn = [x for v in gn.values() for x in v]
            P('| %s | %s | %s | %s | %s | %s | %s | %s | %.2f → %.2f | %.2f → %.2f |' % (
                GNAME[game], form, ci(boot(go, s_auc, seed='v1')), ci(boot(gn, s_auc, seed='v1')),
                ci(boot_paired(gn, go, s_auc, seed='v2')), ci(boot(go, s_bacc, seed='v3')), ci(boot(gn, s_bacc, seed='v3')),
                ci(boot_paired(gn, go, s_bacc, seed='v4')), s_tpr(io), s_tpr(inn), s_tnr(io), s_tnr(inn)))
    P('\n对比项（第一版 → 第二版）：\n')
    P('| 对比 | 第一版 | 第二版 |')
    P('|---|---|---|')
    for form in FORMS_B23:
        P('| 中国象棋 − 国际象棋 AUC，%s（独立重抽） | %s | %s |' % (
            form, ci(boot_indep(g_old[(XQ, form)], g_old[(CH, form)], s_auc)), ci(boot_indep(g_new[(XQ, form)], g_new[(CH, form)], s_auc))))
    for game in (XQ, CH):
        P('| %s cells − fen AUC（配对） | %s | %s |' % (
            GNAME[game], ci(boot_paired(g_old[(game, 'cells')], g_old[(game, 'fen')], s_auc)),
            ci(boot_paired(g_new[(game, 'cells')], g_new[(game, 'fen')], s_auc))))
    for game in (XQ, CH):
        for form in FORMS_B23:
            so, sn = b3_subcases(old, rold, game, form), b3_subcases(jobs, res, game, form)
            for (name, go), (_, gn) in zip(so, sn):
                npos = sum(t for v in gn.values() for _, t in v)
                nneg = sum(1 for v in gn.values() for _, t in v if not t)
                P('| %s %s %s（%d / %d） | %s | %s |' % (GNAME[game], form, name, npos, nneg, ci(boot(go, s_auc)), ci(boot(gn, s_auc))))
        for form in FORMS_B23:
            for cat, lab, fn in (('cap', '能被吃 判是', s_tpr), ('near', '差一点 判否', s_tnr), ('far', '够不着 判否', s_tnr)):
                go = noul_groups(old, rold, 'B3', game, form, filt=lambda x, cat=cat: x['cat'] == cat)
                gn = noul_groups(jobs, res, 'B3', game, form, filt=lambda x, cat=cat: x['cat'] == cat)
                P('| %s %s %s | %s | %s |' % (GNAME[game], form, lab, ci(boot(go, fn)), ci(boot(gn, fn))))
    P('\n逐题差与抖动（|Δp| 是同一道题两次回包的差；抖动 = 同一版本同一请求体重发，前 %d 个局面 fen）：\n' % N_JIT)
    P('| 棋种 | 形态 | 题数 | |二 − 一| 均值 | 最大 | 跨 0.5 翻转 | 二 − 一 均值（带符号，正例 / 反例） | 第一版抖动 |Δp| 均值 | 第二版抖动 |Δp| 均值 |')
    P('|---|---|---:|---|---|---|---|---|---|')
    jit_pos = {g: [p['id'] for p in positions(g)[:N_JIT]] for g in (XQ, CH)}
    for game in (XQ, CH):
        for form in FORMS_B23:
            ds, flips, sp, sn = [], 0, [], []
            for k, j in jobs.items():
                if (j['part'], j['game'], j['form'], j['rep']) != ('B3', game, form, 0):
                    continue
                for n, v in res[k].items():
                    o = rold[k][n]
                    ds.append(abs(v - o))
                    flips += (v >= 0.5) != (o >= 0.5)
                    (sp if j['truth'][n]['truth'] else sn).append(v - o)

            def jit(jb, rb):
                d = []
                for pid in jit_pos[game]:
                    kk = [jobkey('B3', game, pid, 'fen', 'multi', '-', r) for r in (0,) + JIT_REPS]
                    for n in jb[kk[0]]['truth']:
                        vals = [rb[x][n] for x in kk]
                        d += [abs(vals[a] - vals[b]) for a in range(3) for b in range(a + 1, 3)]
                return sum(d) / len(d)
            P('| %s | %s | %d | %.3f | %.2f | %d | %+.3f / %+.3f | %s | %s |' % (
                GNAME[game], form, len(ds), sum(ds) / len(ds), max(ds), flips, sum(sp) / len(sp), sum(sn) / len(sn),
                '%.3f' % jit(old, rold) if form == 'fen' else '—', '%.3f' % jit(jobs, res) if form == 'fen' else '—'))
    P('')


def report(only=None):
    jobs = build()
    selfcheck(jobs)
    log = load()
    res = collect(jobs, log)
    if only:
        unknown = only - {'B2C', 'B2P', 'B3v1'}
        assert not unknown, ('--only 只支持 B2C、B2P、B3v1', unknown)
        out = []
        if 'B2C' in only:
            report_b2c(jobs, res, log, out.append)
        if 'B2P' in only:
            report_b2p(jobs, res, log, out.append)
        if 'B3v1' in only:
            report_b3v1(jobs, res, out.append)
        text = '\n'.join(out)
        print(text)
        return text
    out = []
    P = out.append
    P('# 实验 B 数字表（exp_xiangqi_board.py report 生成）\n')
    kb = [k for k, j in jobs.items() if j['part'] not in ('B2C', 'B2P')]   # B0–B3（B3 为第二版）；补测在各自那节单独统计
    ms = {log[k]['resp'].get('model') for k in jobs}
    us = [log[k]['resp'].get('usage', {}) for k in kb]
    el = sorted(log[k]['resp'].get('_elapsed', 0) for k in kb)
    P('请求 %d 次；模型串 %s；输入 %d token；花费 $%.4f；单次耗时中位 %.2f 秒（%.2f–%.2f）\n' % (
        len(kb), sorted(ms), sum(u.get('input_tokens', 0) for u in us), sum(u.get('cost', 0) for u in us),
        el[len(el) // 2], el[0], el[-1]))
    P('区间：按局面聚类 bootstrap %d 次，95%% 百分位区间。noul 以 p≥0.5 判「是」。\n' % BOOT)

    # ---- B0
    P('## B0 纯规则（不给棋盘，3 次同一请求体）\n')
    for game in (XQ, CH):
        ks = [jobkey('B0', game, '-', '-', 'multi', '-', r) for r in range(3)]
        tr = jobs[ks[0]]['truth']
        P('### %s\n' % GNAME[game])
        P('| 陈述 | 真值 | p（3 次） | 均值 | 判对 |')
        P('|---|---|---|---:|---|')
        rows, spread = [], []
        for n in sorted(tr, key=lambda n: tr[n]['id']):
            ps = [res[k][n] for k in ks]
            m = sum(ps) / 3
            ok = (m >= 0.5) == tr[n]['truth']
            rows.append((m, tr[n]['truth']))
            spread.append(max(ps) - min(ps))
            text = dict((s, x) for s, _, x in B0[game])[tr[n]['id']]
            P('| %s %s | %s | %s | %.2f | %s |' % (tr[n]['id'], text.replace(GNAME[game] + '里，', ''),
                                              '真' if tr[n]['truth'] else '假', ' / '.join('%.2f' % x for x in ps), m, '✓' if ok else '✗'))
        k_ok = sum((m >= 0.5) == t for m, t in rows)
        lo, hi = wilson(k_ok, 12)
        P('\n判对 %d/12（Wilson %.2f–%.2f）；AUC %.2f；3 次之间最大极差 %.2f，中位 %.2f；逐次判对 %s\n' % (
            k_ok, lo, hi, s_auc(rows), max(spread), sorted(spread)[6],
            ' / '.join(str(sum((res[k][n] >= 0.5) == tr[n]['truth'] for n in tr)) for k in ks)))

    # ---- B1
    P('## B1 识子（choice，12 格/局面，30 局面）\n')
    P('| 棋种 | 形态 | 准确率 | 有子格 | 空格 | p(正解) | p(正解)×候选数 | 正解归一化名次 |')
    P('|---|---|---|---|---|---|---|---|')
    b1g = {}
    for game in (XQ, CH):
        for form in FORMS_B1:
            g = choice_groups(jobs, res, game, form)
            b1g[(game, form)] = g
            go = choice_groups(jobs, res, game, form, filt=lambda t: t['truth'] != '空')
            ge = choice_groups(jobs, res, game, form, filt=lambda t: t['truth'] == '空')
            P('| %s | %s | %s | %s | %s | %s | %s | %s |' % (
                GNAME[game], form, ci(boot(g, s_c('ok'))), ci(boot(go, s_c('ok'))), ci(boot(ge, s_c('ok'))),
                ci(boot(g, s_c('pt'))), ci(boot(g, s_c('mult')), 1), ci(boot(g, s_c('rank')))))
    P('\n候选数：中国象棋 15、国际象棋 13；均匀猜的 p(正解)×候选数 = 1，归一化名次 = 0.5。\n')
    P('### B1 错在哪（有子格）\n')
    P('| 棋种 | 形态 | 有子格数 | 答成空 | 子种对、颜色错 | 颜色对、子种错 | 都错 |  空格答成有子 |')
    P('|---|---|---:|---:|---:|---:|---:|---:|')
    for game in (XQ, CH):
        for form in FORMS_B1:
            c = collections.Counter()
            items = [x for v in b1g[(game, form)].values() for x in v]
            for x in items:
                t, ch = x['truth'], x['choice']
                if t == '空':
                    c['e_total'] += 1
                    c['e_wrong'] += ch != '空'
                    continue
                c['total'] += 1
                if ch == t:
                    continue
                if ch == '空':
                    c['empty'] += 1
                elif ch[1:] == t[1:] or piece_same(game, ch, t):
                    c['color'] += 1
                elif ch[0] == t[0]:
                    c['kind'] += 1
                else:
                    c['both'] += 1
            P('| %s | %s | %d | %d | %d | %d | %d | %d/%d |' % (GNAME[game], form, c['total'], c['empty'], c['color'], c['kind'],
                                                        c['both'], c['e_wrong'], c['e_total']))
    P('\n### B1 形态之间的配对差（准确率，a − b）\n')
    P('| 棋种 | 对比 | 差 |')
    P('|---|---|---|')
    for game in (XQ, CH):
        for a, b in (('cells', 'fen'), ('pieces', 'fen'), ('board', 'fen'), ('cells', 'pieces'), ('cells', 'board')):
            P('| %s | %s − %s | %s |' % (GNAME[game], a, b, ci(boot_paired(b1g[(game, a)], b1g[(game, b)], s_c('ok')))))
    P('\n### B1 两棋种之差（中国象棋 − 国际象棋，不同局面独立重抽）\n')
    P('| 形态 | 准确率差 | p(正解)差 |')
    P('|---|---|---|')
    for form in FORMS_B1:
        P('| %s | %s | %s |' % (form, ci(boot_indep(b1g[(XQ, form)], b1g[(CH, form)], s_c('ok'))),
                               ci(boot_indep(b1g[(XQ, form)], b1g[(CH, form)], s_c('pt')))))
    P('\n### B1 按子种（有子格；对/总）\n')
    for game in (XQ, CH):
        rows = []
        for form in FORMS_B1:
            c = collections.defaultdict(lambda: [0, 0])
            for v in b1g[(game, form)].values():
                for x in v:
                    if x['truth'] != '空':
                        c[x['truth']][0] += x['ok']
                        c[x['truth']][1] += 1
            rows.append((form, c))
        labs = sorted(set(l for _, c in rows for l in c), key=lambda l: list(b1_labels(game)).index(l))
        P('| %s | %s |' % (GNAME[game], ' | '.join(labs)))
        P('|---|%s' % ('---|' * len(labs)))
        for form, c in rows:
            P('| %s | %s |' % (form, ' | '.join('%d/%d' % tuple(c[l]) for l in labs)))
        P('')

    # ---- B2 / B3
    for part, title in (('B2', 'B2 规则落盘（noul「这一步是否符合规则」，正例 = 合法）'),
                        ('B3', 'B3 受攻判断（第二版：state 轮到黑方走，noul「黑方现在能否吃掉」，正例 = 能被吃；第一版作废，见末节）')):
        P('## %s\n' % title)
        P('| 棋种 | 形态 | 题数（正/反） | AUC | 准确率@0.5 | 平衡准确率 | 正例判是 | 反例判否 | 正例均 p | 反例均 p |')
        P('|---|---|---|---|---|---|---|---|---|---|')
        gg = {}
        for game in (XQ, CH):
            for form in FORMS_B23:
                g = noul_groups(jobs, res, part, game, form)
                gg[(game, form)] = g
                items = [x for v in g.values() for x in v]
                npos = sum(t for _, t in items)
                P('| %s | %s | %d（%d/%d） | %s | %s | %s | %s | %s | %s | %s |' % (
                    GNAME[game], form, len(items), npos, len(items) - npos, ci(boot(g, s_auc)), ci(boot(g, s_acc)),
                    ci(boot(g, s_bacc)), ci(boot(g, s_tpr)), ci(boot(g, s_tnr)),
                    fmt(s_meanp([x for x in items if x[1]])), fmt(s_meanp([x for x in items if not x[1]]))))
        P('\n配对差（cells − fen，同一批局面）：')
        for game in (XQ, CH):
            P('- %s：AUC %s；准确率 %s' % (GNAME[game], ci(boot_paired(gg[(game, 'cells')], gg[(game, 'fen')], s_auc)),
                                     ci(boot_paired(gg[(game, 'cells')], gg[(game, 'fen')], s_acc))))
        P('\n两棋种之差（中国象棋 − 国际象棋，独立重抽）：')
        for form in FORMS_B23:
            P('- %s：AUC %s；平衡准确率 %s' % (form, ci(boot_indep(gg[(XQ, form)], gg[(CH, form)], s_auc)),
                                       ci(boot_indep(gg[(XQ, form)], gg[(CH, form)], s_bacc))))
        P('')
        if part == 'B2':
            P('### B2 按违规类型（违规步判「否」的比例、均 p；AUC = 该类违规步 vs 同棋种同形态全部合法步）\n')
            for game in (XQ, CH):
                P('#### %s\n' % GNAME[game])
                P('| 类型 | 看别的子? | 步数 | fen 判否 | fen 均 p | fen AUC | cells 判否 | cells 均 p | cells AUC |')
                P('|---|---|---:|---|---|---|---|---|---|')
                for t in B2_TYPES[game] + [None]:
                    cells_ = []
                    nstep = 0
                    for form in FORMS_B23:
                        if t is None:
                            g = noul_groups(jobs, res, 'B2', game, form, filt=lambda x: x['truth'])
                            items = [x for v in g.values() for x in v]
                            nstep = len(items)
                            cells_ += ['%s（判是）' % ci(boot(g, s_tpr)), fmt(s_meanp(items)), '—']
                            continue
                        g = noul_groups(jobs, res, 'B2', game, form, filt=lambda x, t=t: x['truth'] or x['type'] == t)
                        gi = {k: [x for x in v if not x[1]] for k, v in g.items()}
                        items = [x for v in gi.values() for x in v]
                        nstep = len(items)
                        if not items:
                            cells_ += ['—', '—', '—']
                            continue
                        cells_ += [ci(boot(gi, s_tnr)), fmt(s_meanp(items)), ci(boot(g, s_auc))]
                    if t is not None and nstep == 0:
                        continue
                    name = '合法步' if t is None else '%s %s' % (t, TYPE_ZH[t])
                    loc = '' if t is None else ('否' if t in LOCAL else '是')
                    P('| %s | %s | %d | %s |' % (name, loc, nstep, ' | '.join(cells_)))
                P('')
                # 两组类型合并
                P('合并：')
                for form in FORMS_B23:
                    for lab, fl in (('只看这个子与起止格', lambda x: x['truth'] or x['type'] in LOCAL),
                                    ('要看路径上或别处的子', lambda x: x['truth'] or x['type'] not in LOCAL)):
                        g = noul_groups(jobs, res, 'B2', game, form, filt=fl)
                        gi = {k: [x for x in v if not x[1]] for k, v in g.items()}
                        P('- %s %s：违规 %d 步，判否 %s，AUC（vs 合法步）%s' % (
                            form, lab, sum(len(v) for v in gi.values()), ci(boot(gi, s_tnr)), ci(boot(g, s_auc))))
                P('')
            P('### B2 合法步按子种（判「是」= 对）\n')
            for game in (XQ, CH):
                for form in FORMS_B23:
                    c = collections.defaultdict(list)
                    for k, j in jobs.items():
                        if (j['part'], j['game'], j['form'], j['mode'], j['rep']) != ('B2', game, form, 'multi', 0):
                            continue
                        for n, p in res[k].items():
                            t = j['truth'][n]
                            c[(t['truth'], t['kind'])].append(p)
                    P('- %s %s：合法 %s；违规 %s' % (
                        GNAME[game], form,
                        '，'.join('%s %d/%d' % (B.piece_name(game, kd.upper()), sum(p >= 0.5 for p in v), len(v))
                                 for (ok, kd), v in sorted(c.items()) if ok),
                        '，'.join('%s %d/%d' % (B.piece_name(game, kd.upper()), sum(p < 0.5 for p in v), len(v))
                                 for (ok, kd), v in sorted(c.items()) if not ok)))
            P('')
        if part == 'B3':
            P('### B3 按类别（能被吃 = 判是为对；差一点 / 够不着 = 判否为对）\n')
            P('| 棋种 | 形态 | 能被吃 判是 | 差一点 判否 | 够不着 判否 | AUC 能被吃 vs 差一点 | AUC 能被吃 vs 够不着 |')
            P('|---|---|---|---|---|---|---|')
            for game in (XQ, CH):
                for form in FORMS_B23:
                    gc = noul_groups(jobs, res, 'B3', game, form, filt=lambda x: x['cat'] == 'cap')
                    gn = noul_groups(jobs, res, 'B3', game, form, filt=lambda x: x['cat'] == 'near')
                    gf = noul_groups(jobs, res, 'B3', game, form, filt=lambda x: x['cat'] == 'far')
                    gcn = noul_groups(jobs, res, 'B3', game, form, filt=lambda x: x['cat'] in ('cap', 'near'))
                    gcf = noul_groups(jobs, res, 'B3', game, form, filt=lambda x: x['cat'] in ('cap', 'far'))
                    nc = sum(len(v) for v in gc.values()); nn = sum(len(v) for v in gn.values()); nf = sum(len(v) for v in gf.values())
                    P('| %s | %s | %s（%d） | %s（%d） | %s（%d） | %s | %s |' % (
                        GNAME[game], form, ci(boot(gc, s_tpr)), nc, ci(boot(gn, s_tnr)), nn, ci(boot(gf, s_tnr)), nf,
                        ci(boot(gcn, s_auc)), ci(boot(gcf, s_auc))))
            P('\n「差一点」里挡住吃子的原因（一个子可有多条）与判否比例（fen / cells）：')
            for game in (XQ, CH):
                c = collections.defaultdict(lambda: {f: [] for f in FORMS_B23})
                for k, j in jobs.items():
                    if j['part'] != 'B3' or j['game'] != game or j['mode'] != 'multi' or j['rep'] != 0:
                        continue
                    for n, p in res[k].items():
                        t = j['truth'][n]
                        for r in t['near']:
                            c[r][j['form']].append(p)
                P('- %s：%s' % (GNAME[game], '；'.join('%s fen %d/%d、cells %d/%d' % (
                    B.VIOLATIONS.get(r, r), sum(p < 0.5 for p in v['fen']), len(v['fen']),
                    sum(p < 0.5 for p in v['cells']), len(v['cells'])) for r, v in sorted(c.items()))))
            P('\n能被吃的子按「谁能吃它」（fen / cells 判是）：')
            for game in (XQ, CH):
                c = collections.defaultdict(lambda: {f: [] for f in FORMS_B23})
                for k, j in jobs.items():
                    if j['part'] != 'B3' or j['game'] != game or j['mode'] != 'multi' or j['rep'] != 0:
                        continue
                    for n, p in res[k].items():
                        t = j['truth'][n]
                        if t['truth']:
                            key = '+'.join(sorted({B.piece_name(game, a.upper()) for a in t['att']}))
                            c[key][j['form']].append(p)
                P('- %s：%s' % (GNAME[game], '；'.join('%s fen %d/%d、cells %d/%d' % (
                    key, sum(p >= 0.5 for p in v['fen']), len(v['fen']), sum(p >= 0.5 for p in v['cells']), len(v['cells']))
                    for key, v in sorted(c.items()))))
            P('\n同一种子的「能吃」对比「差一点吃不到」（正例 = 能被这种子吃，反例 = 这种子够得着但被挡住）：\n')
            P('| 棋种 | 形态 | 对比 | 正 / 反 | AUC | 正例判是 | 反例判否 |')
            P('|---|---|---|---|---|---|---|')
            for game in (XQ, CH):
                for form in FORMS_B23:
                    for name, g in b3_subcases(jobs, res, game, form):
                        items = [x for v in g.values() for x in v]
                        npos = sum(t for _, t in items)
                        P('| %s | %s | %s | %d / %d | %s | %s | %s |' % (GNAME[game], form, name, npos, len(items) - npos,
                                                                  ci(boot(g, s_auc)), fmt(s_tpr(items)), fmt(s_tnr(items))))
            P('')

    # ---- 跨部分：识子 vs 关系
    P('## 识子 vs 关系：同一形态、同一批局面\n')
    P('| 棋种 | 形态 | B1 识子准确率 | B2 AUC | B2 准确率 | B3 AUC | B3 平衡准确率 |')
    P('|---|---|---|---|---|---|---|')
    for game in (XQ, CH):
        for form in FORMS_B23:
            g2 = noul_groups(jobs, res, 'B2', game, form)
            g3 = noul_groups(jobs, res, 'B3', game, form)
            P('| %s | %s | %s | %s | %s | %s | %s |' % (GNAME[game], form, ci(boot(b1g[(game, form)], s_c('ok'))),
                                                   ci(boot(g2, s_auc)), ci(boot(g2, s_acc)), ci(boot(g3, s_auc)), ci(boot(g3, s_bacc))))
    P('\n局面层面：每个局面的 B1-fen 准确率与 B2-fen / B3-fen 准确率的相关（Spearman，看读不准的局面是否也判不准）：')
    for game in (XQ, CH):
        a = {k: s_c('ok')(v) for k, v in b1g[(game, 'fen')].items()}
        for part in ('B2', 'B3'):
            g = noul_groups(jobs, res, part, game, 'fen')
            b = {k: (s_acc(v) if part == 'B2' else s_bacc(v)) for k, v in g.items()}
            ks = sorted(k for k in a if b.get(k) is not None)
            P('- %s B1 vs %s：ρ = %s（%d 局面）' % (GNAME[game], part, fmt(spearman([a[k] for k in ks], [b[k] for k in ks])), len(ks)))
    P('')

    # ---- 抖动
    P('## 抖动：同一请求体重复 3 次（前 %d 个局面，fen）\n' % N_JIT)
    jit_pos = {g: [p['id'] for p in positions(g)[:N_JIT]] for g in (XQ, CH)}
    P('| 棋种 | 部分 | 题数 | 两两 |Δp| 均值 | 最大 | 跨 0.5 翻转的题 | 3 次指标（准确率 / AUC） |')
    P('|---|---|---:|---|---|---|---|')
    for game in (XQ, CH):
        for part in ('B1', 'B2', 'B3'):
            ds, flips, nq = [], 0, 0
            per_rep = []
            for rep in (0,) + JIT_REPS:
                if part == 'B1':
                    g = choice_groups(jobs, res, game, 'fen', rep=rep, pos_set=set(jit_pos[game]))
                    per_rep.append('%.2f' % s_c('ok')([x for v in g.values() for x in v]))
                else:
                    g = noul_groups(jobs, res, part, game, 'fen', rep=rep, pos_set=set(jit_pos[game]))
                    items = [x for v in g.values() for x in v]
                    per_rep.append('%.2f / %s' % (s_acc(items), fmt(s_auc(items))))
            for pid in jit_pos[game]:
                ks = [jobkey(part, game, pid, 'fen', 'multi', '-', r) for r in (0,) + JIT_REPS]
                tr = jobs[ks[0]]['truth']
                for n in tr:
                    nq += 1
                    if part == 'B1':
                        vals = [res[k][n]['p'][tr[n]['truth']] for k in ks]
                        chs = {res[k][n]['choice'] for k in ks}
                        flips += len(chs) > 1
                    else:
                        vals = [res[k][n] for k in ks]
                        flips += len({v >= 0.5 for v in vals}) > 1
                    ds += [abs(vals[a] - vals[b]) for a in range(3) for b in range(a + 1, 3)]
            P('| %s | %s | %d | %.3f | %.2f | %d | %s |' % (GNAME[game], part + ('（p(正解)，翻转 = 选中项变了）' if part == 'B1' else ''),
                                                      nq, sum(ds) / len(ds), max(ds), flips, ' ; '.join(per_rep)))
    P('')

    # ---- 单题 vs 多题
    P('## 同请求多题 vs 一题一请求（前 %d 个局面，fen）\n' % N_SGL)
    P('| 棋种 | 部分 | 题数 | |单题 − 多题r0| 均值 | 最大 | 对照：|多题r1 − 多题r0| 均值 | 判断不同的题（单题 vs r0） | 对照：r1 vs r0 | 指标：单题 / r0 / r1 / r2 |')
    P('|---|---|---:|---|---|---|---|---|---|')
    sgl_pos = {g: [p['id'] for p in positions(g)[:N_SGL]] for g in (XQ, CH)}
    for game in (XQ, CH):
        for part in ('B1', 'B2'):
            d_s, d_j, diff_s, diff_j, nq = [], [], 0, 0, 0
            for pid in sgl_pos[game]:
                k0 = jobkey(part, game, pid, 'fen', 'multi', '-', 0)
                k1 = jobkey(part, game, pid, 'fen', 'multi', '-', 1)
                tr = jobs[k0]['truth']
                for n in tr:
                    ks = jobkey(part, game, pid, 'fen', 'single', n, 0)
                    nq += 1
                    if part == 'B1':
                        tt = tr[n]['truth']
                        v0, v1, vs = res[k0][n]['p'][tt], res[k1][n]['p'][tt], res[ks][n]['p'][tt]
                        diff_s += res[ks][n]['choice'] != res[k0][n]['choice']
                        diff_j += res[k1][n]['choice'] != res[k0][n]['choice']
                    else:
                        v0, v1, vs = res[k0][n], res[k1][n], res[ks][n]
                        diff_s += (vs >= 0.5) != (v0 >= 0.5)
                        diff_j += (v1 >= 0.5) != (v0 >= 0.5)
                    d_s.append(abs(vs - v0))
                    d_j.append(abs(v1 - v0))
            # 指标
            mets = []
            if part == 'B1':
                gs = choice_groups(jobs, res, game, 'fen', mode='single', pos_set=set(sgl_pos[game]))
                mets.append('%.2f' % s_c('ok')([x for v in gs.values() for x in v]))
                for rep in (0,) + JIT_REPS:
                    g = choice_groups(jobs, res, game, 'fen', rep=rep, pos_set=set(sgl_pos[game]))
                    mets.append('%.2f' % s_c('ok')([x for v in g.values() for x in v]))
                mets = '准确率 ' + ' / '.join(mets)
            else:
                gs = noul_groups(jobs, res, part, game, 'fen', mode='single', pos_set=set(sgl_pos[game]))
                its = [x for v in gs.values() for x in v]
                mets.append('%.2f/%.2f' % (s_acc(its), s_auc(its)))
                for rep in (0,) + JIT_REPS:
                    g = noul_groups(jobs, res, part, game, 'fen', rep=rep, pos_set=set(sgl_pos[game]))
                    its = [x for v in g.values() for x in v]
                    mets.append('%.2f/%.2f' % (s_acc(its), s_auc(its)))
                mets = '准确率/AUC ' + ' ; '.join(mets)
            P('| %s | %s | %d | %.3f | %.2f | %.3f | %d | %d | %s |' % (
                GNAME[game], part, nq, sum(d_s) / nq, max(d_s), sum(d_j) / nq, diff_s, diff_j, mets))
    P('\n（B1 的 Δ 是 p(正解) 的差，「判断不同」= 选中项不同；B2 的「判断不同」= 跨 0.5。）\n')
    report_b2c(jobs, res, log, P)
    report_b2p(jobs, res, log, P)
    report_b3v1(jobs, res, P)
    text = '\n'.join(out)
    print(text)
    return text


def piece_same(game, a, b):
    """「红帅」vs「黑将」这类同子种不同名的情况（中国象棋红黑子名不同）。"""
    inv = {}
    for L in B.ORDER[game]:
        inv[B.label(game, L)] = L
        inv[B.label(game, L.lower())] = L
    return a in inv and b in inv and inv[a] == inv[b]


def spearman(a, b):
    def ranks(v):
        s = sorted(range(len(v)), key=lambda i: v[i])
        r = [0.0] * len(v)
        i = 0
        while i < len(s):
            j = i
            while j + 1 < len(s) and v[s[j + 1]] == v[s[i]]:
                j += 1
            for k in range(i, j + 1):
                r[s[k]] = (i + j) / 2
            i = j + 1
        return r
    ra, rb = ranks(a), ranks(b)
    n = len(a)
    ma, mb = sum(ra) / n, sum(rb) / n
    cov = sum((x - ma) * (y - mb) for x, y in zip(ra, rb))
    va = math.sqrt(sum((x - ma) ** 2 for x in ra))
    vb = math.sqrt(sum((y - mb) ** 2 for y in rb))
    return cov / (va * vb) if va and vb else None


if __name__ == '__main__':
    args = [a for a in sys.argv[1:] if not a.startswith('--')]
    only = None
    for a in sys.argv[1:]:
        if a.startswith('--only'):
            only = set(a.split('=', 1)[1].split(',')) if '=' in a else None
    if args == ['check']:
        check()
    elif args == ['run']:
        expect, workers = None, WORKERS
        for a in sys.argv[1:]:
            if a.startswith('--expect='):
                expect = a.split('=', 1)[1]
            if a.startswith('--workers='):
                workers = int(a.split('=', 1)[1])
        run(only, expect, workers)
    elif args == ['b2c-extra']:
        raise SystemExit(0 if gen_b2c_extra() else 1)
    elif args == ['b2p-gen']:
        raise SystemExit(0 if gen_b2p() else 1)
    elif args == ['void-b3']:
        void_b3()
    elif args == ['fingerprint']:
        print(fingerprint(build()))
    elif args == ['report']:
        report(only)
    else:
        raise SystemExit(__doc__)
