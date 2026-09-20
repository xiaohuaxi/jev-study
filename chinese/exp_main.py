# 让本脚本从任意目录都能找到仓库根部的 jevkit.py / corpus.py
import sys as _sys, pathlib as _pathlib
_sys.path.insert(0, str(_pathlib.Path(__file__).resolve().parent.parent))
# -*- coding: utf-8 -*-
"""主实验：内容语言 × 提问语言 2x2，12 用例 x 3 次重复。"""
import json, statistics as st, sys
sys.path.insert(0, __import__("os").path.dirname(__import__("os").path.abspath(__file__)))
import jevkit as jev
from corpus import *

REPEAT = 3
COMBOS = [("zh", "zh"), ("zh", "en"), ("en", "en"), ("en", "zh")]

def build(case, slang, qlang):
    cid, zh, en, dept, isbug, urg = case
    state = zh if slang == "zh" else en
    if qlang == "zh":
        qs = {"dept": choice_q(Q_DEPT_ZH, DEPTS_ZH), "bug": {"type":"noul","instructions":Q_BUG_ZH},
              "urg": {"type":"score","instructions":Q_URG_ZH,"criteria":LV_ZH}}
    else:
        qs = {"dept": choice_q(Q_DEPT_EN, DEPTS_EN), "bug": {"type":"noul","instructions":Q_BUG_EN},
              "urg": {"type":"score","instructions":Q_URG_EN,"criteria":LV_EN}}
    return state, qs

def choice_q(instr, crit):
    return {"type": "choice", "instructions": instr, "criteria": crit}

jobs = []
for case in CASES:
    for slang, qlang in COMBOS:
        for r in range(REPEAT):
            s, q = build(case, slang, qlang)
            jobs.append((f"{case[0]}|{slang}{qlang}|{r}", s, q))

print("发起 %d 次请求 ..." % len(jobs))
res = jev.fan(jobs, workers=10)
print(jev.spend())

rows = {}
for k, d in res.items():
    cid, combo, r = k.split("|")
    if "_error" in d:
        print("FAIL", k, d["_error"]); continue
    a = d["answers"]
    rows.setdefault((cid, combo), []).append(
        (a["dept"]["choice"], a["bug"]["noul"], a["urg"]["score"], a["dept"]["confidence"]))

json.dump({f"{c}|{m}": v for (c, m), v in rows.items()}, open("main_raw.json","w"), ensure_ascii=False, indent=1)

label = {c[0]: (c[3], c[4], c[5]) for c in CASES}
print("\n=== 各组表现（12 用例 × 3 次）===")
print("组合(内容/提问) | 部门对 | 故障判对 | 重复内最大抖动 | urgency 均值")
for slang, qlang in COMBOS:
    combo = slang + qlang
    dep_ok = bug_ok = n = 0
    jitter = []; urgs = []
    for cid, (gdept, gbug, gurg) in label.items():
        v = rows.get((cid, combo), [])
        if not v: continue
        n += 1
        dep_ok += sum(1 for x in v if x[0] == gdept) / len(v)
        bug_ok += sum(1 for x in v if (x[1] >= .5) == gbug) / len(v)
        jitter.append(max(x[1] for x in v) - min(x[1] for x in v))
        urgs.append(st.mean(x[2] for x in v))
    print("  内容%s/提问%s   |  %4.1f/%d  |  %4.1f/%d   |  noul ±%.3f   |  %.2f" %
          (slang, qlang, dep_ok, n, bug_ok, n, max(jitter), st.mean(urgs)))

print("\n=== 逐例 urgency 分数（0-2 档，看语言是否让刻度漂移）===")
print("用例 预期 | 内容zh提问zh 内容zh提问en 内容en提问en 内容en提问zh | zh-en(全同语)")
for c in CASES:
    cid = c[0]; g = c[5]
    vals = {}
    for slang, qlang in COMBOS:
        v = rows.get((cid, slang+qlang), [])
        vals[slang+qlang] = st.mean(x[2] for x in v) if v else float("nan")
    print("  %-3s  %d  |   %.2f         %.2f         %.2f         %.2f      |  %+.2f" %
          (cid, g, vals["zhzh"], vals["zhen"], vals["enen"], vals["enzh"], vals["zhzh"]-vals["enen"]))

print("\n=== 逐例部门判断（× 表示与构造标签不符）===")
for c in CASES:
    cid, gdept = c[0], c[3]
    line = []
    for slang, qlang in COMBOS:
        v = rows.get((cid, slang+qlang), [])
        got = set(x[0] for x in v)
        mark = "".join(sorted(got))
        line.append(("%-10s" % ("/".join(sorted(got)))) + ("" if got == {gdept} else " ×"))
    print("  %-3s 应为 %-9s | %s" % (cid, gdept, " | ".join(line)))
