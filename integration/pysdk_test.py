import os, time
from typesafe_sdk import TypeSafeClient, Noul, Choice, Score

# 官方 Python SDK，只换 key 和 base_url，指向 OpenRouter
client = TypeSafeClient(
    api_key=os.environ.get("OPENROUTER_API_KEY") or os.environ["API_KEY_OPENROUTER"],
    base_url="https://openrouter.ai/api",
    model="jev-1.13",
)
t0 = time.time()
resp = client.system_one(
    state={"ticket": "付款以后页面变成空白，换了两个浏览器仍然如此。", "tier": "enterprise"},
    questions={
        "is_bug": Noul(instructions="这是否属于软件故障？"),
        "dept": Choice(instructions="哪个团队最适合处理？", criteria={
            "billing": "账单与支付", "frontend": "页面渲染与浏览器", "account": "账户与权限"}),
        "urgency": Score(instructions="有多紧急？", criteria=["可以等", "本周处理", "立即处理"]),
    },
)
print("耗时 %.2fs" % (time.time() - t0))
print("model        :", resp.model)
print("is_bug       :", resp.nouls["is_bug"].noul)
print("dept         :", resp.choices["dept"].choice, resp.choices["dept"].probabilities,
      "conf=", resp.choices["dept"].confidence)
print("urgency      :", resp.scores["urgency"].score, resp.scores["urgency"].legend)
print("usage        :", resp.usage)
print("answers keys :", list(resp.answers))
print("类型          :", type(resp.nouls["is_bug"]).__name__, type(resp.choices["dept"]).__name__)

# 异常映射：故意发一个非法题型，看 SDK 抛什么
from typesafe_sdk import TypeSafeBadRequestError, TypeSafeAuthenticationError
try:
    client.system_one(state="x", questions={"q": Score(instructions="多严重？",
                      criteria=["1","2","3","4","5","6","7","8","9","10","11"])})
except Exception as e:
    print("11 档位 ->", type(e).__name__, str(e)[:120])
try:
    TypeSafeClient(api_key="sk-or-v1-bogus", base_url="https://openrouter.ai/api",
                   model="jev-1.13").system_one(state="x", questions={"q": Noul(instructions="?")})
except Exception as e:
    print("坏 key   ->", type(e).__name__, str(e)[:120])

# 异步客户端是否也能指向 OpenRouter
import asyncio
from typesafe_sdk import AsyncTypeSafeClient
async def go():
    async with AsyncTypeSafeClient(api_key=os.environ.get("OPENROUTER_API_KEY") or os.environ["API_KEY_OPENROUTER"],
                                   base_url="https://openrouter.ai/api", model="jev-1.13") as ac:
        r = await ac.system_one(state="退款请求，日志显示登录 42 次",
                                questions={"risk": Noul(instructions="有风险吗？")})
        return r.nouls["risk"].noul
print("async     ->", asyncio.run(go()))

# models 列表在 OpenRouter 上能不能用
try:
    print("models()  ->", client.models.list())
except Exception as e:
    print("models()  ->", type(e).__name__, str(e)[:160])
