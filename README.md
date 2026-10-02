[English](README.md) | [简体中文](README.zh-CN.md)

# jev-study

A hands-on study of [Jev](https://typesafe.ai/) (TypeSafe's "System One" model) accessed through OpenRouter: integration, Chinese-language behaviour, game loops with two board-game case studies (chess and Chinese chess / xiangqi), and in-context learning. Every headline number in the reports comes from real API calls, and most of them can be rerun with the scripts in this repo; the few that cannot say so where they appear. Reports are in Chinese.

~238,200 API calls, about $13.1 in total. All tests ran against the snapshot `typesafe/jev-1.13-20260917` through OpenRouter; the official TypeSafe endpoint, Vercel AI Gateway and Cloudflare Workers AI were not tested. The test cases are hand-built, with no third-party labelled set, so the data shows whether two conditions differ, not an accuracy rate: a `0.9` in a response is the model's output, not "90% correct".

## Reports

| Report | Key findings | Calls |
|---|---|---|
| [Integration](integration/README.md) (in Chinese) | One OpenRouter key and one `curl` are enough; no TypeSafe account needed. Asking 12 questions in one request takes as long as asking one, and costs 1/8 of 12 separate requests. Context has two limits: `state` plus the costliest single question ≤ 32,743 tokens, and the whole request ≤ 65,792 billed tokens (the docs only say "32k" / "64k"; the pairing explanation was first proposed by [Archer Hume](https://archerhume.com/posts/jevs-architecture-unmasked/)). | ~160, plus 695 for the limit bisection |
| [Chinese](chinese/README.md) (in Chinese) | Chinese costs nothing on classification (12/12 in all four language mixes) and idioms such as sarcasm, double negatives and slang are read correctly. What shifts `score` results is the wording of the level descriptions (median shift 0.50, up to 1.32 on a 2.0 scale), not the language. About one token per Chinese character; a key sentence is found anywhere in a 30,000-character document. | ~570 |
| [Games](games/README.md) (in Chinese) | A game loop takes a few dozen lines, but taking only the top answer each step, it behaves like a one-step greedy picker and gets stuck circling at dead ends. The state adapter matters more than the prompt: precomputed passable directions gave 0 illegal moves, a raw ASCII map gave 28% wall bumps. A serial loop tops out around 0.9 Hz; one request can carry 900 questions. | ~1,100 |
| ↳ [Chess](games/chess/README.md) (in Chinese) | Mate-in-one looks perfect (10/10) only because SAN marks the mating move with `#`; strip the marks and it finds 10 of 48. Best move 6/12, and rewording the question does not reduce blunders. | ~1,310 |
| ↳ [Chinese chess](games/xiangqi/README.md) (in Chinese) | The early "chess 10/10 vs. xiangqi 2/32" gap came from the `#` marker and invalid test positions. Jev cannot read a xiangqi FEN (6% of occupied squares), knows the rules but cannot apply them to the board, and with an adapter that precomputes captures and checks it plays at roughly greedy-capture level. | ~10,900 |
| [In-context learning](learning/README.md) (in Chinese) | Jev does learn from examples placed in `state`: few-shot classification with meaningless labels goes from 23% to 85% with one example per class. In bandits, sampling from its probabilities beats always taking `choice` (85% vs 62% late-game hits). Without distance hints it rarely reaches goals that need a long detour (about a quarter of such starts); across repeated maze games, most of the improvement comes from the code that records traps and recomputes distances. | ~226,070 |

## Quick start

```bash
export OPENROUTER_API_KEY="sk-or-v1-..."     # API_KEY_OPENROUTER also works

python3 integration/replicate.py             # reruns the three headline findings, 33 calls
```

Scripts can be run from any directory. Most use only the standard library and run on Python 3.9; they call Jev over plain HTTP rather than through the official SDK. The exceptions (the SDK tests, the chess and xiangqi experiments) list their `pip install` lines in the [Chinese README](README.zh-CN.md#怎么跑). Each script writes its log next to itself; logs are git-ignored.

**Running everything costs real money**: about $13 in total, mostly the in-context learning bandits (`learning/exp_icl_bandit3.py` and `exp_icl_bandit4.py`, 158,400 calls, about $9.2). The [Chinese README](README.zh-CN.md#每个脚本对应哪条结论) maps every script to the finding it backs and its call count.

## Play against Jev in the browser

Chess (no packages needed):

```bash
python3 games/chess/play_chess.py
```

Chinese chess:

```bash
python3 -m pip install pyffish==0.0.90 cchess==1.25.5 chess==1.11.2
python3 games/xiangqi/play_xiangqi.py
```

Each starts a local server on 127.0.0.1 and opens the browser. You move, Jev answers, and the side panel shows its top five moves with probabilities. The key stays in the local process and never reaches the page. A move takes about 1.1 seconds; a 40-move chess game costs about $0.002. Jev sees exactly the same request as in the experiments, so the chess and xiangqi findings above apply as-is.

## Layout

```
jevkit.py       shared: API wrapper, concurrency, usage counter, question builders
corpus.py       shared: test corpus
integration/    integration report + scripts
chinese/        Chinese-language report + scripts
games/          game-loop report + general scripts; one subdirectory per board game
  chess/        chess report, experiments, browser game (play_chess.py)
  xiangqi/      Chinese chess report, experiments, position set, browser game (play_xiangqi.py)
learning/       in-context learning report + 12 experiment scripts
xiangqi/        redirect kept for old links (moved to games/xiangqi/)
```

`games/play_chess.py` and `xiangqi/play_xiangqi.py` are also redirects kept for old links and commands.

## License

MIT, see [LICENSE](LICENSE).
