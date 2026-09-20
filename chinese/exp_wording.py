# 让本脚本从任意目录都能找到仓库根部的 jevkit.py / corpus.py
import sys as _sys, pathlib as _pathlib
_sys.path.insert(0, str(_pathlib.Path(__file__).resolve().parent.parent))
# -*- coding: utf-8 -*-
"""实验 D：复现上一轮的 3 个案例，把"内容语言"和"档位描述语言"拆开看谁在驱动分数。"""
import statistics as st, sys
sys.path.insert(0, __import__("os").path.dirname(__import__("os").path.abspath(__file__)))
import jevkit as jev

REPEAT = 5
# 完全照抄上一轮用过的原文与档位
CASES = [
 ("白屏",
  "客户反馈：点击支付后确认页整页空白，Chrome 和 Safari 都能复现，扣款已成功，订单号 A-20931，企业版客户。",
  "Customer reports: after clicking Pay the confirmation page renders entirely blank, reproducible in Chrome and Safari, the charge succeeded, order A-20931, enterprise customer.",
  "严重程度如何？", "How severe is it?",
  ["只是不好看", "有点烦人", "无法继续操作", "服务中断"],
  ["cosmetic only", "annoying", "blocks the user", "service outage"]),
 ("退款",
  "用户要求全额退款，称服务从未可用，但日志显示其账号在过去 30 天登录了 42 次。",
  "The user demands a full refund claiming the service never worked, but logs show the account signed in 42 times in the last 30 days.",
  "处理优先级多高？", "How high is the handling priority?",
  ["可以放着", "正常排期", "本周处理", "立刻升级"],
  ["can wait", "normal queue", "handle this week", "escalate now"]),
 ("审核",
  "一条社区帖子写道：不同意就滚出去，这种人就该被永久封禁，顺便挂出他的工作单位。",
  "A community post reads: if you disagree, get out, people like this deserve a permanent ban, and here is where he works.",
  "处置力度应该多大？", "How strong should the action be?",
  ["无需处理", "提示作者", "隐藏内容", "封禁账号"],
  ["no action", "warn the author", "hide the content", "ban the account"]),
]

jobs = []
for name, zh, en, qzh, qen, lzh, len_ in CASES:
    for slang in ("zh", "en"):
        for llang in ("zh", "en"):
            for r in range(REPEAT):
                state = zh if slang == "zh" else en
                q = {"sev": {"type": "score",
                             "instructions": qzh if llang == "zh" else qen,
                             "criteria": lzh if llang == "zh" else len_}}
                jobs.append((f"{name}|{slang}{llang}|{r}", state, q))

print("发起 %d 次请求 ..." % len(jobs))
res = jev.fan(jobs, workers=10)
print(jev.spend())

acc = {}
for k, d in res.items():
    name, combo, r = k.split("|")
    if "_error" in d: print("FAIL", k, d["_error"]); continue
    acc.setdefault((name, combo), []).append(d["answers"]["sev"]["score"])

print("\n=== 分数（0-3 档，5 次均值，括号内为极差）===")
print("案例 | 内容zh+档位zh | 内容zh+档位en | 内容en+档位en | 内容en+档位zh")
for name, *_ in CASES:
    cells = []
    for combo in ("zhzh", "zhen", "enen", "enzh"):
        v = acc.get((name, combo), [])
        cells.append("%.2f (±%.2f)" % (st.mean(v), (max(v)-min(v))/2) if v else "  -  ")
    print("  %-4s | %s" % (name, " | ".join("%-13s" % c for c in cells)))

print("\n=== 拆解：换内容语言 vs 换档位语言，各自让分数动多少 ===")
for name, *_ in CASES:
    g = lambda c: st.mean(acc[(name, c)])
    d_state = ((g("enzh") - g("zhzh")) + (g("enen") - g("zhen"))) / 2   # 只换内容语言
    d_level = ((g("zhen") - g("zhzh")) + (g("enen") - g("enzh"))) / 2   # 只换档位语言
    print("  %-4s  换内容语言: %+.2f   换档位描述语言: %+.2f   （上一轮误记为语言差的总差: %+.2f）"
          % (name, d_state, d_level, g("zhzh") - g("enen")))
