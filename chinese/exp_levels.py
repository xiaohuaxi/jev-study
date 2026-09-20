# 让本脚本从任意目录都能找到仓库根部的 jevkit.py / corpus.py
import sys as _sys, pathlib as _pathlib
_sys.path.insert(0, str(_pathlib.Path(__file__).resolve().parent.parent))
# -*- coding: utf-8 -*-
"""实验 C：语言固定为中文，只改档位描述的写法，看分数动多少。"""
import statistics as st, sys
sys.path.insert(0, __import__("os").path.dirname(__import__("os").path.abspath(__file__)))
import jevkit as jev
from corpus import CASES

REPEAT = 3
PHRASINGS = {
 "中性三档":   ["低", "中", "高"],
 "场景化三档": ["可以等下个版本", "本周内处理", "正在影响业务需立即处理"],
 "后果导向":   ["用户基本没感觉", "用户已经在抱怨", "再不处理就要丢客户了"],
}
jobs = []
for c in CASES:
    for name, levels in PHRASINGS.items():
        for r in range(REPEAT):
            jobs.append((f"{c[0]}|{name}|{r}", c[1],
                         {"urg": {"type":"score","instructions":"这个工单有多紧急？","criteria":levels}}))
print("发起 %d 次请求 ..." % len(jobs)); res = jev.fan(jobs, workers=10); print(jev.spend())

acc = {}
for k, d in res.items():
    cid, ph, r = k.split("|")
    if "_error" in d: print("FAIL", k, d["_error"]); continue
    acc.setdefault((cid, ph), []).append(d["answers"]["urg"]["score"])

names = list(PHRASINGS)
print("\n=== 同一中文内容，只换档位描述（0-2 档，3 次均值）===")
print("用例 | " + " | ".join("%-10s" % n for n in names) + " | 极差")
spreads = []
for c in CASES:
    v = [st.mean(acc[(c[0], n)]) for n in names]
    sp = max(v) - min(v); spreads.append(sp)
    print("  %-3s | " % c[0] + " | ".join("%-10.2f" % x for x in v) + " | %.2f" % sp)
print("\n  档位措辞造成的极差：中位 %.2f，最大 %.2f（满量程 2.0）" % (st.median(spreads), max(spreads)))
print("  对照：只换内容语言在 0-3 量程上造成 -0.44~+0.19")
