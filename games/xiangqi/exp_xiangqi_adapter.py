# -*- coding: utf-8 -*-
"""实验 C：适配器阶梯、确定性基线与整局（中国象棋实测）。

回答两件事：
  问题 2  适配器替 Jev 算到哪一层它才做出有意义的选择；每一层 Jev 相对「拿同样信息的确定性策略」有没有增益，
          还是棋库在下（C1 静态阶梯，两棋种）。
  问题 3  最佳接法下整局棋力、成本、延迟，以引擎打分为准（C2 整局，只做中国象棋）。

用法（从任意目录都能跑；Python 环境要装好 pyffish / cchess / chess 和引擎，见 boards.py 开头）：
  python exp_xiangqi_adapter.py static [--dry]          C1：两棋种 middle + gain 各 30 局面 × L0–L3，外加抖动组；
                                                         日志 xiangqi_adapter_log.json，断点续跑（已成功的跳过）；--dry 只造请求、跑断言、不发
  python exp_xiangqi_adapter.py calibrate [--workers N]  C2 前置：greedy2 执红对「引擎前 k 名里随机挑」的弱引擎，
                                                         扫 k × depth，找 greedy2 不至于全胜全负的设置（不花钱）；日志 xiangqi_calib_log.jsonl
  python exp_xiangqi_adapter.py games [--workers N] [--only free|jev]
                                                         C2：Jev（L0/L1/L2）与三个免费基线执红，对随机 / 弱引擎各 20 局；
                                                         每步落盘 xiangqi_games_log.jsonl，断点续跑（已记下的 Jev 回包原样复用）
  python exp_xiangqi_adapter.py evalgames [--workers N]  C2：引擎复评每一步执红着法（全部合法着法 searchmoves，深度 EVAL_DEPTH）
                                                         与截断终局评估；日志 xiangqi_games_eval_log.jsonl，断点续跑
  python exp_xiangqi_adapter.py report [static|games|calib|all]   只读日志出表，不发请求（all = 三份依次出）

适配器层（每层的完整选项例子见 report static 的开头）：
  L0  state = boards.state(FEN) ；选项 = U0「车从 h6 走到 e6」
  L1  选项 = U3（吃什么、将军、将死）
  L2  L1 + 安全事实（boards.safety）：走完后对方能吃的我方子（格 + 子）、对方吃子最多吃掉哪个子；不给总分
  L3  L2 + 两层物质净得数值（boards.safety()['gain']，= two_ply）；state 加一句 note 说明这个数的含义与子值
  state 形态：臂名不带后缀 = FEN（照初探接法）；带 @pieces = boards.state(form='pieces') 子力清单。
  C1 两种都跑（同层配对比较）；C2 三层都用 @pieces——实验 B 发现 FEN 下 Jev 读中国象棋盘面只认对 6% 的有子格，
  子力清单 100%，用 FEN 会把「最佳接法」低估。C2 最早用 FEN 开过 115 次请求（L0 对随机 6 局，都没下完），
  已作废、移到 xiangqi_games_fenpartial_log.jsonl，不进分析。
提问句：「你在下中国象棋，执红。从合法着法里选一步最好的。」（国际象棋换成执白），不提示一步杀。
选项键一律 boards.options(texts, 局面, rep=rep)：键与顺序只由 (局面, rep) 定、各层共用（同一局面同一步在 L0–L3 里是同一个键、同一位置）；state 不放着法清单。

口径：
  - 厘兵损失：C1 用局面集存好的 move_scores（深度 12，全部合法着法 searchmoves 同批搜）；C2 用 EVAL_DEPTH 对全部合法着法
    重新 score_moves。每步分数先封顶到 ±CAP（1000 厘兵）再算「最高分 − 该步」，所以单步损失 ∈ [0, 2000]。
  - 失误 = 损失 ≥ 200；与引擎最佳着一致 = 所选着 ∈ 原始（未封顶）score_moves 最高分集合。
  - 确定性基线：主表用「在该基线并列集合里均匀挑」的期望值（= 无穷多个种子的平均，精确、无抽样噪声）；
    另报按局面固定种子（seed_of('C1', 局面, 基线)）单抽一次的数，两者应接近。
  - 区间：率用 Wilson 95%；均值与配对差用按自对弈对局聚类的 bootstrap（10000 次，百分位）。C2 按开局序号配对 bootstrap。
  - C2 截断（120 半回合）时用引擎深度 12 评估终局，红方视角 ≥ +ADJ 记「优势」、≤ −ADJ 记「劣势」、其间「均势」。
    下棋时长将、长捉、重复局面都不实现，只靠 120 半回合上限截断；report games 事后按标准规则重放（rule_end）改判。

v2（独立审查后，只改分析、不重发请求）：
  - 同信息基线改成「只看选项文字的规则」text1 / text2（见 parse_text 一节）：从 Jev 实际看到的选项文字解析事实，配标准子值表
    （兵一律 1）决策，解析结果与 boards.facts / safety 反向核对。C1 主比较 = Jev 各层对同层文字规则（L0 对 random，
    L3 对 greedy2）；greedy1 / greedy2 保留为「对应复杂度的棋库基线」。C2 在 Jev 走到的局面上另算同层文字规则的反事实损失。
  - C2 每步质量只排除「全部候选封顶损失都为 0」的局面（v1 排除最佳分 ≥ 封顶的局面，漏掉优势方的坏着）。
  - 比率类区间按自对弈对局（C1）/ 对局（C2）聚类 bootstrap，0 或全中时退回 Wilson（标 †）；C1 12 个主比较做 Holm；
    两棋种差距之差按两棋种独立重抽；抖动组估计单次请求波动的大小。
  - C2 按标准规则重放：pyffish 带着法历史调 is_optional_game_end / is_immediate_game_end，另用「同一局面第三次出现 + 长将」自写核对。

每次请求记下回包模型串、usage、耗时；模型串不是 typesafe/jev-1.13-20260917 立即停下。
日志都在本目录，被 .gitignore 排除（*_log.json / *_log.jsonl）。
"""
# 让本脚本从任意目录都能找到仓库根部的 jevkit.py
import sys as _sys, pathlib as _pathlib
_sys.path.insert(0, str(_pathlib.Path(__file__).resolve().parent.parent.parent))
import json, math, os, random, re, statistics, sys, time
from concurrent.futures import ProcessPoolExecutor, as_completed

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import boards as b  # noqa: E402
import pyffish as sf  # noqa: E402

XQ, CH = b.XQ, b.CH
# 环境变量可改日志路径（只给离线自检用：拿假回包跑通 report，不碰真日志）
LOG = os.environ.get('XQA_LOG') or os.path.join(HERE, 'xiangqi_adapter_log.json')
GLOG = os.environ.get('XQA_GLOG') or os.path.join(HERE, 'xiangqi_games_log.jsonl')
ELOG = os.environ.get('XQA_ELOG') or os.path.join(HERE, 'xiangqi_games_eval_log.jsonl')
CLOG = os.path.join(HERE, 'xiangqi_calib_log.jsonl')
MODEL = 'typesafe/jev-1.13-20260917'
CAP = 1000            # 每步分数封顶（厘兵）
BLUNDER = 200         # 失误阈值（厘兵损失）
ADJ = 300             # 截断终局判优势 / 劣势的阈值（红方视角厘兵）
EVAL_DEPTH = 10       # C2 逐步复评深度（C1 用局面集里的深度 12）
FINAL_DEPTH = 12      # C2 截断终局评估深度
GIVE = -4             # 送子：所选着的两层物质净得 ≤ -4
LAYERS = ('L0', 'L1', 'L2', 'L3')
PCS = '@pieces'       # 臂名后缀：state 用 boards.state(form='pieces')（子力清单）；不带后缀的臂 state 用 FEN（照初探接法）
ARMS = LAYERS + tuple(L + PCS for L in LAYERS)   # C1 的全部 Jev 臂
FREE = b.BASELINES    # ('random', 'greedy1', 'greedy2')
SAME_INFO = {'L0': 'random', 'L1': 'greedy1', 'L2': 'greedy2', 'L3': 'greedy2'}
ASK = {XQ: '你在下中国象棋，执红。从合法着法里选一步最好的。',
       CH: '你在下国际象棋，执白。从合法着法里选一步最好的。'}
NOTE = {XQ: '每个选项末尾的「两层物质净得」：我方走这步、对方再用对它最有利的一步应对之后，子力差比现在多了多少'
            '（车 9、马 4、炮 4.5、仕相 2、兵 1、过河兵 2；一步将死或让对方无着可走记 1000）',
        CH: '每个选项末尾的「两层物质净得」：我方走这步、对方再用对它最有利的一步应对之后，子力差比现在多了多少'
            '（后 9、车 5、象 3、马 3、兵 1；一步将死记 1000）'}
JITTER_IDX = (1, 7, 13, 19, 25)   # 每棋种每集取这几个序号的局面做抖动组（共 2 棋种 × 2 集 × 5 = 20 个局面）

# C2 设置
N_GAMES = 20
MAX_PLY = 120
JEV_PLAYERS = ('L0' + PCS, 'L1' + PCS, 'L2' + PCS)   # C2 三层都用子力清单作 state（实验 B：FEN 下中国象棋识子只对 6%）
WEAK = 'weak-k5d4'   # 弱引擎设置：calibrate 标定（greedy2 对它「胜或优势」8/20），见 report calib
CALIB_GRID = [(k, d) for d in (1, 2, 3, 4) for k in (3, 5, 8)]


# ================================================================ 公共：选项文字
def fmt_gain(x):
    if x == 0:
        return '0'
    return ('%+d' % x) if float(x).is_integer() else ('%+.1f' % x)


def safety_text(game, s):
    """L2 附在选项描述后面的安全事实（自然语言，不给总分）。"""
    if s.get('end') == 'stalemate':
        return '；走完后对方无着可走（困毙，按规则我方胜）' if game == XQ else '；走完后对方无着可走（逼和）'
    if s.get('end') == 'mate':
        return ''                                        # U3 已写「将死」
    th = s['threatened']
    if not th:
        return '；走完后对方吃不到我方的子'
    items = '、'.join('%s %s' % (t['square'], b.piece_name(game, t['piece'])) for t in th)
    return '；走完后对方能吃的我方子：%s；对方吃子最多吃掉一个%s' % (items, b.piece_name(game, th[0]['piece']))


def _check_safety(game, fen, mv, s):
    """独立核对 threatened：走完后逐个对方合法着法看落点上是不是我方子（国际象棋含过路兵）。"""
    fen1 = b.play(game, fen, mv, check=False)
    board1, stm1 = b.parse(game, fen1)
    mine = (lambda p: p.islower()) if stm1 == 'w' else (lambda p: p.isupper())
    caps = set()
    for r in b.legal(game, fen1):
        fr, to, _ = b.split_move(r)
        if to in board1 and mine(board1[to]):
            caps.add(to)
        elif game == CH and board1[fr] in 'Pp' and fr[0] != to[0] and to not in board1:
            caps.add(to[0] + fr[1])
    got = {t['square'] for t in s['threatened']}
    assert caps == got, ('安全事实与独立核对不符', game, fen, mv, sorted(caps), sorted(got))
    if s['threatened']:
        assert s['max_recapture'] == s['threatened'][0]['value'], ('最多吃掉的子不是清单第一个', fen, mv)


def layer_texts(game, fen, layer, fxs=None, check=True):
    """{着法: 选项描述}。L0 = U0；L1 = U3；L2 = U3 + 安全事实；L3 = L2 + 两层物质净得。"""
    fxs = fxs or b.all_facts(game, fen)
    if layer == 'L0':
        return b.describe_all(game, fen, 'U0', fxs=fxs)
    texts = b.describe_all(game, fen, 'U3', fxs=fxs)
    if layer == 'L1':
        return texts
    out = {}
    for m, t in texts.items():
        s = b.safety(game, fen, m)
        if check:
            _check_safety(game, fen, m, s)
        t += safety_text(game, s)
        if layer == 'L3':
            if s.get('end'):                             # 一步将死 / 困毙：按 note 写 1000（国际象棋逼和写 0）
                t += '；两层物质净得 %s' % fmt_gain(s['two_ply'])
            else:
                t += '；两层物质净得 %s' % fmt_gain(s['gain'])
        out[m] = t
    b.assert_distinct(out)
    return out


def split_arm(arm):
    """'L2' -> ('L2', 'fen')；'L2@pieces' -> ('L2', 'pieces')。"""
    layer, _, form = arm.partition('@')
    return layer, (form or 'fen')


def build_request(game, fen, arm, pos_id, rep=0, fxs=None, check=True):
    """arm = 层名，可带 @pieces 后缀换 state 形态。键与顺序只由 (局面, rep) 定：同一局面的各层、两种 state 共用。"""
    layer, form = split_arm(arm)
    texts = layer_texts(game, fen, layer, fxs, check)
    crit, k2m = b.options(texts, pos_id, rep=rep)
    for k, m in k2m.items():
        assert crit[k] == texts[m], '键 → 着法 → 描述对不上'
    st = b.state(game, fen, form=form)
    if layer == 'L3':
        st['note'] = NOTE[game]
    q = {'move': {'type': 'choice', 'instructions': ASK[game], 'criteria': crit}}
    return st, q, k2m


def parse_resp(d, crit):
    """-> (选中键, {键: 概率}, 置信度)。不符合断言直接抛错。"""
    assert d.get('model') == MODEL, ('回包模型串不是 %s：%r，立即停下' % (MODEL, d.get('model')))
    assert not d.get('_fake') or os.environ.get('XQA_ALLOW_FAKE'), '日志里混进了离线自检的假回包'
    a = d['answers']['move']
    p = {k: float(v) for k, v in a['probabilities'].items()}
    assert set(p) == set(crit), '回包选项键与请求不一致'
    assert a['choice'] in crit
    assert abs(sum(p.values()) - 1) <= 0.03, ('概率和', sum(p.values()))
    return a['choice'], p, float(a['confidence'])


# ================================================================ 只看选项文字的规则（v2：真正的同信息基线）
# greedy1 / greedy2 用精确子值（过河兵 2）并计入兵过河、升变这类非吃子得失，这些在 L1 / L2 的选项文字里看不到，
# 所以它们只是「对应复杂度的棋库基线」。下面的规则只读 Jev 看到的那段选项文字：从文字里解析出事实，
# 再配标准子值表（文字只写棋子名，看不出兵有没有过河，一律按 1 算）做决策。
#   text1（配 L1）：能将死就走 > 吃子值最大 > 将军 > 随机。L1 文字（U3）不写困毙，所以 text1 看不到困毙（greedy1 也不看）。
#   text2（配 L2）：最大化「吃子值 − 对方最多吃回的子值」，将死 / 中国象棋困毙记 WIN；并列再按 text1 的顺序挑。
#     「最多吃回」取文字里「对方吃子最多吃掉一个 X」的 X；国际象棋「逼和」记 0（C1 / C2 里都没出现）。
#   并列时均匀随机：主表取并列集合期望，另报按局面固定种子单抽一次。
# 解析结果逐项与生成文字用的事实（boards.facts / boards.safety）反向核对，防解析 bug。
TEXT_VAL = {XQ: {'车': 9, '马': 4, '炮': 4.5, '仕': 2, '士': 2, '相': 2, '象': 2, '兵': 1, '卒': 1, '帅': 0, '将': 0},
            CH: {'后': 9, '车': 5, '象': 3, '马': 3, '兵': 1, '王': 0}}
TEXT_RULES = ('text1', 'text2')
SAME_TEXT = {'L0': 'random', 'L1': 'text1', 'L2': 'text2', 'L3': 'greedy2'}   # v2 主比较：同层、同信息
WIN = 1000
_TXT = re.compile(r'^(?P<piece>\S)从 (?P<fr>[a-i]\d) 走到 (?P<to>[a-i]\d)'
                  r'(?:，车从 (?P<cf>[a-h]\d) 走到 (?P<ct>[a-h]\d))?(?:，升变为(?P<promo>\S))?'
                  r'(?:，吃掉对方的(?P<cap>\S))?(?:，(?P<mark>将军|将死))?(?P<rest>.*)$')
_THREAT = re.compile(r'^；走完后对方能吃的我方子：(?P<items>.+)；对方吃子最多吃掉一个(?P<top>\S)$')
_END_TXT = {'；走完后对方无着可走（困毙，按规则我方胜）': XQ, '；走完后对方无着可走（逼和）': CH}


def parse_text(game, text, layer):
    """从一条 L1 / L2 选项描述里解析事实。只看文字，不碰棋盘。"""
    m = _TXT.match(text)
    assert m, ('选项文字解析失败', text)
    f = {'piece': m['piece'], 'from': m['fr'], 'to': m['to'], 'castle': (m['cf'], m['ct']) if m['cf'] else None,
         'promo': m['promo'], 'cap': m['cap'], 'check': m['mark'] is not None, 'mate': m['mark'] == '将死',
         'end': 'mate' if m['mark'] == '将死' else None, 'threat': None, 'top': None}
    rest = m['rest']
    if layer == 'L1':
        assert rest == '', ('L1 文字多出内容', text)
        return f
    assert layer == 'L2', layer
    if f['mate']:
        assert rest == '', ('将死之后不该有安全事实', text)
    elif rest in _END_TXT:
        assert _END_TXT[rest] == game, text
        f['end'], f['threat'] = 'stalemate', []
    elif rest == '；走完后对方吃不到我方的子':
        f['threat'] = []
    else:
        t = _THREAT.match(rest)
        assert t, ('L2 安全事实解析失败', text)
        f['threat'] = [tuple(x.split(' ')) for x in t['items'].split('、')]
        assert all(len(x) == 2 for x in f['threat']), text
        f['top'] = t['top']
    for name in [f['cap'], f['top']] + [x[1] for x in (f['threat'] or [])]:
        assert name is None or name in TEXT_VAL[game], ('不认识的棋子名', name, text)
    return f


def check_text_facts(game, fen, fs, layer):
    """反向核对：文字解析出的事实 == 生成文字时用的 boards.facts / boards.safety。"""
    board = b.parse(game, fen)[0]
    name = lambda p: b.piece_name(game, p) if p else None  # noqa: E731
    for mv, f in fs.items():
        fx = b.facts(game, fen, mv, board)
        want = (name(fx['piece']), fx['from'], fx['to'], fx['castle'], name(fx['promo']), name(fx['captured']),
                fx['check'], fx['mate'])
        got = (f['piece'], f['from'], f['to'], f['castle'], f['promo'], f['cap'], f['check'], f['mate'])
        assert got == want, ('文字解析与 facts 不符', game, fen, mv, got, want)
        if layer == 'L2':
            s = b.safety(game, fen, mv)
            assert f['end'] == s.get('end'), ('文字解析的终局与 safety 不符', fen, mv, f['end'], s.get('end'))
            if not s.get('end'):
                th = [(t['square'], name(t['piece'])) for t in s['threatened']]
                assert f['threat'] == th, ('文字解析的被吃子与 safety 不符', fen, mv, f['threat'], th)
                assert f['top'] == (th[0][1] if th else None), ('文字解析的最多吃回与 safety 不符', fen, mv)


def text_score2(game, f):
    """text2 的分：吃子值 − 对方最多吃回的子值（标准子值、兵一律 1）；将死 / 中国象棋困毙记 WIN。"""
    if f['mate'] or (f['end'] == 'stalemate' and game == XQ):
        return WIN
    if f['end'] == 'stalemate':
        return 0
    v = TEXT_VAL[game]
    return (v[f['cap']] if f['cap'] else 0) - (v[f['top']] if f['top'] else 0)


def _text1_pick(game, fs, cands):
    """text1 的挑法（只用 L1 文字事实）：能将死就走 > 吃子值最大 > 将军 > 全部。返回并列集合。"""
    mates = [m for m in cands if fs[m]['mate']]
    if mates:
        return mates
    caps = {m: TEXT_VAL[game][fs[m]['cap']] for m in cands if fs[m]['cap']}
    if caps:
        top = max(caps.values())
        return [m for m in cands if caps.get(m) == top]
    return [m for m in cands if fs[m]['check']] or list(cands)


def text_rule_ties(game, texts, layer, fen=None):
    """{着法: 选项描述} → 同层文字规则的并列集合（排好序）。给 fen 时反向核对解析结果。"""
    fs = {m: parse_text(game, t, layer) for m, t in texts.items()}
    if fen is not None:
        check_text_facts(game, fen, fs, layer)
    moves = sorted(fs)
    if layer == 'L1':
        return sorted(_text1_pick(game, fs, moves))
    s2 = {m: text_score2(game, fs[m]) for m in moves}
    top = max(s2.values())
    return sorted(_text1_pick(game, fs, [m for m in moves if s2[m] == top]))


# ================================================================ 公共：统计
def clip(x):
    return max(-CAP, min(CAP, x))


def cap_losses(scores):
    """= boards.losses(scores, cap=CAP)：每步分数先截到 ±CAP 再算「最高分 − 该步」。"""
    return b.losses(scores, cap=CAP)


def best_set(scores):
    top = max(scores.values())
    return {m for m, v in scores.items() if v == top}


def wilson(k, n, z=1.96):
    if n == 0:
        return (float('nan'), float('nan'))
    p = k / n
    den = 1 + z * z / n
    c = (p + z * z / (2 * n)) / den
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / den
    return (max(0.0, c - h), min(1.0, c + h))


def boot_dist(values, clusters, B=10000, seed=0, stat=None):
    """按簇重抽样的 bootstrap 统计量（未排序，第 i 个是第 i 次重抽）。values 与 clusters 等长；stat 默认求均值。"""
    stat = stat or (lambda xs: sum(xs) / len(xs))
    by = {}
    for v, c in zip(values, clusters):
        by.setdefault(c, []).append(v)
    keys = sorted(by)
    rng = random.Random(seed)
    out = []
    for _ in range(B):
        xs = []
        for _k in range(len(keys)):
            xs.extend(by[keys[rng.randrange(len(keys))]])
        out.append(stat(xs))
    return out


def pct_ci(dist):
    s = sorted(dist)
    B = len(s)
    return s[int(0.025 * B)], s[int(0.975 * B) - 1]


def boot(values, clusters, B=10000, seed=0, stat=None):
    """按簇重抽样的 bootstrap 百分位 95% 区间。"""
    return pct_ci(boot_dist(values, clusters, B, seed, stat))


def boot_p(values, clusters, B=10000, seed=0):
    """配对差均值的双侧 bootstrap p（与百分位区间对偶：2 × min(重抽均值 ≤ 0 的比例, ≥ 0 的比例)，下限 1/B）。"""
    d = boot_dist(values, clusters, B, seed)
    lo = sum(1 for x in d if x <= 0) / B
    hi = sum(1 for x in d if x >= 0) / B
    return max(1 / B, min(1.0, 2 * min(lo, hi)))


def flip_p(values, clusters, B=20000, seed=0):
    """按簇整体翻符号的随机化检验（零假设：配对差按簇对称分布在 0 两侧）：双侧 p = (1 + #|T*| ≥ |T|) / (1 + B)。"""
    by = {}
    for v, c in zip(values, clusters):
        by[c] = by.get(c, 0.0) + v
    sums = [by[k] for k in sorted(by)]
    n = len(values)
    t = abs(sum(sums)) / n
    rng = random.Random(seed)
    hit = 0
    for _ in range(B):
        if abs(sum(s if rng.random() < 0.5 else -s for s in sums)) / n >= t - 1e-12:
            hit += 1
    return (1 + hit) / (1 + B)


def holm(ps):
    """Holm 逐步校正后的 p（单调化）。"""
    m = len(ps)
    order = sorted(range(m), key=lambda i: ps[i])
    adj, run = [0.0] * m, 0.0
    for r, i in enumerate(order):
        run = max(run, min(1.0, (m - r) * ps[i]))
        adj[i] = run
    return adj


def fmt_p(p, B=10000):
    return ('<%.4f' % (1 / B)) if p <= 1 / B else ('%.4f' % p if p < 0.01 else '%.3f' % p)


def fmt_rate_cl(xs, clusters, seed=11):
    """0/1（或期望比例）序列的率 + 按簇 bootstrap 区间（v2：比率类区间按自对弈对局 / 对局聚类）。"""
    k = sum(xs)
    ks = ('%d' % round(k)) if abs(k - round(k)) < 1e-9 else ('%.1f' % k)
    if abs(k) < 1e-9 or abs(k - len(xs)) < 1e-9:      # 0 或全中时簇 bootstrap 退化成 [0, 0] / [100, 100]，改用 Wilson（标 †）
        lo, hi = wilson(round(k), len(xs))
        return '%s/%d %.0f%% [%.0f, %.0f]†' % (ks, len(xs), 100 * k / len(xs), 100 * lo, 100 * hi)
    lo, hi = boot([100 * x for x in xs], clusters, seed=seed)
    return '%s/%d %.0f%% [%.0f, %.0f]' % (ks, len(xs), 100 * k / len(xs), lo, hi)


def mean(xs):
    return sum(xs) / len(xs) if xs else float('nan')


def fmt_ci(ci, f='%.0f'):
    return '[' + (f % ci[0]) + ', ' + (f % ci[1]) + ']'


def fmt_rate(k, n):
    lo, hi = wilson(k, n)
    return '%d/%d %.0f%% [%.0f, %.0f]' % (k, n, 100 * k / n if n else float('nan'), 100 * lo, 100 * hi)


# ================================================================ C1 静态阶梯
def static_positions(data):
    ps = []
    for g in (XQ, CH):
        for s in ('middle', 'gain'):
            sel = b.select(data, g, s)
            assert len(sel) == 30, (g, s, len(sel))
            ps += sel
    return ps


def jitter_ids(ps):
    out = []
    for g in (XQ, CH):
        for s in ('middle', 'gain'):
            sel = [p for p in ps if p['game'] == g and p['set'] == s]
            out += [sel[i]['id'] for i in JITTER_IDX]
    return out


def static_jobs(ps):
    """[(日志键, 局面, 层, 顺序 rep)]。主跑每局面每层 1 次（rep 0）；抖动组 L0 / L2 另发同一请求体 2 次（same1/2）
    和换 rep 2 次（shuf1/2，rep 1/2：键映射与顺序都换，描述不变）。"""
    jobs = []
    for p in ps:
        for L in ARMS:
            jobs.append(('%s|%s|r0' % (p['id'], L), p, L, 0))
    jit = set(jitter_ids(ps))
    for p in ps:
        if p['id'] not in jit:
            continue
        for L in ('L0', 'L2'):
            for j in (1, 2):
                jobs.append(('%s|%s|same%d' % (p['id'], L, j), p, L, 0))
                jobs.append(('%s|%s|shuf%d' % (p['id'], L, j), p, L, j))
    return jobs


def load_json(path):
    if os.path.exists(path):
        with open(path, encoding='utf-8') as f:
            return json.load(f)
    return {}


def save_json(path, obj):
    tmp = path + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(obj, f, ensure_ascii=False)
    os.replace(tmp, path)


def gain_check(p, layer, st, q, k2m):
    """gain 集：L3 里写的两层物质净得与局面集存的 gains 逐项一致。"""
    if p['set'] != 'gain' or layer != 'L3':
        return
    crit = q['move']['criteria']
    for k, m in k2m.items():
        want = '；两层物质净得 %s' % fmt_gain(p['gains'][m])
        assert crit[k].endswith(want), ('L3 数值与局面集 gains 不符', p['id'], m, crit[k], want)


def run_static(dry=False):
    data = b.load_positions()
    ps = static_positions(data)
    jobs = static_jobs(ps)
    log = load_json(LOG)
    todo = [j for j in jobs if j[0] not in log or '_error' in log[j[0]]['resp']]
    print('C1 共 %d 个请求，日志已有 %d 个成功，需发 %d 个' % (len(jobs), len(jobs) - len(todo), len(todo)))
    cache = {}
    built = []
    t0 = time.time()
    for key, p, L, rep in todo:
        ck = (p['id'], L, rep)
        if ck not in cache:
            cache[ck] = build_request(p['game'], p['fen'], L, p['id'], rep)
            gain_check(p, split_arm(L)[0], *cache[ck])
        st, q, k2m = cache[ck]
        built.append((key, p, L, rep, st, q, k2m))
    print('造请求与断言用时 %.1f 秒' % (time.time() - t0))
    if dry:
        chars = [len(json.dumps(x[4], ensure_ascii=False)) + len(json.dumps(x[5], ensure_ascii=False)) for x in built]
        print('请求体字符数：中位 %d，最大 %d；合计约 %d 字符' % (statistics.median(chars), max(chars), sum(chars)))
        for L in LAYERS:
            ex = next(x for x in built if x[2] == L)
            k = next(iter(ex[5]['move']['criteria']))
            print(L, ex[1]['id'], '例：', ex[5]['move']['criteria'][k])
        return
    import jevkit as jev
    CH_ = 48
    for i in range(0, len(built), CH_):
        chunk = built[i:i + CH_]
        res = jev.fan([(x[0], x[4], x[5]) for x in chunk], workers=6)
        bad = None
        for key, p, L, rep, st, q, k2m in chunk:
            d = res[key]
            log[key] = {'pos': p['id'], 'layer': L, 'rep': rep, 'state': st, 'questions': q, 'k2m': k2m, 'resp': d}
            if '_error' not in d and d.get('model') != MODEL:
                bad = (key, d.get('model'))
        save_json(LOG, log)
        errs = sum('_error' in res[x[0]] for x in chunk)
        print('  已发 %d/%d，本批失败 %d | %s' % (min(i + CH_, len(built)), len(built), errs, jev.spend()))
        if bad:
            raise SystemExit('回包模型串不对，立即停下：%s → %r' % bad)
        for key, p, L, rep, st, q, k2m in chunk:
            if '_error' not in res[key]:
                parse_resp(res[key], q['move']['criteria'])
    print(jev.spend())


def tie_set(game, fen, kind):
    """复刻 boards.baseline 的并列集合：该基线会在这些着法里均匀随机挑。"""
    moves = b.legal(game, fen)
    if kind == 'random':
        return moves
    if kind == 'greedy1':
        board = b.parse(game, fen)[0]
        fxs = {m: b.facts(game, fen, m, board) for m in moves}
        mates = [m for m in moves if fxs[m]['mate']]
        if mates:
            return mates
        caps = {m: b.value(game, fxs[m]['captured'], fxs[m]['cap_sq']) for m in moves if fxs[m]['captured']}
        if caps:
            top = max(caps.values())
            return [m for m in moves if caps.get(m) == top]
        checks = [m for m in moves if fxs[m]['check']]
        return checks or moves
    g = b.two_ply(game, fen)
    top = max(g.values())
    return [m for m in moves if g[m] == top]


def static_records():
    """把日志与局面集拼成逐请求记录；同时核对日志里的请求与脚本当前会造的请求逐字相同。"""
    data = b.load_positions()
    ps = static_positions(data)
    byid = {p['id']: p for p in ps}
    log = load_json(LOG)
    if not log:
        raise SystemExit('还没有 C1 日志：先跑 static')
    jobs = static_jobs(ps)
    miss = [j[0] for j in jobs if j[0] not in log or '_error' in log[j[0]]['resp']]
    if miss:
        raise SystemExit('C1 日志缺 %d 条或有失败条目（例 %s），先补跑 static' % (len(miss), miss[:3]))
    recs, cache = [], {}
    for key, p, L, rep in jobs:
        e = log[key]
        ck = (p['id'], L, rep)
        if ck not in cache:
            cache[ck] = build_request(p['game'], p['fen'], L, p['id'], rep, check=False)
        st, q, k2m = cache[ck]
        assert e['state'] == st and e['questions'] == q and e['k2m'] == k2m, ('日志里的请求与脚本当前的请求不一致', key)
        crit = q['move']['criteria']
        ch, prob, conf = parse_resp(e['resp'], crit)
        u = e['resp'].get('usage', {})
        recs.append({'key': key, 'kind': key.split('|')[2], 'pos': p['id'], 'game': p['game'], 'set': p['set'],
                     'layer': L, 'move': k2m[ch], 'pm': {k2m[k]: v for k, v in prob.items()}, 'conf': conf,
                     'n': len(crit), 'cost': u.get('cost', 0.0), 'tok': u.get('input_tokens', 0),
                     'elapsed': e['resp'].get('_elapsed')})
    return byid, recs


def pos_metrics(p, move=None, dist=None):
    """一个局面上某个选择（单着，或着法上的分布）的各项指标；dist 用于基线并列集合的期望。"""
    sc = p['move_scores']
    L = cap_losses(sc)
    best = best_set(sc)
    dist = dist or {move: 1.0}
    out = {'loss': sum(w * L[m] for m, w in dist.items()),
           'blunder': sum(w for m, w in dist.items() if L[m] >= BLUNDER),
           'agree': sum(w for m, w in dist.items() if m in best)}
    if p['set'] == 'gain':
        out['answer'] = sum(w for m, w in dist.items() if m == p['answer'])
        out['bait'] = sum(w for m, w in dist.items() if m in p['baits'])
    return out


def static_texts(log, pid, layer):
    """C1 日志里 Jev 实际看到的 {着法: 选项描述}（FEN 臂 r0）；@pieces 臂的选项文字与键表必须逐字相同。"""
    e = log['%s|%s|r0' % (pid, layer)]
    e2 = log['%s|%s|r0' % (pid, layer + PCS)]
    assert e2['questions'] == e['questions'] and e2['k2m'] == e['k2m'], ('两种 state 的选项文字不同', pid, layer)
    return {e['k2m'][k]: t for k, t in e['questions']['move']['criteria'].items()}


def report_static():
    byid, recs = static_records()
    main = [r for r in recs if r['kind'] == 'r0']
    ps = list(byid.values())
    clus = {p['id']: '%s-%s' % (p['game'], p['source']['selfplay']) for p in ps}
    print('# C1 静态阶梯：%d 次请求（主跑 %d），模型 %s' % (len(recs), len(main), MODEL))
    print('日志合计：输入 %d tok | 花费 $%.4f | 耗时中位 %.2f 秒' % (
        sum(r['tok'] for r in recs), sum(r['cost'] for r in recs), statistics.median(r['elapsed'] for r in recs)))

    # 例子：每层同一个局面同一步棋的完整选项描述
    log = load_json(LOG)
    ex_pos = 'xq-gain-01'
    print('\n## 各层选项描述例子（%s，%s）' % (ex_pos, byid[ex_pos]['fen']))
    for L in LAYERS:
        e = log['%s|%s|r0' % (ex_pos, L)]
        crit = e['questions']['move']['criteria']
        k = next(k for k, m in e['k2m'].items() if m == byid[ex_pos]['baits'][0])
        k2 = next(k for k, m in e['k2m'].items() if m == byid[ex_pos]['answer'])
        print('- %s 诱饵 %s：%s' % (L, e['k2m'][k], crit[k]))
        print('  %s 得子 %s：%s' % (L, e['k2m'][k2], crit[k2]))
    print('- L3 的 state.note：%s' % NOTE[XQ])
    e = log['%s|%s|r0' % (ex_pos, 'L0' + PCS)]
    print('- @pieces 臂的 state（同一局面）：%s' % json.dumps(e['state'], ensure_ascii=False))
    e = log['%s|%s|r0' % (ex_pos, 'L0')]
    print('- 不带后缀（FEN）臂的 state：%s' % json.dumps(e['state'], ensure_ascii=False))

    # 逐局面指标：基线（并列集合期望 + 固定种子单抽）、只看文字的规则（v2）与 Jev 各层
    rows = {}   # (pos, arm) -> metrics
    seeded = {}
    ties = {}
    mism = {g: {'cand': 0, 'cand_diff': 0, 'pos_diff': 0, 'tie1_diff': 0, 'tie2_diff': 0} for g in (XQ, CH)}
    for p in ps:
        for kind in FREE:
            ts = tie_set(p['game'], p['fen'], kind)
            pick = b.baseline(p['game'], p['fen'], kind, random.Random(b.seed_of('C1', p['id'], kind)))
            assert pick in ts, ('基线单抽不在并列集合里', p['id'], kind)
            rows[(p['id'], kind)] = pos_metrics(p, dist={m: 1 / len(ts) for m in ts})
            seeded[(p['id'], kind)] = pos_metrics(p, move=pick)
            ties[(p['id'], kind)] = ts
        # 同层文字规则：从日志里 Jev 实际看到的选项文字解析（FEN 臂与 @pieces 臂文字相同，断言），并反向核对
        for L, kind in (('L1', 'text1'), ('L2', 'text2')):
            texts = static_texts(log, p['id'], L)
            ts = text_rule_ties(p['game'], texts, L, fen=p['fen'])
            pick = random.Random(b.seed_of('C1', p['id'], kind)).choice(ts)
            rows[(p['id'], kind)] = pos_metrics(p, dist={m: 1 / len(ts) for m in ts})
            seeded[(p['id'], kind)] = pos_metrics(p, move=pick)
            ties[(p['id'], kind)] = ts
        # 文字能推出的「吃子 − 最多吃回」与 greedy2 实际用的两层物质值不一致的候选（审查点 1 的复算）
        fs2 = {m: parse_text(p['game'], t, 'L2') for m, t in static_texts(log, p['id'], 'L2').items()}
        g2 = b.two_ply(p['game'], p['fen'])
        nd = sum(1 for m in fs2 if text_score2(p['game'], fs2[m]) != g2[m])
        mm = mism[p['game']]
        mm['cand'] += len(fs2)
        mm['cand_diff'] += nd
        mm['pos_diff'] += nd > 0
        mm['tie1_diff'] += set(ties[(p['id'], 'text1')]) != set(ties[(p['id'], 'greedy1')])
        mm['tie2_diff'] += set(ties[(p['id'], 'text2')]) != set(ties[(p['id'], 'greedy2')])
    print('\n## 只看选项文字的规则 vs 棋库基线（v2）')
    print('| 棋种 | 候选着法 | 文字推出的「吃子−最多吃回」≠ greedy2 的值（候选 / 局面） | text1 与 greedy1 并列集合不同的局面 | text2 与 greedy2 并列集合不同的局面 |')
    print('|---|---|---|---|---|')
    for g in (XQ, CH):
        mm = mism[g]
        print('| %s | %d | %d / %d | %d/60 | %d/60 |' % (g, mm['cand'], mm['cand_diff'], mm['pos_diff'],
                                                       mm['tie1_diff'], mm['tie2_diff']))
    print('（解析结果与 boards.facts / boards.safety 逐项反向核对通过；FEN 臂与 @pieces 臂的选项文字逐字相同）')

    extra = {}
    for r in main:
        p = byid[r['pos']]
        m = pos_metrics(p, move=r['move'])
        rows[(r['pos'], r['layer'])] = m
        L = cap_losses(p['move_scores'])
        tot = sum(r['pm'].values())
        pm = {k: v / tot for k, v in r['pm'].items()}
        best = best_set(p['move_scores'])
        # 引擎最佳集合在 Jev 概率排序里的归一化位置（并列概率取平均名次），0 = 排第一
        def nrank(targets):
            ranks = []
            for t in targets:
                hi = sum(1 for k in pm if pm[k] > pm[t])
                eq = sum(1 for k in pm if pm[k] == pm[t])
                ranks.append((hi + (eq - 1) / 2) / (len(pm) - 1))
            return min(ranks)
        lay = split_arm(r['layer'])[0]
        same = SAME_TEXT[lay]
        ex = {'eloss': sum(pm[k] * L[k] for k in pm), 'nrank': nrank(best),
              'pbest_x': sum(pm[k] for k in best) / len(best) * len(pm), 'conf': r['conf'],
              'in_g2': r['move'] in ties[(r['pos'], 'greedy2')],
              'in_same': r['move'] in ties[(r['pos'], same)]}
        # greedy2 并列集合（>1 步）里 Jev 挑得比均匀挑好多少：所选着损失 − 集合平均损失（负 = 比均匀挑好）
        t2 = ties[(r['pos'], 'greedy2')]
        ex['tie_gain'] = (L[r['move']] - mean([L[m] for m in t2])) if (r['move'] in t2 and len(t2) > 1) else None
        # Jev 所选着在引擎排名里的归一化位置（0 = 最好）
        sc = p['move_scores']
        hi = sum(1 for v in sc.values() if v > sc[r['move']])
        eq = sum(1 for v in sc.values() if v == sc[r['move']])
        ex['erank'] = (hi + (eq - 1) / 2) / (len(sc) - 1)
        if p['set'] == 'gain':
            ex['nrank_ans'] = nrank([p['answer']])
            ex['pans_x'] = pm[p['answer']] * len(pm)
        extra[(r['pos'], r['layer'])] = ex

    arms = list(FREE) + list(TEXT_RULES) + list(ARMS)
    expected = set(FREE) | set(TEXT_RULES)
    for g in (XQ, CH):
        for sets in (('middle',), ('gain',), ('middle', 'gain')):
            sel = [p for p in ps if p['game'] == g and p['set'] in sets]
            ids = [p['id'] for p in sel]
            cl = [clus[i] for i in ids]
            title = '%s / %s（%d 局面，%d 个自对弈簇）' % ('中国象棋' if g == XQ else '国际象棋', '+'.join(sets), len(ids), len(set(cl)))
            print('\n## %s' % title)
            print('（率的区间一律按自对弈对局聚类 bootstrap；基线与文字规则是并列集合期望，Jev 是单次选择）')
            hdr = '| 臂 | 平均损失（封顶）[95%] | 中位损失 | 失误率 ≥200 | 与最佳着一致 |'
            if sets == ('gain',):
                hdr += ' 选得子着 | 选诱饵 |'
            print(hdr)
            print('|' + '---|' * (hdr.count('|') - 1))
            for a in arms:
                ms = [rows[(i, a)] for i in ids]
                loss = [m['loss'] for m in ms]
                line = '| %s | %.0f %s | %.0f | ' % (a, mean(loss), fmt_ci(boot(loss, cl, seed=1)), statistics.median(loss))
                fields = ('blunder', 'agree') + (('answer', 'bait') if sets == ('gain',) else ())
                for f in fields:
                    v = [m[f] for m in ms]
                    if a in expected:
                        line += '%.0f%% %s | ' % (100 * mean(v), fmt_ci(boot([100 * x for x in v], cl, seed=2)))
                    else:
                        line += fmt_rate_cl(v, cl) + ' | '
                print(line)
            print('\n基线 / 文字规则按局面固定种子单抽一次（核对用）：' + '；'.join(
                '%s 平均损失 %.0f、失误 %d、一致 %d' % (a, mean([seeded[(i, a)]['loss'] for i in ids]),
                                              round(sum(seeded[(i, a)]['blunder'] for i in ids)),
                                              round(sum(seeded[(i, a)]['agree'] for i in ids))) for a in list(FREE) + list(TEXT_RULES)))
            print('\nJev 各层补充指标（均值）：')
            print('| 层 | Σp·损失 | 最佳着在 Jev 排序的归一化位置（0=第一） | p(最佳)×候选数 | 所选着的引擎归一化名次（0=最好） | 置信度 | 所选在 greedy2 并列集合内 | 所选在同层文字规则并列集合内 |' +
                  (' p(得子着)×候选数 | 得子着归一化位置 |' if sets == ('gain',) else ''))
            print('|---|---|---|---|---|---|---|---|' + ('---|---|' if sets == ('gain',) else ''))
            for L in ARMS:
                es = [extra[(i, L)] for i in ids]
                line = '| %s | %.0f | %.2f | %.2f | %.2f | %.2f | %s | %s |' % (
                    L, mean([e['eloss'] for e in es]), mean([e['nrank'] for e in es]), mean([e['pbest_x'] for e in es]),
                    mean([e['erank'] for e in es]), mean([e['conf'] for e in es]),
                    fmt_rate_cl([float(e['in_g2']) for e in es], cl), fmt_rate_cl([float(e['in_same']) for e in es], cl))
                if sets == ('gain',):
                    line += ' %.2f | %.2f |' % (mean([e['pans_x'] for e in es]), mean([e['nrank_ans'] for e in es]))
                print(line)
            for kind in ('greedy2', 'text1', 'text2'):
                g2 = [len(ties[(i, kind)]) / len(byid[i]['move_scores']) for i in ids]
                print('（%s 并列集合平均占全部合法着法的 %.0f%%，即均匀挑落进集合的概率）' % (kind, 100 * mean(g2)))
            print('\n落在 greedy2 并列集合（>1 步）里时，Jev 所选着损失 − 集合内均匀挑的期望损失（负 = Jev 在并列着里挑得更好）：')
            print('| 层 | 局面数 | 差值均值 [95%] |')
            print('|---|---|---|')
            for L in ARMS:
                tg = [(extra[(i, L)]['tie_gain'], clus[i]) for i in ids if extra[(i, L)]['tie_gain'] is not None]
                if len(tg) >= 3:
                    v = [x for x, _ in tg]
                    print('| %s | %d | %+.0f %s |' % (L, len(v), mean(v), fmt_ci(boot(v, [c for _, c in tg], seed=4))))
                else:
                    print('| %s | %d | — |' % (L, len(tg)))
            print('\n配对差（前者 − 后者，按局面配对、自对弈簇 bootstrap；负 = 前者更好）。'
                  '「主比较」= Jev 对同层文字规则（L0 对 random，L3 对 greedy2，都是严格同信息）；'
                  '「棋库基线」= L1 对 greedy1、L2 对 greedy2（对应复杂度，但用了文字里没有的信息）：')
            print('| 类别 | 对比 | 平均损失差 [95%] | 失误率差（百分点）[95%] | 一致率差（百分点）[95%] |')
            print('|---|---|---|---|---|')
            pairs = [('主比较', a, SAME_TEXT[split_arm(a)[0]]) for a in ARMS]
            pairs += [('棋库基线', a, SAME_INFO[split_arm(a)[0]]) for a in ARMS if split_arm(a)[0] in ('L1', 'L2')]
            pairs += [('规则间', 'text1', 'greedy1'), ('规则间', 'text2', 'greedy2')]
            for suf in ('', PCS):
                pairs += [('层间', 'L1' + suf, 'L0' + suf), ('层间', 'L2' + suf, 'L1' + suf), ('层间', 'L3' + suf, 'L2' + suf)]
            pairs += [('state', L + PCS, L) for L in LAYERS]       # 同层 pieces − FEN
            for cat, a, c in pairs:
                line = '| %s | %s − %s | ' % (cat, a, c)
                for f, sc_ in (('loss', 1), ('blunder', 100), ('agree', 100)):
                    d = [sc_ * (rows[(i, a)][f] - rows[(i, c)][f]) for i in ids]
                    line += '%+.0f %s | ' % (mean(d), fmt_ci(boot(d, cl, seed=3)))
                print(line)

    # 12 个配对比较（两棋种 × 两种 state × L1–L3，合并 60 局面）的 Holm 校正
    print('\n## 12 个配对比较的多重比较校正（合并 middle + gain，每棋种 60 局面；平均损失差）')
    print('p 值两种：簇 bootstrap 双侧 p（与上面的百分位区间对偶，B = 10000）、按簇整体翻符号的随机化检验（B = 20000）；'
          '各自在同一族 12 个比较里做 Holm。')
    for fam, ref in (('主比较（同层文字规则；L3 对 greedy2）', SAME_TEXT), ('棋库基线（L1 对 greedy1，L2 / L3 对 greedy2）', SAME_INFO)):
        print('\n### %s' % fam)
        print('| 棋种 | 臂 | 对照 | 平均损失差 [95%] | bootstrap p | Holm 后 | 翻符号 p | Holm 后 | 校正后仍显著（两种都 < 0.05） |')
        print('|---|---|---|---|---|---|---|---|---|')
        comps = []
        for g in (XQ, CH):
            ids = [p['id'] for p in ps if p['game'] == g]
            cl = [clus[i] for i in ids]
            for suf in ('', PCS):
                for L in ('L1', 'L2', 'L3'):
                    a, c = L + suf, ref[L]
                    d = [rows[(i, a)]['loss'] - rows[(i, c)]['loss'] for i in ids]
                    comps.append((g, a, c, mean(d), boot(d, cl, seed=3), boot_p(d, cl, seed=3), flip_p(d, cl, seed=13)))
        hb = holm([x[5] for x in comps])
        hf = holm([x[6] for x in comps])
        for (g, a, c, md, ci, pb, pf), ab, af in zip(comps, hb, hf):
            print('| %s | %s | %s | %+.0f %s | %s | %s | %s | %s | %s |' % (
                g, a, c, md, fmt_ci(ci), fmt_p(pb), fmt_p(ab), fmt_p(pf, 20000), fmt_p(af, 20000),
                '是' if max(ab, af) < 0.05 else '否'))

    # 两棋种差距之差（未匹配局面，两棋种独立重抽）
    print('\n## 两棋种「Jev − 同层基线」差距之差（中国象棋差距 − 国际象棋差距；两棋种各自按自对弈簇独立重抽，B = 10000）')
    print('| 臂 | 对照 | 中国象棋差距 | 国际象棋差距 | 差距之差 [95%] |')
    print('|---|---|---|---|---|')
    for suf in ('', PCS):
        for L in ('L1', 'L2', 'L3'):
            for ref in ((SAME_TEXT, SAME_INFO) if L != 'L3' else (SAME_TEXT,)):
                a, c = L + suf, ref[L]
                dists, ms = [], []
                for g, sd in ((XQ, 21), (CH, 22)):
                    ids = [p['id'] for p in ps if p['game'] == g]
                    d = [rows[(i, a)]['loss'] - rows[(i, c)]['loss'] for i in ids]
                    ms.append(mean(d))
                    dists.append(boot_dist(d, [clus[i] for i in ids], seed=sd))
                dd = [x - y for x, y in zip(*dists)]
                print('| %s | %s | %+.0f | %+.0f | %+.0f %s |' % (a, c, ms[0], ms[1], ms[0] - ms[1], fmt_ci(pct_ci(dd))))

    # 抖动
    print('\n## 抖动组（%d 个局面 × L0/L2；same = 同一请求体重发，shuf = 换 rep（键映射与顺序都换））' % len(jitter_ids(ps)))
    print('| 层 | 方式 | 三次选同一着的局面 | 三次所选着损失极差中位 / 最大 | 选中项概率极差中位 | 任一选项概率最大差（中位 / 最大） | 同一局面三次损失的方差（局面平均）| 其平方根 |')
    print('|---|---|---|---|---|---|---|---|')
    byk = {r['key']: r for r in recs}
    wvar = {}
    for L in ('L0', 'L2'):
        for how in ('same', 'shuf'):
            same, lr, pr, mx, vs = 0, [], [], [], []
            ids = jitter_ids(ps)
            for i in ids:
                rs = [byk['%s|%s|r0' % (i, L)]] + [byk['%s|%s|%s%d' % (i, L, how, j)] for j in (1, 2)]
                mvs = [r['move'] for r in rs]
                same += len(set(mvs)) == 1
                Ls = cap_losses(byid[i]['move_scores'])
                lr.append(max(Ls[m] for m in mvs) - min(Ls[m] for m in mvs))
                vs.append(statistics.variance([Ls[m] for m in mvs]))
                pr.append(max(r['pm'][rs[0]['move']] for r in rs) - min(r['pm'][rs[0]['move']] for r in rs))
                mx.append(max(max(r['pm'][m] for r in rs) - min(r['pm'][m] for r in rs) for m in rs[0]['pm']))
            wvar[(L, how)] = mean(vs)
            print('| %s | %s | %d/%d | %.0f / %.0f | %.2f | %.2f / %.2f | %.0f | %.0f |' % (
                L, how, same, len(ids), statistics.median(lr), max(lr), statistics.median(pr), statistics.median(mx),
                max(mx), mean(vs), math.sqrt(mean(vs))))

    # 抖动组在同一批局面上：只用第一次请求 vs 三种键序各算一次 / 三次平均，配对差均值挪多少
    print('\n抖动组局面上，按哪一次请求算配对差（每棋种 10 个局面；r0 = 主跑那次，shuf1/2 = 换键序重发）：')
    print('| 棋种 | 对比 | 用 r0 | 用 shuf1 | 用 shuf2 | 三次平均 | 三次之间极差 |')
    print('|---|---|---|---|---|---|---|')
    for g in (XQ, CH):
        ids = [i for i in jitter_ids(ps) if byid[i]['game'] == g]
        for L, c in (('L0', 'random'), ('L2', 'text2'), ('L2', 'greedy2')):
            vals = []
            for tag in ('r0', 'shuf1', 'shuf2'):
                vals.append(mean([cap_losses(byid[i]['move_scores'])[byk['%s|%s|%s' % (i, L, tag)]['move']]
                                  - rows[(i, c)]['loss'] for i in ids]))
            print('| %s | %s − %s | %+.0f | %+.0f | %+.0f | %+.0f | %.0f |' % (
                g, L, c, vals[0], vals[1], vals[2], mean(vals), max(vals) - min(vals)))

    # 单次请求波动对 12 个主比较的影响：按局面重抽的区间已把它算在局面间差异里；这里再叠加一份做保守放宽
    print('\n单次请求波动对主比较的影响（σ²_w = 抖动组 shuf 方式「同一局面三次损失的方差」的局面平均；'
          '局面间差异已含这部分，再叠加一份是保守放宽：SE\' = √(SE_boot² + min(σ²_w, Var(d)) / n)）：')
    print('| 棋种 | 对比 | 平均损失差 | 局面间方差 Var(d) | σ²_w 占 Var(d)（按 L2 / 按 L0） | SE_boot | 放宽后区间（按 L2 的 σ²_w） | 放宽后区间（按 L0 的 σ²_w，上界） |')
    print('|---|---|---|---|---|---|---|---|')
    for g in (XQ, CH):
        ids = [p['id'] for p in ps if p['game'] == g]
        cl = [clus[i] for i in ids]
        for suf in ('', PCS):
            for L in ('L1', 'L2', 'L3'):
                a, c = L + suf, SAME_TEXT[L]
                d = [rows[(i, a)]['loss'] - rows[(i, c)]['loss'] for i in ids]
                se = statistics.pstdev(boot_dist(d, cl, seed=3))
                vd = statistics.variance(d)
                n = len(d)
                out = []
                for key in (('L2', 'shuf'), ('L0', 'shuf')):
                    s2 = math.sqrt(se * se + min(wvar[key], vd) / n)     # 单次请求的方差不可能超过局面间总方差，封顶 Var(d)
                    out.append('[%.0f, %.0f]' % (mean(d) - 1.96 * s2, mean(d) + 1.96 * s2))
                print('| %s | %s − %s | %+.0f | %.0f | %.0f%% / %.0f%% | %.0f | %s | %s |' % (
                    g, a, c, mean(d), vd, 100 * wvar[('L2', 'shuf')] / vd, 100 * wvar[('L0', 'shuf')] / vd, se, out[0], out[1]))


# ================================================================ C2 整局
def opening(i):
    """第 i 局的开局：按局序号固定种子，随机 2–4 个半回合（双方都随机）。各格共用同一批开局。"""
    rng = random.Random(b.seed_of('C2-open', i))
    n = 2 + rng.randrange(3)
    fen, mv = b.START[XQ], []
    for _ in range(n):
        m = rng.choice(b.legal(XQ, fen))
        mv.append(m)
        fen = b.play(XQ, fen, m)
    return mv


def weak_params(opp):
    # 'weak-k5d2' -> (5, 2)
    s = opp.split('-')[1]
    k, d = s[1:].split('d')
    return int(k), int(d)


_ENG = None


def _engine():
    global _ENG
    if _ENG is None:
        _ENG = b.Engine(XQ)
    return _ENG


def opp_move(opp, i, ply, fen):
    rng = random.Random(b.seed_of('C2-opp', opp, i, ply, fen))
    if opp == 'random':
        return rng.choice(b.legal(XQ, fen))
    k, d = weak_params(opp)
    top = _engine().top(fen, k, d)
    return rng.choice([m for m, _ in top])


def game_id(player, opp, i):
    return '%s|%s|%02d' % (player, opp, i)


def append_lines(path, recs):
    import fcntl      # 只在这里用；放到顶上的话 Windows 上连 import 本文件都不行（网页版 play_xiangqi.py 要 import 它）
    with open(path, 'a', encoding='utf-8') as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        for r in recs:
            f.write(json.dumps(r, ensure_ascii=False) + '\n')
        f.flush()
        fcntl.flock(f, fcntl.LOCK_UN)


def read_lines(path):
    out = []
    if os.path.exists(path):
        with open(path, encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if line:
                    out.append(json.loads(line))
    return out


def _fake_resp(q, k2m, move):
    """离线自检用的假回包：选中 move（概率 0.9），其余均分。"""
    crit = q['move']['criteria']
    m2k = {m: k for k, m in k2m.items()}
    rest = round(0.1 / max(1, len(crit) - 1), 4)
    probs = {k: (0.9 if k == m2k[move] else rest) for k in crit}
    return {'model': MODEL, 'answers': {'move': {'type': 'choice', 'choice': m2k[move], 'probabilities': probs,
                                                 'confidence': 0.9}},
            'usage': {'input_tokens': 0, 'output_tokens': 0, 'cost': 0.0}, '_elapsed': 0.0, '_fake': True}


def play_game(args):
    """跑一局（在子进程里）。每步立刻追加到日志；prior 是这局日志里已有的步（断点续跑时复用已花钱的 Jev 回包）。"""
    player, opp, i, path, prior = args
    gid = game_id(player, opp, i)
    prior = {r['ply']: r for r in prior}
    op = opening(i)
    fen = b.START[XQ]
    ply = 0
    while True:
        st = b.status(XQ, fen)
        if st in ('mate', 'stalemate') or ply >= MAX_PLY:
            break
        red = fen.split()[1] == 'w'
        rec = {'type': 'step', 'game': gid, 'ply': ply, 'fen': fen}
        if ply < len(op):
            rec.update(who='open', move=op[ply])
        elif not red:
            rec.update(who='opp', move=opp_move(opp, i, ply, fen))
        elif player in FREE:
            rng = random.Random(b.seed_of('C2-player', player, opp, i, ply, fen))
            rec.update(who='player', move=b.baseline(XQ, fen, player, rng))
        elif len(b.legal(XQ, fen)) == 1:                 # 只有一步可走：直接走，不问 Jev（记 forced）
            rec.update(who='player', move=b.legal(XQ, fen)[0], layer=player, forced=True)
        else:
            st_, q, k2m = build_request(XQ, fen, player, gid + '|%d' % ply, check=False)
            old = prior.get(ply)
            if old and old.get('fen') == fen and old.get('resp') and '_error' not in old['resp']:
                assert old['k2m'] == k2m and old['questions'] == q, ('续跑时请求与日志不一致', gid, ply)
                d = old['resp']
            elif os.environ.get('XQA_FAKE_JEV'):          # 离线自检：假回包（选 greedy2 的着），不发请求
                assert os.environ.get('XQA_GLOG'), '假回包只许写进另指定的日志'
                d = _fake_resp(q, k2m, b.baseline(XQ, fen, 'greedy2', random.Random(ply)))
            else:
                import jevkit as jev
                d = jev.call(st_, q)
                if '_error' in d:
                    raise RuntimeError('Jev 请求失败：%s %s' % (gid, d['_error']))
            ch, prob, conf = parse_resp(d, q['move']['criteria'])
            rec.update(who='player', move=k2m[ch], layer=player, k2m=k2m, questions=q, resp=d)
        old = prior.get(ply)
        if old is not None:
            assert old['fen'] == fen and old['move'] == rec['move'], ('续跑时对局走向与日志不一致', gid, ply, old['move'], rec['move'])
        else:
            append_lines(path, [rec])
        fen = b.play(XQ, fen, rec['move'])
        ply += 1
    st = b.status(XQ, fen)
    red = fen.split()[1] == 'w'
    if st in ('mate', 'stalemate'):
        result = 'loss' if red else 'win'
        end = st
    else:
        result, end = 'trunc', 'trunc'
    summ = {'type': 'game', 'game': gid, 'player': player, 'opp': opp, 'i': i, 'result': result, 'end': end,
            'plies': ply, 'final_fen': fen, 'opening': op}
    append_lines(path, [summ])
    return summ


def run_games(specs, path, workers):
    """specs: [(player, opp, i)]。已有 game 汇总行的跳过；未完的从日志里接着下。"""
    lines = read_lines(path)
    done = {r['game'] for r in lines if r['type'] == 'game'}
    steps = {}
    for r in lines:
        if r['type'] == 'step':
            steps.setdefault(r['game'], []).append(r)
    todo = [(p, o, i, path, steps.get(game_id(p, o, i), [])) for p, o, i in specs if game_id(p, o, i) not in done]
    print('共 %d 局，已完成 %d，需下 %d 局（其中 %d 局接着日志续下）' % (
        len(specs), len(specs) - len(todo), len(todo), sum(1 for t in todo if t[4])))
    if not todo:
        return
    t0 = time.time()
    n = 0
    with ProcessPoolExecutor(max_workers=workers) as ex:
        futs = {ex.submit(play_game, t): t for t in todo}
        for f in as_completed(futs):
            s = f.result()
            n += 1
            print('  [%d/%d %.0fs] %s %s %s %d 半回合' % (n, len(todo), time.time() - t0, s['game'], s['result'], s['end'], s['plies']))


def final_eval(fen):
    """红方视角的终局评估（深度 FINAL_DEPTH）。"""
    a = _engine().analyse(fen, FINAL_DEPTH)
    red = fen.split()[1] == 'w'
    return {'cp': a['cp'], 'mate': a['mate'], 'red_cp': a['cp'] if red else -a['cp'], 'depth': a['depth']}


def _final_job(args):
    gid, fen = args
    return gid, final_eval(fen)


def cmd_calibrate(workers):
    specs = [('greedy2', 'weak-k%dd%d' % (k, d), i) for k, d in CALIB_GRID for i in range(N_GAMES)]
    run_games(specs, CLOG, workers)
    lines = read_lines(CLOG)
    have = {r['game'] for r in lines if r['type'] == 'final'}
    jobs = [(r['game'], r['final_fen']) for r in lines if r['type'] == 'game' and r['end'] == 'trunc' and r['game'] not in have]
    if jobs:
        with ProcessPoolExecutor(max_workers=workers) as ex:
            recs = [{'type': 'final', 'game': g, 'eval': e} for g, e in ex.map(_final_job, jobs)]
        append_lines(CLOG, recs)
    report_calib()


def adjudicate(summ, fin):
    if summ['result'] != 'trunc':
        return summ['result']
    c = fin['red_cp']
    return 'adv' if c >= ADJ else ('dis' if c <= -ADJ else 'eq')


def report_calib():
    lines = read_lines(CLOG)
    games = {r['game']: r for r in lines if r['type'] == 'game'}
    fins = {r['game']: r['eval'] for r in lines if r['type'] == 'final'}
    print('# 弱引擎标定：greedy2 执红 × 「引擎 MultiPV 前 k 名里按固定种子均匀挑」，每格 %d 局，同一批开局' % N_GAMES)
    print('| 设置 | 胜 | 截断优势 | 均势 | 截断劣势 | 负 | 「胜或优势」率 | 平均半回合 |')
    print('|---|---|---|---|---|---|---|---|')
    for k, d in CALIB_GRID:
        opp = 'weak-k%dd%d' % (k, d)
        gs = [games[g] for g in games if games[g]['opp'] == opp]
        if not gs:
            continue
        res = [adjudicate(s, fins.get(s['game'])) for s in gs]
        c = {x: res.count(x) for x in ('win', 'adv', 'eq', 'dis', 'loss')}
        print('| %s | %d | %d | %d | %d | %d | %s | %.0f |' % (
            opp, c['win'], c['adv'], c['eq'], c['dis'], c['loss'], fmt_rate(c['win'] + c['adv'], len(gs)),
            mean([s['plies'] for s in gs])))


def game_specs():
    specs = []
    for opp in ('random', WEAK):
        for player in JEV_PLAYERS + FREE:
            for i in range(N_GAMES):
                specs.append((player, opp, i))
    return specs


def cmd_games(workers, only=None, n=None, players=None):
    """only = free / jev；n 只下前 n 个开局（冒烟用）；players 逗号分隔，只下这些执红方。"""
    specs = game_specs()
    if only == 'free':
        specs = [s for s in specs if s[0] in FREE]
    elif only == 'jev':
        specs = [s for s in specs if s[0] not in FREE]
    if n:
        specs = [s for s in specs if s[2] < int(n)]
    if players:
        specs = [s for s in specs if s[0] in players.split(',')]
    # Jev 局的并发上限 6（每个进程一次只有一个在飞的请求）
    if any(s[0] not in FREE for s in specs):
        workers = min(workers, 6)
    run_games(specs, GLOG, workers)


def _eval_step(args):
    gid, ply, fen, move = args
    e = _engine()
    scores = e.score_moves(fen, depth=EVAL_DEPTH)
    g = b.two_ply(XQ, fen)
    top = max(g.values())
    # 两个贪心基线在这个局面上的并列集合：报告里拿来算「换成基线在同一局面上会亏多少」（反事实配对）
    ties = {'greedy1': tie_set(XQ, fen, 'greedy1'), 'greedy2': sorted(m for m in g if g[m] == top)}
    return {'type': 'eval', 'game': gid, 'ply': ply, 'depth': EVAL_DEPTH, 'move': move, 'scores': scores,
            'mates': b.mate_moves(XQ, fen), 'stalemates': b.stalemate_moves(XQ, fen),
            'gain_chosen': g[move], 'gain_max': top, 'ties': ties}


def cmd_evalgames(workers):
    lines = read_lines(GLOG)
    ev = read_lines(ELOG)
    have = {(r['game'], r.get('ply')) for r in ev}
    steps = [(r['game'], r['ply'], r['fen'], r['move']) for r in lines
             if r['type'] == 'step' and r['who'] == 'player' and (r['game'], r['ply']) not in have]
    finals = [(r['game'], r['final_fen']) for r in lines
              if r['type'] == 'game' and r['end'] == 'trunc' and (r['game'], None) not in have]
    print('待复评：%d 步执红着法，%d 个截断终局（深度 %d / %d）' % (len(steps), len(finals), EVAL_DEPTH, FINAL_DEPTH))
    t0 = time.time()
    with ProcessPoolExecutor(max_workers=workers) as ex:
        if finals:
            recs = [{'type': 'final', 'game': g, 'eval': e} for g, e in ex.map(_final_job, finals)]
            append_lines(ELOG, recs)
        buf = []
        n = 0
        for r in ex.map(_eval_step, steps, chunksize=4):
            buf.append(r)
            n += 1
            if len(buf) >= 200:
                append_lines(ELOG, buf)
                buf = []
                print('  %d/%d  %.0fs' % (n, len(steps), time.time() - t0))
        if buf:
            append_lines(ELOG, buf)
    print('完成，用时 %.0f 秒' % (time.time() - t0))


def _depth_job(p):
    e = _engine()
    return p['id'], e.score_moves(p['fen'], depth=EVAL_DEPTH)


def cmd_checkdepth(workers):
    """C2 逐步复评用深度 EVAL_DEPTH（比局面集的 12 浅）：在中国象棋 middle + gain 局面上对全部着法重算，
    和局面集里深度 12 的 move_scores 比，看损失、失误判定、最佳着差多少。不花钱。"""
    data = b.load_positions()
    ps = [p for p in static_positions(data) if p['game'] == XQ]
    with ProcessPoolExecutor(max_workers=workers) as ex:
        got = dict(ex.map(_depth_job, ps))
    d_all, agree_bl, n_all, best_same, rand10, rand12 = [], 0, 0, 0, [], []
    for p in ps:
        L12, L10 = cap_losses(p['move_scores']), cap_losses(got[p['id']])
        for m in L12:
            d_all.append(abs(L12[m] - L10[m]))
            agree_bl += (L12[m] >= BLUNDER) == (L10[m] >= BLUNDER)
            n_all += 1
        best_same += bool(best_set(p['move_scores']) & best_set(got[p['id']]))
        rand10.append(mean(list(L10.values())))
        rand12.append(mean(list(L12.values())))
    print('# 复评深度核对：中国象棋 %d 个局面、%d 步，深度 %d vs 12（封顶损失）' % (len(ps), n_all, EVAL_DEPTH))
    print('单步损失绝对差：中位 %.0f，均值 %.0f，90 分位 %.0f' % (
        statistics.median(d_all), mean(d_all), sorted(d_all)[int(0.9 * len(d_all))]))
    print('失误（≥%d）判定一致：%d/%d（%.1f%%）' % (BLUNDER, agree_bl, n_all, 100 * agree_bl / n_all))
    print('两个深度的最高分集合有交集：%d/%d' % (best_same, len(ps)))
    print('随机走子的期望损失：深度 %d 为 %.0f，深度 12 为 %.0f' % (EVAL_DEPTH, mean(rand10), mean(rand12)))


def rule_end(gid, steps, summ):
    """v2：按标准规则（长将 / 重复局面 / 自然限着）重放一局，找它会不会提前结束。
    两套判定：
      pyffish  带着法历史逐步调 is_optional_game_end / is_immediate_game_end（Fairy-Stockfish 的 xiangqi：三次重复判和；
               重复循环里一方每步都将军 → 长将方负、双方都长将 → 和；AXF 长捉规则的近似实现；50 回合（100 半回合）无吃子判和）
      自写     同一局面（棋盘 + 行棋方）第三次出现；从第一次出现到第三次之间，一方每步都将军而另一方不是 → 长将方负，否则判和
               （不判长捉）；另查 FEN 半回合计数 ≥ 100。
    返回 {'py': (半回合, 红方视角结果) 或 None, 'own': (半回合, 结果, 原因) 或 None}，半回合 = 走完第几步之后。"""
    moves = [r['move'] for r in steps]
    fens = [r['fen'] for r in steps] + [summ['final_fen']]
    start = fens[0]
    fsf = [b.to_fsf(XQ, m) for m in moves]
    out = {'py': None, 'own': None}
    for k in range(1, len(moves) + 1):
        stm = fens[k].split()[1]
        for fn in (sf.is_optional_game_end, sf.is_immediate_game_end):
            end, v = fn(XQ, start, fsf[:k])
            if end:
                res = 'draw' if v == 0 else ('win' if (v > 0) == (stm == 'w') else 'loss')
                out['py'] = (k, res, fn.__name__, v)
                break
        if out['py']:
            break
    seen = {}
    for k in range(len(fens)):
        key = b.key_of(fens[k])
        seen.setdefault(key, []).append(k)
        if int(fens[k].split()[4]) >= 100:
            out['own'] = (k, 'draw', '100 半回合无吃子')
            break
        if len(seen[key]) == 3:
            j0 = seen[key][0]
            chk = {'w': [], 'b': []}
            for t in range(j0, k):
                mover = fens[t].split()[1]
                chk[mover].append(sf.gives_check(XQ, fens[t + 1], []))
            pw, pb = all(chk['w']), all(chk['b'])
            if pw and not pb:
                out['own'] = (k, 'loss', '红方长将')
            elif pb and not pw:
                out['own'] = (k, 'win', '黑方长将')
            else:
                out['own'] = (k, 'draw', '三次重复（%s）' % ('双方都长将' if pw and pb else '无长将'))
            break
    return out


def split_vote_rows(steps, evs):
    """一局里「有一步胜却没走」的 Jev 步：立即胜着数、胜着概率合计与最大单项、所选着、所选着概率、其他将军选项的概率。"""
    rows = []
    for r in steps:
        if r['who'] != 'player' or not r.get('resp'):
            continue
        e = evs[(r['game'], r['ply'])]
        wins = set(e['mates']) | set(e['stalemates'])
        crit = r['questions']['move']['criteria']
        k2m = r['k2m']
        pm = {k2m[k]: float(v) for k, v in r['resp']['answers']['move']['probabilities'].items()}
        texts = {k2m[k]: t for k, t in crit.items()}
        checks = sorted(m for m, t in texts.items() if '，将军' in t)       # 不含将死（将死本身是胜着）
        rows.append({'ply': r['ply'], 'n': len(texts), 'wins': len(wins), 'missed': bool(wins) and r['move'] not in wins,
                     'pwin': sum(pm[m] for m in wins), 'pwin_max': max([pm[m] for m in wins] or [0]),
                     'move': r['move'], 'p_move': pm[r['move']], 'is_check': r['move'] in checks,
                     'other_checks': [(m, pm[m]) for m in checks if m != r['move']], 'text': texts[r['move']]})
    return rows


def report_games():
    lines = read_lines(GLOG)
    ev = read_lines(ELOG)
    games = {r['game']: r for r in lines if r['type'] == 'game'}
    steps = {}
    for r in lines:
        if r['type'] == 'step':
            steps.setdefault(r['game'], []).append(r)
    evs = {(r['game'], r['ply']): r for r in ev if r['type'] == 'eval'}
    fins = {r['game']: r['eval'] for r in ev if r['type'] == 'final'}
    specs = game_specs()
    miss = [game_id(*s) for s in specs if game_id(*s) not in games]
    if miss:
        print('（注意：还有 %d 局没下完，例 %s）' % (len(miss), miss[:3]))
    print('# C2 整局（中国象棋，Jev / 基线执红；上限 %d 半回合；弱引擎 = %s；逐步复评深度 %d，截断终局深度 %d，阈值 ±%d）' % (
        MAX_PLY, WEAK, EVAL_DEPTH, FINAL_DEPTH, ADJ))
    print('v2 口径：每步质量只排除「全部候选封顶损失都为 0」的局面（v1 排除最佳分 ≥ 封顶的局面）；率的区间按对局聚类 bootstrap；'
          'Jev 步另算「同层文字规则」（从日志里 Jev 实际看到的选项文字解析）的反事实损失。')
    # 先按标准规则重放，找会提前结束 / 改判的对局
    rules = {}
    for s in specs:
        gid = game_id(*s)
        if gid in games:
            st = sorted(steps.get(gid, []), key=lambda r: r['ply'])
            rules[gid] = rule_end(gid, st, games[gid])
    per = {}
    nchk = 0
    for s in specs:
        gid = game_id(*s)
        if gid not in games:
            continue
        g = games[gid]
        st = sorted(steps.get(gid, []), key=lambda r: r['ply'])
        assert [r['ply'] for r in st] == list(range(g['plies'])), ('步数不连续', gid)
        mine = [r for r in st if r['who'] == 'player']
        evm = [evs.get((gid, r['ply'])) for r in mine]
        if any(e is None for e in evm) or (g['end'] == 'trunc' and gid not in fins):
            print('（%s 还没复评完，先跑 evalgames）' % gid)
            return
        rend = rules[gid]['py'][0] if rules[gid]['py'] else None
        loss, lossu, lossu1, blunder, bluu, bluu1, missed, mate_opp, give, give_avoid = [], [], [], 0, [], 0, 0, 0, 0, 0
        m_opp, m_missed, cf, cf1 = 0, 0, [], []
        for r, e in zip(mine, evm):
            assert e['move'] == r['move']
            L = cap_losses(e['scores'])
            loss.append(L[r['move']])
            blunder += L[r['move']] >= BLUNDER
            row = None
            if 'ties' in e:          # 反事实：同一局面换成基线 / 同层文字规则（并列集合里均匀挑）的期望损失
                row = {'self': L[r['move']], 'random': mean(list(L.values())), 'ply': r['ply'],
                       'pre_rule': rend is None or r['ply'] < rend}
                for kind in ('greedy1', 'greedy2'):
                    row[kind] = mean([L[m] for m in e['ties'][kind]])
                if r.get('questions'):
                    lay = split_arm(r['layer'])[0]
                    texts = {r['k2m'][k]: t for k, t in r['questions']['move']['criteria'].items()}
                    assert set(texts) == set(L), ('选项与复评着法集合不一致', gid, r['ply'])
                    if lay in ('L1', 'L2'):
                        ts = text_rule_ties(XQ, texts, lay, fen=r['fen'])     # 反向核对解析结果
                        nchk += 1
                        row['text'] = mean([L[m] for m in ts])
                    else:
                        row['text'] = row['random']
                elif r.get('forced'):
                    row['text'] = row['self']
            # v2 未定局面：至少有一个候选的封顶损失 > 0（全部为 0 时怎么走都一样，没有信息）
            if max(L.values()) > 0:
                lossu.append(L[r['move']])
                bluu.append(float(L[r['move']] >= BLUNDER))
                if row is not None:
                    cf.append(row)
            # v1 的筛法（最佳分在 ±CAP 以内），只为「与 v1 的差异」保留
            if abs(max(e['scores'].values())) < CAP:
                lossu1.append(L[r['move']])
                bluu1 += L[r['move']] >= BLUNDER
                if row is not None:
                    cf1.append(row)
            if e['mates']:
                m_opp += 1
                m_missed += r['move'] not in e['mates']
            wins_ = set(e['mates']) | set(e['stalemates'])      # 中国象棋困毙也判胜
            if wins_:
                mate_opp += 1
                missed += r['move'] not in wins_
            if e['gain_chosen'] <= GIVE:
                give += 1
                give_avoid += e['gain_max'] - e['gain_chosen'] >= -GIVE
        fin = fins.get(gid)
        res = adjudicate(g, fin) if g['end'] == 'trunc' else g['result']
        if g['result'] == 'win':
            fcp = CAP
        elif g['result'] == 'loss':
            fcp = -CAP
        else:
            fcp = clip(fin['red_cp'])
        py = rules[gid]['py']
        res2, fcp2 = res, fcp
        if py:
            res2 = {'draw': 'rdraw', 'win': 'rwin', 'loss': 'rloss'}[py[1]]
            fcp2 = {'draw': 0, 'win': CAP, 'loss': -CAP}[py[1]]
        jr = [r['resp'] for r in mine if r.get('resp')]
        per[gid] = {'player': s[0], 'opp': s[1], 'i': s[2], 'res': res, 'res2': res2, 'end': g['end'], 'plies': g['plies'],
                    'moves': len(mine), 'loss': mean(loss), 'blunder': blunder, 'missed': missed, 'mate_opp': mate_opp,
                    'lossu': lossu, 'bluu': bluu, 'lossu1': lossu1, 'bluu1': bluu1, 'm_opp': m_opp, 'm_missed': m_missed,
                    'cf': cf, 'cf1': cf1, 'give': give, 'give_avoid': give_avoid, 'fcp': fcp, 'fcp2': fcp2,
                    'lat': [d['_elapsed'] for d in jr], 'tok': sum(d['usage']['input_tokens'] for d in jr),
                    'cost': sum(d['usage'].get('cost', 0.0) for d in jr), 'nreq': len(jr), 'all_loss': loss}
    print('（同层文字规则：%d 个 Jev 步的选项文字解析结果与 boards.facts / boards.safety 逐项核对通过）' % nchk)

    def cell(player, opp):
        return [v for v in per.values() if v['player'] == player and v['opp'] == opp]

    for opp in ('random', WEAK):
        print('\n## 对手：%s' % ('随机走子' if opp == 'random' else '弱引擎 ' + opp))
        print('| 执红 | 局数 | 胜（将死/困毙） | 截断优势 | 均势 | 截断劣势 | 负 | 胜或优势 [95%] | 终局评估均值（±1000 封顶）[95%] | 平均半回合 |')
        print('|---|---|---|---|---|---|---|---|---|---|')
        for player in JEV_PLAYERS + FREE:
            gs = cell(player, opp)
            if not gs:
                continue
            c = {x: sum(1 for v in gs if v['res'] == x) for x in ('win', 'adv', 'eq', 'dis', 'loss')}
            wins = [v for v in gs if v['res'] == 'win']
            wend = '%d（%d/%d）' % (c['win'], sum(v['end'] == 'mate' for v in wins), sum(v['end'] == 'stalemate' for v in wins))
            fc = [v['fcp'] for v in gs]
            print('| %s | %d | %s | %d | %d | %d | %d | %s | %+.0f %s | %.0f |' % (
                player, len(gs), wend, c['adv'], c['eq'], c['dis'], c['loss'], fmt_rate(c['win'] + c['adv'], len(gs)),
                mean(fc), fmt_ci(boot(fc, [v['i'] for v in gs], seed=5)), mean([v['plies'] for v in gs])))
        print('\n按标准规则（pyffish：长将判负、长捉判负、三次重复判和、100 半回合无吃子判和）改判后：')
        print('| 执红 | 胜 | 截断优势 | 均势 | 截断劣势 | 负 | 规则判和 | 对方长将 / 长捉判负（记胜） | 己方长将 / 长捉判负（记负） | 改判局数 | 胜或优势 [95%] | 终局评估均值 [95%] |')
        print('|---|---|---|---|---|---|---|---|---|---|---|---|')
        for player in JEV_PLAYERS + FREE:
            gs = cell(player, opp)
            if not gs:
                continue
            c = {x: sum(1 for v in gs if v['res2'] == x) for x in ('win', 'adv', 'eq', 'dis', 'loss', 'rdraw', 'rwin', 'rloss')}
            fc = [v['fcp2'] for v in gs]
            print('| %s | %d | %d | %d | %d | %d | %d | %d | %d | %d | %s | %+.0f %s |' % (
                player, c['win'], c['adv'], c['eq'], c['dis'], c['loss'], c['rdraw'], c['rwin'], c['rloss'],
                sum(1 for v in gs if v['res2'] != v['res']), fmt_rate(c['win'] + c['adv'] + c['rwin'], len(gs)),
                mean(fc), fmt_ci(boot(fc, [v['i'] for v in gs], seed=5))))
        print('\n| 执红 | 未定局面步数 / 全部步数 | 未定局面每步平均损失 [95%] | 未定局面失误 ≥200 [95%] | 全部步平均损失 | 一步杀 机会 / 漏掉 | 一步胜（杀或困毙）机会 / 漏掉 | 送子（两层物质 ≤−4）/ 其中可避免 |')
        print('|---|---|---|---|---|---|---|---|')
        for player in JEV_PLAYERS + FREE:
            gs = cell(player, opp)
            if not gs:
                continue
            allL = [x for v in gs for x in v['all_loss']]
            uL = [x for v in gs for x in v['lossu']]
            uB = [x for v in gs for x in v['bluu']]
            uc = [v['i'] for v in gs for _ in v['lossu']]
            print('| %s | %d / %d | %.0f %s | %s | %.0f | %d / %d | %d / %d | %d / %d |' % (
                player, len(uL), len(allL), mean(uL), fmt_ci(boot(uL, uc, seed=6)), fmt_rate_cl(uB, uc), mean(allL),
                sum(v['m_opp'] for v in gs), sum(v['m_missed'] for v in gs), sum(v['mate_opp'] for v in gs),
                sum(v['missed'] for v in gs), sum(v['give'] for v in gs), sum(v['give_avoid'] for v in gs)))
        print('\n| Jev 层 | 请求数 | 每步延迟 中位 / p90 / 最大（秒） | 每局输入 token 均值 | 每局花费均值 | 本格合计花费 |')
        print('|---|---|---|---|---|---|')
        for player in JEV_PLAYERS:
            gs = cell(player, opp)
            if not gs:
                continue
            lat = sorted(x for v in gs for x in v['lat'])
            print('| %s | %d | %.2f / %.2f / %.2f | %.0f | $%.5f | $%.4f |' % (
                player, sum(v['nreq'] for v in gs), statistics.median(lat), lat[int(0.9 * len(lat))], lat[-1],
                mean([v['tok'] for v in gs]), mean([v['cost'] for v in gs]), sum(v['cost'] for v in gs)))
        print('\n反事实配对（只看 Jev 实际走到的未定局面：同一局面上 Jev 所选着的损失 vs 换成同层文字规则 / 基线的期望损失；'
              '按对局聚类 bootstrap；负 = Jev 更好）。同层文字规则：L0 = random，L1 = text1，L2 = text2：')
        print('| Jev 层 | 步数（局数） | Jev 平均损失 | random | greedy1 | greedy2 | 同层文字规则 | Jev − 同层文字规则 [95%] | Jev − greedy1 [95%] | Jev − greedy2 [95%] |')
        print('|---|---|---|---|---|---|---|---|---|---|')
        for player in JEV_PLAYERS:
            gs = cell(player, opp)
            rows_ = [(v['i'], r) for v in gs for r in v['cf']]
            if not rows_:
                continue
            cl_ = [i for i, _ in rows_]
            dt = [r['self'] - r['text'] for _, r in rows_]
            d1 = [r['self'] - r['greedy1'] for _, r in rows_]
            d2 = [r['self'] - r['greedy2'] for _, r in rows_]
            print('| %s | %d（%d） | %.0f | %.0f | %.0f | %.0f | %.0f | %+.0f %s | %+.0f %s | %+.0f %s |' % (
                player, len(rows_), len(set(cl_)), mean([r['self'] for _, r in rows_]), mean([r['random'] for _, r in rows_]),
                mean([r['greedy1'] for _, r in rows_]), mean([r['greedy2'] for _, r in rows_]),
                mean([r['text'] for _, r in rows_]),
                mean(dt), fmt_ci(boot(dt, cl_, seed=11)), mean(d1), fmt_ci(boot(d1, cl_, seed=9)),
                mean(d2), fmt_ci(boot(d2, cl_, seed=10))))
        print('\n同上，只取按标准规则本不会出现的步之前（剔除规则提前结束之后的步）：')
        print('| Jev 层 | 步数 | Jev − 同层文字规则 [95%] | Jev − greedy2 [95%] |')
        print('|---|---|---|---|')
        for player in JEV_PLAYERS:
            rows_ = [(v['i'], r) for v in cell(player, opp) for r in v['cf'] if r['pre_rule']]
            if not rows_:
                continue
            cl_ = [i for i, _ in rows_]
            dt = [r['self'] - r['text'] for _, r in rows_]
            d2 = [r['self'] - r['greedy2'] for _, r in rows_]
            print('| %s | %d | %+.0f %s | %+.0f %s |' % (player, len(rows_), mean(dt), fmt_ci(boot(dt, cl_, seed=11)),
                                                        mean(d2), fmt_ci(boot(d2, cl_, seed=10))))
        print('\nv1 筛法（最佳分在 ±1000 以内才算）下的同一张表，只为对照：')
        print('| Jev 层 | 步数 | Jev − 同层文字规则 [95%] | Jev − greedy1 [95%] | Jev − greedy2 [95%] |')
        print('|---|---|---|---|---|')
        for player in JEV_PLAYERS:
            rows_ = [(v['i'], r) for v in cell(player, opp) for r in v['cf1']]
            if not rows_:
                continue
            cl_ = [i for i, _ in rows_]
            dt = [r['self'] - r['text'] for _, r in rows_]
            d1 = [r['self'] - r['greedy1'] for _, r in rows_]
            d2 = [r['self'] - r['greedy2'] for _, r in rows_]
            print('| %s | %d | %+.0f %s | %+.0f %s | %+.0f %s |' % (
                player, len(rows_), mean(dt), fmt_ci(boot(dt, cl_, seed=11)), mean(d1), fmt_ci(boot(d1, cl_, seed=9)),
                mean(d2), fmt_ci(boot(d2, cl_, seed=10))))
        print('\n配对差（同开局序号配对，bootstrap；终局评估正 = 更好，损失负 = 更好）：')
        print('| 对比 | 终局评估差 [95%] | 按标准规则改判后的终局评估差 [95%] | 局均未定局面每步损失差 [95%] | 「胜或优势」差（局数） |')
        print('|---|---|---|---|---|')
        idx = lambda pl: {v['i']: v for v in per.values() if v['player'] == pl and v['opp'] == opp}  # noqa: E731
        P0, P1, P2 = JEV_PLAYERS
        for a, c in ((P0, 'random'), (P1, 'greedy1'), (P2, 'greedy2'), (P1, P0), (P2, P1), ('greedy2', 'greedy1')):
            A, C = idx(a), idx(c)
            ii = sorted(set(A) & set(C))
            if not ii:
                continue
            df = [A[i]['fcp'] - C[i]['fcp'] for i in ii]
            df2 = [A[i]['fcp2'] - C[i]['fcp2'] for i in ii]
            ii_u = [i for i in ii if A[i]['lossu'] and C[i]['lossu']]
            dl = [mean(A[i]['lossu']) - mean(C[i]['lossu']) for i in ii_u]
            dw = sum((A[i]['res'] in ('win', 'adv')) - (C[i]['res'] in ('win', 'adv')) for i in ii)
            print('| %s − %s | %+.0f %s | %+.0f %s | %+.0f %s | %+d / %d |' % (
                a, c, mean(df), fmt_ci(boot(df, ii, seed=7)), mean(df2), fmt_ci(boot(df2, ii, seed=7)),
                mean(dl), fmt_ci(boot(dl, ii_u, seed=8)), dw, len(ii)))

    # 按标准规则会提前结束 / 改判的对局
    print('\n## 按标准规则重放（长将 / 重复局面 / 自然限着），会提前结束或改判的对局')
    agree = sum(1 for g in rules.values() if (g['py'] and g['own'] and g['py'][0] == g['own'][0]
                                               and g['py'][1] == g['own'][1]) or (not g['py'] and not g['own']))
    print('pyffish 与自写判定（第三次重复 + 长将，不判长捉）结论一致：%d/%d 局' % (agree, len(rules)))
    print('| 对局 | 原结果（半回合） | pyffish：结束于第几半回合后 / 红方结果 | 自写：半回合 / 结果 / 原因 |')
    print('|---|---|---|---|')
    for gid in sorted(rules, key=lambda x: (x.split('|')[1], x.split('|')[0], x)):
        g = rules[gid]
        if not g['py'] and not g['own']:
            continue
        v = per[gid]
        py = ('%d / %s' % (g['py'][0], g['py'][1])) if g['py'] else '—'
        own = ('%d / %s / %s' % g['own']) if g['own'] else '—'
        print('| %s | %s（%d） | %s | %s |' % (gid, v['res'], v['plies'], py, own))

    # 分票案例：逐次列出漏掉的立即胜
    print('\n## 漏掉一步胜的 Jev 步（L1 / L2）')
    for gid in sorted(per):
        v = per[gid]
        if v['player'] not in JEV_PLAYERS[1:] or not v['missed']:
            continue
        st = sorted(steps[gid], key=lambda r: r['ply'])
        rows_ = split_vote_rows(st, evs)
        mm = [r for r in rows_ if r['missed']]
        print('\n### %s：一步胜机会 %d 次，漏掉 %d 次' % (gid, v['mate_opp'], v['missed']))
        print('| 半回合 | 候选数 | 立即胜着数 | 胜着概率合计 | 胜着最大单项 | 所选着 | 所选着概率 | 所选是将军 | 其他将军选项的概率 |')
        print('|---|---|---|---|---|---|---|---|---|')
        for r in mm:
            print('| %d | %d | %d | %.2f | %.2f | %s | %.2f | %s | %s |' % (
                r['ply'], r['n'], r['wins'], r['pwin'], r['pwin_max'], r['move'], r['p_move'], '是' if r['is_check'] else '否',
                '、'.join('%s %.2f' % x for x in r['other_checks']) or '—'))
        if len(mm) >= 3:
            chk = [r for r in rows_ if r['is_check']]
            print('这局 Jev 选将军的半回合：%s（共 %d 次）' % (', '.join(str(r['ply']) for r in chk), len(chk)))
            print('这局 Jev 从第 %d 到第 %d 半回合的全部选择：' % (mm[0]['ply'], rows_[-1]['ply']))
            for r in rows_:
                if r['ply'] >= mm[0]['ply']:
                    print('  %d %s p=%.2f 胜着 %d（合计 %.2f）%s' % (r['ply'], r['text'], r['p_move'], r['wins'], r['pwin'],
                                                          ' 其他将军 ' + '、'.join('%.2f' % x[1] for x in r['other_checks']) if r['other_checks'] else ''))
    tot = sum(v['cost'] for v in per.values())
    nreq = sum(v['nreq'] for v in per.values())
    print('\nC2 合计：Jev 请求 %d 次，花费 $%.4f' % (nreq, tot))


if __name__ == '__main__':
    args = [a for a in sys.argv[1:] if not a.startswith('--')]
    opts = {}
    for a in sys.argv[1:]:
        if a.startswith('--'):
            k, _, v = a[2:].partition('=')
            opts[k] = v or True
    workers = int(opts.get('workers', 6))
    if args == ['static']:
        run_static(dry='dry' in opts)
    elif args == ['calibrate']:
        cmd_calibrate(workers)
    elif args == ['games']:
        cmd_games(workers, opts.get('only'), opts.get('n'), opts.get('players'))
    elif args == ['evalgames']:
        cmd_evalgames(workers)
    elif args == ['checkdepth']:
        cmd_checkdepth(workers)
    elif args == ['report', 'static'] or args == ['report']:
        report_static()
    elif args == ['report', 'games']:
        report_games()
    elif args == ['report', 'calib']:
        report_calib()
    elif args == ['report', 'all']:
        report_static()
        print()
        report_games()
        print()
        report_calib()
    else:
        raise SystemExit(__doc__)
