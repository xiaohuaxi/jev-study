"""生成中国象棋实测的三套局面集（中国象棋、国际象棋各一份），写入 xiangqi_positions.json。不调 Jev、不花钱。

用法：
  python make_positions.py build [--workers N]   重新生成（固定种子，可复现；8 进程约十几分钟）
  python make_positions.py report                只读 JSON，打印两棋种局面特征的分布对比，标出明显不对齐的地方

依赖同 boards.py（pyffish、cchess、python-chess、Fairy-Stockfish 14.0.1）。

三套局面。每个局面都「轮到红 / 白走、起始未被将」，入库前逐个过 boards.verify_position（与 selftest 同一套断言）：
  mate    一步杀，分三层：
            natural   自对弈里出现的「恰好一步能将死」局面，每棋种 40，每局至多取 2 个；
            textbook  教科书杀型，每棋种 8（下面 BOOK），都是该杀型的典型摆法，另加少量无关子与一两步不成杀的将军；
            legacy    初探用过的旧局面：中国象棋 games/exp_game_xiangqi.py 的 6 个，国际象棋 games/exp_game_chess.py 的 5 个。
          中国象棋另要求没有一步困毙（困毙也判胜，会让答案不唯一）；引擎要在固定深度找到这步杀。
  middle  实战中局：自对弈第 20–60 半回合、子力 ≥20（含将帅）、没有一步杀、引擎评估在 ±300 厘兵内，每棋种 30，每局至多 1 个。
  gain    一步得子：恰好一步按两层物质净得 ≥GAIN_MIN（中国象棋 4 = 一马 / 一炮，国际象棋 3 = 一个轻子），
          其余着法净得都 ≤1；同一局面至少有一步「吃了会被吃回、净亏」的诱饵吃子；没有一步杀；
          引擎也认可这步得子（它在 score_moves 口径下的损失 ≤GAIN_MAX_LOSS 厘兵）。每棋种 30，每局至多 2 个。
  middle 和 gain 都不许有强制杀（修订 1）：整体搜索报 N 步杀、或逐步分数的最高分是杀棋分的局面淘汰，
  gain 另要求得子着自己的分数不是杀棋分——杀棋分不当普通厘兵去和损失阈值比。
自对弈：每步以 15% 概率走纯随机着，否则让引擎按 1–4 层（随机）搜 MultiPV 3、在前三名里随机挑；最多 150 半回合。
所有随机都由 boards.seed_of 按（棋种, 局序号, 用途）固定种子；引擎每次搜索前重建线程并清空置换表，所以整个生成可复现
（同一台机器、同一版本连跑两次，JSON 逐字节相同）。入库局面的 FEN 计数一律重置为 '0 1'（原因见 boards.reset_clock）。
"""
import json, os, random, statistics, sys, time
from multiprocessing import Pool
import boards as B

XQ, CH = B.XQ, B.CH
PREFIX = {XQ: 'xq', CH: 'ch'}
PLAY = {'max_plies': 150, 'p_random': 0.15, 'depths': (1, 2, 3, 4), 'top_k': 3}
QUOTA = {'mate': 40, 'middle': 30, 'gain': 30}
PER_GAME = {'mate': 2, 'middle': 1, 'gain': 2}
MIDDLE = {'ply': (20, 60), 'pieces': 20, 'max_cp': 300}
GAIN_MIN = {XQ: 4, CH: 3}
GAIN_MAX_OTHER = 1
GAIN_MAX_LOSS = 150
MAX_GAMES = 3000

# 初探的旧局面（原样照抄，FEN 是 cchess 的短写法）
LEGACY = {
    XQ: [('初探随机局面 1', '9/9/4ka3/2C4R1/9/8N/9/3K5/7c1/9 w', 'h6e6'),
         ('初探随机局面 2', '3cak3/9/8C/3R5/9/9/3N5/9/9/4K4 w', 'd6f6'),
         ('初探随机局面 3', '2N6/5a3/5k3/9/9/9/9/1c1K3C1/9/2R6 w', 'c0c7'),
         ('初探随机局面 4', '5k3/5a3/9/9/9/9/9/2R6/3c3CN/4K4 w', 'h1f1'),
         ('初探教科书 双车错', '4k4/R8/8R/9/9/9/9/9/9/3K5 w', 'i7i9'),
         ('初探教科书 马后炮', '4k4/9/9/9/5N3/4C4/9/9/9/3K5 w', 'f5e7')],
    CH: [('初探 1', '6k1/5ppp/8/8/8/8/8/R5K1 w - - 0 1', 'a1a8'),
         ('初探 2', '3r3k/6pp/8/8/8/8/5PPP/3R2K1 w - - 0 1', 'd1d8'),
         ('初探 3', 'q5k1/5ppp/8/8/8/8/5PPP/R5K1 w - - 0 1', 'a1a8'),
         ('初探 4', 'k7/8/1K6/8/8/8/8/7R w - - 0 1', 'h1h8'),
         ('初探 5', '6k1/4Rppp/8/8/8/8/5PPP/6K1 w - - 0 1', 'e7e8')],
}

# 教科书杀型。中国象棋用 {格: 子} 摆（大写红方），国际象棋直接给 FEN。每个都附一句杀法说明（供报告与核对）。
BOOK = {
    XQ: [
        ('双车错', {'d9': 'k', 'f9': 'a', 'f7': 'a', 'c9': 'b', 'g9': 'b', 'a6': 'p', 'i6': 'p', 'h7': 'c',
                 'e3': 'R', 'b4': 'R', 'f0': 'K', 'a3': 'P', 'g3': 'P', 'c0': 'B'}, 'b4d4',
         '一车在 e 线封住将的横向出路，另一车平到 d 线将军，两车一横一纵交错成杀'),
        ('马后炮', {'e9': 'k', 'a7': 'b', 'i7': 'b', 'a6': 'p', 'c6': 'p', 'i6': 'p', 'h9': 'r',
                 'e7': 'N', 'b2': 'C', 'f0': 'K', 'e1': 'A', 'a3': 'P', 'i3': 'P', 'g0': 'B'}, 'b2e2',
         'e7 马控住 d9、f9，炮平到马后面的 e2，以马为炮架将军'),
        ('重炮', {'e9': 'k', 'd9': 'a', 'f9': 'a', 'c9': 'b', 'g9': 'b', 'a6': 'p', 'i6': 'p', 'b9': 'r',
                'e5': 'C', 'b3': 'C', 'b6': 'N', 'd0': 'K', 'a3': 'P', 'i3': 'P', 'g0': 'B', 'f0': 'A'}, 'b3e3',
         '前炮在 e5，后炮平到 e3，两炮与将同线，垫士垫象都挡不住'),
        ('卧槽马', {'e9': 'k', 'd9': 'a', 'f9': 'a', 'c9': 'b', 'g9': 'b', 'a6': 'p', 'g6': 'p', 'i6': 'p', 'b2': 'c',
                 'h6': 'N', 'a8': 'R', 'd0': 'K', 'e1': 'A', 'c3': 'P', 'i3': 'P', 'g0': 'B'}, 'h6g8',
         '马跳到黑方二路横线与三路纵线的交叉点 g8 将军，双士未动堵住两侧，a8 车封住 e8'),
        ('铁门栓', {'e9': 'k', 'e8': 'a', 'f9': 'a', 'e7': 'b', 'g9': 'b', 'a6': 'p', 'c6': 'p', 'i6': 'p', 'h9': 'r',
                 'e3': 'C', 'd3': 'R', 'f8': 'P', 'd0': 'K', 'a3': 'P', 'i3': 'P', 'g0': 'B', 'f0': 'A'}, 'd3d9',
         '中炮镇住中路的象、士（士一离开就露将），帅占 d 线助攻，车沉到 d9 将军'),
        ('闷宫', {'e9': 'k', 'e8': 'a', 'f9': 'a', 'c9': 'b', 'a6': 'p', 'c6': 'p', 'i6': 'p', 'a9': 'r',
                'h4': 'C', 'd2': 'R', 'e0': 'K', 'a3': 'P', 'g3': 'P', 'g0': 'B', 'f0': 'A'}, 'h4h9',
         '将在原位，被底士 f9 与中心士 e8 堵住；炮沉底到 h9 以 f9 士为炮架将军，d 线车封住 d9'),
        ('白脸将', {'d9': 'k', 'f9': 'a', 'f7': 'a', 'c9': 'b', 'g9': 'b', 'a6': 'p', 'i6': 'p', 'h7': 'c',
                 'a4': 'R', 'g6': 'N', 'e0': 'K', 'c3': 'P', 'g3': 'P', 'g0': 'B', 'd0': 'A'}, 'a4d4',
         '帅占中路 e 线，将不能平到 e9（会与帅照面）；车平 d 线将军'),
        ('大胆穿心', {'e9': 'k', 'e8': 'a', 'd9': 'a', 'c5': 'b', 'g9': 'b', 'a6': 'p', 'c6': 'p', 'i6': 'p', 'b2': 'c',
                  'e3': 'R', 'a9': 'R', 'g7': 'N', 'f0': 'K', 'a3': 'P', 'i3': 'P', 'c0': 'B'}, 'e3e8',
         '车硬吃中心士 e8 将军：g7 马保护车并控住 f9，d9 士被 a9 车牵制不能回吃'),
    ],
    CH: [
        ('闷杀（smothered mate）', '6rk/6pp/8/6N1/7N/8/PPP5/1K6 w - - 0 1', 'g5f7', '马跳 f7 将军，王被自己的车和兵围死'),
        ('阿纳斯塔西亚杀（Anastasia）', '5r2/4Nppk/8/8/4N3/3R4/PP6/K7 w - - 0 1', 'd3h3', 'e7 马封住 g8、g6，车到 h 线将军'),
        ('阿拉伯杀（Arabian）', '7k/1R6/5N2/8/8/8/PP6/6K1 w - - 0 1', 'b7h7', '车到 h7 将军，f6 马保护车并控住 g8'),
        ('博登杀（Boden）', '2kr4/p2p4/8/8/4NB2/3B4/PP6/6K1 w - - 0 1', 'd3a6', '两象交叉斜线，象到 a6 将军'),
        ('肩章杀（epaulette）', '3rkr2/8/8/8/2Q5/8/PP6/6K1 w - - 0 1', 'c4e6', '王两侧是自己的车，后到 e6 将军'),
        ('达米亚诺杀（Damiano）', '5rk1/5p2/6P1/7Q/8/8/PP6/6K1 w - - 0 1', 'h5h7', 'g6 兵保护，后到 h7 将军'),
        ('歌剧院杀（Opera mate）', '4k2r/5ppp/8/6B1/8/8/PP6/3R2K1 w - - 0 1', 'd1d8', '车沉底 d8 将军，g5 象保护车并控住 e7'),
        ('学者杀（Scholar）', 'r1bqkb1r/pppp1ppp/2n2n2/4p2Q/2B1P3/8/PPPP1PPP/RNB1K1NR w KQkq - 4 4', 'h5f7',
         'c4 象支持，后吃 f7 兵将死'),
    ],
}


# ---------------------------------------------------------------- 自对弈（在子进程里跑）
_ENG = None


def _init(game):
    global _ENG
    _ENG = B.Engine(game)


def selfplay(game, idx, eng):
    """一局自对弈，返回每个半回合开始时的 FEN 列表（第 0 项是开局）。"""
    rng = random.Random(B.seed_of('selfplay', game, idx))
    fen, out = B.START[game], []
    for _ in range(PLAY['max_plies']):
        out.append(fen)
        moves = B.legal(game, fen)
        if not moves:
            return out
        if rng.random() < PLAY['p_random']:
            mv = rng.choice(moves)
        else:
            mv = rng.choice(eng.top(fen, PLAY['top_k'], rng.choice(PLAY['depths'])))[0]
        fen = B.play(game, fen, mv, check=False)
    out.append(fen)
    return out


def endings(game, fen):
    """(一步杀着法, 一步困毙着法)。"""
    return B.mate_moves(game, fen), B.stalemate_moves(game, fen)


def gain_check(game, fen):
    """一步得子条件：返回 (得子着, {着法: 净得}, 诱饵列表) 或 None。先用便宜的条件筛掉大部分局面。"""
    board, _ = B.parse(game, fen)
    moves = B.legal(game, fen)
    caps = [m for m in moves if B._gain_of(game, board, m)[1][0]]          # 吃子着（含过路兵）
    best_now = max([B._gain_of(game, board, m)[0] for m in moves] or [0])  # 净得不可能超过走这一步当下的所得
    if len(caps) < 2 or best_now < GAIN_MIN[game]:
        return None
    gains = B.two_ply(game, fen)
    top = [m for m, v in gains.items() if v >= GAIN_MIN[game]]
    if len(top) != 1:
        return None
    if max(v for m, v in gains.items() if m != top[0]) > GAIN_MAX_OTHER:
        return None
    fxs = B.all_facts(game, fen)
    baits = sorted(m for m in gains if fxs[m]['captured'] and gains[m] < 0)
    if not baits:
        return None
    return top[0], gains, baits


def _scan(args):
    """子进程：下一局，找出三类候选。返回 (局序号, 半回合数, 候选列表)。"""
    game, idx = args
    fens = selfplay(game, idx, _ENG)
    cands = []
    for ply, fen in enumerate(fens):
        fen = B.reset_clock(fen)                   # 计数一律重置（原因见 boards.reset_clock）
        board, stm = B.parse(game, fen)
        if stm != 'w' or B.in_check(game, fen):
            continue
        mates, stales = endings(game, fen)
        if game == XQ and stales:
            continue
        if len(mates) == 1:
            cands.append({'set': 'mate', 'fen': fen, 'ply': ply, 'answer': mates[0]})
        if mates:
            continue
        if MIDDLE['ply'][0] <= ply <= MIDDLE['ply'][1] and len(board) >= MIDDLE['pieces']:
            cands.append({'set': 'middle', 'fen': fen, 'ply': ply})
        g = gain_check(game, fen)
        if g:
            cands.append({'set': 'gain', 'fen': fen, 'ply': ply, 'answer': g[0], 'gains': g[1], 'baits': g[2]})
    return idx, len(fens) - 1, cands


# ---------------------------------------------------------------- 入库前的核对与记录
def notation_ok(game, fen):
    """全部描述档都能无歧义写出（describe_all 内部断言两两不同、标记与档位一致）。"""
    if game == XQ and not B.cn_ok(fen):
        return False
    fxs = B.all_facts(game, fen)
    for style in B.STYLES:
        if style == 'N3' and game == XQ:
            continue
        for lang in (('zh', 'en') if style not in ('N0', 'N3') else ('zh',)):
            B.describe_all(game, fen, style, lang, fxs)
    return True


def record(game, set_, stratum, fen, eng, scores=None, **extra):
    """组装一条局面记录（特征、引擎结论都在这里算）。scores：已经算好的 score_moves，省得重算（引擎可复现，结果相同）。"""
    r = {'id': None, 'game': game, 'set': set_, 'stratum': stratum, 'fen': fen}
    r.update(extra)
    r['features'] = B.features(game, fen)
    a = eng.analyse(fen)
    r['engine'] = {'search_depth': eng.depth, 'depth': a['depth'], 'best': a['best'], 'cp': a['cp'],
                   'mate': a['mate'], 'pv': a['pv']}
    if set_ in ('middle', 'gain'):
        r['move_scores'] = scores if scores is not None else eng.score_moves(fen)
    return r


def build(workers, path=B.POSITIONS, quota=QUOTA):
    t0 = time.time()
    out, meta_games = [], {}
    for game in (XQ, CH):
        eng = B.Engine(game)
        seen, got, rej = set(), {k: [] for k in quota}, {}

        def reject(why):
            rej[why] = rej.get(why, 0) + 1

        # 1) 旧局面原样收入，问题照实记下（不强求干净）；教科书杀型必须完全干净，否则直接报错
        for name, short, ans in LEGACY[game]:
            fen = B.reset_clock(B.norm(game, short))
            iss = B.audit_mate(game, fen, ans)
            seen.add(B.key_of(fen))
            out.append(record(game, 'mate', 'legacy', fen, eng, name=name, legacy_fen=short, answer=ans,
                              legacy_ok=not iss, issues=iss))
        for name, pos, ans, note in BOOK[game]:
            fen = B.reset_clock(B.norm(game, B.board_fen(XQ, pos) + ' w') if game == XQ else B.norm(game, pos))
            assert B.audit_mate(game, fen, ans) == [], (name, fen, B.audit_mate(game, fen, ans))
            assert notation_ok(game, fen), name
            seen.add(B.key_of(fen))
            out.append(record(game, 'mate', 'textbook', fen, eng, name=name, note=note, answer=ans))

        # 2) 自对弈
        n_games = n_plies = 0
        with Pool(workers, initializer=_init, initargs=(game,)) as pool:
            for idx, plies, cands in pool.imap(_scan, [(game, i) for i in range(MAX_GAMES)], chunksize=2):
                n_games, n_plies = n_games + 1, n_plies + plies
                for set_ in quota:
                    pool_ = [c for c in cands if c['set'] == set_]
                    random.Random(B.seed_of('pick', game, idx, set_)).shuffle(pool_)
                    taken = 0
                    for c in pool_:
                        if len(got[set_]) >= quota[set_] or taken >= PER_GAME[set_]:
                            break
                        k = B.key_of(c['fen'])
                        if k in seen:
                            reject('重复局面')
                            continue
                        bad = B.crosscheck(game, c['fen'])
                        assert not bad, ('两库不一致，必须查明', game, c['fen'], bad[:3])
                        assert not B.placement_issues(game, c['fen']), ('自对弈局面不可能摆法有问题', c['fen'])
                        if not notation_ok(game, c['fen']):
                            reject('中文记谱有歧义（多路兵 / 三子同线）')
                            continue
                        if set_ == 'mate':
                            a = eng.analyse(c['fen'])
                            if not (a['best'] == c['answer'] and a['mate'] == 1):
                                reject('引擎没找到一步杀')
                                continue
                        elif set_ == 'middle':
                            a = eng.analyse(c['fen'])
                            if a['mate'] is not None:
                                reject('中局有强制杀')
                                continue
                            if abs(a['cp']) > MIDDLE['max_cp']:
                                reject('中局评估超出 ±%d' % MIDDLE['max_cp'])
                                continue
                            scores = eng.score_moves(c['fen'])
                            if B.is_mate_score(max(scores.values())):
                                reject('中局逐步分数的最高分是杀棋分')
                                continue
                        else:
                            # 杀棋分不当普通厘兵用：有强制杀（整体搜索报 N 步杀，或逐步分数的最高分 / 得子着是杀棋分）
                            # 的局面直接淘汰，不拿「3 步杀 vs 2 步杀只差 1 厘兵」去和损失阈值比
                            a = eng.analyse(c['fen'])
                            scores = eng.score_moves(c['fen'])
                            if a['mate'] is not None or B.is_mate_score(max(scores.values())) \
                                    or B.is_mate_score(scores[c['answer']]):
                                reject('得子局面有强制杀')
                                continue
                            if B.losses(scores)[c['answer']] > GAIN_MAX_LOSS:
                                reject('引擎不认可这步得子（损失 >%d）' % GAIN_MAX_LOSS)
                                continue
                        seen.add(k)
                        taken += 1
                        extra = {'answer': c['answer']} if set_ != 'middle' else {}
                        if set_ == 'gain':
                            extra.update(gains=c['gains'], baits=c['baits'],
                                         rule={'min_gain': GAIN_MIN[game], 'max_other': GAIN_MAX_OTHER,
                                               'max_engine_loss': GAIN_MAX_LOSS})
                        got[set_].append(record(game, set_, 'natural' if set_ == 'mate' else 'selfplay', c['fen'], eng,
                                                scores=scores if set_ != 'mate' else None,
                                                source={'selfplay': idx, 'ply': c['ply']}, **extra))
                if n_games % 50 == 0:
                    print('  %s 已下 %d 局：%s  (%.0fs)' % (game, n_games, {k: len(v) for k, v in got.items()},
                                                          time.time() - t0), flush=True)
                if all(len(got[k]) >= quota[k] for k in quota):
                    pool.terminate()
                    break
        eng.close()
        for set_ in ('mate', 'middle', 'gain'):
            out.extend(got[set_])
        meta_games[game] = {'selfplay_games': n_games, 'selfplay_plies': n_plies, 'rejected': rej,
                            'got': {k: len(v) for k, v in got.items()}}
        print('%s：自对弈 %d 局，%s，淘汰 %s' % (game, n_games, meta_games[game]['got'], rej), flush=True)

    # 编号
    for game in (XQ, CH):
        for set_, stratum, tag in (('mate', 'natural', 'mate-nat'), ('mate', 'textbook', 'mate-book'),
                                   ('mate', 'legacy', 'mate-old'), ('middle', 'selfplay', 'mid'),
                                   ('gain', 'selfplay', 'gain')):
            rows = [r for r in out if r['game'] == game and r['set'] == set_ and r['stratum'] == stratum]
            for i, r in enumerate(rows, 1):
                r['id'] = '%s-%s-%02d' % (PREFIX[game], tag, i)
    order = {'mate': 0, 'middle': 1, 'gain': 2}
    strat = {'natural': 0, 'textbook': 1, 'legacy': 2, 'selfplay': 3}
    out.sort(key=lambda r: (r['game'] != XQ, order[r['set']], strat[r['stratum']], r['id']))

    # 入库前再过一遍与 selftest 相同的复核
    engs = {g: B.Engine(g) for g in (XQ, CH)}
    try:
        for r in out:
            B.verify_position(r, engs, slow=False)
    finally:
        for e in engs.values():
            e.close()

    with B.Engine(XQ) as e:
        eng_id = e.id
    meta = {
        'generated_by': 'make_positions.py build',
        'versions': {'pyffish': '.'.join(map(str, B.sf.version())), 'cchess': _ver('cchess'), 'chess': _ver('chess'),
                     'engine': eng_id},
        'engine': {'depth': B.DEPTH, 'threads': 1, 'hash_mb': B.HASH_MB, 'mate_cp': B.MATE_CP,
                   'mate_bound': B.MATE_BOUND,
                   'note': 'engine = analyse()（整体搜索）；move_scores = score_moves()（每步 searchmoves 单独搜），'
                           '厘兵损失用 boards.losses(move_scores)；|cp| ≥ mate_bound 是杀棋分；'
                           'middle / gain 已排除强制杀（最高分与得子着都不是杀棋分），但个别着法的分数可能是「送杀」的负杀棋分'},
        'selfplay': PLAY, 'quota': quota, 'per_game': PER_GAME, 'middle': MIDDLE,
        'gain': {'min_gain': GAIN_MIN, 'max_other': GAIN_MAX_OTHER, 'max_engine_loss': GAIN_MAX_LOSS},
        'games': meta_games,
        'values': {'xiangqi': '车 9 马 4 炮 4.5 仕相 2 兵 1（过河 2）', 'chess': '兵 1 马 3 象 3 车 5 后 9'},
        'coords': 'ICCS（中国象棋横线 0–9，红方底线为 0）/ UCI；所有局面都是红 / 白先走',
    }
    with open(path, 'w', encoding='utf-8') as f:
        f.write('{"meta": %s,\n "positions": [\n' % json.dumps(meta, ensure_ascii=False))
        f.write(',\n'.join('  ' + json.dumps(r, ensure_ascii=False) for r in out))
        f.write('\n]}\n')
    print('写入 %s：%d 个局面，用时 %.0fs' % (path, len(out), time.time() - t0))


def _ver(mod):
    from importlib.metadata import version
    return version(mod)


# ---------------------------------------------------------------- 分布对比
FEATS = ('legal', 'checks', 'captures', 'pieces', 'escapes', 'material')


def _q(xs):
    xs = sorted(xs)
    if not xs:
        return '-'
    med = statistics.median(xs)
    q1, q3 = xs[len(xs) // 4], xs[(3 * len(xs)) // 4]
    return '%g [%g–%g] (%g–%g)' % (med, q1, q3, xs[0], xs[-1])


def report(path=B.POSITIONS):
    data = B.load_positions(path)
    P = data['positions']
    print('局面数：')
    groups = {}
    for p in P:
        groups.setdefault((p['set'], p['stratum']), {}).setdefault(p['game'], []).append(p)
    for (set_, stratum), d in groups.items():
        print('  %-6s %-9s 中国象棋 %3d  国际象棋 %3d' % (set_, stratum, len(d.get(XQ, [])), len(d.get(CH, []))))
    print('\n特征分布：中位数 [四分位] (最小–最大)')
    flags = []
    for (set_, stratum), d in groups.items():
        print('\n== %s / %s ==' % (set_, stratum))
        for f in FEATS:
            xs = {g: [p['features'][f] for p in d.get(g, []) if p['features'][f] is not None] for g in (XQ, CH)}
            print('  %-9s 中国象棋 %-28s 国际象棋 %s' % (f, _q(xs[XQ]), _q(xs[CH])))
            if xs[XQ] and xs[CH] and f in ('legal', 'checks', 'captures', 'escapes'):
                a, b = statistics.median(xs[XQ]), statistics.median(xs[CH])
                if max(a, b) > 0 and (min(a, b) / max(a, b) < 0.75):
                    flags.append('%s/%s 的 %s：中国象棋中位 %g vs 国际象棋 %g' % (set_, stratum, f, a, b))
        if set_ == 'mate':
            for g in (XQ, CH):
                ps = d.get(g, [])
                if not ps:
                    continue
                pieces = {}
                for p in ps:
                    k = p['features'].get('mate_piece', '无唯一杀着')
                    pieces[k] = pieces.get(k, 0) + 1
                one = sum(p['features']['checks'] == 1 for p in ps)
                cap = sum(p['features'].get('mate_capture', False) for p in ps)
                print('  %s 杀着棋子 %s；杀着吃子 %d/%d；只有一步将军（U2 等于直接给答案）%d/%d' % (
                    '中国象棋' if g == XQ else '国际象棋', dict(sorted(pieces.items())), cap, len(ps), one, len(ps)))
            bins = ((1, 1), (2, 3), (4, 6), (7, 99))
            row = lambda ps: ' '.join('%d-%s:%d' % (lo, hi if hi < 99 else '+', sum(lo <= p['features']['checks'] <= hi for p in ps))
                                      for lo, hi in bins)
            print('  将军着法数分档  中国象棋 %s | 国际象棋 %s' % (row(d.get(XQ, [])), row(d.get(CH, []))))
        if set_ in ('middle', 'gain'):
            for g in (XQ, CH):
                ps = d.get(g, [])
                if not ps:
                    continue
                cps = [p['engine']['cp'] for p in ps]
                agree = sum(max(p['move_scores'], key=p['move_scores'].get) == p['engine']['best'] for p in ps)
                line = '  %s 引擎评估 %s；score_moves 最高分着法 = analyse 最佳着 %d/%d' % (
                    '中国象棋' if g == XQ else '国际象棋', _q(cps), agree, len(ps))
                if set_ == 'gain':
                    gv = [p['gains'][p['answer']] for p in ps]
                    nb = [len(p['baits']) for p in ps]
                    eb = sum(p['engine']['best'] == p['answer'] for p in ps)
                    line += '；得子净值 %s；诱饵数 %s；引擎最佳着 = 得子着 %d/%d' % (_q(gv), _q(nb), eb, len(ps))
                print(line)
    print('\n明显不对齐（中位数相差超过 25%）：')
    for f in flags:
        print('  - ' + f)
    for g, m in data['meta']['games'].items():
        print('\n%s 自对弈 %d 局 / %d 半回合，淘汰原因 %s' % (g, m['selfplay_games'], m['selfplay_plies'], m['rejected']))


if __name__ == '__main__':
    args = sys.argv[1:]
    path = args[args.index('--out') + 1] if '--out' in args else B.POSITIONS
    if args[:1] == ['build']:
        w = int(args[args.index('--workers') + 1]) if '--workers' in args else 8
        build(w, path, {k: 3 for k in QUOTA} if '--tiny' in args else QUOTA)   # --tiny：每类只要 3 个，试跑流程用
    elif args[:1] == ['report']:
        report(path)
    else:
        print(__doc__)
