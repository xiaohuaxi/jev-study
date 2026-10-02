# -*- coding: utf-8 -*-
"""上下文的三种计数各按什么量算：计费 input_tokens、第一道门（state + 单题）、第二道门（整请求）。

    python3 exp_ctx_count.py run [部分 ...]   # 发请求；已做完的部分 / 已钉死的边界跳过（断点续跑）。不给部分名 = 全部
    python3 exp_ctx_count.py report           # 只读日志出表，不发请求、不需要 key

部分：
  unit    内容 token 的独立量度：随机数字串每位恰 1 token（计费差分验证），中文填充每字几 token
  bill    计费拆解：state（字符串 / 对象 / 数组 / 键名）、三种题型、选项与档位的个数和长度、描述、题名，每种 2 次
  archer  照 Archer Hume 的题形复现 268 / 276 / 318，另把官方文档四个示例原样发一遍
  gate1   第一道门：固定题、只改 state 位数，二分到 1 token；题型、选项、多题、「最长」按什么量取
  gate2   第二道门：多种形状（题多 / 题少、state 长 / 短、选择题 / 打分题 / 对象 state）各二分到 1 token

计数口径：「内容 token」一律用随机数字串造——Jev 的分词把数字逐位切开，N 位数字恰好 N 个 token
（unit 部分用计费差分逐档验证）。所以 state 的位数、题文的位数就是它们的内容 token 数，不需要外部分词器。
每个边界在「过」与「拒」两侧各重发 CONFIRM 次，确认不是偶发。

原始请求逐条追加到 ctx_count_log.jsonl（被 .gitignore 排除，不入库）：每条记部分、边界名、足以复原请求的
形状参数（params，经 realize() 原样还原）、状态码、错误体、usage、耗时、时间戳；成功回包只留答案条数。
随机数字串由种子决定，重跑得到同一批请求。并发不超过 3（二分本身是串行的，只让不同边界并行）。
模型与入口见仓库根部的 jevkit.py（OpenRouter，typesafe/jev-1.13-20260917）；所有 400 max_tokens_exceeded 都是刻意探墙的预期结果。
"""
import json, os, random, ssl, sys, threading, time, urllib.error, urllib.request
from concurrent.futures import ThreadPoolExecutor

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))  # 仓库根部的 jevkit.py
LOG = os.path.join(HERE, "ctx_count_log.jsonl")
PRICE = 0.042 / 1e6
CONFIRM = 4
WORKERS = 3
_lock = threading.Lock()

FILL = '这是一段用于把输入撑到指定长度的中文填充文本，内容本身没有意义。'


# ---------------------------------------------------------------- 请求形状：可序列化的参数 -> 真实请求体
_DIG = {}


def digits(n, seed=0):
    """种子固定的随机数字串；同一种子下短串是长串的前缀，N 与 N+1 只差末尾一位。"""
    if n <= 0:
        return ""
    base = _DIG.get(seed, "")
    if len(base) < n:
        R = random.Random(9000 + seed)
        base = "".join(R.choice("0123456789") for _ in range(max(n, 70000)))
        _DIG[seed] = base
    return base[:n]


def realize(x, i=None):
    """把参数里的宏展开成请求体：
    {"$d": n, "$s": seed}            n 位随机数字串
    {"$zh": n}                       n 个字的中文填充（exp_ctx_rule.py 同款）
    {"$many": n, "key": "q%d", "item": spec}   n 道题（item 里的 {"$i": fmt} 换成序号）
    {"$opts": k, "name": "%d", "desc": spec}   choice 选项表（desc 可为 null）
    {"$levels": k, "desc": spec}               score 档位数组
    {"$i": "fmt"}                    序号代入 fmt
    """
    if isinstance(x, dict):
        if "$d" in x:
            return digits(x["$d"], x.get("$s", 0))
        if "$zh" in x:
            n = x["$zh"]
            return (FILL * (n // len(FILL) + 1))[:n]
        if "$i" in x:
            return x["$i"] % i
        if "$many" in x:
            return {x["key"] % j: realize(x["item"], j) for j in range(x["$many"])}
        if "$opts" in x:
            return {x["name"] % j: realize(x.get("desc"), j) for j in range(x["$opts"])}
        if "$levels" in x:
            return [realize(x["desc"], j) for j in range(x["$levels"])]
        return {k: realize(v, i) for k, v in x.items()}
    if isinstance(x, list):
        return [realize(v, i) for v in x]
    return x


def D(n, s=0):
    return {"$d": n, "$s": s}


def noul(instr="x", crit=None):
    q = {"type": "noul", "instructions": instr}
    if crit is not None:
        q["criteria"] = crit
    return q


def choice(instr="x", crit=None):
    return {"type": "choice", "instructions": instr, "criteria": crit}


def score(instr="x", levels=None):
    return {"type": "score", "instructions": instr, "criteria": levels}


# ---------------------------------------------------------------- 发请求与日志
# jevkit.py 在导入时就要求 key，所以只在真发请求时才导入；report 不需要 key
CTX = ssl.create_default_context()


def post(state, questions):
    from jevkit import KEY, URL, MODEL
    body = json.dumps({"model": MODEL, "state": state, "questions": questions}).encode()
    req = urllib.request.Request(URL, data=body, headers={
        "Authorization": "Bearer " + KEY, "Content-Type": "application/json"})
    attempts = []
    for a in range(6):
        t0 = time.time()
        try:
            with urllib.request.urlopen(req, timeout=180, context=CTX) as r:
                d = json.loads(r.read())
            attempts.append(200)
            return 200, d, None, time.time() - t0, attempts, len(body)
        except urllib.error.HTTPError as e:
            err = e.read().decode("utf-8", "replace")[:600]
            attempts.append(e.code)
            if e.code in (408, 429, 500, 502, 503, 504, 520, 529):
                time.sleep(2.0 * (a + 1))
                continue
            return e.code, None, err, time.time() - t0, attempts, len(body)
        except Exception as e:  # 网络抖动
            attempts.append("net")
            err = repr(e)[:300]
            time.sleep(2.0 * (a + 1))
    return "net", None, err, time.time() - t0, attempts, len(body)


def send(part, tag, params, meta=None):
    state = realize(params["state"])
    qs = realize(params["questions"])
    code, d, err, el, attempts, nbytes = post(state, qs)
    rec = {"ts": time.strftime("%Y-%m-%dT%H:%M:%S"), "part": part, "tag": tag, "meta": meta or {},
           "params": params, "status": code, "attempts": attempts, "bytes": nbytes, "elapsed": round(el, 3),
           "error": err, "usage": (d or {}).get("usage"), "n_answers": len((d or {}).get("answers", {})),
           "model": (d or {}).get("model")}   # 响应里的模型串（服务端解析出的快照）
    from jevkit import URL, MODEL
    rec["req_url"], rec["req_model"] = URL, MODEL   # 2026-09-25 之后新增：请求入口与请求模型
    if d and len(qs) <= 3:  # 小请求留答案，便于核对题型确实被识别
        rec["answers"] = d.get("answers")
    with _lock:
        with open(LOG, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    return rec


def outcome(rec):
    if rec["status"] == 200:
        return "pass"
    if rec["status"] == 400 and rec["error"] and "max_tokens_exceeded" in rec["error"]:
        return "reject"
    return "other"


def load():
    out = []
    if os.path.exists(LOG):
        with open(LOG, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    out.append(json.loads(line))
    return out


# ---------------------------------------------------------------- 二分
def bisect(part, tag, make, guess, info=None, step0=32):
    """make(N) -> params；找最大的「过」的 N。N 是某段数字串的位数（= token 数）。
    先从 guess 起按倍增找一过一拒的夹逼，再二分到相邻；最后 N 与 N+1 各重发 CONFIRM 次。"""
    done = [r for r in load() if r["part"] == part and r["tag"] == tag and r["meta"].get("role") == "confirm"]
    if len(done) >= 2 * CONFIRM:
        print("  [跳过] %s 已钉死" % tag)
        return
    cache = {}

    def probe(n):
        if n not in cache:
            r = send(part, tag, make(n), dict(info or {}, N=n, role="probe"))
            o = outcome(r)
            if o == "other":
                raise RuntimeError("%s N=%d 非预期回应 %s %s" % (tag, n, r["status"], r["error"]))
            cache[n] = o
        return cache[n]

    lo = hi = None
    n = guess
    if probe(n) == "pass":
        lo, step = n, step0
        while hi is None:
            m = lo + step
            if probe(m) == "pass":
                lo = m
            else:
                hi = m
            step *= 2
    else:
        hi, step = n, step0
        while lo is None:
            m = max(hi - step, 0)
            if probe(m) == "pass":
                lo = m
            else:
                hi = m
                if m == 0:
                    raise RuntimeError("%s：N=0 也被拒" % tag)
            step *= 2
    while hi - lo > 1:
        m = (lo + hi) // 2
        if probe(m) == "pass":
            lo = m
        else:
            hi = m
    res = {}
    for n, want in ((lo, "pass"), (hi, "reject")):
        got = []
        for k in range(CONFIRM):
            r = send(part, tag, make(n), dict(info or {}, N=n, role="confirm", want=want))
            got.append(outcome(r))
        res[n] = got
    print("  %-34s 最大过 N=%d（确认 %s）；N=%d（确认 %s）" % (
        tag, lo, "/".join(res[lo]), hi, "/".join(res[hi])))


# ---------------------------------------------------------------- unit / bill / archer：只看计费
QX = {"q": noul("x")}
LET = "abcdefghij"


def unit_jobs():
    J = [("st_empty", {"state": "", "questions": QX}), ("st_x", {"state": "x", "questions": QX})]
    for n in (1, 2, 10, 100, 1000, 10000, 30000):
        J.append(("st_d%d" % n, {"state": D(n), "questions": QX}))
    for n in (100, 1000, 10000):
        J.append(("st_zh%d" % n, {"state": {"$zh": n}, "questions": QX}))
    J.append(("st_zhobj1000", {"state": {"doc": {"$zh": 1000}}, "questions": QX}))
    return J


def bill_jobs():
    J = []
    S = lambda st: {"state": st, "questions": QX}
    # state 的结构与键名
    J += [("st_obj_a_empty", S({"a": ""})), ("st_obj_a_x", S({"a": "x"})), ("st_obj_doc_d100", S({"doc": D(100)})),
          ("st_obj_2keys", S({"a": D(50), "b": D(50, 1)})), ("st_obj_10keys", S({"k%d" % j: D(10, j) for j in range(10)})),
          ("st_obj_nest2", S({"a": {"b": D(100)}})), ("st_obj_nest3", S({"a": {"b": {"c": D(100)}}})),
          ("st_arr1", S([D(100)])), ("st_arr2", S([D(50), D(50, 1)])), ("st_obj_arr", S({"a": [D(50), D(50, 1)]})),
          ("st_obj_key30", S({"k" + "7" * 29: "x"})), ("st_obj_num", S({"a": 12345})), ("st_obj_num1", S({"a": 1})),
          ("st_obj_bool", S({"a": True})), ("st_obj_null", S({"a": None})), ("st_obj_empty", S({})), ("st_arr_empty", S([]))]
    Q = lambda qs: {"state": "x", "questions": qs}
    # noul
    for n in (1, 10, 100, 1000):
        J.append(("n_i_d%d" % n, Q({"q": noul(D(n, 1))})))
    J += [("n_i_obj", Q({"q": noul({"q": "x"})})), ("n_i_arr", Q({"q": noul(["x"])})),
          ("n_crit_tf_x", Q({"q": noul("x", {"true": "x", "false": "x"})})),
          ("n_crit_tf_d10", Q({"q": noul("x", {"true": D(10, 2), "false": D(10, 3)})})),
          ("n_crit_t_x", Q({"q": noul("x", {"true": "x"})})), ("n_crit_f_x", Q({"q": noul("x", {"false": "x"})})),
          ("n_crit_only", Q({"q": {"type": "noul", "criteria": {"true": "x", "false": "x"}}}))]
    # 题名（键名）
    J += [("key_a", Q({"a": noul("x")})), ("key_50x", Q({"x" * 50: noul("x")})), ("key_d30", Q({"7" * 30: noul("x")})),
          ("key_zh", Q({"问题一": noul("x")})), ("key_200", Q({"k" * 200: noul("x")}))]
    # 题数
    for n in (1, 2, 3, 5, 10, 100, 1000):
        J.append(("n_count%d" % n, Q({"$many": n, "key": "q%d", "item": noul("x")})))
    # choice：选项个数、名字长度、描述
    for k in (2, 3, 4, 5, 10):
        J.append(("c_k%d" % k, Q({"q": choice("x", {"$opts": k, "name": "%d", "desc": None})})))
    J += [("c_k100", Q({"q": choice("x", {"$opts": 100, "name": "%03d", "desc": None})})),
          ("c_k255", Q({"q": choice("x", {"$opts": 255, "name": "%03d", "desc": None})})),
          ("c_k2_desc_empty", Q({"q": choice("x", {"0": "", "1": ""})})),
          ("c_k2_desc_x", Q({"q": choice("x", {"0": "x", "1": "x"})})),
          ("c_k2_desc_d10", Q({"q": choice("x", {"0": D(10, 2), "1": D(10, 3)})})),
          ("c_k2_desc_d100", Q({"q": choice("x", {"0": D(100, 2), "1": D(100, 3)})})),
          ("c_k2_name_d10", Q({"q": choice("x", {"1" + digits(9, 2): None, "2" + digits(9, 3): None})})),
          ("c_k2_name_ab", Q({"q": choice("x", {"a": None, "b": None})})),
          ("c_i_d100", Q({"q": choice(D(100, 1), {"0": None, "1": None})})),
          ("c_desc_obj", Q({"q": choice("x", {"0": {"a": "x"}, "1": None})}))]
    # score：档位个数、描述长度
    for k in (2, 3, 4, 5, 10):
        J.append(("s_k%d" % k, Q({"q": score("x", {"$levels": k, "desc": {"$i": "%d"}})})))
    J += [("s_k2_x", Q({"q": score("x", ["x", "x"])})), ("s_k2_ab", Q({"q": score("x", ["a", "b"])})),
          ("s_k2_d10", Q({"q": score("x", [D(10, 2), D(10, 3)])})),
          ("s_k2_d100", Q({"q": score("x", [D(100, 2), D(100, 3)])})),
          ("s_i_d100", Q({"q": score(D(100, 1), ["0", "1"])})),
          ("s_k2_empty", Q({"q": score("x", ["", ""])}))]
    # 选项描述有的有、有的没有（混合）时是否另算
    J += [("c_mix_x_null", Q({"q": choice("x", {"0": "x", "1": None})})),
          ("c_mix_x_empty", Q({"q": choice("x", {"0": "x", "1": ""})})),
          ("c_mix_d10_null", Q({"q": choice("x", {"0": D(10, 2), "1": None})})),
          ("c_k3_mix_x_null_null", Q({"q": choice("x", {"0": "x", "1": None, "2": None})})),
          ("c_k3_mix_x_x_null", Q({"q": choice("x", {"0": "x", "1": "x", "2": None})})),
          ("c_k3_all_x", Q({"q": choice("x", {"0": "x", "1": "x", "2": "x"})})),
          ("c_desc_obj_both", Q({"q": choice("x", {"0": {"a": "x"}, "1": {"a": "x"}})})),
          ("c_desc_arr_both", Q({"q": choice("x", {"0": ["x"], "1": ["x"]})})),
          ("s_k3_d10_1_2", Q({"q": score("x", [D(10, 3), "1", "2"])})),
          ("c_i_d100_mix_d10", Q({"q": choice(D(100, 1), {"0": D(10, 2), "1": None})})),
          ("s_i_d50_k3", Q({"q": score(D(50, 1), [D(10, 3), "1", "2"])}))]
    # 混合：可加性
    J += [("mix_ncs", Q({"a": noul("x"), "b": choice("x", {"0": None, "1": None}), "c": score("x", ["0", "1"])})),
          ("mix_cs_long", Q({"a": choice(D(100, 1), {"0": D(10, 2), "1": None}), "b": score(D(50, 1), [D(10, 3), "1", "2"])})),
          ("mix_all_d1000", {"state": D(1000), "questions": {"a": noul(D(100, 1)), "b": choice(D(100, 1), {"0": D(10, 2), "1": None}),
                                                             "c": score(D(50, 1), [D(10, 3), "1", "2"])}})]
    return J


def archer_jobs():
    """Archer 的 type_preamble 那组题形没公开原始请求（证据包只有计数）；state 与 noul 已知是 "x"（见他的
    output-token-accounting 证据：state "x" + noul "x" = 268），choice / score 用几种最小写法各试一遍。"""
    Q = lambda qs: {"state": "x", "questions": qs}
    n = noul("x")
    J = [("n", Q({"n1": n})), ("nn", Q({"n1": n, "n2": noul("x")})), ("n_longkey", Q({"n" * 40: n})),
         ("n_crit", Q({"n1": noul("x", {"true": "x", "false": "x"})})), ("n_crit_true", Q({"n1": noul("x", {"true": "x"})}))]
    C = {"ab_null": {"a": None, "b": None}, "ab_x": {"a": "x", "b": "x"}, "yesno_null": {"yes": None, "no": None},
         "xy_null": {"x": None, "y": None}}
    Sv = {"ab": ["a", "b"], "xx": ["x", "x"], "lowhigh": ["low", "high"], "01": ["0", "1"]}
    for cn, cc in C.items():
        J.append(("c_" + cn, Q({"c1": choice("x", cc)})))
    for sn, ss in Sv.items():
        J.append(("s_" + sn, Q({"s1": score("x", ss)})))
    J += [("ncs_ab", Q({"n1": n, "c1": choice("x", C["ab_null"]), "s1": score("x", Sv["ab"])})),
          ("c3_abc", Q({"c1": choice("x", {"a": None, "b": None, "c": None})})),
          ("c4_abcd", Q({"c1": choice("x", {"a": None, "b": None, "c": None, "d": None})})),
          ("s3_abc", Q({"s1": score("x", ["a", "b", "c"])}))]
    # 官方文档 api 页的四个示例，原样
    st = "Help! My payouts have been failing for 3 days."
    J += [("doc_noul", {"state": st, "questions": {"is_urgent": noul("Does this convey urgency?", {
              "true": "Explicitly time-sensitive", "false": "No urgency expressed"})}}),
          ("doc_noul_plain", {"state": st, "questions": {"is_urgent": noul("Does this convey urgency?")}}),
          ("doc_choice", {"state": st, "questions": {"department": choice("Which team should handle this?", {
              "billing": "Payments, invoicing, refunds", "technical": "Bugs, outages, integrations",
              "sales": "Pricing, upgrades, new accounts"})}}),
          ("doc_score", {"state": st, "questions": {"frustration": score("How frustrated is the customer?",
                                                                         ["Calm", "Frustrated", "Very angry"])}})]
    return J


def run_fixed(part, jobs, reps):
    have = {}
    for r in load():
        if r["part"] == part:
            have[r["tag"]] = have.get(r["tag"], 0) + 1
    todo = [(t, p) for t, p in jobs for _ in range(max(0, reps - have.get(t, 0)))]
    print("== %s：%d 条待发（已有 %d 种）" % (part, len(todo), len(have)))
    with ThreadPoolExecutor(max_workers=WORKERS) as ex:
        list(ex.map(lambda tp: send(part, tp[0], tp[1]), todo))


# ---------------------------------------------------------------- gate1 / gate2：二分
def many_x(n):
    return {"$many": n, "key": "q%d", "item": noul("x")}


def G1():
    """(边界名, 题表, state 构造)；N = state 里那段数字串的位数。"""
    plain = lambda n: D(n)
    A = noul(D(6000, 1))
    B = choice("x", {"$opts": 4, "name": "%d", "desc": D(2000, 3)})
    L = [
        ("noul_x", {"q": noul("x")}, plain),
        ("noul_d1000", {"q": noul(D(1000, 1))}, plain),
        ("noul_d10000", {"q": noul(D(10000, 1))}, plain),
        ("noul_d20000", {"q": noul(D(20000, 1))}, plain),
        ("noul_crit_d5000x2", {"q": noul("x", {"true": D(5000, 5), "false": D(5000, 6)})}, plain),
        ("choice_k2", {"q": choice("x", {"0": None, "1": None})}, plain),
        ("choice_k255", {"q": choice("x", {"$opts": 255, "name": "%03d", "desc": None})}, plain),
        ("choice_k5_desc2000", {"q": choice("x", {"$opts": 5, "name": "%d", "desc": D(2000, 3)})}, plain),
        ("score_k2", {"q": score("x", ["0", "1"])}, plain),
        ("score_k10_desc1000", {"q": score("x", {"$levels": 10, "desc": D(1000, 4)})}, plain),
        ("multi_d10000_d5000", {"a": noul(D(10000, 1)), "b": noul(D(5000, 2))}, plain),
        ("multi_300x_d10000", dict(realize(many_x(300)), z=noul(D(10000, 1))), plain),
        ("which_A_instr6000", {"a": A}, plain),
        ("which_B_opts4x2000", {"b": B}, plain),
        ("which_AB", {"a": A, "b": B}, plain),
        ("key_200", {"k" * 200: noul("x")}, plain),
        ("state_obj_doc", {"q": noul("x")}, lambda n: {"doc": D(n)}),
        ("state_obj_plus5000", {"q": noul("x")}, lambda n: {"a": D(n), "b": D(5000, 7)}),
        ("zh_obj_oldstyle", {"q": noul("这段文本是否没有意义？")}, lambda n: {"doc": {"$zh": n}}),
        ("zh_plain_oldstyle", {"q": noul("这段文本是否没有意义？")}, lambda n: {"$zh": n}),
        # 反过来：state 为空，N 落在题文里（state 与题文是否按同一把尺子算）
        ("qvar_state_empty", lambda n: {"q": noul(D(n, 1))}, lambda n: ""),
    ]
    return L


def G2():
    L = [
        ("many7000_x", many_x(7000), lambda n: D(n)),
        ("many4200_x_bigstate", many_x(4200), lambda n: D(n)),
        ("few3_d21000", {"a": noul(D(21000, 1)), "b": noul(D(21000, 2)), "c": noul(D(21000, 3))}, lambda n: D(n)),
        ("q1000_d50", {"$many": 1000, "key": "q%d", "item": noul(D(50, 1))}, lambda n: D(n)),
        ("choice30_k255", {"$many": 30, "key": "c%d", "item": choice("x", {"$opts": 255, "name": "%03d", "desc": None})},
         lambda n: D(n)),
        ("score390_k10_d10", {"$many": 390, "key": "s%d", "item": score("x", {"$levels": 10, "desc": D(10, 4)})},
         lambda n: D(n)),
        ("objstate_5000x", many_x(5000), lambda n: {"a": D(n), "b": D(1000, 7), "c": {"d": D(1000, 8)}}),
        ("qvar_state_empty_4q", lambda n: {"a": noul(D(21000, 1)), "b": noul(D(21000, 2)), "c": noul(D(21000, 3)),
                                           "d": noul(D(n, 4))}, lambda n: ""),
    ]
    return L


def run_search(part, tag, qs, stf, target):
    """先发 N=0（state 段为空）拿到这个形状的固定计费 b0，按 target - b0 猜边界，再二分。
    qs 可以是函数（N 落在题文里）：题文不能为空，于是用 N=1 的计费减 1 当 b0。"""
    varq = callable(qs)
    mk = lambda n: {"state": stf(n), "questions": qs(n) if varq else qs}
    base = [r for r in load() if r["part"] == part and r["tag"] == tag and r["meta"].get("role") == "zero"
            and r["status"] == 200]
    if base:
        b0 = base[0]["usage"]["input_tokens"]
    else:
        n0 = 1 if varq else 0
        r = send(part, tag, mk(n0), {"N": n0, "role": "zero"})
        if r["status"] != 200:
            raise RuntimeError("%s N=%d 失败 %s %s" % (tag, n0, r["status"], r["error"]))
        b0 = r["usage"]["input_tokens"] - n0
    guess = max(target - b0, 1)
    bisect(part, tag, mk, guess, {"b0": b0}, step0=8)


def run_gates(part, specs, target):
    print("== %s：%d 个边界" % (part, len(specs)))
    with ThreadPoolExecutor(max_workers=WORKERS) as ex:
        futs = [ex.submit(run_search, part, t, q, f, target) for t, q, f in specs]
        for f in futs:
            f.result()


BUILDERS = {
    "unit": lambda: run_fixed("unit", unit_jobs(), 2),
    "bill": lambda: run_fixed("bill", bill_jobs(), 2),
    "archer": lambda: run_fixed("archer", archer_jobs(), 2),
    "gate1": lambda: run_gates("gate1", G1(), 33003),
    "gate2": lambda: run_gates("gate2", G2(), 65792),
}


# ---------------------------------------------------------------- report（只读日志）
# Archer Hume 证据包 tokenAccounting 与 output-token-accounting 里的计费；doc_* 是官方 api 页示例回包里印的数
#（noul 那节同一请求印了两个数 296 与 307；这些示例数不一定是那个请求的真实回包）
ARCHER = {"n": 268, "nn": 276, "n_longkey": 268, "n_crit": 286, "n_crit_true": 280, "c_ab_null": 284, "s_ab": 286,
          "ncs_ab": 318, "c3_abc": 290, "c4_abcd": 296, "s3_abc": 292}
DOCS = {"doc_noul": "296 / 307", "doc_choice": "318", "doc_score": "304"}


def spend_line(rs):
    tok = sum((r["usage"] or {}).get("input_tokens", 0) for r in rs)
    return "%d 次请求（200：%d，拒：%d），计费输入 %d tok，$%.4f" % (
        len(rs), sum(1 for r in rs if r["status"] == 200), sum(1 for r in rs if outcome(r) == "reject"), tok, tok * PRICE)


def billed(rs, tag):
    v = sorted(set(r["usage"]["input_tokens"] for r in rs if r["tag"] == tag and r["status"] == 200))
    return v


def rep_fixed(log, part, ref=None):
    rs = [r for r in log if r["part"] == part]
    if not rs:
        return {}
    print("\n## %s（%s）" % (part, spend_line(rs)))
    tags = []
    for r in rs:
        if r["tag"] not in tags:
            tags.append(r["tag"])
    out = {}
    print("| 形状 | 计费 input_tokens（各次去重） | 相对 %s |" % (ref or "—"))
    print("|---|---:|---:|")
    for t in tags:
        v = billed(rs, t)
        bad = [r for r in rs if r["tag"] == t and r["status"] != 200]
        if v:
            out[t] = v[0]
        refv = ref if isinstance(ref, int) else None
        d = ("%+d" % (v[0] - refv)) if (v and refv is not None) else ""
        err = ("；失败 %d：%s" % (len(bad), (bad[0]["error"] or "")[:80])) if bad else ""
        extra = ("（Archer %d）" % ARCHER[t]) if part == "archer" and t in ARCHER else ""
        extra += ("（文档示例 %s）" % DOCS[t]) if part == "archer" and t in DOCS else ""
        print("| %s | %s%s | %s |" % (t, "/".join(map(str, v)) or "—", extra + err, d))
    return out


def rep_gate(log, part, cap):
    rs = [r for r in log if r["part"] == part]
    if not rs:
        return
    print("\n## %s（%s）" % (part, spend_line(rs)))
    print("| 边界 | b0（N=0 计费） | 最大过 N | 过侧确认 | 拒侧确认 | 过侧计费 | 计费−b0 | %d−过侧计费 | 请求数 |" % cap)
    print("|---|---:|---:|---|---|---:|---:|---:|---:|")
    tags = []
    for r in rs:
        if r["tag"] not in tags:
            tags.append(r["tag"])
    for t in tags:
        g = [r for r in rs if r["tag"] == t]
        z = [r for r in g if r["meta"].get("role") == "zero" and r["status"] == 200]
        b0 = (z[0]["usage"]["input_tokens"] - z[0]["meta"]["N"]) if z else None
        passN = [r["meta"]["N"] for r in g if r["meta"].get("role") in ("probe", "confirm") and outcome(r) == "pass"]
        rejN = [r["meta"]["N"] for r in g if r["meta"].get("role") in ("probe", "confirm") and outcome(r) == "reject"]
        other = [r for r in g if outcome(r) == "other"]
        if not passN:
            print("| %s | %s | — | | | | | | %d |" % (t, b0, len(g)))
            continue
        lo = max(passN)
        bad = [n for n in rejN if n <= lo] + [n for n in passN if rejN and n >= min(rejN)]
        cf = lambda n: "".join("过" if outcome(r) == "pass" else "拒" for r in g
                               if r["meta"].get("role") == "confirm" and r["meta"]["N"] == n)
        bl = sorted(set(r["usage"]["input_tokens"] for r in g if r["status"] == 200 and r["meta"]["N"] == lo))
        print("| %s | %s | %d | %s | %s | %s | %s | %s | %d%s |" % (
            t, b0, lo, cf(lo), cf(lo + 1), "/".join(map(str, bl)),
            (bl[0] - b0) if (bl and b0 is not None) else "", (cap - bl[0]) if bl else "", len(g),
            ("；不单调 %s" % bad) if bad else "" + ("；其他错误 %d" % len(other) if other else "")))


# ---------------------------------------------------------------- 计费公式（由 bill 部分拆出来；report 用它逐条复算）
F_REQ, F_NOUL, F_CHOICE, F_SCORE, F_ITEM, F_DESC_HDR = 259, 7, 11, 13, 5, 6
_ZH = set(FILL + "？这段文本是否没有意义")


def tok(v):
    """内容 token 数：只对本脚本造得出确数的文本给值（数字串逐位 1 token、中文填充逐字 1 token、单个短英文词 1 token），
    其余（对象、数组、一般英文句子）返回 None，不参与复算。"""
    if not isinstance(v, str):
        return None
    if v == "":
        return 0
    if v.isdigit() or all(c in _ZH for c in v):
        return len(v)
    if v.isascii() and v.isalpha() and len(v) <= 4:
        return 1
    return None


def q_cost(q):
    t = q["type"]
    parts = [tok(q.get("instructions", ""))]
    if t == "noul":
        base = F_NOUL
        c = q.get("criteria")
        if c:
            base += F_DESC_HDR + sum(F_ITEM for _ in c)
            parts += [tok(v) for v in c.values()]
    elif t == "choice":
        c = q["criteria"]
        base = F_CHOICE + F_ITEM * len(c)
        parts += [tok(k) for k in c]
        if any(c.values()):
            descs = [v for v in c.values() if v is not None]
            base += F_DESC_HDR + F_ITEM * len(descs)
            parts += [tok(v) for v in descs]
    else:
        c = q["criteria"]
        base = F_SCORE + F_ITEM * len(c)
        parts += [tok(v) for v in c]
    if any(x is None for x in parts):
        return None
    return base + sum(parts)


def predict(params):
    """按公式算计费与「state + 最贵单题」；算不出（含对象 state 等）返回 (None, None)。"""
    st = tok(realize(params["state"]))
    qs = realize(params["questions"])
    cs = [q_cost(q) for q in qs.values()]
    if st is None or any(c is None for c in cs):
        return None, None
    return F_REQ + st + sum(cs), st + max(cs)


def rep_formula(log):
    ok = [r for r in log if r["status"] == 200]
    hit = miss = skip = 0
    bad = []
    for r in ok:
        b, _ = predict(r["params"])
        if b is None:
            skip += 1
        elif b == r["usage"]["input_tokens"]:
            hit += 1
        else:
            miss += 1
            bad.append((r["part"], r["tag"], b, r["usage"]["input_tokens"]))
    print("\n## 公式复算：计费 = %d + T(state) + Σ题；noul %d+T(题文)[+%d+Σ(%d+T(真/假描述))]；choice %d+T(题文)+Σ(%d+T(选项名))"
          "[有非空描述时 +%d+Σ非 null 描述(%d+T)]；score %d+T(题文)+Σ(%d+T(档位))" % (
              F_REQ, F_NOUL, F_DESC_HDR, F_ITEM, F_CHOICE, F_ITEM, F_DESC_HDR, F_ITEM, F_SCORE, F_ITEM))
    print("成功请求 %d 条：公式可算 %d 条，逐条相等 %d、不等 %d；含对象 / 英文句子等不可算 %d 条" % (len(ok), hit + miss, hit, miss, skip))
    for x in bad[:10]:
        print("  不等：%s %s 预测 %d 实际 %d" % x)


def rep_branch(log):
    rs = [r for r in log if r["part"] == "gate1" and r["meta"].get("role") in ("probe", "confirm")]
    tags = []
    for r in rs:
        if r["tag"] not in tags:
            tags.append(r["tag"])
    print("\n## gate1 按公式换算：state + 最贵单题（计费单位）在最大过点与最小拒点")
    print("| 边界 | 过：state+最贵单题 | 拒：state+最贵单题 | 32768 − 过 |")
    print("|---|---:|---:|---:|")
    for t in tags:
        g = [r for r in rs if r["tag"] == t]
        ps = [predict(r["params"])[1] for r in g if outcome(r) == "pass"]
        js = [predict(r["params"])[1] for r in g if outcome(r) == "reject"]
        if None in ps or None in js or not ps or not js:
            print("| %s | （对象 state，公式不覆盖） | | |" % t)
            continue
        print("| %s | %d | %d | %d |" % (t, max(ps), min(js), 32768 - max(ps)))


def report():
    log = load()
    if not log:
        raise SystemExit("日志为空：先 python3 exp_ctx_count.py run")
    rep_fixed(log, "unit", 267)
    rep_fixed(log, "bill", 268)
    rep_fixed(log, "archer", 268)
    rep_gate(log, "gate1", 32768)
    rep_gate(log, "gate2", 65536)
    rep_formula([r for r in log if r["part"] != "pilot"])
    rep_branch(log)
    main = [r for r in log if r["part"] != "pilot"]
    print("\n日志合计（不含 pilot）：" + spend_line(main))
    print("含 pilot：" + spend_line(log))


if __name__ == "__main__":
    args = sys.argv[1:]
    if args and args[0] == "run":
        gs = args[1:] or list(BUILDERS)
        for g in gs:
            if g not in BUILDERS:
                raise SystemExit("未知部分 %s；可选 %s" % (g, " ".join(BUILDERS)))
        for g in gs:
            BUILDERS[g]()
    elif args == ["report"]:
        report()
    else:
        raise SystemExit(__doc__)
