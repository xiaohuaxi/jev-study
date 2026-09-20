# 让本脚本从任意目录都能找到仓库根部的 jevkit.py / corpus.py
import sys as _sys, pathlib as _pathlib
_sys.path.insert(0, str(_pathlib.Path(__file__).resolve().parent.parent))
# -*- coding: utf-8 -*-
"""中文键名：选项键、state 字段名、以及只给键名不给描述行不行。"""
import statistics as st, sys, json
sys.path.insert(0, __import__("os").path.dirname(__import__("os").path.abspath(__file__)))
import jevkit as jev
from corpus import CASES

print("=== 1. choice 的选项键直接用中文 ===")
r = jev.call("付款成功后确认页整页空白，换了两个浏览器仍然如此。",
             {"部门": {"type": "choice", "instructions": "哪个团队最适合处理？",
                       "criteria": {"账单组": "支付、发票、退款",
                                    "前端组": "页面显示与浏览器",
                                    "账号组": "登录与权限"}}})
print(json.dumps(r.get("answers", r), ensure_ascii=False))

print("\n=== 2. 只给中文键名、描述留空 ===")
r = jev.call("付款成功后确认页整页空白，换了两个浏览器仍然如此。",
             {"部门": {"type": "choice", "instructions": "哪个团队最适合处理？",
                       "criteria": {"账单组": None, "前端组": None, "账号组": None}}})
print(json.dumps(r.get("answers", r), ensure_ascii=False))

print("\n=== 3. score 档位用中文、问题名也用中文 ===")
r = jev.call("付款成功后确认页整页空白。",
             {"紧急度": {"type": "score", "instructions": "有多紧急？",
                         "criteria": ["可以等", "本周处理", "立即处理"]}})
print(json.dumps(r.get("answers", r), ensure_ascii=False))

print("\n=== 4. state 字段名用中文 vs 用英文（6 用例 × 3 次）===")
EN_KEYS = lambda t: {"ticket": t, "customer_tier": "enterprise", "waited_minutes": 43}
ZH_KEYS = lambda t: {"工单内容": t, "客户等级": "企业版", "已等待分钟": 43}
DEPTS = {"billing": "支付、发票、退款", "frontend": "页面显示与浏览器",
         "account": "登录与权限", "api": "接口与集成"}
jobs = []
for c in CASES[:6]:
    for tag, mk in (("英文键", EN_KEYS), ("中文键", ZH_KEYS)):
        for r_ in range(3):
            jobs.append((f"{c[0]}|{tag}|{r_}", mk(c[1]),
                         {"dept": {"type":"choice","instructions":"哪个团队最适合处理？","criteria":DEPTS},
                          "urg": {"type":"score","instructions":"有多紧急？",
                                  "criteria":["可以等下个版本","本周内处理","正在影响业务需立即处理"]}}))
res = jev.fan(jobs, workers=10)
acc = {}
for k, d in res.items():
    cid, tag, r_ = k.split("|")
    if "_error" in d: print("FAIL", k); continue
    acc.setdefault((cid, tag), []).append(d["answers"])
print("用例 | 英文键(部门/紧急) | 中文键(部门/紧急) | 部门一致 | 紧急差")
for c in CASES[:6]:
    e, z = acc[(c[0], "英文键")], acc[(c[0], "中文键")]
    ed = set(a["dept"]["choice"] for a in e); zd = set(a["dept"]["choice"] for a in z)
    eu = st.mean(a["urg"]["score"] for a in e); zu = st.mean(a["urg"]["score"] for a in z)
    print("  %-3s | %-9s %.2f | %-9s %.2f | %s | %+.2f" %
          (c[0], "/".join(ed), eu, "/".join(zd), zu, "是" if ed == zd else "否", zu - eu))
print("\n" + jev.spend())
