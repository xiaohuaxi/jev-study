# 让本脚本从任意目录都能找到仓库根部的 jevkit.py / corpus.py
import sys as _sys, pathlib as _pathlib
_sys.path.insert(0, str(_pathlib.Path(__file__).resolve().parent.parent))
# -*- coding: utf-8 -*-
"""长中文文档里的关键句放在不同位置，还找得到吗。"""
import statistics as st, sys
sys.path.insert(0, __import__("os").path.dirname(__import__("os").path.abspath(__file__)))
import jevkit as jev

FILLER = ("客服记录：客户咨询了会员权益的适用范围，并询问了团队席位的分配方式。"
          "坐席已按标准话术说明了套餐差异，客户表示了解，暂无进一步诉求。"
          "客户另外询问了移动端是否支持深色模式，坐席确认已支持并指导了开启路径。")
NEEDLE = "客户补充：另外我上个月被重复扣款两笔，一模一样的金额，共 1998 元，只下过一个订单。"
Q = {"dup": {"type": "noul", "instructions": "客户是否反映了重复扣款的问题？"},
     "dept": {"type": "choice", "instructions": "哪个团队最适合处理这个工单？",
              "criteria": {"billing": "支付、发票、退款", "frontend": "页面与浏览器",
                           "account": "登录与权限", "general": "一般咨询，无需专项处理"}}}

def doc(chars, pos):
    n = chars // len(FILLER) + 1
    body = (FILLER * n)[:chars]
    if pos == "无":   return body            # 对照组：不插关键句
    if pos == "开头": return NEEDLE + body
    if pos == "末尾": return body + NEEDLE
    h = len(body) // 2
    return body[:h] + NEEDLE + body[h:]

if __name__ == "__main__":
    print("对照：只有这一句话时 ->", end=" ")
    r = jev.call(NEEDLE, Q)
    print("命中 %.2f, 部门 %s" % (r["answers"]["dup"]["noul"], r["answers"]["dept"]["choice"]))
    print("对照：只有填充文本、没有关键句 ->", end=" ")
    r = jev.call(doc(3000, "无"), {"dup": Q["dup"]})
    print("误报 %.2f" % r["answers"]["dup"]["noul"])

    jobs = []
    for chars in (3000, 12000, 30000):
        for pos in ("开头", "中间", "末尾"):
            for rep in range(3):
                jobs.append((f"{chars}|{pos}|{rep}", doc(chars, pos), Q))
    res = jev.fan(jobs, workers=6)
    acc = {}
    for k, d in res.items():
        ch, pos, rep = k.split("|")
        if "_error" in d: print("FAIL", k, d["_error"]); continue
        acc.setdefault((int(ch), pos), []).append(d["answers"])

    print("\n=== 关键句藏在不同位置（命中概率 / 部门判断）===")
    print("文档长度 |   开头        |   中间        |   末尾")
    for chars in (3000, 12000, 30000):
        cells = []
        for pos in ("开头", "中间", "末尾"):
            v = acc.get((chars, pos), [])
            if not v: cells.append("    -    "); continue
            m = st.mean(a["dup"]["noul"] for a in v)
            dp = set(a["dept"]["choice"] for a in v)
            cells.append("%.2f %-8s" % (m, "/".join(sorted(dp))))
        print("  %5d 字 | %s" % (chars, " | ".join(cells)))
    print("\n" + jev.spend())
