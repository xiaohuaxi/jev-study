"""在浏览器里和 Jev 下国际象棋：一条命令起本地服务，自动打开网页。

    export OPENROUTER_API_KEY="sk-or-v1-..."     # 或 API_KEY_OPENROUTER
    python3 games/play_chess.py                  # 可加 --port 9000、--no-browser

只用标准库，Python 3.9 起。棋盘和棋规都在网页里（chess.js 算当前局面的全部合法着法）；
本脚本只做一件事：把网页送来的局面拼成请求发给 Jev，把回答交回网页。

交给 Jev 的内容和 exp_game_chess.py 里 ask() 发的逐字一致——FEN、轮到谁、全部合法着法
（键是 UCI、描述是 SAN，排列顺序与 python-chess 相同）、同一句问题——所以那份实验的结论
可以直接沿用。逐字比对见 play_chess_check.py。

合法着法由网页算好送来，本脚本只查格式、不重新核对合不合法（只用标准库就没有棋规库）：
它信任本机这个网页。网页里的库从 jsdelivr 加载、和网页同源运行，理论上也能借这个接口
调 Jev（拿不到 key）；所以同时在途的请求最多 2 个。

key 只在本进程里用：不进网页、不打印、不写日志。服务只监听 127.0.0.1。

网页只用一个接口：POST /api/move
  请求  {"fen": "...", "moves": [{"uci": "e2e4", "san": "e4"}, ...]}   moves = 当前局面全部合法着法
  回答  {"move": "e7e5", "san": "e5", "candidates": [{"uci": ..., "san": ..., "p": ...}, ...],
         "confidence": 0.61, "legal": 20, "elapsed": 0.93, "input_tokens": 612,
         "cost": 2.6e-05, "model": "typesafe/jev-1.13-20260917"}
  出错  {"error": "..."}，4xx 是请求不对（429 是上一步还没回来），502 是 Jev 那边没答上来
"""
# 让本脚本从任意目录都能找到仓库根部的 jevkit.py
import sys as _sys, pathlib as _pathlib
_sys.path.insert(0, str(_pathlib.Path(__file__).resolve().parent.parent))
import argparse, http.client, json, re, threading, time, urllib.parse, webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import jevkit as jev

PAGE = _pathlib.Path(__file__).resolve().parent / 'play_chess.html'
UCI = re.compile(r'^[a-h][1-8][a-h][1-8][qrbn]?$')
SAN = re.compile(r'^[A-Za-z0-9=+#\-]{2,8}$')
CASTLE = re.compile(r'^(-|K?Q?k?q?)$')
EP = re.compile(r'^(-|[a-h][36])$')
FILES = 'abcdefgh'
TOP = 5            # 回给网页的候选数
MAX_BODY = 65536
DEADLINE = 20      # 一次调用最多等几秒。平时 1 秒上下，偶尔会有一次拖几十秒，
ATTEMPTS = 2       # 到点就断开另发一次；最坏约 40 秒后报错，网页上有「重试」
BUSY = threading.BoundedSemaphore(2)     # 同时在途的请求上限
STATS = {'calls': 0, 'cost': 0.0, 'lost': 0}   # lost：没拿到回包的次数（超时断开或网络出错），花没花钱不知道
LOCK = threading.Lock()


def sq(name):
    """'e4' -> python-chess 的格子编号（a1=0 … h8=63）"""
    return (int(name[1]) - 1) * 8 + FILES.index(name[0])


def parse_board(placement):
    """FEN 第一段 -> {格子编号: 棋子字母}"""
    rows = placement.split('/')
    if len(rows) != 8:
        raise ValueError('FEN 的棋盘不是 8 行')
    board = {}
    for i, row in enumerate(rows):
        rank, f = 7 - i, 0
        for ch in row:
            if ch in '12345678':
                f += int(ch)
            elif ch in 'pnbrqkPNBRQK' and f < 8:
                board[rank * 8 + f] = ch
                f += 1
            else:
                raise ValueError('FEN 的棋盘写得不对')
        if f != 8:
            raise ValueError('FEN 的棋盘写得不对')
    return board


def attacked(board, square, by_white):
    """square 是否被 by_white 一方攻击。只用来判断轮到的一方是不是被将军。"""
    r, f = divmod(square, 8)
    own = str.upper if by_white else str.lower

    def at(rr, ff):
        return board.get(rr * 8 + ff) if 0 <= rr < 8 and 0 <= ff < 8 else None

    pr = r - 1 if by_white else r + 1
    if own('p') in (at(pr, f - 1), at(pr, f + 1)):
        return True
    for dr, df in ((1, 2), (2, 1), (-1, 2), (-2, 1), (1, -2), (2, -1), (-1, -2), (-2, -1)):
        if at(r + dr, f + df) == own('n'):
            return True
    for dr in (-1, 0, 1):
        for df in (-1, 0, 1):
            if (dr or df) and at(r + dr, f + df) == own('k'):
                return True
    for dirs, kinds in ((((1, 0), (-1, 0), (0, 1), (0, -1)), 'rq'),
                        (((1, 1), (1, -1), (-1, 1), (-1, -1)), 'bq')):
        for dr, df in dirs:
            rr, ff = r + dr, f + df
            while 0 <= rr < 8 and 0 <= ff < 8:
                p = board.get(rr * 8 + ff)
                if p:
                    if p in [own(k) for k in kinds]:
                        return True
                    break
                rr, ff = rr + dr, ff + df
    return False


def is_ep(board, uci):
    """兵斜着走到空格，只可能是吃过路兵。"""
    return board[sq(uci[:2])] in 'Pp' and uci[0] != uci[2] and sq(uci[2:4]) not in board


def order_key(board, in_check, uci):
    """复现 python-chess generate_legal_moves 的枚举顺序。

    没被将军：非兵的子按起点格从大到小（同一子按终点从大到小）→ 易位（短在前）→ 兵吃子
    （起点、终点从大到小，升变按后车象马）→ 兵走一格（终点从大到小）→ 兵走两格 → 吃过路兵。
    被将军：王的着法排最前（终点从大到小），其余同上。
    """
    fr, to = sq(uci[:2]), sq(uci[2:4])
    promo = 'qrbn'.index(uci[4]) if len(uci) == 5 else 0
    piece = board[fr].lower()
    if piece == 'k' and abs(fr - to) == 2:
        return (1, -to)
    if piece == 'k' and in_check:
        return (-1, -to)
    if piece != 'p':
        return (0, -fr, -to)
    if is_ep(board, uci):
        return (5, -fr)
    if uci[0] != uci[2]:
        return (2, -fr, -to, promo)
    if abs(fr - to) == 8:
        return (3, -to, promo)
    return (4, -to)


def build(fen, moves):
    """网页送来的局面 -> 交给 Jev 的 state 和 questions，与 exp_game_chess.py 的 ask() 逐字一致。"""
    fields = fen.split(' ') if isinstance(fen, str) else []
    if (len(fields) != 6 or fields[1] not in ('w', 'b') or not CASTLE.match(fields[2])
            or not fields[2] or not EP.match(fields[3]) or not fields[4].isdigit() or not fields[5].isdigit()):
        raise ValueError('FEN 格式不对')
    board = parse_board(fields[0])
    white = fields[1] == 'w'
    kings = [s for s, p in board.items() if p == ('K' if white else 'k')]
    if len(kings) != 1:
        raise ValueError('轮到的一方要有且只有一个王')
    if not isinstance(moves, list) or not 1 <= len(moves) <= 255:
        raise ValueError('moves 要列出当前局面的全部合法着法（1 到 255 个）')
    seen = set()
    for m in moves:
        u, s = (m.get('uci'), m.get('san')) if isinstance(m, dict) else (None, None)
        if not isinstance(u, str) or not UCI.match(u) or not isinstance(s, str) or not SAN.match(s):
            raise ValueError('着法格式不对：%r' % (m,))
        p = board.get(sq(u[:2]))
        if u in seen or p is None or p.isupper() != white:
            raise ValueError('着法和局面对不上：%s' % u)
        seen.add(u)
    in_check = attacked(board, kings[0], not white)
    ordered = sorted(moves, key=lambda m: order_key(board, in_check, m['uci']))
    # python-chess 的 FEN 只在真能吃过路兵时才写过路兵格
    ep = [m['uci'][2:4] for m in moves if is_ep(board, m['uci'])]
    fields[3] = ep[0] if ep else '-'

    # 以下照抄 exp_game_chess.py 的 ask()；对局里 extra 恒为空串
    crit = {}
    for m in ordered:
        crit[m['uci']] = m['san']
    st = {'fen': ' '.join(fields), 'side_to_move': 'white' if white else 'black',
          'legal_moves_uci': sorted(crit.keys())}
    q = {'move': jev.choice(
        '你在下国际象棋，执%s。从合法着法里选一步最好的。%s' % (
            '白' if white else '黑', ''), crit)}
    return st, q


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
    """问一次 Jev。超时、断网、429/5xx 就另发一次；拿不到答案返回 {'_error': (原因, 说明)}。"""
    # 请求体与 jevkit.call 发的一模一样
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


def answer(fen, moves):
    """问 Jev 走哪一步。请求不对抛 ValueError；Jev 没答上来返回 {'error': ...}。"""
    st, q = build(fen, moves)
    r = call(st, q)
    if '_error' in r:
        code, msg = r['_error']
        return {'error': 'Jev 没答上来（%s）：%s' % (code, msg[:200])}
    a = r['answers']['move']
    san = q['move']['criteria']
    top = sorted(a['probabilities'].items(), key=lambda kv: -kv[1])[:TOP]
    u = r.get('usage', {})
    return {'move': a['choice'], 'san': san[a['choice']],
            'candidates': [{'uci': k, 'san': san[k], 'p': p} for k, p in top],
            'confidence': a.get('confidence'), 'legal': len(san),
            'elapsed': round(r['_elapsed'], 3), 'input_tokens': u.get('input_tokens'),
            'cost': u.get('cost'), 'model': r.get('model', jev.MODEL)}


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
            req = json.loads(self.rfile.read(int(n)))
            if not isinstance(req, dict):
                raise ValueError('请求体要是一个 JSON 对象')
            out = answer(req.get('fen'), req.get('moves'))
        except ValueError as e:
            return self.reply(400, {'error': str(e)})
        except Exception as e:      # 回包形状不对或本脚本自己出错，都不算请求的错
            out = {'error': '本地脚本没处理好 Jev 的回答：%r' % (e,)}
        finally:
            BUSY.release()
        if 'error' in out:
            print('  ' + out['error'])
            return self.reply(502, out)
        print('  Jev 走 %-7s %.2f 秒  %d 个候选  输入 %d tok  $%.7f' % (
            out['san'], out['elapsed'], out['legal'], out['input_tokens'] or 0, out['cost'] or 0))
        self.reply(200, out)

    def log_message(self, fmt, *args):
        pass    # 不打每条请求的访问日志，终端只留上面那行


def main():
    ap = argparse.ArgumentParser(description='在浏览器里和 Jev 下国际象棋')
    ap.add_argument('--port', type=int, default=8765)
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
    print('和 Jev 下棋：%s  （模型 %s）' % (url, jev.MODEL))
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
