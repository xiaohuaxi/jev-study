# jev-study

试着把 TypeSafe 的 Jev 接进真实项目，顺手把每个结论都测了一遍。**报告里的每个数字，这里都有对应脚本可以重跑。**

> A hands-on study of [Jev](https://typesafe.ai/) (TypeSafe's "System One" model) accessed through OpenRouter:
> integration, Chinese-language behaviour, and game loops. Every figure in the reports is reproducible
> by the scripts in this repo. Reports are in Chinese. ~1,450 API calls, about $0.15 total.
> There is also a one-command browser game: play chess against Jev (`python3 games/play_chess.py`).

## 这是什么

三份实测记录，外加能把它们原样跑出来的脚本：

| 专题 | 读什么 | 规模 |
|---|---|---|
| [接入](integration/README.md) | 怎么调通、上限、错误码、延迟、官方 SDK 能不能换入口、真实花费 | 约 730 次请求 |
| [中文表现](chinese/README.md) | 中英对照、绕弯表达、档位文案对打分的影响、汉字容量、长文定位 | 约 570 次请求 |
| [打游戏](games/README.md) | GridWorld、国际象棋、中国象棋初探、实时循环的频率与成本、一次问几百个问题；另有[浏览器里和 Jev 下国际象棋](#在浏览器里和-jev-下棋)的网页版 | 约 1,230 次请求（含复核）；做网页版另用约 790 次，不在可复跑的脚本里 |

全部经 OpenRouter 实测，只覆盖模型快照 `typesafe/jev-1.13-20260917`；官方直连、Vercel AI Gateway、Cloudflare Workers AI 都没跑。其余没跑到的，各报告文末的「未验证」一节列了。

用例是我自己构造的，没有第三方标注集。**这些数据能看出两个条件之间有没有差别，得不出准确率**——回包里的 `0.9` 是模型的输出，不是"90% 正确"。

## 怎么跑

```bash
export OPENROUTER_API_KEY="sk-or-v1-..."     # 或 API_KEY_OPENROUTER，两个名字都认

python3 integration/replicate.py             # 先跑这个：三条头条结论的复跑，33 次请求
```

从任意目录跑都行，脚本自己会找到仓库根部的 `jevkit.py` 和 `corpus.py`。

**多数脚本只用标准库，Python 3.9 就能跑**——调 Jev 是直接发 HTTP 请求，不经过官方 SDK（在系统自带的 3.9.6 上实跑验证过）。

要装东西的只有这几个：`integration/pysdk_test.py` 和 `integration/sdk_gaps.py` 用官方 `typesafe-sdk`（它自己要求 Python ≥3.10），`games/exp_game_chess.py` 要 `pip install chess`，`games/exp_game_xiangqi.py` 要 `pip install cchess chess`，`games/play_chess_check.py` 要 `pip install chess` 和 Node。另有 `integration/jssdk_test.mjs` 用官方 `@typesafe-ai/sdk`，Node ≥20。

**会真的花钱。** 全套约 1,450 次请求、$0.15 上下。最贵的是单次塞三万到六万 token 的那几个（`exp_ctx_rule.py`、`exp_game_scale.py`、`exp_needle.py`、`exp_token.py`）。

**`jev.spend()` 打印的「失败」计数不一定是出错。** 探上限、探非法参数的实验本来就期望收到 4xx。

## 在浏览器里和 Jev 下棋

```bash
export OPENROUTER_API_KEY="sk-or-v1-..."     # 或 API_KEY_OPENROUTER
python3 games/play_chess.py                  # 不用装任何包，Python 3.9 起
```

脚本在本机起一个服务（只监听 127.0.0.1），自动打开浏览器。你在棋盘上走一步，Jev 回一步，右边列出它最看好的五步和各自的概率。能选执白或执黑、重开、升变选子、导出 PGN；将死、逼和、和棋都会正常结束（三次重复、五十回合按 chess.js 的做法直接判和，正式规则里要一方提出）。网址后面加 `?fen=...` 可以从指定局面开始。按 Ctrl+C 结束，终端会打印这次请求了几次、花了多少。

- **key 不进浏览器**：只在本机这个脚本进程里用，网页拿不到，也不打印、不写日志。脚本信任本机这个网页：合法着法由网页算好送来，脚本不重新核对；网页里的库和网页同源运行，理论上也能借脚本调 Jev（拿不到 key），所以同时在途的请求限 2 个。
- **要联网**：调 Jev 要连 OpenRouter；棋规和棋盘（[chess.js](https://github.com/jhlywa/chess.js)、[cm-chessboard](https://github.com/shaack/cm-chessboard)）从 jsdelivr 加载。
- **每步约 1.1 秒，一盘 40 步约 $0.002。** 偶尔有一次调用会拖几十秒，脚本等到 20 秒就断开另发一次，页面上会显示已经等了几秒。
- **Jev 看到的和[实验](games/README.md)里的一字不差**：同样的 FEN、轮到谁、全部合法着法、同一句问题，所以那边的结论照样适用——一步杀很准，静态局面会送子。`games/play_chess_check.py` 逐字节比对过 31,604 个局面，不调 Jev（要联网下 chess.js）。
- 网页只通过一个接口（`POST /api/move`）要 Jev 的回答，格式写在 `games/play_chess.py` 开头。

## 每个脚本对应哪条结论

| 脚本 | 验证什么 | 请求数 |
|---|---|---|
| `jevkit.py` | 公共库：并发发请求、用量统计、三种题型的构造器 | — |
| `corpus.py` | 语料：12 个中英平行工单用例、10 类中文特有表达、7 种同义写法、5 组同义句 | — |
| `integration/replicate.py` | **三条头条结论的复跑**：扇出经济性、档位文案效应、模型串与错误码 | 33 |
| `integration/exp_limits.py` | 题型上限（choice 255 / score 10）、state 四种形态、两个入口等价、聊天接口被拒、并发 20 | ~35 |
| `integration/exp_ctx_rule.py` | **上下文的两道墙**：state+最长问题 32,768、整请求 65,536；也是对旧结论的更正证据 | 10 |
| `integration/pysdk_test.py` | 官方 Python SDK 指向 OpenRouter：同步、异步、异常映射 | 4 |
| `integration/sdk_gaps.py` | SDK 换入口后丢了什么：`usage.cost`、`id`、`provider` 都拿不到 | 1 |
| `integration/jssdk_test.mjs` | 官方 JS SDK 指向 OpenRouter，含类型推断 | 1 |
| `chinese/exp_main.py` | **2×2 主实验**：内容语言 × 提问语言，12 用例每格 3 次 | 144 |
| `chinese/exp_wording.py` | 拆开「内容语言」与「档位描述语言」两个变量 | 60 |
| `chinese/exp_levels.py` | **档位措辞效应**：只改三档写法，分数极差中位 0.50、最大 1.32 | 108 |
| `chinese/exp_tricky.py` | 10 类中文特有表达 + 4 条英文对照 + 7 种写法鲁棒性 | 63 |
| `chinese/exp_rhetorical.py` | 反问句是不是中文吃亏：4 句反问 + 3 句陈述，中英各 5 次 | 70 |
| `chinese/exp_keys.py` | 中文键名：选项键、描述留空、问题名、state 字段名 | 39 |
| `chinese/exp_needle.py` | 长中文文档里的关键句放开头/中间/末尾，3 千到 3 万字 | 29 |
| `chinese/exp_control.py` | **上面那个实验的对照组**：文档里确实没有关键句时会不会硬说有 | 9 |
| `chinese/exp_token.py` | 中文 token 经济性、汉字容量二分探到 31,880 字 | ~20 |
| `games/exp_game_grid.py` | **GridWorld 三臂对照**：JSON 状态 / ASCII 地图 / JSON+访问计数 | ~400 |
| `games/exp_game_objective.py` | 同一张图只换目标那一句话 | ~86 |
| `games/exp_game_probe.py` | 七个固定场景；一次问 1 个 vs 3 个的延迟与计费 | 50 |
| `games/exp_game_rate.py` | 串行循环 Hz、固定 10 Hz 重叠飞行、决策过期 tick 数、成本核对 | 75 |
| `games/exp_game_scale.py` | 候选项 2→255 的延迟与位置偏好、一次问 1→500 个问题 | ~59 |
| `games/exp_game_chess.py` | 一步杀、最佳着法选中率、对随机走子 4 局（需 python-chess） | ~128 |
| `games/play_chess.py` | **在浏览器里和 Jev 下国际象棋**（网页是旁边的 `play_chess.html`）：请求与 `exp_game_chess.py` 逐字节相同 | 每步 1 次 |
| `games/play_chess_check.py` | 上面那句"逐字节相同"的证据：31,604 个局面比对两边的请求体（需 python-chess 与 Node，要联网下 chess.js） | 不调 API |
| `games/exp_game_xiangqi.py` | 中国象棋初探：同一套接法换成中国象棋，看盘、规则、一步杀（需 cchess 与 python-chess） | ~25 |

## 两个教训

`chinese/exp_control.py` 单独存在是有原因的。第一版长文实验的对照组写错了分支，"没有关键句"那组实际上照样插了关键句，结果显示"无关键句也有 0.97 命中"，看着像模型在胡乱说是——其实是脚本的 bug。修好后对照组是 0.01。

**做这类测试一定要有对照组，而且要断言对照文本里真的不含目标内容**，否则很容易把自己的 bug 当成模型缺陷发出去。

同样的教训还有一条：探边界要沿每个维度分别加压。上下文那条我一开始只往 `state` 里灌长文，那种形状下两道墙正好重合在 32K，就看成一道了，还错误地断言官方文档写错了。见 `integration/exp_ctx_rule.py`。

## 目录

```
jevkit.py       共用：调用封装、并发、用量统计、三种题型构造器
corpus.py       共用：测试语料
integration/    接入实测 + 脚本
chinese/        中文表现实测 + 脚本
games/          打游戏实测 + 脚本 + 浏览器对弈（play_chess.py）
```

脚本跑完会在自己旁边写运行日志（`*_log.json` / `.jsonl`），这些是可重跑的产物，已在 `.gitignore` 里排除。

## 许可

MIT，见 [LICENSE](LICENSE)。
