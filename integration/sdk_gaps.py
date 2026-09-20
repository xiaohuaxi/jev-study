import os, json
from typesafe_sdk import TypeSafeClient, Noul
c = TypeSafeClient(api_key=os.environ.get("OPENROUTER_API_KEY") or os.environ["API_KEY_OPENROUTER"],
                   base_url="https://openrouter.ai/api", model="jev-1.13")
r = c.system_one(state="付款后白屏", questions={"q": Noul(instructions="是故障吗？")})
print("SDK 的 usage 字段:", r.usage, "| 有 cost 吗:", hasattr(r.usage, "cost"))
print("SDK 响应对象字段:", sorted(type(r).model_fields.keys()))
print("OpenRouter 额外返回的 id / provider / cost 是否保留:",
      hasattr(r, "id"), hasattr(r, "provider"))
