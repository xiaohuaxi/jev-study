"""换个问法，Jev 会不会下得好一点：提示"有杀"、叫它"以赢棋为目标"、具体提醒"别被白吃"。

需要 python-chess：python3 -m pip install chess。两组，问法都走 exp_game_chess.py 里原样的 ask()：
  A 一步杀：exp_game_chess.py 的 5 个局面 + 随机对局里抽的 35 个有一步杀的局面（固定种子），
    四种问法各问一次，看选没选中将死着法。exp_game_chess.py 的 A 组在问题末尾加了
    "注意：这里存在一步将死的机会。"，网页对弈版（play_chess.py）不加，这里两种都测。
  B 吃亏：网页对弈版最终测试里 Jev 下的 3 盘（人这边随机走子）重放出来，取 Jev 面对的全部局面
    （去掉有一步杀的），加上 exp_game_chess.py 的 6 个战术局面。三种问法各问两次，用
    exp_game_chess.py 的两层物质搜索打分：比最好的一步差 2 分及以上记一次吃亏，再分成
    "走完自己的子被吃回来、比走之前少 2 分以上"（送子）和"自己没少、只是没吃到白给的子"（漏吃）。
    同一问法问两次，用来看问法之间的差别有多少只是两次问答本身的出入。
"""
import sys as _sys, pathlib as _pathlib
_sys.path.insert(0, str(_pathlib.Path(__file__).resolve().parent.parent))
import io, json, os, random, statistics
from concurrent.futures import ThreadPoolExecutor
import chess, chess.pgn
import jevkit as jev

HERE = os.path.dirname(os.path.abspath(__file__))
VARIANTS = {                  # 接在"你在下国际象棋，执X。从合法着法里选一步最好的。"后面
    '原问法': '',             # 网页对弈版、exp_game_chess.py 的 B/C 组就是这样问的
    '提示有杀': '注意：这里存在一步将死的机会。',       # exp_game_chess.py 的 A 组
    '以赢棋为目标': '选的时候以最终赢下这盘棋为目标。',
    '具体提醒': '先看有没有一步就能将死对方的着法；没有的话，确认走完之后自己的子不会被对方白白吃掉。',
}
B_VARIANTS = ('原问法', '以赢棋为目标', '具体提醒')
# 网页对弈版最终测试的 3 盘：(Jev 执哪方, 着法)
GAMES = [
    ('b', '1. Nh3 Nf6 2. b4 d5 3. e3 Nc6 4. Be2 Nxb4 5. Bg4 Nxc2+ 6. Ke2 Bxg4+ 7. Kd3 Bxd1 8. Ba3 Nxa3 9. Rxd1 Nxb1 10. Rg1 Nxd2 11. f4 d4 12. Rgc1 dxe3+ 13. Kc3 Qd3+ 14. Kb2 O-O-O 15. Rc6 bxc6 16. Nf2 Qd4+ 17. Kc2 Qxa1 18. Nd3 Qxa2+ 19. Kc1 Qb1#'),
    ('w', '1. e4 g5 2. Nf3 d5 3. exd5 e6 4. Nxg5 c6 5. Nxf7 Nh6 6. Nd6+ Ke7 7. Nxc8+ Qxc8 8. Nc3 a6 9. d6+ Ke8 10. d7+ Kxd7 11. Nd5 Qe8 12. Nf6+ Kd8 13. Nxe8 Nd7 14. Bxa6 Nb8 15. O-O Ng4 16. Qxg4 Kc8 17. Qxe6+ Nd7 18. Qxc6+ Kd8 19. Qxd7+ Kxd7 20. Bxb7 Kxe8 21. Bxa8 Kf7 22. Bd5+ Kg6 23. Bf7+ Kf5 24. Bg6+ Ke5 25. Re1+ Kd6 26. Re6+ Kxe6 27. Bf7+ Kd6 28. Bd5 Kd7 29. Bc6+ Kxc6 30. Rb1 h6 31. d4 Bb4 32. d5+ Kd7 33. d6 Ke6 34. Bxh6 Ba5 35. Re1+ Kf6 36. Bg7+ Kf7 37. Re7+ Kg6 38. Re6+ Kh7 39. Bxh8 Be1 40. Rxe1'),
    ('b', '1. b3 Nf6 2. b4 d5 3. c3 Nc6 4. Ba3 Nxb4 5. e4 dxe4 6. Ke2 Qxd2+ 7. Nxd2 Nxa2 8. Bd6 Nxc3+ 9. Ke3 Nxd1+ 10. Rxd1 Nd5+ 11. Ke2 Nc3+ 12. Ke1 exd6 13. f4 exf3 14. Nb3 Nxd1 15. Kxd1 fxg2 16. Nd2 Bg4+ 17. Kc1 gxf1=Q+ 18. Nxf1 O-O-O 19. Ne2 Bxe2 20. Rg1 Bxf1 21. Kc2 Bd3+ 22. Kc1 Bb1 23. Kd1 Bc2+ 24. Ke1 Re8+ 25. Kf1 Re1+ 26. Kf2 Rxg1 27. h4 Rf1+ 28. Ke2 Re1+ 29. Kxe1 Be4 30. h5 Bd3 31. Kf2 Bf1 32. Kg1 d5 33. Kh1 Bg2+ 34. Kh2 Bd6+ 35. Kxg2 Bg3 36. Kg1 Bh2+ 37. Kf1 d4 38. Ke1 Bg3+ 39. Ke2 d3+ 40. Kf3 Bd6'),
]


def load_experiment():
    """原样执行 exp_game_chess.py（去掉末尾的 main() 调用），拿到它的 ask()、局面表和打分函数。"""
    p = os.path.join(HERE, 'exp_game_chess.py')
    src = open(p, encoding='utf-8').read().rstrip()
    assert src.endswith('\nmain()'), '实验脚本末尾不是 main()，这里的载入方式要跟着改'
    ns = {'__file__': p, '__name__': 'exp_game_chess'}
    exec(compile(src[:-len('main()')], p, 'exec'), ns)
    return ns


def mates_of(b):
    out = []
    for m in b.legal_moves:
        b.push(m)
        if b.is_checkmate():
            out.append(m.uci())
        b.pop()
    return out


def main():
    ns = load_experiment()
    ask, best_material, material = ns['ask'], ns['best_material'], ns['material']

    mate_pos = list(ns['MATES'])
    rng = random.Random(20260922)
    while len(mate_pos) < 40:
        b = chess.Board()
        while not b.is_game_over() and b.fullmove_number < 120:
            if mates_of(b) and b.fen() not in mate_pos:
                mate_pos.append(b.fen())
                break
            b.push(rng.choice(list(b.legal_moves)))

    blun_pos = []
    for side, moves in GAMES:
        game = chess.pgn.read_game(io.StringIO(moves))
        b = game.board()
        for mv in game.mainline_moves():
            if b.turn == (side == 'w') and not mates_of(b):
                blun_pos.append(b.fen())
            b.push(mv)
    blun_pos += [f for _, f in ns['TACTICS']]

    jobs = [('A', i, v, 0) for i in range(len(mate_pos)) for v in VARIANTS]
    jobs += [('B', i, v, k) for i in range(len(blun_pos)) for v in B_VARIANTS for k in (0, 1)]
    print('A 组 %d 个局面、B 组 %d 个局面，共 %d 次请求' % (len(mate_pos), len(blun_pos), len(jobs)))

    def run(job):
        g, i, v, k = job
        return ask(chess.Board((mate_pos if g == 'A' else blun_pos)[i]), VARIANTS[v])
    with ThreadPoolExecutor(max_workers=4) as ex:
        res = dict(zip(jobs, ex.map(run, jobs)))
    json.dump({'mate_pos': mate_pos, 'blun_pos': blun_pos, 'res': [[list(j), res[j]] for j in jobs]},
              open(os.path.join(HERE, 'game_chess_prompt_log.json'), 'w'), ensure_ascii=False)
    fails = sum('_error' in r for r in res.values())

    print('\nA 一步杀：选中将死着法')
    for v in VARIANTS:
        hit, confs = 0, []
        for i, f in enumerate(mate_pos):
            r = res[('A', i, v, 0)]
            if '_error' in r:
                continue
            a = r['answers']['move']
            hit += a['choice'] in mates_of(chess.Board(f))
            confs.append(a.get('confidence') or 0)
        print('  %-6s %d/%d，confidence 中位 %.2f' % (v, hit, len(confs), statistics.median(confs)))

    print('\nB 吃亏：比两层物质搜索的最好一步差 2 分及以上')
    pick = {}
    for v in B_VARIANTS:
        for k in (0, 1):
            hang = miss = 0
            loss = []
            for i, f in enumerate(blun_pos):
                r = res[('B', i, v, k)]
                if '_error' in r:
                    continue
                b = chess.Board(f)
                c = r['answers']['move']['choice']
                pick[(v, k, i)] = c
                sc = {m.uci(): s for m, s in best_material(b).items()}
                d = max(sc.values()) - sc[c]
                loss.append(d)
                if d >= 2:
                    if sc[c] <= material(b, b.turn) - 2:
                        hang += 1
                    else:
                        miss += 1
            print('  %-6s 第 %d 次：%d 步里送子 %d、漏吃 %d，平均每步差 %.2f 分' % (
                v, k + 1, len(loss), hang, miss, statistics.mean(loss)))

    def same(x, y):
        idx = [i for i in range(len(blun_pos)) if x + (i,) in pick and y + (i,) in pick]
        return '%d/%d' % (sum(pick[x + (i,)] == pick[y + (i,)] for i in idx), len(idx))
    print('\n选同一步的局面数（B 组）')
    for v in B_VARIANTS:
        print('  %-6s 自己问两次：%s' % (v, same((v, 0), (v, 1))))
    for v in B_VARIANTS[1:]:
        print('  %-6s 与原问法（各取第 1 次）：%s' % (v, same((v, 0), ('原问法', 0))))
    print('\n失败 %d 次；%s' % (fails, jev.spend()))


main()
