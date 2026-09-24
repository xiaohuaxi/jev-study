"""在浏览器里和 Jev 下中国象棋：一条命令起本地服务，自动打开网页。

    export OPENROUTER_API_KEY="sk-or-v1-..."     # 或 API_KEY_OPENROUTER
    python3 -m pip install pyffish==0.0.90 cchess==1.25.5 chess==1.11.2
    python3 games/xiangqi/play_xiangqi.py        # 可加 --port 9000、--no-browser

棋规全在本脚本这边，用的是中国象棋实测那套（boards.py，以 pyffish 为准），网页只画棋盘、点选着法。

交给 Jev 的请求就是整局实验用的那套：exp_xiangqi_adapter.build_request(..., 'L2@pieces', ...)。
state 是子力清单；每个选项写明走哪个子、吃什么、是否将军 / 将死 / 困毙、走完对方能吃我方哪些子、
最多吃掉哪个，选项键是无意义的字母串。平常每一步（没有一步胜、没去掉着法、不止一步可走）和实验只差两处：
Jev 执黑时问句里的「执红」换成「执黑」；选项键和顺序按这局的编号和步数另抽一套（实验按对局和步数抽）。
所以那份实验的结论可以用到这些步上；实验里 Jev 只执红，执黑是同一套接法，没单独测过。

另外照本目录 README.md 第八节的接法清单多做两件事（整局实验里没有）：
  - 一步就能赢（将死或困毙对方）时程序直接走，不问 Jev：能赢的着法一多，它的票会分散，可能选出不赢的；
  - 走了会因长将（或长捉）当场判负的着法不列给 Jev；你走这种着法，网页会拦下来。
只有一步可走时也直接走，这一条和实验相同。
胜负全按 pyffish 判：将死、困毙判负；同一局面第三次出现时，一方长将（或按 pyffish 的近似判法长捉）判负，否则判和；
连续一百个半回合没有吃子判和。

key 只在本进程里用：不进网页、不打印、不写日志。服务只监听 127.0.0.1。

网页只用一个接口：POST /api/move
  请求  {"moves": ["h2e2", "h9g7", ...], "jev": "b", "game": "k3v9x2m1"}
        moves 是从开局起的全部着法（ICCS 坐标），jev 是 Jev 执哪方（w 红 / b 黑），game 是这局的编号（网页随机生成）
  回答  轮到 Jev 就先让它走一步，再回走完后的局面：
        {"moves": [... 含 Jev 这一步], "record": ["炮二平五", ...], "fen": "...", "turn": "w", "check": false,
         "legal": [{"move": "h0g2", "text": "马二进三", "banned": false}, ...],     对局结束时为空
         "end": null 或 {"winner": "w" / "b" / null, "reason": "将死"},
         "jev": null 或 {"move": "h9g7", "text": "马８进７", "auto": null / "forced" / "win",
                         "candidates": [{"move", "text", "desc", "p"}, ...], "confidence": 0.4,
                         "legal": 44, "options": 44, "elapsed": 0.9, "input_tokens": 2011, "cost": 9e-05, "model": "..."}}
        auto 不为 null 时是程序直接走的，没问 Jev，candidates 为空；desc 是 Jev 看到的那段选项文字。
  出错  {"error": "..."}，4xx 是请求不对（429 是上一步还没回来），502 是 Jev 那边没答上来
"""
# 让本脚本从任意目录都能找到仓库根部的 jevkit.py
import sys as _sys, pathlib as _pathlib
_sys.path.insert(0, str(_pathlib.Path(__file__).resolve().parent.parent.parent))
import argparse, http.client, json, re, threading, time, urllib.parse, webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
try:
    import pyffish as sf
    import cchess, chess  # noqa: F401  boards.py 顶上要导入；python-chess 这个网页其实用不到
except ImportError as e:
    raise SystemExit('缺少 Python 库 %s。先装好这三个（不需要引擎）：\n'
                     '    python3 -m pip install pyffish==0.0.90 cchess==1.25.5 chess==1.11.2' % e.name)
import boards as b
import exp_xiangqi_adapter as xa
import jevkit as jev

PAGE = _pathlib.Path(__file__).resolve().parent / 'play_xiangqi.html'
XQ = b.XQ
START = b.START[XQ]
ARM = 'L2@pieces'                # 实验里最好的接法：子力清单 + L2 选项
ASK_BLACK = xa.ASK[XQ].replace('执红', '执黑')
assert ASK_BLACK != xa.ASK[XQ]
MOVE = re.compile(r'^[a-i][0-9][a-i][0-9]$')
GAME = re.compile(r'^[0-9a-z]{4,32}$')
MAX_PLIES = 1000
TOP = 5            # 回给网页的候选数
MAX_BODY = 65536
DEADLINE = 20      # 一次调用最多等几秒。平时 1 秒上下，偶尔会有一次拖几十秒，
ATTEMPTS = 2       # 到点就断开另发一次；最坏约 40 秒后报错，网页上有「重试」
BUSY = threading.BoundedSemaphore(2)     # 同时在途的请求上限
STATS = {'calls': 0, 'cost': 0.0, 'lost': 0}   # lost：没拿到回包的次数（超时断开或网络出错），花没花钱不知道
LOCK = threading.Lock()
DONE = {}          # 最近走过的着法 -> (fens, fsf)，见 replay()
b._key_pool()      # 选项键池第一次用到时才生成，两个请求同时去生成会出错，所以启动时先生成好


def other(side):
    return 'b' if side == 'w' else 'w'


def notation(fen, mv):
    """中文记谱（cchess）。它写不准的局面（多路兵、同一纵线三个同种子）在后面补上坐标。"""
    try:
        t = b.cn_notation(fen, mv)
        if b.cn_text(fen, mv) != t:
            t += '（%s）' % mv
        return t
    except Exception:
        return mv


def rule_end(fens, fsf):
    """按 pyffish 看走完 fsf（从开局起的着法）后对局是否因重复或限着结束。fens 是每步走之前的局面再加上当前局面。
    返回 None，或 (赢家 'w' / 'b' / None, pyffish 给的分值)。分值按轮到的一方算，正数是它赢。"""
    fen = fens[-1]
    key = b.key_of(fen)
    if int(fen.split()[4]) < 100 and all(b.key_of(f) != key for f in fens[:-1]):
        return None     # 局面头一回出现、限着也没到，pyffish 不会判结束；免得每步都把整局重放一遍
    stm = fen.split()[1]
    for fn in (sf.is_immediate_game_end, sf.is_optional_game_end):
        end, v = fn(XQ, START, fsf)
        if end:
            return (None if v == 0 else (stm if v > 0 else other(stm))), v
    return None


def ending(fens, fsf):
    """对局是否已经结束：{'winner': 'w' / 'b' / None, 'reason': ...}，没结束返回 None。
    fens 是每步走之前的局面再加上当前局面，fsf 是对应的着法（Fairy-Stockfish 写法）。"""
    fen = fens[-1]
    stm = fen.split()[1]
    st = b.status(XQ, fen)
    if st in ('mate', 'stalemate'):
        return {'winner': other(stm), 'reason': '将死' if st == 'mate' else '困毙'}
    r = rule_end(fens, fsf)
    if r is None:
        return None
    winner = r[0]
    if winner is None:
        return {'winner': None, 'reason': '一百个半回合没有吃子，判和' if int(fen.split()[4]) >= 100
                else '同一局面出现三次，判和'}
    # 输的一方在这个循环里每步都将军，就是长将；否则是 pyffish 判的长捉（它的近似实现）
    loser = other(winner)
    key = b.key_of(fen)
    first = next(i for i, f in enumerate(fens) if b.key_of(f) == key)
    checks = [b.in_check(XQ, fens[t + 1]) for t in range(first, len(fens) - 1) if fens[t].split()[1] == loser]
    return {'winner': winner, 'reason': '长将，判负' if checks and all(checks) else '长捉，判负'}


def key_after(fen, mv):
    """走 mv 之后的局面键（同 boards.key_of：棋盘 + 轮到谁），不调 pyffish。"""
    board, stm = b.parse(XQ, fen)
    board[mv[2:]] = board.pop(mv[:2])
    return '%s %s - -' % (b.board_fen(XQ, board), other(stm))


def banned(fens, fsf, moves):
    """moves 里走了会因长将 / 长捉当场判负的着法。只有走到出现过的局面才可能判负（限着到了只判和），
    所以先用局面键筛，剩下的再交给 pyffish。"""
    seen = {b.key_of(f) for f in fens}
    mover = fens[-1].split()[1]
    out = set()
    for mv in moves:
        if key_after(fens[-1], mv) not in seen:
            continue
        f = b.to_fsf(XQ, mv)
        r = rule_end(fens + [sf.get_fen(XQ, fens[-1], [f])], fsf + [f])
        if r is not None and r[0] == other(mover):
            out.add(mv)
    return out


def remember(moves, fens, fsf):
    with LOCK:
        if len(DONE) >= 64:
            DONE.pop(next(iter(DONE)))      # 丢掉最早记下的
        DONE[tuple(moves)] = (tuple(fens), tuple(fsf))


def replay(moves):
    """从开局按顺序走 moves，每步都查合法、查对局是否已经结束。返回 (fens, fsf)，fens 比 moves 多一个（当前局面）。
    pyffish 每调一次约 1 毫秒，一盘下到后面从头重放要好几百毫秒；每次请求只比上次回的多一步，所以从记下的接着走。"""
    fens, fsf, done = [START], [], 0
    for k in (len(moves), len(moves) - 1, len(moves) - 2):
        hit = DONE.get(tuple(moves[:k])) if k >= 0 else None
        if hit:
            fens, fsf, done = list(hit[0]), list(hit[1]), k
            break
    for i in range(done, len(moves)):
        legal = sf.legal_moves(XQ, fens[-1], [])
        if not legal or rule_end(fens, fsf):         # 没有着法就是将死或困毙
            raise ValueError('第 %d 步之前对局已经结束' % (i + 1))
        f = b.to_fsf(XQ, moves[i])
        if f not in legal:
            raise ValueError('第 %d 步 %s 不合法' % (i + 1, moves[i]))
        fsf.append(f)
        fens.append(sf.get_fen(XQ, fens[-1], [f]))
    remember(moves, fens, fsf)
    return fens, fsf


def send(body):
    """发一次请求，按总时长截断：到点就断开连接。返回 (状态码, 回包字节, 用时)。

    不用 urllib 的 timeout：它只管多久没收到数据，不管总共等了多久，上游隔一会儿来一点数据
    它就一直等（实测有一次拖了 76 秒）。这里每读一块都按剩下的时间重设超时。
    """
    t0 = time.time()
    left = lambda: max(0.05, t0 + DEADLINE - time.time())
    u = urllib.parse.urlsplit(jev.URL)
    if u.scheme == 'https':
        conn = http.client.HTTPSConnection(u.hostname, u.port, timeout=left(), context=jev.CTX)
    else:
        conn = http.client.HTTPConnection(u.hostname, u.port, timeout=left())
    try:
        conn.request('POST', u.path or '/', body, {
            'Authorization': 'Bearer ' + jev.KEY, 'Content-Type': 'application/json'})
        sock = conn.sock        # 回包带 Connection: close 时 getresponse 会把 conn.sock 清掉，先留住
        sock.settimeout(left())
        resp = conn.getresponse()
        data = b''
        # 读完整个回包 http.client 会自己收尾；回包带 Connection: close 时连 socket 一起关掉，再碰 sock 就报错
        while not resp.isclosed():
            if time.time() - t0 >= DEADLINE:
                raise TimeoutError('%d 秒没收完' % DEADLINE)
            sock.settimeout(left())
            chunk = resp.read1(65536)
            if not chunk:
                break
            data += chunk
        return resp.status, data, time.time() - t0
    finally:
        conn.close()


def call(st, q):
    """问一次 Jev。超时、断网、429 和几种 5xx 就另发一次；拿不到答案返回 {'_error': (原因, 说明)}。"""
    # 请求体与 jev.call 发的一模一样
    body = json.dumps({"model": jev.MODEL, "state": st, "questions": q}).encode()
    last = None
    for i in range(ATTEMPTS):
        try:
            status, data, took = send(body)
        except (OSError, http.client.HTTPException) as e:
            with LOCK:
                STATS['lost'] += 1
            if isinstance(e, TimeoutError) or 'timed out' in str(e):
                last = ('超时', '等了 %d 秒没回，断开了' % DEADLINE)
            else:
                last = ('网络', repr(e)[:200])
            continue
        if status == 200:
            try:
                d = json.loads(data)
            except ValueError:
                last = ('回包', '不是 JSON：%r' % data[:100])
                break
            d['_elapsed'] = took
            with LOCK:
                STATS['calls'] += 1
                STATS['cost'] += (d.get('usage') or {}).get('cost') or 0.0
            return d
        last = (status, data.decode('utf-8', 'replace')[:300])
        if status not in (429, 500, 502, 503, 504, 520, 529):     # 与 jevkit.py 重试的状态码相同
            break
        time.sleep(1)
    return {'_error': (last[0], '%s（一共试了 %d 次）' % (last[1], i + 1))}


def jev_turn(fens, fsf, game):
    """轮到 Jev：返回它这一步的说明（见文件开头的 jev 字段），Jev 没答上来返回 {'error': ...}。"""
    fen = fens[-1]
    legal = b.legal(XQ, fen)
    fxs = b.all_facts(XQ, fen)
    out = {'legal': len(legal), 'candidates': []}
    wins = [m for m in legal if fxs[m]['mate']] + [m for m in legal if fxs[m]['stalemate']]
    if wins:
        return dict(out, move=wins[0], auto='win', options=0)
    ban = banned(fens, fsf, legal)
    allowed = [m for m in legal if m not in ban] or legal
    if len(allowed) == 1:
        return dict(out, move=allowed[0], auto='forced', options=0)
    pos_id = 'play|%s|%d' % (game, len(fsf))
    st, q, k2m = xa.build_request(XQ, fen, ARM, pos_id, fxs={m: fxs[m] for m in allowed}, check=False)
    if fen.split()[1] == 'b':
        q['move']['instructions'] = ASK_BLACK
    r = call(st, q)
    if '_error' in r:
        code, msg = r['_error']
        return {'error': 'Jev 没答上来（%s）：%s' % (code, msg[:200])}
    crit = q['move']['criteria']
    choice, probs, conf = xa.parse_resp(r, crit)
    top = sorted(probs.items(), key=lambda kv: -kv[1])[:TOP]
    u = r.get('usage', {})
    return dict(out, move=k2m[choice], auto=None, options=len(crit), confidence=conf,
                candidates=[{'move': k2m[k], 'text': notation(fen, k2m[k]), 'desc': crit[k], 'p': p} for k, p in top],
                elapsed=round(r['_elapsed'], 3), input_tokens=u.get('input_tokens'), cost=u.get('cost'),
                model=r.get('model'))


def answer(req):
    """处理一次 POST /api/move。请求不对抛 ValueError；Jev 没答上来返回 {'error': ...}。"""
    if not isinstance(req, dict):
        raise ValueError('请求体要是一个 JSON 对象')
    moves, side, game = req.get('moves'), req.get('jev'), req.get('game')
    if not isinstance(moves, list) or len(moves) > MAX_PLIES or not all(isinstance(m, str) and MOVE.match(m) for m in moves):
        raise ValueError('moves 要是从开局起的着法列表（ICCS 坐标，如 h2e2），最多 %d 步' % MAX_PLIES)
    if side not in ('w', 'b'):
        raise ValueError('jev 要是 w（Jev 执红）或 b（Jev 执黑）')
    if not isinstance(game, str) or not GAME.match(game):
        raise ValueError('game 要是 4 到 32 位的小写字母或数字')
    moves = list(moves)
    fens, fsf = replay(moves)
    end = ending(fens, fsf)
    turn = None
    if end is None and fens[-1].split()[1] == side:
        turn = jev_turn(fens, fsf, game)
        if 'error' in turn:
            return turn
        turn['text'] = notation(fens[-1], turn['move'])
        moves.append(turn['move'])
        fsf.append(b.to_fsf(XQ, turn['move']))
        fens.append(sf.get_fen(XQ, fens[-1], [fsf[-1]]))
        remember(moves, fens, fsf)
        end = ending(fens, fsf)
    fen = fens[-1]
    legal = []
    if end is None:
        moves_now = b.legal(XQ, fen)
        ban = banned(fens, fsf, moves_now)
        legal = [{'move': m, 'text': notation(fen, m), 'banned': m in ban} for m in moves_now]
        if all(x['banned'] for x in legal):     # 步步都判负就不拦了，走哪步都是输
            for x in legal:
                x['banned'] = False
    return {'moves': moves, 'record': [notation(fens[i], m) for i, m in enumerate(moves)],
            'fen': fen, 'turn': fen.split()[1], 'check': b.in_check(XQ, fen),
            'legal': legal, 'end': end, 'jev': turn}


class Handler(BaseHTTPRequestHandler):
    hosts = origins = ()
    timeout = 30        # 读请求最多等 30 秒，挡住只连不发的连接

    def reply(self, code, body, ctype='application/json; charset=utf-8'):
        data = body if isinstance(body, bytes) else json.dumps(body, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header('Content-Type', ctype)
        self.send_header('Content-Length', str(len(data)))
        self.send_header('Cache-Control', 'no-store')
        self.end_headers()
        self.wfile.write(data)

    def from_here(self):
        # 只认本机地址，挡住别的网站借浏览器调这个接口（也挡 DNS rebinding）
        origin = self.headers.get('Origin')
        return self.headers.get('Host') in self.hosts and (origin is None or origin in self.origins)

    def do_GET(self):
        if not self.from_here():
            return self.reply(403, {'error': '只接受本机访问'})
        if self.path.split('?')[0] not in ('/', '/index.html'):
            return self.reply(404, {'error': '没有这个地址'})
        self.reply(200, PAGE.read_bytes(), 'text/html; charset=utf-8')

    def do_POST(self):
        if self.path != '/api/move':
            return self.reply(404, {'error': '没有这个地址'})
        if not self.from_here():
            return self.reply(403, {'error': '只接受本机访问'})
        if not self.headers.get('Content-Type', '').startswith('application/json'):
            return self.reply(415, {'error': '要用 application/json'})
        n = self.headers.get('Content-Length', '')
        if not n.isdigit():
            return self.reply(400, {'error': '缺少或写错了 Content-Length'})
        if not 0 < int(n) <= MAX_BODY:
            return self.reply(413, {'error': '请求体要在 1 到 %d 字节之间' % MAX_BODY})
        if not BUSY.acquire(blocking=False):
            return self.reply(429, {'error': '上一步还在等 Jev，稍后再试'})
        try:
            out = answer(json.loads(self.rfile.read(int(n))))
        except ValueError as e:
            return self.reply(400, {'error': str(e)})
        except Exception as e:      # 回包形状不对或本脚本自己出错，都不算请求的错
            out = {'error': '本地脚本没处理好：%r' % (e,)}
        finally:
            BUSY.release()
        if 'error' in out:
            print('  ' + out['error'])
            return self.reply(502, out)
        t = out['jev']
        if t and t['auto']:
            print('  Jev 走 %s（%s，程序直接走，没问 Jev）' % (t['text'], '一步就赢' if t['auto'] == 'win' else '只有这一步'))
        elif t:
            print('  Jev 走 %s  %.2f 秒  %d 个选项  输入 %d tok  $%.7f' % (
                t['text'], t['elapsed'], t['options'], t['input_tokens'] or 0, t['cost'] or 0))
        if out['end']:
            e = out['end']
            print('  对局结束：%s（%s）' % ({'w': '红胜', 'b': '黑胜', None: '和棋'}[e['winner']], e['reason']))
        self.reply(200, out)

    def log_message(self, fmt, *args):
        pass    # 不打每条请求的访问日志，终端只留上面那几行


def main():
    ap = argparse.ArgumentParser(description='在浏览器里和 Jev 下中国象棋')
    ap.add_argument('--port', type=int, default=8766)
    ap.add_argument('--no-browser', action='store_true', help='不自动打开浏览器')
    args = ap.parse_args()
    try:
        srv = ThreadingHTTPServer(('127.0.0.1', args.port), Handler)
    except OSError:
        srv = ThreadingHTTPServer(('127.0.0.1', 0), Handler)    # 端口被占就让系统挑一个
    port = srv.server_address[1]
    Handler.hosts = ('127.0.0.1:%d' % port, 'localhost:%d' % port)
    Handler.origins = tuple('http://' + h for h in Handler.hosts)
    url = 'http://127.0.0.1:%d/' % port
    print('和 Jev 下中国象棋：%s  （模型 %s）' % (url, jev.MODEL))
    print('浏览器没自动打开就手动打开上面的地址。按 Ctrl+C 结束。')
    if not args.no_browser:
        webbrowser.open(url)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        srv.server_close()
        print('\n本次请求 Jev %d 次，花费 $%.6f%s' % (STATS['calls'], STATS['cost'], (
            '；另有 %d 次没拿到回包（超时断开或网络出错），这几次花没花钱不知道' % STATS['lost']
            if STATS['lost'] else '')))


if __name__ == '__main__':
    main()
