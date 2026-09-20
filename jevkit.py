"""Jev 实测公共库：并发发请求、记录用量。仅用标准库，兼容 Python 3.9。

STATS["fail"] 统计的是最终未拿到 200 的调用。探测上限、探测非法参数这类实验
本就期望收到 4xx，那里的 fail 是预期结果，不是脚本出错。
"""
import json, os, ssl, time, urllib.request
from concurrent.futures import ThreadPoolExecutor

KEY = os.environ.get("OPENROUTER_API_KEY") or os.environ.get("API_KEY_OPENROUTER")
if not KEY:
    raise SystemExit("请先设置 OPENROUTER_API_KEY（或 API_KEY_OPENROUTER）")
URL = "https://openrouter.ai/api/v1/systemone"
MODEL = "typesafe/jev-1.13-20260917"
CTX = ssl.create_default_context()
STATS = {"calls": 0, "in": 0, "out": 0, "cost": 0.0, "fail": 0}

def call(state, questions, model=MODEL, retries=3):
    body = json.dumps({"model": model, "state": state, "questions": questions}).encode()
    req = urllib.request.Request(URL, data=body, headers={
        "Authorization": "Bearer " + KEY, "Content-Type": "application/json"})
    last = None
    for attempt in range(retries):
        try:
            t0 = time.time()
            with urllib.request.urlopen(req, timeout=120, context=CTX) as r:
                d = json.loads(r.read())
            d["_elapsed"] = time.time() - t0
            u = d.get("usage", {})
            STATS["calls"] += 1
            STATS["in"] += u.get("input_tokens", 0)
            STATS["out"] += u.get("output_tokens", 0)
            STATS["cost"] += u.get("cost", 0.0)
            return d
        except urllib.error.HTTPError as e:
            last = (e.code, e.read().decode()[:300])
            if e.code in (429, 529, 500, 502, 503):
                time.sleep(1.5 * (attempt + 1)); continue
            break
        except Exception as e:  # 网络抖动
            last = ("net", repr(e)[:200]); time.sleep(1.5 * (attempt + 1))
    STATS["fail"] += 1
    return {"_error": last}

def fan(jobs, workers=8):
    """jobs: [(key, state, questions)] -> {key: response}"""
    out = {}
    with ThreadPoolExecutor(max_workers=workers) as ex:
        futs = {ex.submit(call, s, q): k for k, s, q in jobs}
        for f, k in futs.items():
            out[k] = f.result()
    return out

def noul(instr): return {"type": "noul", "instructions": instr}
def choice(instr, crit): return {"type": "choice", "instructions": instr, "criteria": crit}
def score(instr, levels): return {"type": "score", "instructions": instr, "criteria": levels}

def spend():
    return "调用 %d 次 | 输入 %d tok | 输出 %d tok | 花费 $%.6f | 失败 %d" % (
        STATS["calls"], STATS["in"], STATS["out"], STATS["cost"], STATS["fail"])
