# Jev 实测接入记录：OpenRouter 路径

> **实测日期：2026-09-20**；「偶尔有一次会拖几十秒」「浏览器能直接调」两条是 2026-09-21 补的；概率和、`choice` 是否为概率最高项两条是 2026-09-22 用本仓库各专题日志复算改的
> **入口：** OpenRouter（`https://openrouter.ai/api`），未使用 TypeSafe 官方账号
> **模型解析串：** 请求写 `jev-1.13` / `jev-latest`，服务端一律回 `typesafe/jev-1.13-20260917`
> **SDK 版本：** PyPI `typesafe-sdk` 0.7.0、npm `@typesafe-ai/sdk` 0.6.0
> **成本：** 全套验证约 730 次请求（含多次 3 万 token 的上限试探、上下文两道墙的复测与中文专项评测），累计 **$0.12**
>
> 本文所有数字都来自实际请求的响应，不是文档转述。凡未实际跑到的，文末「未验证」一节列清。
> 文献侧结论见 Jev 接入与使用（文献版）（文献版，未收录本仓库）；两边有出入的地方，本文「与文献结论的出入」一节逐条对照。

## 一句话

**拿一个 OpenRouter key，一条 curl 就能调通 Jev，全程不需要 TypeSafe 账号；真正值钱的不是"能调通"，而是一次请求里塞 12 个判断和塞 1 个判断耗时一样——12 倍的吞吐、1/8 的价钱。**

## 五分钟接通

```bash
export OPENROUTER_API_KEY="sk-or-v1-..."

curl https://openrouter.ai/api/v1/systemone \
  -H "Authorization: Bearer $OPENROUTER_API_KEY" \
  -H 'Content-Type: application/json' \
  -d '{
    "model": "jev-1.13",
    "state": "付款以后页面变成空白，换了两个浏览器仍然如此。",
    "questions": {
      "is_bug": { "type": "noul", "instructions": "这是否属于软件故障？" }
    }
  }'
```

实测回包（1.0 秒）：

```json
{
  "model": "typesafe/jev-1.13-20260917",
  "answers": { "is_bug": { "type": "noul", "noul": 0.77 } },
  "usage": { "input_tokens": 285, "output_tokens": 21, "cost": 0.00001197 },
  "id": "gen-dec-1789904867-cdGA2flsFYB9BSvTFUUm",
  "provider": "TypeSafe"
}
```

285 个输入 token 收 $0.00001197，换算回去正好是 **$0.042 / 百万输入 token**；`output_tokens` 照样统计，但不计费。官方公布的价格在 OpenRouter 这条路上原样成立。

### 找不到模型是正常的

`GET /api/v1/models` 返回 446 个模型，**没有一个带 `jev` 或 `typesafe` 字样**。Jev 不在常规模型目录里，只能直接往 `/v1/systemone` 发。想在目录里搜到它再动手的人会在这里卡住。

用聊天接口调它会被明确顶回来：

```text
POST /api/v1/chat/completions  ->  400
typesafe/jev-1.13 is a decisions model and cannot be used with the
chat/completions endpoint. Use the /api/alpha/decisions endpoint instead.
```

注意这句错误提示给的是 **`/api/alpha/decisions`**，和文档里的 `/v1/systemone` 不是同一个路径。实测两个都在、行为一致、回包结构相同。生产建议用 `/v1/systemone`——它是官方 SDK 写死的路径，而 `alpha` 这个名字本身就写着"随时会变"。

### 模型名哪些能写

| 写法 | 结果 |
|---|---|
| `jev-1.13` | ✅ 通 |
| `jev-latest` | ✅ 通 |
| `typesafe/jev-1.13` | ✅ 通 |
| `typesafe/jev-1.13-20260917` | ✅ 通（**要钉版本就钉这个**） |
| `jev-1.13.0` | ❌ 400 `Model typesafe/jev-1.13.0 does not exist` |
| `jev-preview` | ❌ 400 |
| `typesafe/jev` | ❌ 400 |

## 返回长什么样

三种题型一次问完，state 用 JSON 对象（实测 string / 对象 / 数组 / 嵌套对象都收）：

```json
{
  "model": "jev-1.13",
  "state": {
    "ticket": "付款以后页面变成空白，换了两个浏览器仍然如此，订单号 A-20931。",
    "customer_tier": "enterprise",
    "first_reply_minutes": 43
  },
  "questions": {
    "is_bug":     { "type": "noul",   "instructions": "这是否属于软件故障？" },
    "department": { "type": "choice", "instructions": "哪个团队最适合处理这个问题？",
                    "criteria": { "billing": "账单、付款或退款问题",
                                  "frontend": "页面显示或浏览器问题",
                                  "account": "账户、权限或登录问题" } },
    "urgency":    { "type": "score",  "instructions": "这个问题有多紧急？",
                    "criteria": ["可以等下个版本", "本周应解决", "正在影响业务需立即处理"] }
  }
}
```

实测回包（0.95 秒，$0.0000215）：

```json
{
  "model": "typesafe/jev-1.13-20260917",
  "answers": {
    "is_bug":     { "type": "noul", "noul": 0.86 },
    "needs_human":{ "type": "noul", "noul": 0.62 },
    "department": { "type": "choice", "choice": "frontend",
                    "probabilities": { "frontend": 0.94, "billing": 0.06, "account": 0 },
                    "confidence": 0.91 },
    "urgency":    { "type": "score", "score": 1.97,
                    "legend": { "0": "可以等下个版本", "1": "本周应解决", "2": "正在影响业务需立即处理" },
                    "probabilities": { "0": 0, "1": 0.03, "2": 0.97 },
                    "confidence": 0.95 }
  },
  "usage": { "input_tokens": 511, "output_tokens": 88, "cost": 0.000021462 }
}
```

几个只有实测才看得到的细节：

- **概率是归一化的分布，但只显示两位小数**：多数回包显示和为 1.00，也会是 0.99，选项越多越常见。本仓库国际象棋问法对比和中国象棋专题的日志里共 11,916 条 choice 回答，按选项数分：2–5 项的 184 条里没有，11–20 项 4%，21–40 项 11%，41 项以上 25%（`integration/analyze_choice_top.py`，离线）。校验时别做严格相等。（原文写的是“概率严格和为 1，小数两位，实测多组 `sum` 都是 1.0000000000，没有浮点残差”。）
- **`choice` 基本就是概率最高的那项，但不保证。** 上面那 11,916 条 choice 回答（7 份日志，OpenRouter、`typesafe/jev-1.13-20260917`）里，choice 是唯一最高项 11,415 条，落在并列最高的几项里 413 条，比最高项低 88 条（0.74%）。这 88 条按回包的两位小数看都正好低 0.01，没有一条低 0.02 以上；头两档只差 0.01 的 855 条里，choice 落在低的那档约一成。88 条全在概率和正好 1.00 的回包里，和为 0.99、头两档也只差 0.01 的 31 条里一条没有，像是服务端取两位小数后为凑满 1.00 调了某一项、把顺序顶反了一档（推断，看不到服务端怎么算）。所以头两档只差 0.01 时当并列看；要按最高概率决策就自己对 `probabilities` 取最大，要 Jev 的选择就读 `choice`。[网页对弈版](../README.md#在浏览器里和-jev-下棋)的一盘实战里也碰到过：Jev 第 16 步显示 0.19 的那步没选，选了 0.18 的。统计同样见 `integration/analyze_choice_top.py`。
- **`noul` 没有 `confidence` 字段**，只有一个 0–1 的数；`choice` 和 `score` 才有。想对是非题做"不确定就转人工"，得自己用 0.5 附近的区间判断，没有现成的置信度可读。
- **`score` 返回的是概率加权后的小数**（1.97 不是 2），外加一个 `legend` 把档位序号翻回你写的原文。这个小数是档位位置的概率期望，比只看 `argmax` 多保留位置信息，但仍会丢掉分布形状：概率落在隔开的两档时它会指向一个概率为 0 的档，不同分布也能给出同一个分数。做阈值前先定按位置期望，还是按“至少第 k 档”的概率合计，并保留完整 `probabilities`；生产阈值要用标注集定（依据是另一轮 score 专项实测，未收录本仓库）。（原文写的是“做阈值时用小数比用 `argmax` 信息量大得多”。）
- **`criteria` 的描述可以留空**。JS SDK 里 `choice("哪个团队？", { billing: null, frontend: null, account: null })` 实测能跑，键名自己就是语义。

### 边界

| 项目 | 实测 |
|---|---|
| `choice` 选项数 | 255 上限确凿：256 项报 `Too many choices. Must have at most 255 choices.`；1 项也接受（返回概率 1.0） |
| `score` 档位数 | 10 上限确凿：11 档报 `Too many score levels. Must have at most 10 levels.`；1 档也接受 |
| `questions` 为空 | 400 `At least one question is required` |
| 一次问 40 个问题 | ✅ 正常返回 40 条答案 |

## 官方 SDK 指到 OpenRouter

"只换 key 和 base URL"这句实测成立。JS SDK 完整跑通：

```js
import { TypeSafeClient, noul, choice, score } from "@typesafe-ai/sdk";

const client = new TypeSafeClient({
  apiKey: process.env.OPENROUTER_API_KEY,   // 不是 TypeSafe 的 key
  baseURL: "https://openrouter.ai/api",     // SDK 自己补 /v1/systemone
});

const res = await client.systemOne({
  model: "jev-1.13",
  state: { ticket: "付款以后页面变成空白，换了两个浏览器仍然如此。", tier: "enterprise" },
  questions: {
    is_bug:  noul("这是否属于软件故障？"),
    dept:    choice("哪个团队最适合处理？", { billing: null, frontend: null, account: null }),
    urgency: score("有多紧急？", ["可以等", "本周处理", "立即处理"]),
  },
});

console.log(res.answers.dept.choice);          // frontend
console.log(res.answers.dept.probabilities);   // { frontend: 0.93, billing: 0.07, account: 0 }
```

实测 1.00 秒返回，答案类型由问题定义推断出来，`res.answers.dept.choice` 在 TypeScript 里是三个键的联合类型而不是 `string`。

Python SDK 同样跑通了（`typesafe-sdk` 要求 Python ≥3.10，本机系统自带的是 3.9.6，装了 3.13 之后验证）。它的依赖也值得一提：`httpx2`、`pydantic` ≥2.12、`tenacity`。关键常量与 JS 侧一致：

```text
API_KEY_ENV      = "TYPESAFE_API_KEY"
BASE_URL_ENV     = "TYPESAFE_BASE_URL"     # 不改代码也能换入口
DEFAULT_BASE_URL = "https://api.typesafe.ai"
DEFAULT_MODEL    = "jev-latest"
DEFAULT_TIMEOUT  = 10.0
SYSTEM_ONE_PATH  = "/v1/systemone"
```

构造参数是 `base_url=`（JS 侧是 `baseURL`），方法名 `system_one()`，响应上有 `.nouls` / `.choices` / `.scores` 三个分类访问器：

```python
from typesafe_sdk import TypeSafeClient, Noul, Choice, Score

client = TypeSafeClient(
    api_key=os.environ["OPENROUTER_API_KEY"],   # 不是 TypeSafe 的 key
    base_url="https://openrouter.ai/api",
    model="jev-1.13",
)
resp = client.system_one(
    state={"ticket": "付款以后页面变成空白，换了两个浏览器仍然如此。", "tier": "enterprise"},
    questions={
        "is_bug": Noul(instructions="这是否属于软件故障？"),
        "dept":   Choice(instructions="哪个团队最适合处理？",
                         criteria={"billing": "账单与支付", "frontend": "页面渲染与浏览器",
                                   "account": "账户与权限"}),
        "urgency": Score(instructions="有多紧急？", criteria=["可以等", "本周处理", "立即处理"]),
    },
)
print(resp.nouls["is_bug"].noul)            # 0.9
print(resp.choices["dept"].choice)          # frontend
print(resp.scores["urgency"].score)         # 1.92
```

1.07 秒返回。异步客户端 `AsyncTypeSafeClient` 同样可以指向 OpenRouter，实测通过。异常映射也是对的：11 个档位抛 `TypeSafeBadRequestError`，坏 key 抛 `TypeSafeAuthenticationError`。

### 但 SDK 换了入口后有两个东西会坏

**第一，列模型的方法直接抛异常。** `client.models.list()` 打到 OpenRouter 的 `/v1/models`，拿回来的是 OpenRouter 自己的模型目录格式，SDK 按 TypeSafe 的 schema 校验不过：

```text
TypeSafeAPIResponseValidationError:
GET https://openrouter.ai/api/v1/models: 200 Invalid response data at 'models'.
```

HTTP 是 200，错在客户端校验。判断模型可用性别指望这个方法。

**第二，OpenRouter 多给的字段会被 SDK 丢掉。** 原始回包里有 `cost`、`id`、`provider`，而 SDK 的响应对象只有 `answers` / `model` / `usage` 三个字段，`usage` 里也只有 `input_tokens` 和 `output_tokens`——**`cost` 拿不到**。想按实际花费记账或者要留 `id` 做排查，就得绕过 SDK 走原始 HTTP。

## 实测数据

### 扇出几乎免费——这是接它的真正理由

同一段 state，12 个是非判断：

| 做法 | 耗时 | 输入 token | 花费 |
|---|---|---|---|
| 1 个问题 | 0.9–1.1 s | 328 | $0.0000138 |
| **12 个问题，一次请求** | **0.90–0.91 s** | **487** | **$0.0000205** |
| 12 个问题，拆 12 次请求 | 10.8–11.8 s | 3,936 | $0.000166 |

耗时一列跑了两批（间隔约一小时），给的是两批的范围；token 与花费两批完全一致。

问题从 1 个加到 12 个，**耗时没变**，输入 token 只从 328 涨到 487——state 只吃一遍，问题各自 fan out。拆成 12 次请求则是 **12.0–12.9 倍耗时、8.1 倍价钱**（两批分别测得）。

这条直接决定接入姿势：**别一个判断发一次请求**。把一个场景里所有要判的事一次性列全，反而更快更便宜。

额度比 12 个大得多。后来把问题数一路加上去测过（见 [打游戏实测记录](../games/README.md) 第五节）：**128 个问题 1.31 秒、300 个 1.71 秒、900 个 2.4–2.8 秒**，再多就撞整请求 64K 的墙。平均每个判断摊到 5.7 毫秒。逐题准确率 300 题以内两跑全对，500 题错 4–7 个、900 题错 3–4 个（99% 上下）——延迟平坦，准确率到几百题还是会漏。**实测范围内没碰到题数上限，先撞的是 token 墙**（1,000 题报 token 超限）。（原文写的是"问题数没有独立上限，天花板是 token"；token 墙挡在前面，更多题数有没有单独的上限测不到。）

### 稳不稳

同一份输入连发 6 次：

```text
noul=0.90  0.90  0.90  0.90  0.91  0.90      choice 全部 frontend，p=0.99，conf=0.99
```

基本稳定，偶有 ±0.01 抖动。**阈值别卡在整数边界上**——你要是把线画在 0.90，这组输入里就有一次会翻到另一边。留 0.02 以上的缓冲。

### 延迟与并发

- 单次请求稳定在 **0.85–1.0 秒**（本机经公网到 OpenRouter，未做多地对比）。官方宣称的 70–500ms 是美西本地测的，别照抄进你的 SLA。
- 3 万 token 的大 state：**1.6–1.7 秒**，涨得很平。
- **20 个请求并发打出去：20 个全 200**，中位 0.93 秒、最慢 1.70 秒，墙钟 2.79 秒，没撞到任何限流。OpenRouter 侧对 Jev 的具体配额没有公开数字，这次也没触到。
- **偶尔有一次会拖几十秒**（2026-09-21 补）：做网页对弈版前后约 790 次调用，有 3 次单次调用超过 20 秒——21 秒、76 秒，还有一次 90 秒还没回；那天平时每次中位 1.10 秒。**urllib 的 timeout 挡不住这种慢**：它管的是多久没收到数据，不是总时长，那次 21 秒的调用就是在 20 秒 timeout 下照样等完的。要限时得自己按总时长截断，做法见 [打游戏实测记录](../games/README.md) 第六节。

### 上下文是两道墙：state + 最长问题 32K，整请求 64K

> **2026-09-20 晚更正。** 本节原来的标题是「上下文真实上限是 32K 量级，不是 64K」，正文断言「官方文档说的 64K 总预算，在这条路上不成立」。**那是测法造成的错觉**：当时只往 `state` 里灌长文，而那种形状下两道墙正好重合在 32K。后来一次问 900 个小问题、计费 64,537 token 却正常返回，才发现总预算这条是对的。复现脚本 `exp_ctx_rule.py`。

逐级加大 state 探到的第一道边界：

| 计费输入 token | 结果 |
|---|---|
| 32,246 | ✅ |
| 32,728 | ✅ |
| **32,924** | ✅ 最大成功值 |
| ~33,020 | ❌ `max_tokens_exceeded` |

这道墙落在 **32,768（2^15）左右**——计费的 `input_tokens` 还包含约 250–300 token 的问题与协议开销，所以能过的最大计费值略高于 32,768。

但它管的**不是整个请求，而是「`state` 加上最长的那一个 question」**。固定住这个配对、只把请求总量堆高，能过的总量远超 32.9K：

| 请求形状 | 每对（state + 最长问题） | 整请求计费 | 结果 |
|---|---:|---:|:--|
| state 32K + 1 个短问题 | ≈32K | 32,283 | ✅ |
| state 33K + 1 个短问题 | ≈33K | ~33K | ❌ |
| state 30K + **1 个 5K 长问题** | ≈35K | ~35K | ❌ 总量更小反而被拒 |
| state 15K + 3 个 10K 长问题 | ≈25K | **45,334** | ✅ 总量大得多却通过 |
| state 15K + **2 个 20K 长问题** | ≈35K | ~55K | ❌ 总量比下一行小，那一对超了就不行 |
| state 15K + 5 个 10K 长问题 | ≈25K | **65,380** | ✅ |
| state 5K + **29** 个 2K 长问题 | ≈7K | **63,951** | ✅ |
| state 5K + **30** 个 2K 长问题 | ≈7K | ~66,000 | ❌ 只多一个问题就过线 |
| 900 个小问题（state 很小） | ≈小 | **64,537** | ✅ |
| 1000 个小问题 | ≈小 | ~71,700 | ❌ |

所以两条同时成立，**和官方文档写的一字不差**：

```text
state + 单个最长 question  ≤ 32,768
整个请求                   ≤ 65,536
```

这两个数大概率是**服务端内部计数**的口径（推断），从外面观测到的边界各差一段固定开销：墙一按「`state` 字数 + 单个问题字数」算，32,736 过 / 32,737 拒（+32 即 32,768）；墙二按计费 `input_tokens` 算，65,792 过 / 65,793 拒（−256 即 65,536）。这是另做的一轮二分复核（92 次请求，脚本未收录本仓库）钉下来的，上面两张表的计费值按同一口径读。

实用含义：**长状态省不下来时，把要判的事拆成多个问题不会让你更早撞墙**（每个问题各自和 state 配对算），但总量仍封在 64K。

这个限制**来自上游 TypeSafe 而不是网关**：证据是错误体形状。OpenRouter 自己的校验返回 zod 风格的结构化数组（如缺 `state` 时逐字段报错），而超限错误是 `HTTP 400: {"detail":{"error_type":"max_tokens_exceeded"}}` 这种**上游原样包一层**的形状，和 255 选项、10 档位这两条已知的 TypeSafe 限制报错形状完全一致。不过没有官方 key 直连做对照，**不能断定官方直连也是 32K**。

> 原文这里还有一句「上限算的是整个请求，不是单看 state」，举的例子是 3 万 token 的 state 加 40 个问题一起过、计费 29,849 token。那个例子两道墙都没碰到，**证不出结论**，已按上表更正。

### 浏览器能直接调：跨域全开

（2026-09-21 补测）OpenRouter 的 Jev 接口对任何来源的网页都放行跨域。不带 key 的预检请求回 204、`Access-Control-Allow-Origin: *`，允许的请求头里有 `Authorization` 和 `Content-Type`，允许的方法里有 `POST`；带 key 真发，从 `http://localhost` 和 `https://example.com` 两个来源都是 200，同样回 `*`。再在真浏览器（无头 Chrome，页面在 `http://127.0.0.1`）里用假 key 直接 `fetch`，拿到的是读得出内容的 401，没被跨域拦下。

所以**把 key 写进网页，浏览器不会替你拦**：写进页面的 key，打开页面的人都拿得到。网页要调 Jev，要么像网页对弈版那样经本地或服务端转一道，要么让用户填他自己的 key。

复现（不需要 key）：

```bash
curl -si -X OPTIONS https://openrouter.ai/api/v1/systemone \
  -H 'Origin: https://example.com' -H 'Access-Control-Request-Method: POST' \
  -H 'Access-Control-Request-Headers: authorization,content-type' | grep -i '^access-control'
```

## 与文献结论的出入

integration-from-docs.md（文献版，未收录本仓库） 是基于官方与平台文档写的，这次实测推翻或补充了五条。**注意范围：以下全部在 OpenRouter 这条路上测得，官方直连未验证。**

| 文献说 | 实测 |
|---|---|
| 固定版本 ID 是 `jev-1.13.0`，生产应钉它 | OpenRouter **拒绝** `jev-1.13.0`（400 不存在）。真正能钉的是 `typesafe/jev-1.13-20260917` |
| 还有 `jev-preview` 别名 | 同样 400 不存在 |
| schema 错误返回 422 | 一律 **400**，没见过 422 |
| 入口是 `/v1/systemone` | 还有一个文档没提的 `/api/alpha/decisions`，行为一致 |
| `score` 接受 2–10 个有序等级 | 上限 10 确凿。下界官方原文是建议（"Should have at least two levels; the API accepts up to 10"），不是接口承诺：OpenRouter 收 1 档、恒返回概率 1，Python SDK 不拦，JS SDK 在请求端拒绝——约定外用法，别依赖（`choice` 同样 1 项也收）。原来写的是"下界更宽：1 档也收"，把官方建议误读成了硬下限 |

有三条文献结论实测确认无误：**$0.042/M 输入、输出免费**，**官方 SDK 换 base URL 即可复用**，以及**上下文那两条预算（state+最长问题 32K、整请求 64K）**——后者一度被我误判为不成立，见上一节的更正记录。

错误码的完整实测：

| 场景 | 实际返回 |
|---|---|
| key 无效（OpenRouter） | `401 User not found.` |
| 题型写成 `boolean` | `400`，zod 报错，明说合法值只有 `noul` / `choice` / `score` |
| 缺 `state` | `400`，逐字段说明 |
| `questions` 为空 | `400 At least one question is required` |
| 选项/档位超限 | `400`，上游原文包一层 |
| 超出上下文 | `400 max_tokens_exceeded` |
| 官方直连不带 key | `403 authentication_error`（顺带确认 `api.typesafe.ai` 真实在线） |

**结论：写重试逻辑别只认 429/529。** 这条路上绝大多数失败是 400，而 400 重试再多次也没用——该分流到告警。

## 中文能不能用：能，而且不是阈值该担心的地方

这一节上一版写错了，保留更正记录。

上一版我用 3 个案例得出"中文打分比英文高出大半档，所以阈值要跨语言重调"。数字没错，**归因错了**：我给中英文写的档位描述并不完全等价，那个差距里有三分之一来自档位文案而不是内容语言。把两个变量拆开重测（2×2、12 用例、每格 3–5 次）之后：

- **分类判断上中文完全不吃亏**：四种语言组合各 12/12 判对。
- **语言对打分的影响逐例最多约 18% 满量程，12 例平均只有 −0.04、方向还不固定**，有的用例反而英文打得更高。
- **真正的大变量是档位描述怎么写**：语言全固定为中文，只改三档的措辞，分数移动中位 0.50、最大 1.32（满量程 2.0）。

所以正确的告诫不是"中英文要各调一套阈值"，而是：**阈值要钉在你最终上线的那套档位文案上，档位文案一改就得重标。**

中文专项的完整数据——含讽刺/双重否定/委婉拒绝/语音转写/繁体等 10 类表达的识别、反问句专测、简繁与 emoji 鲁棒性、中文键名、一字一 token 与 31,880 汉字容量、3 万字长文的位置无关性——见 [Jev 的中文表现实测](../chinese/README.md)。

## 接生产前该做的事

1. **钉快照版本**：写 `typesafe/jev-1.13-20260917`，不要写 `jev-latest`。别名一换，你调好的阈值全部作废。
2. **一次问全**：一个场景所有判断打包进一次请求，别按问题拆请求。
3. **阈值留缓冲**：概率有 ±0.01 抖动，线别画在会被抖过去的位置。
4. **先量 calibration**：`0.9` 是模型的置信度，不是你业务上的 90% 正确率。拿自己的标注集量一遍准确率再定线。
5. **错误分流**：400 归告警（你的请求有问题），429/529 才退避重试。
6. **`state` 按 32K 规划**（加上最长的那个问题一起算），进来前先截断或摘要；整请求另有 64K 的墙，问题多了照样会撞。
7. **key 只放服务端**，OpenRouter key 能花钱，不能进前端包、不能进仓库。跨域是全开的，浏览器不会替你拦。
8. **过一遍两层数据政策**：走网关意味着请求同时经过 OpenRouter 和 TypeSafe，两家的留存政策都要看。
9. **档位文案当配置管起来**：改一次档位描述等于换一把尺子，分数会整体位移，必须连着阈值一起重标。
10. **要记账就别全靠 SDK**：官方 SDK 会丢掉 OpenRouter 返回的 `cost`，按花费做成本归集得走原始 HTTP。
11. **每次调用设总时长上限**：偶尔一次会拖几十秒，urllib 的 timeout 只管多久没收到数据，管不住总时长。

## 未验证

- **TypeSafe 官方直连**：无账号，只确认了 `api.typesafe.ai` 在线且无 key 返回 403。官方的 64K 上下文、250k tokens/s + 1200 RPM 限流、422 错误码，全部未验证。
- **Vercel AI Gateway 与 Cloudflare Workers AI** 两条路径本次一次都没跑。
- **限流**：并发 20 未触发，更高并发未试，OpenRouter 对 Jev 的实际配额未知。
- **只测了一个快照** `typesafe/jev-1.13-20260917`，跨版本行为差异未知。
- **calibration 未验证**：本文所有概率只用来看接口行为，没有标注集，不能说明 Jev 判得准不准。
- **中文结论的边界**见中文专题末节：用例是构造的、偏容易，难用例上的中英差距未知。
