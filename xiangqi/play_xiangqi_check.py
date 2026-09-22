"""网页版中国象棋（play_xiangqi.py）的离线核对：不调 Jev、不花钱、不需要 key。依赖同 play_xiangqi.py。

    python3 xiangqi/play_xiangqi_check.py          # 约五分钟

核对四件事，Jev 的回答一律用假的（选中第一个选项），请求在交给网络之前就截下：
1. 请求和整局实验逐字节相同：随机下若干局，Jev 执红、执黑各一半，每次要问 Jev 时，把网页版要发的请求体
   和 exp_xiangqi_adapter.build_request(..., 'L2@pieces', 同一个局面编号) 造的比较。那边的局面是另沿着
   boards.play 从开局走出来的，安全事实也打开了独立核对。执黑时只许问句里的「执红」换成「执黑」。
   有着法因长将被去掉的那几步不在比较之列，单独计数。
2. 判结束的粗筛不改结果：网页版只在局面重复或限着到了时才问 pyffish 对局是否结束；这里每一步都问一遍
   pyffish，看两者是否处处相同。对局用几种走法凑出三次重复、长将、限着、将死、困毙。
   筛长将着法时不调 pyffish、自己摆出走完后的局面键，这里也逐步和 pyffish 走出的局面比。
3. 几个特定局面：长将的着法会被拦下（你走）或不列给 Jev（它走）；一步将死、一步困毙时程序直接走；
   只有一步可走时直接走；对局结束后再送着法、着法不合法、字段不对都报错。
4. 接着上次走和从头重放，回答完全相同；回头再问早先的局面（新开一局、刷新网页）也一样。
"""
import sys as _sys, pathlib as _pathlib
_sys.path.insert(0, str(_pathlib.Path(__file__).resolve().parent.parent))
import json, os, random, re
os.environ.setdefault('OPENROUTER_API_KEY', 'not-used-by-this-check')   # jevkit 导入时要 key；这里一个请求都不发
import play_xiangqi as px     # 先导入它：缺库时由它打印安装命令
import pyffish as sf
import boards as b
import exp_xiangqi_adapter as xa

XQ = b.XQ
SENT = []
PREFER = []


def fake_call(st, q):
    """假 Jev：记下请求体，选 PREFER 里最靠前的着法，没有就选第一个选项。"""
    SENT.append(json.dumps({"model": px.jev.MODEL, "state": st, "questions": q}).encode())
    crit = q['move']['criteria']
    move_of = {k: ''.join(re.search(r'从 ([a-i]\d) 走到 ([a-i]\d)', t).groups()) for k, t in crit.items()}
    k = next((k for m in PREFER for k in crit if move_of[k] == m), next(iter(crit)))
    probs = {x: (0.6 if x == k else 0.4 / (len(crit) - 1)) for x in crit}
    return {'model': px.jev.MODEL, 'usage': {'input_tokens': 0, 'cost': 0.0}, '_elapsed': 0.0,
            'answers': {'move': {'type': 'choice', 'choice': k, 'probabilities': probs, 'confidence': 0.5}}}


px.call = fake_call           # 从这里起，网页版要发的请求都被截下，不出本机


def start_at(fen):
    px.START = b.norm(XQ, fen) if fen else b.START[XQ]
    px.DONE.clear()


def ask(moves, jev, game='check001'):
    return px.answer({'moves': moves, 'jev': jev, 'game': game})


def always_end(fens, fsf):
    """不粗筛、每一步都问 pyffish。"""
    stm = fens[-1].split()[1]
    for fn in (sf.is_immediate_game_end, sf.is_optional_game_end):
        end, v = fn(XQ, px.START, fsf)
        if end:
            return (None if v == 0 else (stm if v > 0 else px.other(stm))), v
    return None


def check_requests(n_games, rng):
    same = diff = cut = asked = 0
    for g in range(n_games):
        start_at(None)
        jev = 'wb'[g % 2]
        game = 'chk%03d' % g
        moves, fen = [], b.START[XQ]      # fen 由这里沿 boards.play 另走一遍，不用网页版的
        while True:
            SENT.clear()
            r = ask(moves, jev, game)
            if SENT:
                asked += 1
                ply = len(moves)
                if r['jev']['options'] < r['jev']['legal']:
                    cut += 1
                else:
                    st, q, _ = xa.build_request(XQ, fen, 'L2@pieces', 'play|%s|%d' % (game, ply))
                    if jev == 'b':
                        q['move']['instructions'] = q['move']['instructions'].replace('执红', '执黑')
                    want = json.dumps({"model": px.jev.MODEL, "state": st, "questions": q}).encode()
                    same += want == SENT[0]
                    diff += want != SENT[0]
            if r['jev']:
                fen = b.play(XQ, fen, r['jev']['move'])
            if r['end'] or len(r['moves']) >= 120:
                break
            m = rng.choice([x['move'] for x in r['legal'] if not x['banned']])
            fen = b.play(XQ, fen, m)
            moves = r['moves'] + [m]
    print('1. 随机 %d 局，问 Jev %d 次：请求体与实验逐字节相同 %d 次，不同 %d 次；另有 %d 次去掉了长将着法、不比较'
          % (n_games, asked, same, diff, cut))
    return diff == 0 and same > 0


def pick(style, fen, moves, rng):
    legal = b.legal(XQ, fen)
    back = moves[-2][2:] + moves[-2][:2] if len(moves) >= 2 else None
    if style == 'random':
        return rng.choice(legal)
    if style == 'shuffle':                  # 常走回头棋，凑三次重复
        return back if back in legal and rng.random() < 0.5 else rng.choice(legal)
    if style == 'grab':                     # 爱吃子，凑将死、困毙、限着
        board = b.parse(XQ, fen)[0]
        caps = [m for m in legal if m[2:] in board]
        return rng.choice(caps) if caps and rng.random() < 0.7 else rng.choice(legal)
    if fen.split()[1] == 'w' and rng.random() < 0.9:      # checky：红方爱将军、黑方常走回头，凑长将
        checks = [m for m in legal if sf.gives_check(XQ, fen, [b.to_fsf(XQ, m)])]
        if checks:
            return rng.choice(checks)
    return back if back in legal and rng.random() < 0.6 else rng.choice(legal)


def check_prefilter(rng):
    plan = [('random', None, 10), ('shuffle', None, 20), ('grab', None, 30), ('checky', None, 20),
            ('checky', '3k5/9/9/9/9/9/9/9/9/R3K4 w - - 0 1', 30)]
    steps = mism = keys = key_bad = 0
    kinds = {}
    for style, start, n in plan:
        start_at(start)
        for _ in range(n):
            fens, fsf, moves = [px.START], [], []
            while True:
                a, c = px.rule_end(fens, fsf), always_end(fens, fsf)
                steps += 1
                mism += a != c
                if c or not sf.legal_moves(XQ, fens[-1], []) or len(fsf) >= 400:
                    e = px.ending(fens, fsf)
                    k = e['reason'] if e else '下满 400 半回合'
                    kinds[k] = kinds.get(k, 0) + 1
                    break
                m = pick(style, fens[-1], moves, rng)
                moves.append(m)
                fsf.append(b.to_fsf(XQ, m))
                fens.append(sf.get_fen(XQ, fens[-1], [fsf[-1]]))
                keys += 1
                key_bad += px.key_after(fens[-2], m) != b.key_of(fens[-1])
    start_at(None)
    print('2. 判结束的粗筛：%d 局、%d 步，与每步都问 pyffish 不一致 %d 步；结局 %s' % (
        sum(n for *_, n in plan), steps, mism, '、'.join('%s %d' % kv for kv in sorted(kinds.items()))))
    print('   筛长将着法用的局面键：%d 步里与 pyffish 走出的局面不一致 %d 步' % (keys, key_bad))
    return mism == 0 and key_bad == 0 and all(k in kinds for k in ('将死', '困毙', '长将，判负', '同一局面出现三次，判和', '一百个半回合没有吃子，判和'))


def check_cases():
    bad = []

    def ok(cond, what):
        if not cond:
            bad.append(what)

    # 你（执红）长将：第三次重复前那一步被拦；硬送过去，服务端判你输
    start_at('3k5/9/9/9/9/9/9/9/9/R3K4 w - - 0 1')
    PREFER[:] = ['d9d8', 'd8d9']
    mv = []
    for i, m in enumerate(['a0a9', 'a9a8', 'a8a9', 'a9a8', 'a8a9']):
        r = ask(mv, 'b')
        banned = [x['move'] for x in r['legal'] if x['banned']]
        ok(banned == (['a8a9'] if i == 4 else []), '你长将时拦下的着法不对：第 %d 步 %s' % (i + 1, banned))
        if i < 4:
            mv = ask(mv + [m], 'b')['moves']
    r = ask(mv + ['a8a9'], 'b')
    ok(r['end'] == {'winner': 'b', 'reason': '长将，判负'} and r['jev'] is None and r['legal'] == [], '你长将后没判负：%s' % r['end'])

    # Jev（执红）长将：第三次重复前那一步不列给它
    start_at('4k4/9/9/9/9/9/8p/9/9/R2K5 w - - 0 1')
    ok(not b.mate_moves(XQ, px.START) and not b.stalemate_moves(XQ, px.START), '这个局面不该有一步胜')
    PREFER[:] = ['a0a9', 'a9a8', 'a8a9']
    mv = ask([], 'w')['moves']
    for m in ['e9e8', 'e8e9', 'e9e8', 'e8e9']:
        SENT.clear()
        r = ask(mv + [m], 'w')
        mv = r['moves']
    j = r['jev']
    crit = json.loads(SENT[-1])['questions']['move']['criteria']
    ok(j['options'] == j['legal'] - 1 and j['move'] != 'a8a9' and not any('从 a8 走到 a9' in t for t in crit.values()),
       'Jev 长将的着法没去掉：%s' % j)

    # 一步将死、一步困毙：程序直接走，不问 Jev；你走出困毙也判赢
    start_at('3k5/9/9/9/9/9/9/9/9/R3K4 w - - 0 1')
    SENT.clear()
    r = ask([], 'w')
    ok(r['jev']['auto'] == 'win' and not SENT and r['end'] == {'winner': 'w', 'reason': '将死'}, '一步将死没直接走：%s' % r['jev'])
    start_at('4k4/9/9/9/9/9/9/9/9/R2K5 w - - 0 1')
    SENT.clear()
    r = ask(['a0a9', 'e9e8', 'a9a8', 'e8e9'], 'w')
    ok(r['jev']['auto'] == 'win' and not SENT and r['end'] == {'winner': 'w', 'reason': '困毙'}, '一步困毙没直接走：%s' % r['jev'])
    r = ask(['a0a9', 'e9e8', 'a9a8', 'e8e9', 'a8f8'], 'b')
    ok(r['jev'] is None and r['end'] == {'winner': 'w', 'reason': '困毙'}, '你困毙 Jev 没判赢：%s' % r['end'])

    # 只有一步可走：直接走
    start_at('3k5/9/9/9/9/9/9/9/9/R3K4 w - - 0 1')
    SENT.clear()
    r = ask(['a0a9'], 'b')
    ok(r['jev']['auto'] == 'forced' and r['jev']['move'] == 'd9d8' and not SENT, '只有一步时没直接走：%s' % r['jev'])

    # 请求不对要报错
    start_at(None)
    for req, want in [({'moves': 'h2e2', 'jev': 'b', 'game': 'abcd1234'}, 'moves 要是'),
                      ({'moves': ['h2e2'], 'jev': 'x', 'game': 'abcd1234'}, 'jev 要是'),
                      ({'moves': ['h2e2'], 'jev': 'b', 'game': 'AB'}, 'game 要是'),
                      ({'moves': ['h2e3'], 'jev': 'b', 'game': 'abcd1234'}, '不合法'),
                      ({'moves': ['h9g7'], 'jev': 'b', 'game': 'abcd1234'}, '不合法'),
                      ({'moves': ['h2e2'] * 1001, 'jev': 'b', 'game': 'abcd1234'}, '最多'),
                      ([1, 2], '对象')]:
        try:
            px.answer(req)
            bad.append('该报错没报：%r' % (req,))
        except ValueError as e:
            ok(want in str(e), '报错不对：%s' % e)
    start_at('3k5/9/9/9/9/9/9/9/9/R3K4 w - - 0 1')
    try:
        ask(['a0d0', 'd9d8'], 'b')
        bad.append('将死之后还能走')
    except ValueError as e:
        ok('已经结束' in str(e), '将死之后再走的报错不对：%s' % e)
    start_at(None)
    PREFER[:] = []
    print('3. 特定局面：%s' % ('全部符合' if not bad else '；'.join(bad)))
    return not bad


def cold(moves, game):
    """同一请求，不用记下的对局、从开局重放。"""
    keep = px.DONE
    px.DONE = {}
    try:
        return ask(moves, 'w', game)
    finally:
        px.DONE = keep


def check_cache(rng):
    start_at(None)
    seen, moves, n, differ = [], [], 0, 0
    while n < 60:
        r = ask(moves, 'w', 'cache001')
        differ += r != cold(moves, 'cache001')
        seen.append(list(moves))
        n += 1
        moves = [] if r['end'] else r['moves'] + [rng.choice([x['move'] for x in r['legal'] if not x['banned']])]
    for old in rng.sample(seen, 15):        # 回头再问早先的局面：新开一局、刷新网页都会这样
        differ += ask(old, 'w', 'cache001') != cold(old, 'cache001')
        n += 1
    print('4. 接着走 vs 从头重放：%d 次请求（含回头再问的 15 次），回答不同 %d 次' % (n, differ))
    return differ == 0


def main():
    rng = random.Random(20260922)
    results = [check_requests(8, rng), check_prefilter(rng), check_cases(), check_cache(rng)]
    if not all(results):
        raise SystemExit(1)


main()
