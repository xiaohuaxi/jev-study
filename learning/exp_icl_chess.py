"""国际象棋小探针：state 里附上"之前在这个局面犯过的错"，Jev 会不会改正？堆很多别处的错误记录呢？

局面：games/chess/exp_game_chess_prompt.py 的 B 组里，原问法两次中至少一次送子（比两层物质搜索最好一步差 2 分
及以上、且走完自己比走之前少 2 分以上）的局面，共 38 个；"犯过的错"就是它当时送子的那步。
请求沿用 games/chess/exp_game_chess.py 的 ask()：选项键 UCI、描述 SAN（带 #、+、x）、state 放 FEN、行棋方、
合法着法清单；本实验另加一个 past_experience 字段，问题末尾统一加一句"state 里的 past_experience
是你以前下棋的记录（如果有），可以参考"，所有写法同一问句。

写法（每个局面每种问 2 次）：
  base        不给记录
  rec1        同一局面的一条记录："上次在这个局面走了 X，对方 Y 吃回，按子力净亏 k 分"
  lesson      程序归纳好的结论："这个局面走 X 是送子，别走"
  note        把上一条写进 X 这个选项的描述里（"Nxd5（上次走过：被 exd5 吃回，净亏 3）"）
  mix         rec1 再加一条同局面的好记录："走了 Z（两层搜索最好的一步），没丢子，净得 j 分"
  other10/60/250  不给本局面的记录，只给其他局面的送子记录 10 / 60 / 250 条（250 条约 2.7 万 token）
              ——"越下越有经验"最接近的形态，也是上下文容量的直接检验
  buried      rec1 夹在 250 条其他记录中间

指标：重走记录里那步的比例、送子率、平均比最好一步差几分、选中最好一步的比例。

用法：python3 exp_icl_chess.py run | report   结果写 icl_chess_log.json，断点续跑
需要 python-chess（python3 -m pip install chess）；还要先跑过 games/chess/exp_game_chess_prompt.py，
本脚本从那个脚本写在 games/chess/ 下的 game_chess_prompt_log.json 里挑局面，也载入 games/chess/exp_game_chess.py。
"""
# 让本脚本从任意目录都能找到仓库根部的 jevkit.py 和同目录的其他 exp_icl_*.py
import sys as _sys, pathlib as _pathlib
_sys.path[:0] = [str(_pathlib.Path(__file__).resolve().parent), str(_pathlib.Path(__file__).resolve().parent.parent)]
import json, os, random, statistics, sys, threading
from concurrent.futures import ThreadPoolExecutor
try:
    import chess
except ImportError as e:
    raise SystemExit('缺少 Python 库 %s。先装好：\n    python3 -m pip install chess' % e.name)

HERE = os.path.dirname(os.path.abspath(__file__))
LOG = os.path.join(HERE, 'icl_chess_log.json')
CHESS_DIR = os.path.join(os.path.dirname(HERE), 'games', 'chess')   # 国际象棋实测脚本与它的日志所在目录
SRC = os.path.join(CHESS_DIR, 'game_chess_prompt_log.json')
LOCK = threading.Lock()
REPS = 2
CONDS = ['base', 'rec1', 'lesson', 'note', 'mix', 'other10', 'other60', 'other250', 'buried']
TAIL = 'state 里的 past_experience 是你以前下棋的记录（如果有），可以参考。'


def load_chess():
    p = os.path.join(CHESS_DIR, 'exp_game_chess.py')
    src = open(p, encoding='utf-8').read().rstrip()
    assert src.endswith('\nmain()')
    ns = {'__file__': p, '__name__': 'exp_game_chess'}
    exec(compile(src[:-len('main()')], p, 'exec'), ns)   # 只定义函数，不跑它的 main
    return ns


NS = load_chess()
best_material, material = NS['best_material'], NS['material']


def scores(b):
    return {m.uci(): s for m, s in best_material(b).items()}


def refute(b, uci):
    """走 uci 后对方最狠的回应（按子力），返回 (对方着法 SAN, 净亏分)。"""
    me = b.turn
    before = material(b, me)
    b2 = b.copy(); b2.push_uci(uci)
    worst, wm = None, None
    for r in b2.legal_moves:
        b2.push(r); v = material(b2, me); b2.pop()
        if worst is None or v < worst:
            worst, wm = v, r
    return b2.san(wm), before - worst


def record(fen, uci, good=False):
    b = chess.Board(fen)
    san = b.san(chess.Move.from_uci(uci))
    side = '白' if b.turn else '黑'
    rep, loss = refute(b, uci)
    if good:
        return '局面 %s（执%s）：你走了 %s，对方最好的应对是 %s，按子力你净%s %d 分。这步不错。' % (
            fen, side, san, rep, '得' if loss <= 0 else '亏', abs(loss))
    return '局面 %s（执%s）：你走了 %s，对方接着 %s 吃回，按子力你净亏 %d 分。这步是送子。' % (fen, side, san, rep, loss)


def hang_positions():
    if not os.path.exists(SRC):
        raise SystemExit('找不到 %s。\n这份局面来自国际象棋问法实测，先跑一遍：python3 games/chess/exp_game_chess_prompt.py'
                         '（在仓库根目录下）' % SRC)
    d = json.load(open(SRC))
    bp = d['blun_pos']
    out = {}
    for (g, i, v, k), r in d['res']:
        if g != 'B' or v != '原问法' or 'answers' not in r or i in out:
            continue
        b = chess.Board(bp[i]); c = r['answers']['move']['choice']; sc = scores(b)
        if max(sc.values()) - sc[c] >= 2 and sc[c] <= material(b, b.turn) - 2:
            out[i] = c
    return [(bp[i], out[i]) for i in sorted(out)]


def filler_pool(exclude, n=400):
    """随机对局里找送子着法当"其他局面的记录"，固定种子。"""
    rng = random.Random(20260924)
    pool = []
    while len(pool) < n:
        b = chess.Board()
        for _ in range(rng.randint(8, 50)):
            if b.is_game_over():
                break
            b.push(rng.choice(list(b.legal_moves)))
        if b.is_game_over() or b.fen() in exclude:
            continue
        sc = scores(b)
        hangs = [u for u, s in sc.items() if s <= material(b, b.turn) - 2 and s < 900]
        if hangs:
            pool.append(record(b.fen(), rng.choice(sorted(hangs))))
    return pool


def build(fen, bad, cond, pool, rep):
    b = chess.Board(fen)
    crit = {m.uci(): b.san(m) for m in b.legal_moves}
    st = {'fen': fen, 'side_to_move': 'white' if b.turn else 'black', 'legal_moves_uci': sorted(crit)}
    sc = scores(b)
    best = max(sc, key=lambda u: (sc[u], u))
    rng = random.Random('%s|%s|%d' % (fen, cond, rep))
    exp = None
    if cond == 'rec1':
        exp = [record(fen, bad)]
    elif cond == 'lesson':
        exp = ['经验：在局面 %s 里，%s 是送子，别走。' % (fen, b.san(chess.Move.from_uci(bad)))]
    elif cond == 'note':
        rp, loss = refute(b, bad)
        crit[bad] = '%s（上次走过：被 %s 吃回，净亏 %d 分）' % (crit[bad], rp, loss)
    elif cond == 'mix':
        exp = [record(fen, bad), record(fen, best, good=True)]
        rng.shuffle(exp)
    elif cond.startswith('other'):
        exp = rng.sample(pool, int(cond[5:]))
    elif cond == 'buried':
        exp = rng.sample(pool, 250)
        exp.insert(125, record(fen, bad))
    if exp:
        st['past_experience'] = '\n'.join(exp)
    q = {'move': {'type': 'choice', 'instructions': '你在下国际象棋，执%s。从合法着法里选一步最好的。%s' % (
        '白' if b.turn else '黑', TAIL), 'criteria': crit}}
    return st, q


def run():
    import jevkit as jev
    pos = hang_positions()
    pool = filler_pool({f for f, _ in pos})
    log = json.load(open(LOG)) if os.path.exists(LOG) else {}
    jobs = [(i, c, r) for i in range(len(pos)) for c in CONDS for r in range(REPS)]
    todo = [j for j in jobs if '%d|%s|%d' % j not in log or '_error' in log['%d|%s|%d' % j]]
    print('局面 %d 个，共 %d 题，待发 %d' % (len(pos), len(jobs), len(todo)))

    def one(j):
        i, c, r = j
        st, q = build(pos[i][0], pos[i][1], c, pool, r)
        resp = jev.call(st, q)
        with LOCK:
            log['%d|%s|%d' % j] = resp
    with ThreadPoolExecutor(max_workers=8) as ex:
        list(ex.map(one, todo))
    json.dump(log, open(LOG, 'w'), ensure_ascii=False)
    print(jev.spend())


def report():
    pos = hang_positions()
    log = json.load(open(LOG))
    print('局面 %d 个 × 每种写法 %d 次；失败 %d' % (len(pos), REPS, sum('_error' in v for v in log.values())))
    print('%-9s %-9s %-9s %-9s %-10s %-9s %s' % ('写法', '重走错步', '送子', '选中最好', '平均差几分', '置信中位', '输入token中位'))
    for c in CONDS:
        rep = hang = hit = 0; loss, conf, tok = [], [], []; n = 0
        for i, (fen, bad) in enumerate(pos):
            b = chess.Board(fen); sc = scores(b); top = max(sc.values())
            for r in range(REPS):
                v = log.get('%d|%s|%d' % (i, c, r))
                if not v or '_error' in v:
                    continue
                a = v['answers']['move']; ch = a['choice']; n += 1
                rep += ch == bad
                d = top - sc[ch]
                hang += d >= 2 and sc[ch] <= material(b, b.turn) - 2
                hit += sc[ch] == top
                loss.append(min(d, 20)); conf.append(a.get('confidence') or 0); tok.append(v['usage']['input_tokens'])
        print('%-9s %-9s %-9s %-9s %-10.2f %-9.2f %d' % (c, '%d/%d' % (rep, n), '%d/%d' % (hang, n), '%d/%d' % (hit, n),
                                                    statistics.mean(loss), statistics.median(conf), statistics.median(tok)))
    print('（平均差几分把将杀的 999 截到 20）')


if __name__ == '__main__':
    if len(sys.argv) < 2 or sys.argv[1] not in ('run', 'report'):
        print(__doc__)
    elif sys.argv[1] == 'run':
        run(); report()
    else:
        report()
