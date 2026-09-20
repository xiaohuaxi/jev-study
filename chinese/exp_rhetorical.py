# 让本脚本从任意目录都能找到仓库根部的 jevkit.py / corpus.py
import sys as _sys, pathlib as _pathlib
_sys.path.insert(0, str(_pathlib.Path(__file__).resolve().parent.parent))
# -*- coding: utf-8 -*-
"""核查：中文短反问是不是真的比英文吃亏，还是只是"句子短"。"""
import statistics as st, sys
sys.path.insert(0, __import__("os").path.dirname(__import__("os").path.abspath(__file__)))
import jevkit as jev
REPEAT = 5
Q_ZH, Q_EN = "这位客户是否对服务不满？", "Is this customer dissatisfied with the service?"
ITEMS = [
 ("反问", "这也算能用？",               "You call this usable?"),
 ("反问", "就这？",                     "That's it?"),
 ("反问", "有人管吗？",                 "Is anyone even handling this?"),
 ("反问", "你们这个东西真的测过吗？",   "Did you people actually test this thing?"),
 ("陈述", "完全不能用。",               "Completely unusable."),
 ("陈述", "很失望。",                   "Very disappointed."),
 ("陈述", "这个功能有问题。",           "This feature is broken."),
]
jobs = []
for i, (kind, zh, en) in enumerate(ITEMS):
    for r in range(REPEAT):
        jobs.append((f"{i}|zh|{r}", zh, {"q": {"type":"noul","instructions":Q_ZH}}))
        jobs.append((f"{i}|en|{r}", en, {"q": {"type":"noul","instructions":Q_EN}}))
print("发起 %d 次请求 ..." % len(jobs)); res = jev.fan(jobs, workers=10); print(jev.spend())
acc = {}
for k, d in res.items():
    i, lang, r = k.split("|")
    if "_error" in d: print("FAIL", k); continue
    acc.setdefault((int(i), lang), []).append(d["answers"]["q"]["noul"])
print("\n句型 | 中文原句 | 中文 | 英文 | 差(英-中)")
gaps = {"反问": [], "陈述": []}
for i, (kind, zh, en) in enumerate(ITEMS):
    z, e = st.mean(acc[(i,"zh")]), st.mean(acc[(i,"en")])
    gaps[kind].append(e - z)
    print("  %-4s | %-14s | %.2f | %.2f | %+.2f" % (kind, zh, z, e, e - z))
print("\n  反问句 英文比中文平均高 %+.2f（%d 句）" % (st.mean(gaps["反问"]), len(gaps["反问"])))
print("  陈述句 英文比中文平均高 %+.2f（%d 句）" % (st.mean(gaps["陈述"]), len(gaps["陈述"])))
