# -*- coding: utf-8 -*-
"""实验 A：一步杀，把「选项文字 / 提示句 / 盘面形态 / 记谱写法 / 提问语言 / 题型」一次拆开一个。

    python exp_xiangqi_mate.py run [--dry] [--limit N] [--workers 6]   # 发请求，原始回包写 xiangqi_mate_log.json；
                                                                       # 已成功的跳过（断点续跑），--dry 只列计划不发
    python exp_xiangqi_mate.py report [--out PATH] [--log PATH]        # 只读日志出表（markdown），不发请求、不需要 key

回答「两棋种（中国象棋 vs 国际象棋）一步杀的差距是不是真的、来自哪里」：H1 选项文字泄露（描述阶梯 U0→U3、
原样 SAN）、H5 记谱写法与提问语言（中国象棋 2×2），并给 H2–H4 旁证（盘面四种形态、只给坐标、逐步是非、
选中着法是否将军）。底座是同目录 boards.py 与 xiangqi_positions.json。

局面：两棋种 set='mate' 的 natural 40 + textbook 8 做主分析；legacy（初探旧局面）只进「旧格式复现」臂。
臂（基线 = U0 描述 + FEN + 带提示 + 中文提问 + 无意义键 + 打乱；一次只动一个因素）：
  U0 / U1 / U2 / U3         描述阶梯（boards.describe_all）
  U0-nohint / U2-nohint     去掉「注意：这里存在一步将死的机会。」
  coord                     描述只给坐标，不含棋子名
  N0                        原生写法不带标记：中国象棋中文记谱；国际象棋 SAN 去掉 x + #
  N3（仅国际象棋）          原样 SAN（杀着带 #），但键仍是无意义键
  cells / pieces / board    state 换成格子表 / 子力清单 / 字符棋盘（描述 U0）
  en-U0                     英文提问 + 英文 state + 英文描述（Rook from h6 to e6）
  en-N0（仅中国象棋）       英文提问 + 英文 state + 中文记谱；与 U0、N0、en-U0 组成「语言 × 写法」2×2
  noul                      每个合法着法一道 noul「走完这一步，对方是否被将死？」，一次请求问完，取最大
  U2-cells / U2-pieces      补测：U2 描述 + 格子表 / 子力清单 state，其余与 U2 完全相同（同一套键与顺序）。
                            FEN 下 U2 分不开「读不出盘」与「算不出哪个将军是杀」，这两臂把读盘去掉再看 k 分档与免费基线；
                            报告第六节那张 k·份额表（FEN / 格子表 / 子力清单三行）由 report 第 4d 节逐格输出
  抖动                      每棋种 10 个局面（8 自然 + 2 教科书）× U0 × rep 1、2（换 rep 换键↔着法映射与选项顺序）
  旧格式复现                初探原格式：选项键是坐标、state 带合法着法清单；中国象棋照 games/exp_game_xiangqi.py 的
                            C1（中文记谱 / 带吃子的坐标描述）与 C2（FEN / 子力清单）各跑两轮，共 32 次，与旧的
                            「32 次中 2 次」同构；国际象棋照 games/exp_game_chess.py 原样 SAN，5 局面 × 2 次
选项键：boards.options() 修订 1 起，键↔着法与顺序只由 (局面, rep) 定、各臂共用，臂间差异里不混进键名和顺序。
共 1,618 次请求，实测 $0.093（2026-09-22，输入约 220 万 token）：原批次 1,426 次 $0.081，补测两臂 192 次 $0.012。

断言：描述两两不同、无标记臂不含泄露（describe_all 自带）；键 → 着法 → 描述回查一致；答案是局面唯一杀着；
回包模型串必须是 typesafe/jev-1.13-20260917（不是就停）；choice 键集合一致、概率和与 1 相差 ≤0.03；noul 题一题不缺。
日志 xiangqi_mate_log.json 被 .gitignore 排除（*_log.json），不入库。
"""
# 让本脚本从任意目录都能找到仓库根部的 jevkit.py
import sys as _sys, pathlib as _pathlib
_sys.path.insert(0, str(_pathlib.Path(__file__).resolve().parent.parent))
import json, math, os, random, statistics, sys, time
from collections import Counter, defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import boards as B

LOG = os.path.join(HERE, 'xiangqi_mate_log.json')
MODEL = 'typesafe/jev-1.13-20260917'
COST_CAP = 0.5          # 美元；累计超过就停下
XQ, CH = B.XQ, B.CH

ASK = {(XQ, 'zh'): '你在下中国象棋，执红。从合法着法里选一步最好的。',
       (CH, 'zh'): '你在下国际象棋，执白。从合法着法里选一步最好的。',
       (XQ, 'en'): 'You are playing xiangqi (Chinese chess) as Red. Choose the best move from the legal moves.',
       (CH, 'en'): 'You are playing chess as White. Choose the best move from the legal moves.'}
HINT = {'zh': '注意：这里存在一步将死的机会。', 'en': 'Note: there is a checkmate-in-one opportunity here.'}
NOUL_CTX = {XQ: '你在下中国象棋，执红。', CH: '你在下国际象棋，执白。'}
NOUL_Q = '走完这一步，对方是否被将死？这一步：'

# 臂 → (适用棋种, 描述档, 语言, state 形态, 带提示, 题型)
ARMS = {
    'U0':        ((XQ, CH), 'U0', 'zh', 'fen', True, 'choice'),
    'U1':        ((XQ, CH), 'U1', 'zh', 'fen', True, 'choice'),
    'U2':        ((XQ, CH), 'U2', 'zh', 'fen', True, 'choice'),
    'U3':        ((XQ, CH), 'U3', 'zh', 'fen', True, 'choice'),
    'U0-nohint': ((XQ, CH), 'U0', 'zh', 'fen', False, 'choice'),
    'U2-nohint': ((XQ, CH), 'U2', 'zh', 'fen', False, 'choice'),
    'coord':     ((XQ, CH), 'coord', 'zh', 'fen', True, 'choice'),
    'N0':        ((XQ, CH), 'N0', 'zh', 'fen', True, 'choice'),
    'N3':        ((CH,), 'N3', 'zh', 'fen', True, 'choice'),
    'cells':     ((XQ, CH), 'U0', 'zh', 'cells', True, 'choice'),
    'pieces':    ((XQ, CH), 'U0', 'zh', 'pieces', True, 'choice'),
    'board':     ((XQ, CH), 'U0', 'zh', 'board', True, 'choice'),
    'en-U0':     ((XQ, CH), 'U0', 'en', 'fen', True, 'choice'),
    'en-N0':     ((XQ,), 'N0', 'en', 'fen', True, 'choice'),
    'noul':      ((XQ, CH), 'U0', 'zh', 'fen', None, 'noul'),
    # 补测（实验 A 之后加）：盘面读清以后标了将军，看能不能在将军着法里挑中杀着；其余与 U2 完全相同
    'U2-cells':  ((XQ, CH), 'U2', 'zh', 'cells', True, 'choice'),
    'U2-pieces': ((XQ, CH), 'U2', 'zh', 'pieces', True, 'choice'),
}
SUPP_ARMS = ('U2-cells', 'U2-pieces')
MAIN_ARMS = list(ARMS)
JITTER_REPS = (1, 2)


# ---------------------------------------------------------------- 局面
_DATA = None


def data():
    global _DATA
    if _DATA is None:
        _DATA = B.load_positions()
    return _DATA


def main_positions(game):
    ps = [p for p in B.select(data(), game=game, set_='mate') if p['stratum'] in ('natural', 'textbook')]
    return sorted(ps, key=lambda p: p['id'])


def legacy_positions(game):
    """旧格式复现要原样重放全部旧局面（含按真实规则无唯一正解的 xq-mate-old-02…06），分析时再分开列。"""
    return sorted(B.select(data(), game=game, set_='mate', stratum='legacy', include_invalid_legacy=True),
                  key=lambda p: p['id'])


def jitter_ids(game):
    ps = main_positions(game)
    rng = random.Random(B.seed_of('jitter', game))
    nat = sorted(p['id'] for p in ps if p['stratum'] == 'natural')
    book = sorted(p['id'] for p in ps if p['stratum'] == 'textbook')
    return sorted(rng.sample(nat, 8) + rng.sample(book, 2))


def cluster_of(p):
    """自然局面按自对弈对局聚类（同一盘至多取 2 个），其余各自一类。"""
    if p.get('source'):
        return '%s-sp%d' % (p['game'], p['source']['selfplay'])
    return p['id']


_FX = {}


def fxs_of(game, fen):
    k = (game, fen)
    if k not in _FX:
        _FX[k] = B.all_facts(game, fen)
    return _FX[k]


# ---------------------------------------------------------------- 请求构造
def build_main(p, arm, rep=0):
    game, fen, pid = p['game'], p['fen'], p['id']
    _, style, lang, form, hint, qtype = ARMS[arm]
    fxs = fxs_of(game, fen)
    assert [m for m, f in fxs.items() if f['mate']] == [p['answer']], ('答案不是唯一杀着', pid)
    assert not any(f['stalemate'] for f in fxs.values()) or game == CH, ('中国象棋局面另有一步困毙', pid)
    texts = B.describe_all(game, fen, style, lang, fxs)          # 自带：两两不同、标记与档位一致
    crit, k2m = B.options(texts, pid, rep=rep)                  # 键↔着法与顺序只由 (局面, rep) 定，各臂共用
    for k, t in crit.items():                                    # 键 → 着法 → 描述回查
        assert texts[k2m[k]] == t and k2m[k] in fxs, (pid, arm, k)
    st = B.state(game, fen, form, 'en' if lang == 'en' else 'zh')
    assert not any('legal' in s for s in st), '主分析的 state 不许带着法清单'
    if qtype == 'choice':
        instr = ASK[(game, lang)] + ((' ' if lang == 'en' else '') + HINT[lang] if hint else '')
        qs = {'move': {'type': 'choice', 'instructions': instr, 'criteria': crit}}
    else:
        qs = {k: {'type': 'noul', 'instructions': NOUL_CTX[game] + NOUL_Q + t} for k, t in crit.items()}
    return {'game': game, 'pid': pid, 'arm': arm, 'rep': rep, 'qtype': qtype, 'answer': p['answer'],
            'k2m': k2m, 'req': {'state': st, 'questions': qs}}


# 旧格式：照抄 games/exp_game_xiangqi.py / games/exp_game_chess.py
OLD_XQ_ASK = '你在下中国象棋，执红。从合法着法里选一步最好的。注意：这里存在一步将死的机会。'
OLD_CH_ASK = '你在下国际象棋，执白。从合法着法里选一步最好的。注意：这里存在一步将死的机会。'
OLD_COORDS = '坐标用 ICCS 记法：纵线 a 到 i 从红方左手边数起，横线 0 到 9 从红方底线数起'
OLD_NAME = B.CN_NAME


def old_xq_moves(fen):
    """games/exp_game_xiangqi.py 的 legal_moves 原样：cchess 枚举顺序，[(iccs, 中文记谱, 起点, 终点, 起点子, 终点子, cchess 认为是杀)]"""
    import cchess
    b = cchess.ChessBoard(fen)
    out = []
    for pf, pt in list(b.create_moves()):
        if b.get_fench(pt) == 'k' or not (bool(b.is_valid_move(pf, pt)) and not b.is_checked_move(pf, pt)):
            continue
        mv = cchess.ChessBoard(fen).move(pf, pt)
        out.append((mv.to_iccs(), mv.to_text(), pf, pt, b.get_fench(pf), b.get_fench(pt),
                    bool(mv.is_checking and mv.is_checkmate)))
    return out


def old_board_list(fen):
    import cchess
    b = cchess.ChessBoard(fen)
    red, black = {}, {}
    for x in range(9):
        for y in range(10):
            f = b.get_fench((x, y))
            if f:
                (red if f.isupper() else black).setdefault(OLD_NAME[f], []).append(B.sq_of(x, y))
    return {'coords': OLD_COORDS, '红方子力': red, '黑方子力': black, '轮到': '红方'}


def build_legacy():
    """-> [请求]。中国象棋：C1 = 旧随机局面 1–4 × {中文记谱, 坐标} × 2 轮；C2 = 旧教科书 2 个 × {FEN, 子力清单} × 2 次 × 2 轮。"""
    out = []
    for p in legacy_positions(XQ):
        fen = p['legacy_fen']
        ms = old_xq_moves(fen)
        moves = sorted(m[0] for m in ms)
        cn = {m[0]: m[1] for m in ms}
        xyd = {m[0]: '%s从 %s 走到 %s%s' % (OLD_NAME[m[4]], B.sq_of(*m[2]), B.sq_of(*m[3]),
                                          '，吃掉对方的%s' % OLD_NAME[m[5]] if m[5] else '') for m in ms}
        fen_state = {'fen': fen, 'side_to_move': '红方', 'coords': OLD_COORDS, 'legal_moves_iccs': moves}
        cc_mates = [m[0] for m in ms if m[6]]
        book = p['name'].startswith('初探教科书')
        variants = ([('old-cn', fen_state, cn), ('old-list', dict(old_board_list(fen), legal_moves_iccs=moves), cn)]
                    if book else [('old-cn', fen_state, cn), ('old-xy', fen_state, xyd)])
        for arm, st, crit in variants:
            for rep in range(4 if book else 2):
                out.append({'game': XQ, 'pid': p['id'], 'arm': arm, 'rep': rep, 'qtype': 'choice',
                            'answer': p['answer'], 'k2m': {m: m for m in crit}, 'cchess_mates': cc_mates,
                            'req': {'state': st, 'questions': {'move': {
                                'type': 'choice', 'instructions': OLD_XQ_ASK, 'criteria': crit}}}})
    import chess
    for p in legacy_positions(CH):
        b = chess.Board(p['legacy_fen'])
        crit = {m.uci(): b.san(m) for m in b.legal_moves}
        st = {'fen': b.fen(), 'side_to_move': 'white', 'legal_moves_uci': sorted(crit)}
        for rep in range(2):
            out.append({'game': CH, 'pid': p['id'], 'arm': 'old-san', 'rep': rep, 'qtype': 'choice',
                        'answer': p['answer'], 'k2m': {m: m for m in crit},
                        'req': {'state': st, 'questions': {'move': {
                            'type': 'choice', 'instructions': OLD_CH_ASK, 'criteria': crit}}}})
    return out


def jobkey(e):
    return '%s|%s|%s|%d' % (e['game'], e['arm'], e['pid'], e['rep'])


def all_jobs():
    out = []
    for game in (XQ, CH):
        ps = main_positions(game)
        assert len(ps) == 48, (game, len(ps))
        for arm in MAIN_ARMS:
            if game not in ARMS[arm][0]:
                continue
            for p in ps:
                out.append(build_main(p, arm, 0))
        jit = set(jitter_ids(game))
        for p in ps:
            if p['id'] in jit:
                for rep in JITTER_REPS:
                    out.append(build_main(p, 'U0', rep))
    out += build_legacy()
    keys = [jobkey(e) for e in out]
    assert len(set(keys)) == len(keys)
    return out


# ---------------------------------------------------------------- 日志与解析
def load(path=None):
    path = path or LOG
    if os.path.exists(path):
        with open(path, encoding='utf-8') as f:
            return json.load(f)
    return {}


def save(log):
    tmp = LOG + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(log, f, ensure_ascii=False)
    os.replace(tmp, LOG)


def ok_entry(e):
    return e is not None and 'resp' in e and '_error' not in e['resp']


def parse(e):
    """-> {'probs': {着法: p}, 'chosen': 着法, 'conf', 'argmax_ok'}；不符合断言直接抛错。"""
    r = e['resp']
    assert r.get('model') == MODEL, ('模型串不对，停下', r.get('model'))
    qs = e['req']['questions']
    ans = r['answers']
    k2m = e['k2m']
    if e['qtype'] == 'choice':
        a = ans['move']
        crit = qs['move']['criteria']
        p = {k: float(v) for k, v in a['probabilities'].items()}
        assert set(p) == set(crit), ('choice 键不一致', jobkey(e))
        assert a['choice'] in crit
        assert abs(sum(p.values()) - 1) <= 0.03, ('概率和', jobkey(e), sum(p.values()))
        probs = {k2m[k]: v for k, v in p.items()}
        top = max(p.values())
        return {'probs': probs, 'chosen': k2m[a['choice']], 'conf': float(a['confidence']),
                'argmax_ok': p[a['choice']] >= top - 1e-9, 'ties': [k2m[k] for k, v in p.items() if v == top]}
    assert set(ans) == set(qs), ('noul 缺题', jobkey(e))
    probs = {}
    for k in qs:
        assert ans[k]['type'] == 'noul'
        v = float(ans[k]['noul'])
        assert 0 <= v <= 1
        probs[k2m[k]] = v
    top = max(probs.values())
    ties = [m for m, v in probs.items() if v == top]
    return {'probs': probs, 'chosen': None, 'conf': None, 'argmax_ok': True, 'ties': ties}


# ---------------------------------------------------------------- run
def run(dry=False, limit=None, workers=6):
    jobs = all_jobs()
    log = load()
    todo = []
    for e in jobs:
        k = jobkey(e)
        old = log.get(k)
        if ok_entry(old):
            assert old['req'] == e['req'] and old['k2m'] == e['k2m'], ('日志里的请求与脚本当前构造的不一致：%s' % k)
            continue
        todo.append(e)
    cnt = Counter((e['game'], e['arm']) for e in jobs)
    print('计划 %d 次请求（日志已有 %d 次成功，待发 %d 次）' % (len(jobs), len(jobs) - len(todo), len(todo)))
    for (g, a), n in sorted(cnt.items()):
        print('  %-8s %-10s %d' % (g, a, n))
    chars = [len(json.dumps(e['req'], ensure_ascii=False)) for e in todo]
    if chars:
        print('待发请求体字符数：中位 %d，最大 %d，合计 %d（中文约一字一 token，按 $0.042/百万 token 粗估上限 $%.3f）' % (
            statistics.median(chars), max(chars), sum(chars), sum(chars) * 0.042 / 1e6))
    if dry:
        return
    if limit:
        todo = todo[:limit]
    import jevkit as jev
    spent = sum(x['resp'].get('usage', {}).get('cost', 0.0) for x in log.values() if ok_entry(x))
    step = 60
    for i in range(0, len(todo), step):
        batch = todo[i:i + step]
        res = jev.fan([(jobkey(e), e['req']['state'], e['req']['questions']) for e in batch], workers=workers)
        now = time.time()
        bad_model = []
        for e in batch:
            k = jobkey(e)
            d = res[k]
            log[k] = dict(e, resp=d, t=now)
            if '_error' not in d:
                spent += d.get('usage', {}).get('cost', 0.0)
                if d.get('model') != MODEL:
                    bad_model.append((k, d.get('model')))
        save(log)                      # 先落盘再断言，断言失败也不丢已花钱拿到的回包
        if bad_model:
            raise SystemExit('回包模型串不是 %s，停下：%s' % (MODEL, bad_model[:5]))
        for e in batch:
            k = jobkey(e)
            if '_error' in log[k]['resp']:
                print('FAIL', k, log[k]['resp']['_error'])
            else:
                parse(log[k])
        print('  已发 %d/%d，%s，累计花费 $%.5f' % (min(i + step, len(todo)), len(todo), jev.spend(), spent))
        if spent > COST_CAP:
            raise SystemExit('累计花费超过 $%.2f，先停下' % COST_CAP)
    print(jev.spend())


# ---------------------------------------------------------------- 统计工具
def wilson(k, n, z=1.96):
    if n == 0:
        return (float('nan'), float('nan'))
    ph = k / n
    den = 1 + z * z / n
    c = (ph + z * z / (2 * n)) / den
    h = z * math.sqrt(ph * (1 - ph) / n + z * z / (4 * n * n)) / den
    return (max(0.0, c - h), min(1.0, c + h))


NB = 2000


def _group(items):
    cl = defaultdict(list)
    for it in items:
        cl[it['cl']].append(it)
    return cl


def boot1(items, stat, seed='b1'):
    """按聚类（自对弈对局 / 单个局面）有放回重抽，stat(items) -> float 或 None。返回 (点估计, 下限, 上限)。"""
    cl = _group(items)
    ids = sorted(cl)
    rng = random.Random(B.seed_of(seed, len(items)))
    vals = []
    for _ in range(NB):
        s = []
        for _ in ids:
            s.extend(cl[rng.choice(ids)])
        v = stat(s)
        if v is not None:
            vals.append(v)
    vals.sort()
    if not vals:
        return (stat(items), float('nan'), float('nan'))
    return (stat(items), vals[int(0.025 * len(vals))], vals[min(len(vals) - 1, int(0.975 * len(vals)))])


def boot2(a, b, stat, seed='b2'):
    """两组独立（两棋种）各自按聚类重抽，stat(a, b) -> float 或 None。"""
    ca, cb = _group(a), _group(b)
    ia, ib = sorted(ca), sorted(cb)
    rng = random.Random(B.seed_of(seed, len(a), len(b)))
    vals = []
    for _ in range(NB):
        sa, sb = [], []
        for _ in ia:
            sa.extend(ca[rng.choice(ia)])
        for _ in ib:
            sb.extend(cb[rng.choice(ib)])
        v = stat(sa, sb)
        if v is not None:
            vals.append(v)
    vals.sort()
    return (stat(a, b), vals[int(0.025 * len(vals))], vals[min(len(vals) - 1, int(0.975 * len(vals)))])


def mean(xs, key):
    xs = [x[key] for x in xs if x.get(key) is not None]
    return sum(xs) / len(xs) if xs else None


def fci(t, d=2):
    v, lo, hi = t
    if v is None:
        return '–'
    f = '%%.%df' % d
    return (f + ' [' + f + ', ' + f + ']') % (v, lo, hi)


def fsig(t, d=2):
    """差值 + 区间，区间不含 0 时加 *。"""
    s = fci(t, d)
    v, lo, hi = t
    if v is not None and not (lo <= 0 <= hi):
        s += ' *'
    return s


def fhit(k, n):
    lo, hi = wilson(k, n)
    return '%s/%d (%.0f%% [%.0f, %.0f])' % (('%g' % k), n, 100 * k / n if n else 0, 100 * lo, 100 * hi)


# ---------------------------------------------------------------- 记录
def midrank_norm(probs, mv):
    """正解排名的归一化位置：按概率从高到低，并列取平均名次；0 = 排第一，1 = 排最后。"""
    v = probs[mv]
    n = len(probs)
    higher = sum(1 for x in probs.values() if x > v)
    eq = sum(1 for x in probs.values() if x == v)
    rank = higher + (eq + 1) / 2
    return (rank - 1) / (n - 1)


def records(log):
    pos = {p['id']: p for p in data()['positions']}
    out = []
    for k, e in log.items():
        if not ok_entry(e):
            continue
        x = parse(e)
        p = pos[e['pid']]
        probs = x['probs']
        ans = e['answer']
        n = len(probs)
        legacy = e['arm'].startswith('old-')
        if legacy:
            checks, fx = None, None
        else:
            fx = fxs_of(p['game'], p['fen'])
            assert set(fx) == set(probs), ('选项与合法着法不一致', k)
            checks = [m for m, f in fx.items() if f['check']]
        if e['qtype'] == 'choice':
            hit = float(x['chosen'] == ans)
            pa = probs[ans]
            pn = pa * n
        else:
            hit = (1.0 / len(x['ties'])) if ans in x['ties'] else 0.0
            pa = probs[ans]
            tot = sum(probs.values())
            pn = pa / tot * n if tot > 0 else None
        r = {'key': k, 'game': e['game'], 'arm': e['arm'], 'rep': e['rep'], 'pid': e['pid'],
             'stratum': p['stratum'], 'cl': cluster_of(p), 'n': n, 'hit': hit, 'p': pa, 'pn': pn,
             'nrank': midrank_norm(probs, ans), 'conf': x['conf'], 'chosen': x['chosen'],
             'argmax_ok': x['argmax_ok'], 'probs': probs, 'answer': ans,
             'model': e['resp'].get('model'), 'usage': e['resp'].get('usage', {}),
             'elapsed': e['resp'].get('_elapsed'), 'qtype': e['qtype']}
        if not legacy:
            ft = p['features']
            r.update(k_checks=len(checks), mate_capture=ft['mate_capture'], mate_piece=ft['mate_piece'],
                     captures=ft['captures'])
            cs = sum(probs[m] for m in checks)
            r['check_mass'] = cs
            r['check_share_k'] = (pa / cs * len(checks)) if cs > 0 else None
            r['check_base'] = len(checks) / n
            caps = [m for m, f in fx.items() if f['captured']]
            r['cap_mass'] = sum(probs[m] for m in caps)
            r['cap_base'] = len(caps) / n
            if x['chosen'] is not None:
                r['chosen_check'] = float(fx[x['chosen']]['check'])
                r['chosen_cap'] = float(fx[x['chosen']]['captured'] is not None)
            else:
                ties = x['ties']
                r['chosen_check'] = sum(fx[m]['check'] for m in ties) / len(ties)
                r['chosen_cap'] = sum(fx[m]['captured'] is not None for m in ties) / len(ties)
        else:
            r['cchess_mates'] = e.get('cchess_mates')
            r['legacy_ok'] = p.get('legacy_ok')
            r['issues'] = p.get('issues')
            r['name'] = p.get('name')
        out.append(r)
    return out


def sel(R, game=None, arm=None, rep=0, stratum=None):
    return [r for r in R if (game is None or r['game'] == game) and (arm is None or r['arm'] == arm)
            and (rep is None or r['rep'] == rep) and (stratum is None or r['stratum'] == stratum)]


def by_pid(rs):
    return {r['pid']: r for r in rs}


def paired(ra, rb, key):
    """同一局面两臂成对：返回 [{'cl', 'd'}]，d = a − b。"""
    a, b = by_pid(ra), by_pid(rb)
    common = sorted(set(a) & set(b))
    return [{'cl': a[i]['cl'], 'd': a[i][key] - b[i][key], 'pid': i} for i in common
            if a[i].get(key) is not None and b[i].get(key) is not None]


def mean_d(items):
    return (sum(i['d'] for i in items) / len(items)) if items else None


# ---------------------------------------------------------------- report
GN = {XQ: '中国象棋', CH: '国际象棋'}
ARM_ZH = {'U0': 'U0 基线（棋子+坐标）', 'U1': 'U1 +吃子', 'U2': 'U2 +将军', 'U3': 'U3 杀着写将死',
          'U0-nohint': 'U0 无提示', 'U2-nohint': 'U2 无提示', 'coord': '只给坐标', 'N0': '原生 N0',
          'N3': '原生 N3（原样 SAN）', 'cells': '格子表', 'pieces': '子力清单', 'board': '字符棋盘',
          'en-U0': '英文 U0', 'en-N0': '英文 + 中文记谱', 'noul': '逐步是非（noul）',
          'U2-cells': 'U2 + 格子表', 'U2-pieces': 'U2 + 子力清单'}


def bins_of(k):
    return '1' if k == 1 else '2–3' if k <= 3 else '4–6' if k <= 6 else '7+'


def report(out=None, path=None, nocheck=False):
    log = load(path)
    if not log:
        raise SystemExit('日志为空：先跑 python exp_xiangqi_mate.py run')
    R = records(log)
    lines = []
    P = lines.append

    # 完整性：日志里每条请求必须与脚本当前构造的逐字相同（--nocheck 只给调试旧日志用）
    jobs = all_jobs()
    missing = [jobkey(e) for e in jobs if not ok_entry(log.get(jobkey(e)))]
    if not nocheck:
        for e in jobs:
            le = log.get(jobkey(e))
            if ok_entry(le):
                assert le['req'] == e['req'] and le['k2m'] == e['k2m'], '日志与脚本当前请求不一致：' + jobkey(e)
        extra = sorted(set(k for k, v in log.items() if ok_entry(v)) - set(jobkey(e) for e in jobs))
        assert not extra, ('日志里有不在当前计划里的条目，不许混进分析', extra[:5])
    models = Counter(r['model'] for r in R)
    us = [r['usage'] for r in R]
    el = [r['elapsed'] for r in R if r['elapsed']]
    P('# 实验 A 数据表（exp_xiangqi_mate.py report 生成）\n')
    P('- 成功回包 %d / 计划 %d；缺 %d%s' % (len(R), len(jobs), len(missing), ('：' + ', '.join(missing[:10])) if missing else ''))
    P('- 模型串：%s' % dict(models))
    P('- 输入 %d tok，输出 %d tok，花费 $%.5f；耗时中位 %.2f s（P90 %.2f s）' % (
        sum(u.get('input_tokens', 0) for u in us), sum(u.get('output_tokens', 0) for u in us),
        sum(u.get('cost', 0.0) for u in us), statistics.median(el), sorted(el)[int(0.9 * len(el))]))
    nam = [r['key'] for r in R if r['qtype'] == 'choice' and not r['argmax_ok']]
    gap = [max(r['probs'].values()) - r['probs'][r['chosen']] for r in R if r['qtype'] == 'choice' and not r['argmax_ok']]
    P('- choice 选中项不是显示概率最大项的回包：%d 个，差距最大 %.2f%s' % (len(nam), max(gap) if gap else 0, ('（%s）' % ', '.join(nam[:5])) if nam else ''))
    P('- 统计口径：分析单位是局面；命中率 Wilson 95%%；均值与差值的区间是按聚类（自然局面按自对弈对局，其余单个局面）bootstrap %d 次的 95%% 百分位区间；差值区间不含 0 标 *。' % NB)
    P('- p×n = p(正解) × 候选数（均匀猜 = 1）；归一化排名 0 = 正解排第一、1 = 排最后，均匀猜期望 0.5；并列取平均名次（概率只有两位小数，0 常大片并列）。\n')

    # 候选数与均匀基线
    P('## 0. 局面概况（主分析 48 + 48）\n')
    P('| 棋种 | 层 | 局面 | 合法着法中位 | 将军着法中位 | 1/n 均值 | 1/k 均值 |')
    P('|---|---|---:|---:|---:|---:|---:|')
    for g in (XQ, CH):
        for st in ('natural', 'textbook'):
            rs = sel(R, g, 'U0', 0, st)
            P('| %s | %s | %d | %g | %g | %.3f | %.3f |' % (GN[g], st, len(rs), statistics.median(r['n'] for r in rs),
                                                        statistics.median(r['k_checks'] for r in rs),
                                                        statistics.mean(1 / r['n'] for r in rs),
                                                        statistics.mean(1 / r['k_checks'] for r in rs)))
    P('')

    # 1. 主表
    P('## 1. 各臂主表（choice 臂；自然 40 + 教科书 8）\n')
    for g in (XQ, CH):
        P('### %s\n' % GN[g])
        P('| 臂 | 自然命中 | 教科书命中 | 合计命中 [Wilson] | p(正解) | p×n | 归一化排名 | 置信度 |')
        P('|---|---:|---:|---|---|---|---|---:|')
        for arm in MAIN_ARMS:
            if g not in ARMS[arm][0] or arm == 'noul':
                continue
            rs = sel(R, g, arm)
            if not rs:
                continue
            nat = [r for r in rs if r['stratum'] == 'natural']
            bk = [r for r in rs if r['stratum'] == 'textbook']
            P('| %s | %g/%d | %g/%d | %s | %s | %s | %s | %.2f |' % (
                ARM_ZH[arm], sum(r['hit'] for r in nat), len(nat), sum(r['hit'] for r in bk), len(bk),
                fhit(sum(r['hit'] for r in rs), len(rs)),
                fci(boot1(rs, lambda s: mean(s, 'p'), 'p' + g + arm)),
                fci(boot1(rs, lambda s: mean(s, 'pn'), 'pn' + g + arm), 1),
                fci(boot1(rs, lambda s: mean(s, 'nrank'), 'nr' + g + arm)),
                mean(rs, 'conf')))
        P('')

    # 1b. 分层 p(正解)：自然 / 教科书
    P('### 自然层与教科书层分开的 p(正解) 与 p×n\n')
    P('| 臂 | 中国象棋 自然 p | 中国象棋 教科书 p | 国际象棋 自然 p | 国际象棋 教科书 p | 中国象棋 自然 p×n | 中国象棋 教科书 p×n | 国际象棋 自然 p×n | 国际象棋 教科书 p×n |')
    P('|---|---|---|---|---|---|---|---|---|')
    for arm in MAIN_ARMS:
        if arm == 'noul':
            continue
        cells = []
        for key, d in (('p', 2), ('pn', 1)):
            for g in (XQ, CH):
                for st in ('natural', 'textbook'):
                    rs = sel(R, g, arm, 0, st)
                    cells.append(fci(boot1(rs, lambda s, key=key: mean(s, key), key + g + arm + st), d) if rs else '–')
        P('| %s | %s |' % (ARM_ZH[arm], ' | '.join(cells)))
    P('')

    # 2. 两臂配对差
    P('## 2. 与基线 U0 的配对差（同一局面两臂成对，差 = 该臂 − U0）\n')
    P('| 臂 | 中国象棋 Δ命中率 | 中国象棋 Δp(正解) | 国际象棋 Δ命中率 | 国际象棋 Δp(正解) | 差中差 Δp（中国象棋 − 国际象棋） |')
    P('|---|---|---|---|---|---|')
    for arm in MAIN_ARMS:
        if arm in ('U0', 'noul') or arm in SUPP_ARMS:     # 补测臂与 U0 差两个因素，只在「其他配对」和第 4c 节里比
            continue
        row = []
        dd = {}
        for g in (XQ, CH):
            if g not in ARMS[arm][0]:
                row += ['–', '–']
                continue
            base = sel(R, g, 'U0')
            rs = sel(R, g, arm)
            dh = paired(rs, base, 'hit')
            dp = paired(rs, base, 'p')
            dd[g] = dp
            row.append(fsig(boot1(dh, mean_d, 'dh' + g + arm)))
            row.append(fsig(boot1(dp, mean_d, 'dp' + g + arm)))
        if len(dd) == 2:
            row.append(fsig(boot2(dd[XQ], dd[CH], lambda a, b: mean_d(a) - mean_d(b), 'dd' + arm)))
        else:
            row.append('–')
        P('| %s | %s |' % (ARM_ZH[arm], ' | '.join(row)))
    P('')

    # 其他有意义的配对
    P('### 其他配对\n')
    P('| 对比 | 棋种 | Δ命中率 | Δp(正解) | Δ归一化排名 |')
    P('|---|---|---|---|---|')
    pairs = [('U2-nohint', 'U0-nohint', '无提示时 U2 − U0'), ('U0', 'U0-nohint', '提示效应（U0）'),
             ('U2', 'U2-nohint', '提示效应（U2）'), ('U2', 'U1', 'U2 − U1'), ('U3', 'U2', 'U3 − U2'),
             ('N3', 'N0', '原样 SAN − 去符号 SAN'), ('N0', 'U0', '原生写法 − U0'), ('coord', 'U0', '去棋子名'),
             ('en-U0', 'U0', '英文 − 中文（统一写法）'), ('en-N0', 'N0', '英文 − 中文（中文记谱）'),
             ('en-N0', 'en-U0', '英文提问下 中文记谱 − 统一写法'),
             ('U2-cells', 'U2', 'U2 下 格子表 − FEN'), ('U2-pieces', 'U2', 'U2 下 子力清单 − FEN'),
             ('U2-cells', 'cells', '格子表下 U2 − U0'), ('U2-pieces', 'pieces', '子力清单下 U2 − U0')]
    for a, b, lab in pairs:
        for g in (XQ, CH):
            ra, rb = sel(R, g, a), sel(R, g, b)
            if not ra or not rb:
                continue
            P('| %s | %s | %s | %s | %s |' % (lab, GN[g], fsig(boot1(paired(ra, rb, 'hit'), mean_d, 'oh' + a + b + g)),
                                            fsig(boot1(paired(ra, rb, 'p'), mean_d, 'op' + a + b + g)),
                                            fsig(boot1(paired(ra, rb, 'nrank'), mean_d, 'on' + a + b + g))))
    P('')

    # 3. 跨棋种
    P('## 3. 跨棋种差（中国象棋 − 国际象棋；局面不同，两组各自按聚类重抽）\n')
    P('| 臂 | 层 | Δ命中率 | Δp(正解) | Δp×n | Δ归一化排名 |')
    P('|---|---|---|---|---|---|')
    for arm in MAIN_ARMS:
        if not (XQ in ARMS[arm][0] and CH in ARMS[arm][0]):
            continue
        for st in (None, 'natural', 'textbook'):
            a, b = sel(R, XQ, arm, 0, st), sel(R, CH, arm, 0, st)
            cells = [fsig(boot2(a, b, lambda x, y, key=key: mean(x, key) - mean(y, key), 'x' + key + arm + str(st)), d)
                     for key, d in (('hit', 2), ('p', 2), ('pn', 1), ('nrank', 2))]
            P('| %s | %s | %s |' % (ARM_ZH[arm], st or '合并', ' | '.join(cells)))
    P('')

    # 4. U2 按将军着法数分档
    P('## 4. 按将军着法数 k 分档（U2 类臂在「全部将军着法里挑中杀着」相对 1/k）\n')
    P('命中/1/k = 命中率 ÷ 该档 1/k 均值（在将军着法里随机挑 = 1）；k·份额 = k × p(杀着) ÷ Σp(将军着法)（均匀分给将军着法 = 1，全压在杀着 = k）；'
      '选中将军 = 选中的着法本身是将军的比例。k = 1 时 U2 只有杀着一条带「将军」，等于给答案。\n')
    for arm in ('U2', 'U2-nohint', 'U0', 'U0-nohint', 'U1', 'U3') + SUPP_ARMS:
        P('### %s\n' % ARM_ZH[arm])
        P('| 棋种 | k 档 | 局面 | 命中 | 1/k 均值 | 命中 ÷ 1/k | k·份额 | 选中将军 |')
        P('|---|---|---:|---|---:|---|---|---:|')
        for g in (XQ, CH):
            rs = sel(R, g, arm)
            for bn in ('1', '2–3', '4–6', '7+'):
                b = [r for r in rs if bins_of(r['k_checks']) == bn]
                if not b:
                    P('| %s | %s | 0 | – | – | – | – | – |' % (GN[g], bn))
                    continue
                inv = statistics.mean(1 / r['k_checks'] for r in b)
                ratio = boot1(b, lambda s: (mean(s, 'hit') / statistics.mean(1 / r['k_checks'] for r in s)), 'rt' + arm + g + bn)
                P('| %s | %s | %d | %s | %.2f | %s | %s | %.2f |' % (
                    GN[g], bn, len(b), fhit(sum(r['hit'] for r in b), len(b)), inv, fci(ratio, 2),
                    fci(boot1(b, lambda s: mean(s, 'check_share_k'), 'ks' + arm + g + bn), 2), mean(b, 'chosen_check')))
        P('')
    P('### 重叠档（k = 2–6）上的跨棋种比较（中国象棋 − 国际象棋）\n')
    P('「分档加权」= 两档各自的差按两棋种合计局面数加权，去掉 k 分布不同的影响。\n')
    P('| 臂 | 口径 | Δ命中率 | Δ(命中 ÷ 1/k) | Δk·份额 |')
    P('|---|---|---|---|---|')

    def strat_diff(key):
        def f(a, b):
            tot, w = 0.0, 0
            for bn in ('2–3', '4–6'):
                aa = [r for r in a if bins_of(r['k_checks']) == bn]
                bb = [r for r in b if bins_of(r['k_checks']) == bn]
                if not aa or not bb:
                    return None
                ma, mb = mean(aa, key), mean(bb, key)
                if ma is None or mb is None:
                    return None
                n = len([r for r in a if bins_of(r['k_checks']) == bn]) + len(bb)
                tot += n * (ma - mb)
                w += n
            return tot / w
        return f

    def ratio_of(s):
        return mean(s, 'hit') / statistics.mean(1 / r['k_checks'] for r in s) if s else None

    for arm in ('U2', 'U2-nohint', 'U0', 'U3') + SUPP_ARMS:
        a = [r for r in sel(R, XQ, arm) if 2 <= r['k_checks'] <= 6]
        b = [r for r in sel(R, CH, arm) if 2 <= r['k_checks'] <= 6]
        for bn in ('2–3', '4–6'):
            aa = [r for r in a if bins_of(r['k_checks']) == bn]
            bb = [r for r in b if bins_of(r['k_checks']) == bn]
            P('| %s | k %s（%d vs %d） | %s | %s | %s |' % (
                ARM_ZH[arm], bn, len(aa), len(bb),
                fsig(boot2(aa, bb, lambda x, y: mean(x, 'hit') - mean(y, 'hit'), 'kh' + arm + bn)),
                fsig(boot2(aa, bb, lambda x, y: (ratio_of(x) - ratio_of(y)) if x and y else None, 'kr' + arm + bn)),
                fsig(boot2(aa, bb, lambda x, y: mean(x, 'check_share_k') - mean(y, 'check_share_k'), 'kk' + arm + bn))))
        P('| %s | 分档加权（%d vs %d） | %s | – | %s |' % (
            ARM_ZH[arm], len(a), len(b), fsig(boot2(a, b, strat_diff('hit'), 'ksh' + arm)),
            fsig(boot2(a, b, strat_diff('check_share_k'), 'ksk' + arm))))
    P('')

    # 4b. 与「在带将军标的着法里随手挑一个」这条免费基线比
    P('### 与免费基线「在将军着法里随手挑一个」比（全部 48 个局面，含 k = 1）\n')
    P('基线命中期望 = 1/k。差 = Jev 命中 − 1/k（按局面配对）；份额差 = p(杀着)/Σp(将军着法) − 1/k。U3 与「能杀就杀」基线都是 100%。\n')
    P('| 棋种 | 臂 | Jev 命中率 | 基线 1/k 均值 | 差 | 份额差 |')
    P('|---|---|---:|---:|---|---|')
    for g in (XQ, CH):
        for arm in ('U2', 'U2-nohint') + SUPP_ARMS:
            rs = sel(R, g, arm)
            items = [{'cl': r['cl'], 'd': r['hit'] - 1 / r['k_checks']} for r in rs]
            items2 = [{'cl': r['cl'], 'd': r['check_share_k'] / r['k_checks'] - 1 / r['k_checks']} for r in rs
                      if r.get('check_share_k') is not None]
            P('| %s | %s | %.2f | %.2f | %s | %s |' % (
                GN[g], ARM_ZH[arm], mean(rs, 'hit'), statistics.mean(1 / r['k_checks'] for r in rs),
                fsig(boot1(items, mean_d, 'fb' + g + arm)), fsig(boot1(items2, mean_d, 'fs' + g + arm))))
    P('')

    # 4c. 补测：盘面读清以后的 U2，与 FEN 下 U2 按局面配对
    P('### 4c. 补测：U2 换成格子表 / 子力清单（与 FEN 下 U2 按局面配对，差 = 新臂 − FEN U2）\n')
    P('「k ≥ 2」去掉只有一步将军的局面（那里 U2 等于给答案）。免费基线差 = 新臂命中 − 1/k（按局面配对）。\n')
    P('| 棋种 | 臂 | 局面范围 | 局面 | 命中（新臂） | 命中（FEN U2） | Δ命中率 | Δp(正解) | k·份额（新臂） | Δk·份额 | 免费基线差（新臂） |')
    P('|---|---|---|---:|---|---|---|---|---|---|---|')
    for g in (XQ, CH):
        for arm in SUPP_ARMS:
            for lab, cond in (('全部', lambda r: True), ('k ≥ 2', lambda r: r['k_checks'] >= 2),
                              ('k 2–6', lambda r: 2 <= r['k_checks'] <= 6)):
                ra = [r for r in sel(R, g, arm) if cond(r)]
                rb = [r for r in sel(R, g, 'U2') if cond(r)]
                if not ra or not rb:
                    continue
                fb = [{'cl': r['cl'], 'd': r['hit'] - 1 / r['k_checks']} for r in ra]
                P('| %s | %s | %s | %d | %s | %s | %s | %s | %s | %s | %s |' % (
                    GN[g], ARM_ZH[arm], lab, len(ra), fhit(sum(r['hit'] for r in ra), len(ra)),
                    fhit(sum(r['hit'] for r in rb), len(rb)),
                    fsig(boot1(paired(ra, rb, 'hit'), mean_d, 'sh' + g + arm + lab)),
                    fsig(boot1(paired(ra, rb, 'p'), mean_d, 'sp' + g + arm + lab)),
                    fci(boot1(ra, lambda s: mean(s, 'check_share_k'), 'sk' + g + arm + lab)),
                    fsig(boot1(paired(ra, rb, 'check_share_k'), mean_d, 'sd' + g + arm + lab)),
                    fsig(boot1(fb, mean_d, 'sf' + g + arm + lab))))
    P('')
    P('差中差（中国象棋的「新臂 − FEN U2」减国际象棋的；k 2–6 的局面，两组各自按聚类重抽）：\n')
    P('| 臂 | Δ命中率 差中差 | Δp(正解) 差中差 | Δk·份额 差中差 |')
    P('|---|---|---|---|')
    for arm in SUPP_ARMS:
        dd = {}
        for g in (XQ, CH):
            ra = [r for r in sel(R, g, arm) if 2 <= r['k_checks'] <= 6]
            rb = [r for r in sel(R, g, 'U2') if 2 <= r['k_checks'] <= 6]
            dd[g] = {key: paired(ra, rb, key) for key in ('hit', 'p', 'check_share_k')}
        P('| %s | %s |' % (ARM_ZH[arm], ' | '.join(
            fsig(boot2(dd[XQ][key], dd[CH][key], lambda a, b: mean_d(a) - mean_d(b), 'sdd' + arm + key))
            for key in ('hit', 'p', 'check_share_k'))))
    P('')

    # 4d. 报告第六节「标了将军以后，在将军着法里挑杀着」那张表：三种盘面各一行，逐格出数。
    # 种子沿用第 4 节「重叠档」与 4c 节同一格的名字（'ksh' / 'sk' / 'sf' + 棋种 + 臂 + 范围），同一格两处的数逐字相同；
    # FEN 行按同一规则取名。
    K2 = 'k ≥ 2'
    P('### 4d. 报告第六节的 k·份额表（FEN / 格子表 / 子力清单）\n')
    P('k·份额与「与随手挑的命中差」只取 k ≥ 2 的局面（k = 1 时 U2 只有杀着一条带「将军」，等于给答案）；命中差 = 命中 − 1/k，按局面配对。'
      '两种棋命中率差取重叠档 k 2–6、按档加权，同上面「重叠档」表。格子表、子力清单两行与第 4、4c 节同一格逐字相同。'
      '±半宽 = 两种棋命中率差区间宽度的一半。\n')
    P('| 盘面 | 局面（k ≥ 2 中/国；k 2–6 中/国） | 中国象棋 k·份额（k ≥ 2） | 与随手挑的命中差（中国象棋，k ≥ 2） | 两种棋命中率差（k 2–6，按档加权） | ±半宽 | 国际象棋 k·份额（k ≥ 2） |')
    P('|---|---|---|---|---|---:|---|')
    for arm, lab in (('U2', 'FEN'), ('U2-cells', '格子表'), ('U2-pieces', '子力清单')):
        xa = [r for r in sel(R, XQ, arm) if r['k_checks'] >= 2]
        ca = [r for r in sel(R, CH, arm) if r['k_checks'] >= 2]
        fb = [{'cl': r['cl'], 'd': r['hit'] - 1 / r['k_checks']} for r in xa]
        a = [r for r in sel(R, XQ, arm) if 2 <= r['k_checks'] <= 6]
        b = [r for r in sel(R, CH, arm) if 2 <= r['k_checks'] <= 6]
        xd = boot2(a, b, strat_diff('hit'), 'ksh' + arm)
        P('| %s | %d/%d；%d/%d | %s | %s | %s | %.2f | %s |' % (
            lab, len(xa), len(ca), len(a), len(b),
            fci(boot1(xa, lambda s: mean(s, 'check_share_k'), 'sk' + XQ + arm + K2)),
            fsig(boot1(fb, mean_d, 'sf' + XQ + arm + K2)),
            fsig(xd), (xd[2] - xd[1]) / 2,
            fci(boot1(ca, lambda s: mean(s, 'check_share_k'), 'sk' + CH + arm + K2))))
    P('')

    # 5. U1 按杀着是否吃子；按杀着棋子
    P('## 5. 按杀着是否吃子分层（U0 / U1 / U2）\n')
    P('| 棋种 | 杀着吃子 | 局面 | U0 命中 | U1 命中 | U2 命中 | U1 − U0 Δp(正解) |')
    P('|---|---|---:|---|---|---|---|')
    for g in (XQ, CH):
        for mc in (True, False):
            rs = {a: [r for r in sel(R, g, a) if r['mate_capture'] == mc] for a in ('U0', 'U1', 'U2')}
            P('| %s | %s | %d | %s | %s | %s | %s |' % (
                GN[g], '是' if mc else '否', len(rs['U0']),
                *[fhit(sum(r['hit'] for r in rs[a]), len(rs[a])) for a in ('U0', 'U1', 'U2')],
                fsig(boot1(paired(rs['U1'], rs['U0'], 'p'), mean_d, 'mc' + g + str(mc)))))
    P('')
    P('### 按杀着棋子（命中数/局面数）\n')
    arms_p = ['U0', 'U1', 'U2', 'U3', 'coord', 'N0', 'cells', 'noul'] + list(SUPP_ARMS)
    P('| 棋种 | 杀着棋子 | 局面 | ' + ' | '.join(ARM_ZH[a] for a in arms_p) + ' |')
    P('|---|---|---:|' + '---|' * len(arms_p))
    for g in (XQ, CH):
        pcs = Counter(r['mate_piece'] for r in sel(R, g, 'U0'))
        for pc, n in pcs.most_common():
            cells = []
            for a in arms_p:
                rs = [r for r in sel(R, g, a) if r['mate_piece'] == pc]
                cells.append('%g/%d' % (sum(r['hit'] for r in rs), len(rs)) if rs else '–')
            P('| %s | %s | %d | %s |' % (GN[g], B.piece_name(g, pc) if g == CH else B.piece_name(g, pc), n, ' | '.join(cells)))
    P('')

    # 6. 逐步是非
    P('## 6. 逐步是非（noul，每步一题，一次请求问完）\n')
    P('命中 = 杀着的 noul 值最高（并列按份额计）；p×n 这里是 p(杀着) ÷ Σp × 候选数。\n')
    P('| 棋种 | 层 | 命中 [Wilson] | p(杀着) | 其余着法最大值 | 其余着法均值 | 归一化排名 | p×n（份额） |')
    P('|---|---|---|---|---|---|---|---|')
    for g in (XQ, CH):
        for st in (None, 'natural', 'textbook'):
            rs = sel(R, g, 'noul', 0, st)
            for r in rs:
                others = [v for m, v in r['probs'].items() if m != r['answer']]
                r['omax'] = max(others)
                r['omean'] = sum(others) / len(others)
            P('| %s | %s | %s | %s | %s | %s | %s | %s |' % (
                GN[g], st or '合并', fhit(sum(r['hit'] for r in rs), len(rs)),
                fci(boot1(rs, lambda s: mean(s, 'p'), 'np' + g + str(st))),
                fci(boot1(rs, lambda s: mean(s, 'omax'), 'no' + g + str(st))),
                fci(boot1(rs, lambda s: mean(s, 'omean'), 'nm' + g + str(st))),
                fci(boot1(rs, lambda s: mean(s, 'nrank'), 'nn' + g + str(st))),
                fci(boot1(rs, lambda s: mean(s, 'pn'), 'nq' + g + str(st)), 1)))
    P('')
    P('noul 与 choice（U0）配对：Δ归一化排名（noul − U0）')
    for g in (XQ, CH):
        P('- %s：%s' % (GN[g], fsig(boot1(paired(sel(R, g, 'noul'), sel(R, g, 'U0'), 'nrank'), mean_d, 'nvu' + g))))
    P('')

    # 7. 选中着法的性质（旁证：它读没读出将军 / 吃子关系）
    P('## 7. 它把概率放在哪类着法上（旁证 H2/H3：有没有从盘面读出将军、吃子关系）\n')
    P('将军质量 = Σp(将军着法)，对照 k/n（均匀）；吃子质量 = Σp(吃子着法)，对照 吃子数/n。「选中将军」「选中吃子」是选中项的性质。\n')
    P('| 棋种 | 臂 | 将军质量 | k/n | 选中将军 | 吃子质量 | 吃子数/n | 选中吃子 |')
    P('|---|---|---|---:|---:|---|---:|---:|')
    for g in (XQ, CH):
        for arm in ('U0', 'U0-nohint', 'coord', 'N0', 'cells', 'pieces', 'board', 'en-U0', 'noul', 'U1', 'U2') + SUPP_ARMS:
            rs = sel(R, g, arm)
            if not rs:
                continue
            if arm == 'noul':
                for r in rs:
                    tot = sum(r['probs'].values())
                    fx = fxs_of(g, [p for p in data()['positions'] if p['id'] == r['pid']][0]['fen'])
                    r['check_mass_n'] = sum(v for m, v in r['probs'].items() if fx[m]['check']) / tot if tot else None
                    r['cap_mass_n'] = sum(v for m, v in r['probs'].items() if fx[m]['captured']) / tot if tot else None
                cm, pm = 'check_mass_n', 'cap_mass_n'
            else:
                cm, pm = 'check_mass', 'cap_mass'
            P('| %s | %s | %s | %.2f | %.2f | %s | %.2f | %.2f |' % (
                GN[g], ARM_ZH[arm], fci(boot1(rs, lambda s: mean(s, cm), 'cm' + g + arm)), mean(rs, 'check_base'),
                mean(rs, 'chosen_check'), fci(boot1(rs, lambda s: mean(s, pm), 'pm' + g + arm)), mean(rs, 'cap_base'),
                mean(rs, 'chosen_cap')))
    P('')

    # 8. 抖动
    P('## 8. 抖动（10 个局面 × U0 × 3 次；换 rep 同时换键↔着法映射与选项顺序，描述与 state 不变）\n')
    P('| 棋种 | 局面 | 三次 p(正解) | 极差 | 三次选中项相同 | 全部选项概率最大绝对差 | 命中 |')
    P('|---|---|---|---:|---|---:|---|')
    jsum = {}
    for g in (XQ, CH):
        rngs, same, maxd = [], 0, []
        for pid in jitter_ids(g):
            rs = [r for r in R if r['game'] == g and r['arm'] == 'U0' and r['pid'] == pid]
            rs.sort(key=lambda r: r['rep'])
            if len(rs) < 3:
                P('| %s | %s | 缺 | | | | |' % (GN[g], pid))
                continue
            ps = [r['p'] for r in rs]
            rg = max(ps) - min(ps)
            sm = len(set(r['chosen'] for r in rs)) == 1
            md = max(max(r['probs'][m] for r in rs) - min(r['probs'][m] for r in rs) for m in rs[0]['probs'])
            rngs.append(rg)
            same += sm
            maxd.append(md)
            P('| %s | %s | %s | %.2f | %s | %.2f | %s |' % (GN[g], pid, ' / '.join('%.2f' % x for x in ps), rg,
                                                          '是' if sm else '否', md, ''.join('✓' if r['hit'] else '✗' for r in rs)))
        if rngs:
            jsum[g] = (statistics.median(rngs), max(rngs), same, len(rngs), statistics.median(maxd), max(maxd))
    for g, (m, mx, s, n, mm, mmx) in jsum.items():
        P('\n%s：p(正解) 三次极差中位 %.2f、最大 %.2f；选中项三次相同 %d/%d；全部选项概率的最大绝对差中位 %.2f、最大 %.2f' % (GN[g], m, mx, s, n, mm, mmx))
    P('')

    # 9. 旧格式复现
    P('## 9. 旧格式复现（初探原格式：坐标键 + state 带合法着法清单）\n')
    P('| 棋种 | 局面 | 臂 | 有效题？ | 命中 | p(正解) 各次 | 选中 | 备注 |')
    P('|---|---|---|---|---|---|---|---|')
    leg = [r for r in R if r['arm'].startswith('old-')]
    groups = defaultdict(list)
    for r in leg:
        groups[(r['game'], r['pid'], r['arm'])].append(r)
    for (g, pid, arm), rs in sorted(groups.items()):
        rs.sort(key=lambda r: r['rep'])
        valid = rs[0]['legacy_ok']
        note = '；'.join(rs[0]['issues']) if rs[0]['issues'] else ''
        P('| %s | %s | %s | %s | %g/%d | %s | %s | %s |' % (
            GN[g], pid, arm, '是' if valid else '否', sum(r['hit'] for r in rs), len(rs),
            ' / '.join('%.2f' % r['p'] for r in rs), ' '.join(r['chosen'] for r in rs), note))
    for g in (XQ, CH):
        rs = [r for r in leg if r['game'] == g]
        v = [r for r in rs if r['legacy_ok']]
        P('\n%s 旧格式：全部 %g/%d；有效题 %g/%d；无效题 %g/%d' % (
            GN[g], sum(r['hit'] for r in rs), len(rs), sum(r['hit'] for r in v), len(v),
            sum(r['hit'] for r in rs if not r['legacy_ok']), len(rs) - len(v)))
    xr = [r for r in leg if r['game'] == XQ]
    for r in xr:
        pass
    P('\n中国象棋旧格式里，选中项是 cchess 认为的杀着（对无效题即旧脚本当时的「正解」）但 pyffish 不认的情况：%d 次' % sum(
        1 for r in xr if r['chosen'] in (r['cchess_mates'] or []) and r['chosen'] != r['answer']))
    P('')

    text = '\n'.join(lines)
    if out:
        with open(out, 'w', encoding='utf-8') as f:
            f.write(text + '\n')
        print('写入', out)
    else:
        print(text)


if __name__ == '__main__':
    args = [a for a in sys.argv[1:] if not a.startswith('--')]

    def opt(name, default=None, cast=str):
        if name in sys.argv:
            return cast(sys.argv[sys.argv.index(name) + 1])
        return default
    if args[:1] == ['run']:
        run(dry='--dry' in sys.argv, limit=opt('--limit', None, int), workers=opt('--workers', 6, int))
    elif args[:1] == ['report']:
        report(out=opt('--out'), path=opt('--log'), nocheck='--nocheck' in sys.argv)
    else:
        raise SystemExit(__doc__)
