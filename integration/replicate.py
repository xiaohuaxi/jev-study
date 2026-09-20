# 让本脚本从任意目录都能找到仓库根部的 jevkit.py / corpus.py
import sys as _sys, pathlib as _pathlib
_sys.path.insert(0, str(_pathlib.Path(__file__).resolve().parent.parent))
# -*- coding: utf-8 -*-
"""独立复跑三条头条结论，核对与报告中的数字是否一致。"""
import statistics as st, sys, time, json
sys.path.insert(0, __import__("os").path.dirname(__import__("os").path.abspath(__file__)))
import jevkit as jev

print("=" * 66)
print("复跑 1：扇出经济性（报告：1 问 0.90s / 12 问 0.90s / 串行 10.82s，8 倍价差）")
state = ("Customer reports: after clicking Pay, the confirmation page renders completely blank. "
         "Reproduced in Chrome 141 and Safari 19. Order A-20931, enterprise plan, first reply 43 minutes ago. "
         "Console shows a failed asset request.")
qs = {k: jev.noul(v) for k, v in [
 ("is_bug","Is this a software defect?"),("needs_human","Must a human handle this?"),
 ("is_regression","Does this look like a regression?"),("is_security","Does this involve a security or privacy risk?"),
 ("is_dup","Does this look like a duplicate of a known issue?"),("affects_revenue","Is revenue directly affected?"),
 ("is_reproducible","Is it reproducible from the description?"),("needs_logs","Do we need more logs from the customer?"),
 ("is_browser_specific","Is it specific to one browser?"),("is_payment_related","Is the payment system implicated?"),
 ("is_urgent","Should this be handled today?"),("is_enterprise","Is this an enterprise customer?")]}
one = {"is_bug": qs["is_bug"]}
t1 = [jev.call(state, one) for _ in range(3)]
t12 = [jev.call(state, qs) for _ in range(3)]
print("  1 问 : %.2fs (中位)  in=%d  cost=$%.8f" % (st.median(r["_elapsed"] for r in t1),
      t1[0]["usage"]["input_tokens"], t1[0]["usage"]["cost"]))
print("  12 问: %.2fs (中位)  in=%d  cost=$%.8f  答案数=%d" % (st.median(r["_elapsed"] for r in t12),
      t12[0]["usage"]["input_tokens"], t12[0]["usage"]["cost"], len(t12[0]["answers"])))
t0 = time.time(); ser_cost = 0
for k, v in qs.items():
    r = jev.call(state, {k: v}); ser_cost += r["usage"]["cost"]
ser = time.time() - t0
print("  12 次串行: %.2fs  cost=$%.8f" % (ser, ser_cost))
print("  => 提速 %.1f 倍，省钱 %.1f 倍" % (ser / st.median(r["_elapsed"] for r in t12),
                                        ser_cost / t12[0]["usage"]["cost"]))

print("=" * 66)
print("复跑 2：档位文案效应（报告：离职收权限 1.90 / 1.48 / 0.58）")
CASE = "有个同事已经离职了，要把他在工作区里的所有权限收回来。"
PH = {"中性三档": ["低","中","高"],
      "场景化三档": ["可以等下个版本","本周内处理","正在影响业务需立即处理"],
      "后果导向": ["用户基本没感觉","用户已经在抱怨","再不处理就要丢客户了"]}
for name, lv in PH.items():
    v = [jev.call(CASE, {"urg": jev.score("这个工单有多紧急？", lv)})["answers"]["urg"]["score"] for _ in range(5)]
    print("  %-10s %.2f  (%.2f~%.2f)" % (name, st.mean(v), min(v), max(v)))

print("=" * 66)
print("复跑 3：模型串与错误码")
import urllib.request, urllib.error
def probe(model=None, questions=None, key=None):
    body = json.dumps({"model": model or "jev-1.13", "state": "x",
                       "questions": questions or {"q": jev.noul("ok?")}}).encode()
    req = urllib.request.Request(jev.URL, data=body, headers={
        "Authorization": "Bearer " + (key or jev.KEY), "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=60) as r: return 200, json.loads(r.read()).get("model")
    except urllib.error.HTTPError as e: return e.code, e.read().decode()[:90]
for m in ("jev-1.13", "typesafe/jev-1.13-20260917", "jev-1.13.0", "jev-preview"):
    print("  model=%-28s -> %s" % (m, probe(model=m)))
print("  题型 boolean (报告说 400) ->", probe(questions={"q": {"type":"boolean","instructions":"ok?"}})[0])
print("  坏 key    (报告说 401) ->", probe(key="sk-or-v1-bogus000")[0])
print("\n" + jev.spend())
