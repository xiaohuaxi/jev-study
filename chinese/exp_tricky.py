# 让本脚本从任意目录都能找到仓库根部的 jevkit.py / corpus.py
import sys as _sys, pathlib as _pathlib
_sys.path.insert(0, str(_pathlib.Path(__file__).resolve().parent.parent))
# -*- coding: utf-8 -*-
"""中文特有表达 + 同义改写鲁棒性。"""
import statistics as st, sys
sys.path.insert(0, __import__("os").path.dirname(__import__("os").path.abspath(__file__)))
import jevkit as jev
from corpus import TRICKY, VARIANTS

REPEAT = 3
# 对照：把最难的几条翻成英文，看是不是中文特有的难
CTRL = [
 ("讽刺",   "Your response time is truly heartwarming. The ticket has been open for six days. Many thanks.",
            "Is this customer dissatisfied with the service?"),
 ("反问",   "You call this usable?", "Is this customer dissatisfied with the service?"),
 ("双重否定", "I wouldn't say it's completely unusable, you just have to retry three or four times every time.",
            "Is this customer hitting a product problem?"),
 ("委婉拒绝", "We got your proposal, quite interesting. We'll study it further on our side and reach out if needed.",
            "Is this customer inclined to close the deal?"),
]

jobs = []
for name, text, q, _ in TRICKY:
    for r in range(REPEAT):
        jobs.append((f"ZH|{name}|{r}", text, {"q": {"type": "noul", "instructions": q}}))
for name, text, q in CTRL:
    for r in range(REPEAT):
        jobs.append((f"EN|{name}|{r}", text, {"q": {"type": "noul", "instructions": q}}))
for name, text in VARIANTS:
    for r in range(REPEAT):
        jobs.append((f"VAR|{name}|{r}", text,
                     {"bug": {"type": "noul", "instructions": "这是否属于页面显示故障？"},
                      "urg": {"type": "score", "instructions": "这个工单有多紧急？",
                              "criteria": ["可以等下个版本", "本周内处理", "正在影响业务需立即处理"]}}))
print("发起 %d 次请求 ..." % len(jobs)); res = jev.fan(jobs, workers=10); print(jev.spend())

acc = {}
for k, d in res.items():
    grp, name, r = k.split("|")
    if "_error" in d: print("FAIL", k, d["_error"]); continue
    acc.setdefault((grp, name), []).append(d["answers"])

print("\n=== 中文特有表达（noul = 判为是的概率，3 次）===")
print("类型       | 概率(均值/极差) | 我预期的读法       | 对得上?")
for name, text, q, expect in TRICKY:
    v = [a["q"]["noul"] for a in acc[("ZH", name)]]
    m = st.mean(v)
    want_yes = not expect.endswith("否")
    ok = "✓" if (m >= .5) == want_yes else "✗ 读反了"
    print("  %-8s |  %.2f (±%.2f)   | %-16s | %s" % (name, m, (max(v)-min(v))/2, expect, ok))

print("\n=== 同一难点换英文说，是否更容易? ===")
for name, text, q in CTRL:
    zh = st.mean(a["q"]["noul"] for a in acc[("ZH", name)])
    en = st.mean(a["q"]["noul"] for a in acc[("EN", name)])
    print("  %-8s 中文 %.2f  英文 %.2f  差 %+.2f" % (name, zh, en, en - zh))

print("\n=== 同一件事的七种写法（简繁/标点/emoji/口语/极简/英文）===")
print("写法       | 是故障 | 紧急度 | 相对标准写法")
base_bug = base_urg = None
for name, text in VARIANTS:
    v = acc[("VAR", name)]
    b = st.mean(a["bug"]["noul"] for a in v); u = st.mean(a["urg"]["score"] for a in v)
    if base_bug is None: base_bug, base_urg = b, u
    print("  %-9s |  %.2f  |  %.2f  |  故障%+.2f 紧急%+.2f" % (name, b, u, b-base_bug, u-base_urg))
