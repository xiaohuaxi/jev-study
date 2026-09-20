# 让本脚本从任意目录都能找到仓库根部的 jevkit.py / corpus.py
import sys as _sys, pathlib as _pathlib
_sys.path.insert(0, str(_pathlib.Path(__file__).resolve().parent.parent))
# -*- coding: utf-8 -*-
"""重做对照组：文档里确实没有关键句时，它会不会硬说有。"""
import statistics as st, sys
sys.path.insert(0, __import__("os").path.dirname(__import__("os").path.abspath(__file__)))
import jevkit as jev
from exp_needle import FILLER, NEEDLE, Q, doc

print("=== 对照组：文档中没有关键句（每档 3 次）===")
for chars in (3000, 12000, 30000):
    v = []
    for _ in range(3):
        r = jev.call(doc(chars, "无"), {"dup": Q["dup"]})
        v.append(r["answers"]["dup"]["noul"])
    print("  %5d 字、无关键句 -> 命中概率 %.2f (%.2f~%.2f)" % (chars, st.mean(v), min(v), max(v)))
print("\n  自检：确认对照文本里真的没有关键句 ->", NEEDLE[:10] not in doc(30000, "无"))
print(jev.spend())
