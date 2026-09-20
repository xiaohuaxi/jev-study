# 让本脚本从任意目录都能找到仓库根部的 jevkit.py / corpus.py
import sys as _sys, pathlib as _pathlib
_sys.path.insert(0, str(_pathlib.Path(__file__).resolve().parent.parent))
# -*- coding: utf-8 -*-
"""中文的 token 经济性，以及 3.2 万 token 上限换算成多少汉字。"""
import sys
sys.path.insert(0, __import__("os").path.dirname(__import__("os").path.abspath(__file__)))
import jevkit as jev
from corpus import PAIRS

BASE_Q = {"q": {"type": "noul", "instructions": "x"}}   # 固定极短问题，便于扣掉开销
# 先测空载开销
empty = jev.call("", BASE_Q)
OVER = empty["usage"]["input_tokens"]
print("空 state 的固定开销: %d token" % OVER)

print("\n=== 同义中英文的 token 用量 ===")
print("中文字数 | 中文 token | 每字 token | 英文字符 | 英文 token | 中/英 token 比")
zr = []
for zh, en in PAIRS:
    a = jev.call(zh, BASE_Q)["usage"]["input_tokens"] - OVER
    b = jev.call(en, BASE_Q)["usage"]["input_tokens"] - OVER
    zr.append(a / b)
    print("  %4d   |   %4d     |   %.2f     |   %4d   |   %4d     |  %.2f" %
          (len(zh), a, a/len(zh), len(en), b, a/b))
import statistics as st
print("\n  同一语义，中文 token 量是英文的 %.2f 倍（中位）" % st.median(zr))
print("  中文每个字约 %.2f token" % st.median([ (jev.call(z, BASE_Q)["usage"]["input_tokens"]-OVER)/len(z) for z,_ in PAIRS[:3] ]))

print("\n=== 3.2 万 token 上限 = 多少汉字 ===")
doc = ("客户来电反映，在完成支付流程之后，订单确认页面没有任何内容显示，整页空白。"
       "客服已指导客户更换浏览器并清理缓存，问题依旧存在。财务侧确认款项已经入账。")
lo, hi = 1000, 60000   # 以汉字数二分
while hi - lo > 500:
    mid = (lo + hi) // 2
    n = mid // len(doc) + 1
    state = (doc * n)[:mid]
    r = jev.call(state, BASE_Q)
    if "_error" in r: hi = mid
    else:
        lo = mid
        print("  %5d 字 -> %5d token ✅" % (mid, r["usage"]["input_tokens"]))
print("\n  实测能塞进去的中文约 %d 字（上界 %d 字已超限）" % (lo, hi))
print(jev.spend())
