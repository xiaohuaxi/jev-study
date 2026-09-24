"""逐字比对：网页版（play_chess.py）和实验（exp_game_chess.py）发给 Jev 的请求体是否一模一样。

不调 Jev、不花钱、不需要 key。需要 python-chess（python3 -m pip install chess）和 Node（在 Python 3.13、
Node v24.20.0 上跑过）；每次跑都要联网，从 jsdelivr 下载网页用的那份 chess.js 并核对哈希。

    python3 games/chess/play_chess_check.py      # 默认随机下 200 局，外加实验里的局面和几个边角局面

做法：
1. Node 载入网页用的同一份 chess.js（jsdelivr 上的 chess.js@1.4.0），随机下 N 局，每一步记下
   chess.js 给的 FEN 和全部合法着法（UCI + SAN）——这正是网页发给本地脚本的东西。一半对局偏爱
   兵和吃子，好多撞到升变、吃过路兵。另外加上 exp_game_chess.py 里的 11 个局面和几个专挑的
   边角局面（过路兵被牵制、将军时吃过路兵、双将、升变吃子、易位、一匹马被牵制时的记谱）。
2. Python 这边：用 python-chess 从开局把同一串着法重下一遍，交给 exp_game_chess.py 里原样的
   ask()；chess.js 的输出交给 play_chess.py 的 answer()。实验那边在 jevkit.call 交给 urllib 时、
   网页那边在 play_chess.send 交给 http.client 时，各自截下要发出去的请求体，逐字节比较。
3. 本地脚本会把 FEN 里吃不了的过路兵格改成 '-'（python-chess 的写法）。chess.js 本来就这么写，
   所以再把每个刚走过两格兵的局面换成"照写过路兵格"的 FEN 送一遍，确认这一步也不出错。
"""
import sys as _sys, pathlib as _pathlib
_sys.path.insert(0, str(_pathlib.Path(__file__).resolve().parent.parent.parent))
import argparse, hashlib, json, os, subprocess, tempfile, urllib.request
os.environ.setdefault('OPENROUTER_API_KEY', 'not-used-by-this-check')   # jevkit 导入时要 key；这里一个请求都不发
import chess
import jevkit as jev

HERE = _pathlib.Path(__file__).resolve().parent
CHESSJS = 'https://cdn.jsdelivr.net/npm/chess.js@1.4.0/dist/esm/chess.js'   # 与 play_chess.html 一致
CHESSJS_SHA256 = '76c7c34f0e2e9ab076521a5d6fe786a9cce537bb1b6f29d32a9c9970b5b232d2'   # 与 npm 上 chess.js-1.4.0.tgz 里的同一文件相同
EDGE = [
    '8/8/8/KPp4r/8/8/8/7k w - c6 0 2',          # 吃过路兵会把自己的王暴露给车：不合法，FEN 里不写过路兵格
    '4k3/8/8/3PpP2/8/8/8/4K3 w - e6 0 2',        # 两个兵都能吃过路兵
    '4k3/8/8/2PpP3/4K3/8/8/8 w - d6 0 2',        # 刚走两格的兵在将军，吃过路兵解将
    '4k3/8/8/8/8/5n2/8/r3K3 w - - 0 1',          # 双将，只能动王
    '1r1b4/P1P5/8/8/8/8/8/4K2k w - - 0 1',       # 升变与升变吃子
    'r3k2r/8/8/8/8/8/8/R3K2R w KQkq - 0 1',      # 两边都能易位
    'r3k2r/8/8/8/8/8/8/R3K2R b KQkq - 0 1',
    '4k3/4r3/8/8/8/2N1N3/8/4K3 w - - 0 1',       # e3 的马被牵制，c3 的马跳 d5 不用标起点
]

NODE = r"""
import {Chess} from './chess.mjs'
const [n, seed] = [parseInt(process.argv[2]), parseInt(process.argv[3])]
let s = seed >>> 0
const rand = () => {   // mulberry32，固定种子可复现
  s = (s + 0x6D2B79F5) >>> 0; let t = s
  t = Math.imul(t ^ t >>> 15, t | 1); t ^= t + Math.imul(t ^ t >>> 7, t | 61)
  return ((t ^ t >>> 14) >>> 0) / 4294967296
}
const legal = c => c.moves({verbose: true}).map(m => ({uci: m.from + m.to + (m.promotion || ''), san: m.san}))
const games = []
for (let g = 0; g < n; g++) {
  const c = new Chess(), moves = [], plies = []
  while (!c.isGameOver() && moves.length < 200) {
    plies.push({fen: c.fen(), moves: legal(c)})
    let ms = c.moves({verbose: true})
    if (g % 2) { const p = ms.filter(m => m.piece === 'p' || m.captured); if (p.length && rand() < 0.7) ms = p }
    const m = ms[Math.floor(rand() * ms.length)]
    c.move({from: m.from, to: m.to, promotion: m.promotion})
    moves.push(m.from + m.to + (m.promotion || ''))
  }
  games.push({moves, plies})
}
const fens = JSON.parse(await new Promise(r => { let d = ''; process.stdin.on('data', x => d += x).on('end', () => r(d)) }))
const fixed = fens.map(f => { const c = new Chess(f); return {src: f, fen: c.fen(), moves: legal(c)} })
process.stdout.write(JSON.stringify({games, fixed}))
"""


def load_experiment():
    """原样执行 exp_game_chess.py（去掉末尾的 main() 调用），拿到它的 ask() 和局面表。"""
    p = HERE / 'exp_game_chess.py'
    src = p.read_text(encoding='utf-8').rstrip()
    assert src.endswith('\nmain()'), '实验脚本末尾不是 main()，比对方式要跟着改'
    ns = {'__file__': str(p), '__name__': 'exp_game_chess'}
    exec(compile(src[:-len('main()')], str(p), 'exec'), ns)
    return ns


SENT = []


class FakeResp:
    def __init__(self, body):
        crit = json.loads(body)['questions']['move']['criteria']
        k = next(iter(crit))
        self.data = json.dumps({'answers': {'move': {'choice': k, 'probabilities': {k: 1.0}}},
                                'usage': {'input_tokens': 0, 'cost': 0.0}}).encode()
    def read(self): return self.data
    def __enter__(self): return self
    def __exit__(self, *a): return False


def fake_urlopen(req, timeout=None, context=None):
    SENT.append(req.data)       # 实验那边：只截请求体；请求头（含 key）不碰
    return FakeResp(req.data)


def fake_send(body):
    SENT.append(body)           # 网页那边：play_chess.send 收到的就是要发出去的请求体
    return 200, FakeResp(body).data, 0.0


def sent_by(fn):
    SENT.clear()
    fn()
    assert len(SENT) == 1
    return SENT[0]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--games', type=int, default=200)
    ap.add_argument('--seed', type=int, default=20260921)
    args = ap.parse_args()

    ns = load_experiment()
    import play_chess
    fens = ns['MATES'] + [f for _, f in ns['TACTICS']] + EDGE

    with tempfile.TemporaryDirectory() as tmp:
        with urllib.request.urlopen(CHESSJS, timeout=60, context=jev.CTX) as r:
            js = r.read()
        assert hashlib.sha256(js).hexdigest() == CHESSJS_SHA256, 'jsdelivr 上的 chess.js 和钉的不一样'
        _pathlib.Path(tmp, 'chess.mjs').write_bytes(js)
        _pathlib.Path(tmp, 'run.mjs').write_text(NODE, encoding='utf-8')
        out = subprocess.run(['node', 'run.mjs', str(args.games), str(args.seed)], cwd=tmp,
                             input=json.dumps(fens), capture_output=True, text=True, check=True)
    data = json.loads(out.stdout)
    jev.urllib.request.urlopen = fake_urlopen       # 从这里起，两边发出的请求都被截下，不出本机
    play_chess.send = fake_send

    cases = []      # (python-chess 局面, chess.js 的 fen, chess.js 的合法着法, 来源)
    for g in data['games']:
        b = chess.Board()
        for ply, mv in zip(g['plies'], g['moves']):
            cases.append((b.copy(), ply['fen'], ply['moves'], 'random'))
            b.push_uci(mv)
    for f in data['fixed']:
        cases.append((chess.Board(f['src']), f['fen'], f['moves'], f['src']))

    same = fen_same = forced = forced_same = 0
    cov = dict(将军=0, 双将=0, 吃过路兵=0, 升变=0, 易位=0, 着法=0)
    bad = []
    for b, fen, moves, src in cases:
        want = sent_by(lambda: ns['ask'](b))
        got = sent_by(lambda: play_chess.answer(fen, moves))
        same += want == got
        fen_same += fen == b.fen()
        fen2 = b.fen(en_passant='fen')     # 刚走过两格兵就写过路兵格，不管吃不吃得了
        if fen2 != fen:     # 换这种写法的 FEN 送进去，看本地脚本能不能归一成同样的请求
            forced += 1
            forced_same += sent_by(lambda: play_chess.answer(fen2, moves)) == want
        if want != got and len(bad) < 5:
            bad.append((src, b.fen(), want.decode()[:400], got.decode()[:400]))
        legal = list(b.legal_moves)
        cov['着法'] += len(legal)
        cov['将军'] += b.is_check()
        cov['双将'] += len(b.checkers()) > 1
        cov['吃过路兵'] += b.has_legal_en_passant()
        cov['升变'] += any(m.promotion for m in legal)
        cov['易位'] += any(b.is_castling(m) for m in legal)

    print('随机对局 %d 局、固定局面 %d 个，共 %d 个局面、%d 个合法着法' % (
        len(data['games']), len(data['fixed']), len(cases), cov.pop('着法')))
    print('其中含：' + '、'.join('%s %d 个局面' % kv for kv in cov.items()))
    print('chess.js 的 FEN 与 python-chess 原样相同：%d/%d' % (fen_same, len(cases)))
    print('请求体逐字节相同：%d/%d' % (same, len(cases)))
    print('FEN 写了过路兵格、其实吃不了的 %d 个局面，换这种写法送进去，请求体也相同：%d/%d' % (
        forced, forced_same, forced))
    for src, fen, w, g in bad:
        print('\n不一致：%s\n  FEN %s\n  实验 %s\n  网页 %s' % (src, fen, w, g))
    if same != len(cases) or forced_same != forced:
        raise SystemExit(1)


main()
