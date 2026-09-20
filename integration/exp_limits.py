# 让本脚本从任意目录都能找到仓库根部的 jevkit.py / corpus.py
import sys as _sys, pathlib as _pathlib
_sys.path.insert(0, str(_pathlib.Path(__file__).resolve().parent.parent))
# -*- coding: utf-8 -*-
"""接口边界：题型上限、state 形态、入口等价性、聊天接口拒绝、并发。

对应报告：jev-integration-measured.md 的「边界」「返回长什么样」「延迟与并发」几节。
其中多条本就期望收到 4xx，jev.spend() 里的 fail 计数是预期结果。
"""
import json, sys, time, urllib.error, urllib.request
from concurrent.futures import ThreadPoolExecutor
sys.path.insert(0, __import__("os").path.dirname(__import__("os").path.abspath(__file__)))
import jevkit as jev

def post(path, body, key=None):
    req = urllib.request.Request("https://openrouter.ai/api" + path,
        data=json.dumps(body).encode(),
        headers={"Authorization": "Bearer " + (key or jev.KEY), "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=90, context=jev.CTX) as r:
            return 200, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()[:120]

Q = {"q": jev.noul("Is this a bug?")}
S = "blank page after payment"

print("=== 题型上限 ===")
for label, q in [
 ("choice 255 项", {"q": jev.choice("which?", {f"k{i}": f"bucket {i}" for i in range(255)})}),
 ("choice 256 项", {"q": jev.choice("which?", {f"k{i}": f"bucket {i}" for i in range(256)})}),
 ("score 10 档",   {"q": jev.score("how bad?", [f"level {i}" for i in range(10)])}),
 ("score 11 档",   {"q": jev.score("how bad?", [f"level {i}" for i in range(11)])}),
 ("questions 为空", {}),
]:
    code, r = post("/v1/systemone", {"model": jev.MODEL, "state": S, "questions": q})
    print("  %-14s -> %s %s" % (label, code, "" if code == 200 else str(r)[:90]))

print("\n=== state 的四种形态 ===")
for label, st in [
 ("字符串", S),
 ("对象",   {"ticket": S, "tier": "enterprise", "retries": 2}),
 ("数组",   [{"text": S}, {"text": "tier: enterprise"}]),
 ("嵌套",   {"ticket": {"body": S, "events": [{"at": "09:12", "what": "charge ok"}]}}),
]:
    code, r = post("/v1/systemone", {"model": jev.MODEL, "state": st, "questions": Q})
    print("  %-8s -> %s  noul=%s  in=%s" % (label, code,
          r["answers"]["q"]["noul"] if code == 200 else "-",
          r["usage"]["input_tokens"] if code == 200 else "-"))

print("\n=== 入口等价性 ===")
for path in ("/v1/systemone", "/alpha/decisions"):
    code, r = post(path, {"model": jev.MODEL, "state": S, "questions": Q})
    print("  %-18s -> %s  %s" % (path, code, r.get("model") if code == 200 else str(r)[:70]))

print("\n=== 用聊天接口调它 ===")
code, r = post("/v1/chat/completions",
               {"model": "typesafe/jev-1.13", "messages": [{"role": "user", "content": "is it a bug?"}]})
print("  /v1/chat/completions -> %s  %s" % (code, str(r)[:160]))

print("\n=== 概率是否严格和为 1 ===")
code, r = post("/v1/systemone", {"model": jev.MODEL,
    "state": "A customer asks to change the billing address on a paid invoice, and the PDF will not download.",
    "questions": {"dept": jev.choice("Which team?", {"billing": "invoices", "frontend": "downloads",
                                                     "account": "profile", "legal": "contracts"}),
                  "sev": jev.score("How severe?", ["cosmetic", "annoying", "blocking", "outage"])}})
if code == 200:
    for k, a in r["answers"].items():
        p = a.get("probabilities", {})
        print("  %-5s sum=%.10f n=%d conf=%s" % (k, sum(p.values()), len(p), a.get("confidence")))

print("\n=== 并发 20 ===")
t0 = time.time()
with ThreadPoolExecutor(max_workers=20) as ex:
    out = list(ex.map(lambda _: post("/v1/systemone",
               {"model": jev.MODEL, "state": S, "questions": Q}), range(20)))
codes = {}
for c, _ in out: codes[c] = codes.get(c, 0) + 1
print("  状态码分布 %s，墙钟 %.2fs" % (codes, time.time() - t0))

print("\n=== 上下文上限（粗探，细探见 exp_token.py）===")
for chars in (120000, 160000):
    code, r = post("/v1/systemone", {"model": jev.MODEL, "state": "ticket detail. " * (chars // 14),
                                      "questions": Q})
    print("  state≈%d 字符 -> %s %s" % (chars, code,
          ("in=%d" % r["usage"]["input_tokens"]) if code == 200 else str(r)[:70]))
