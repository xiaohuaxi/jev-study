# -*- coding: utf-8 -*-
"""Jev 猜规则干净 few-shot：只换"历史怎么写"，看新牌答对率有没有差。

牌：颜色（红/蓝）、数字（1–99）、箭头（朝左/朝右）。每轮按左键或右键，隐藏规则决定对错。
规则族 4 个：
  color   红→左 蓝→右（反：红→右 蓝→左）
  thresh  数字 ≥50→右 否则→左（反：≥50→左 否则→右）
  parity  单数→左 双数→右（反：单数→右 双数→左）
  arrow   顺箭头（箭头朝哪边就按哪边）（反：逆箭头，按箭头反方向）
每族再分"正/反"两个方向（反 = 把正的答案整体左右对调），族×方向合起来就是任务用的具体规则。
每族 50 个任务（25 正 25 反）：一个任务 = 一条固定规则 + 一份 64 张牌的历史序列 + 1 张测试牌。
4 族 × 50 = 200 个任务，任务只生成一次，4/16/64 三个历史长度都是同一份 64 张牌序列的前缀（同任务同测试牌）。

历史：每张牌配一个随机按键（左/右各半概率），对错由该任务的规则判定（按键是瞎按的，不含信息；
只有"对/错"含信息）。测试牌与该任务全部 64 张历史牌都不重复（颜色+数字+箭头三元组不同）。
测试牌在每个规则族内（50 个任务合起来）做了两条平衡：
  1. 正确答案左/右各 25 个（独立随机分配，不按方向配对）；
  2. 非 arrow 的三族里，"正确答案恰好等于箭头指向"的占 25 个、不等于的占 25 个——
     避免"顺手照箭头按"这种跟规则无关的策略也能蒙对一半，把它的干扰摊平。
  arrow 族不需要这条平衡：它的顺箭头比例就是要测的东西本身（正方向恒为顺、反方向恒为逆）。

历史写法（除 none/truth 外，raw/raw_instr/mapped/grouped 各有 4/16/64 三个长度）：
  none       无历史。
  truth      不给历史，直接把规则原文写进 hint（上限对照）。
  raw        一轮一行："第 k 轮：<牌面> → 按了X → 对/错"，问句就是原问句。
  raw_instr  历史文本与 raw 完全一样，只是问句里多一句明确指令："按键是随机按的，别学它，
             只看对错先猜规则、再判新牌"——用来看"想不到要这么读"是不是短板。
  mapped     把每条历史机械翻成"<牌面> → 正确按键"（错的记录翻成另一个键），不做任何统计/归纳，
             相当于替它把"对错"预处理成"哪个键对"。
  grouped    按"正确按键"分两组列牌面："按左才对的牌：…；按右才对的牌：…"，组内保持原始顺序，
             不算数、不统计——比 mapped 更进一步的预处理，只需要 Jev 自己看两组牌有什么共性。

state 字段固定两个、顺序固定"先历史（或 truth 的 hint）、后当前牌"：
  zh: {"历史"/"提示": ..., "当前牌": ...}   en: {"history"/"hint": ..., "current_card": ...}
选项固定两项，zh 用 左/右、en 用 left/right；criteria 字典里两个键谁先谁后，每个任务独立随机一次，
同一任务的全部写法/长度/语言共用这个顺序。

中英配对：同一任务、同一 64 张历史、同一测试牌，只有文本（问句、字段名、牌面描述、选项）中英分开写，
内部判定规则/正确答案/箭头方向全部走同一份中文内部表示（'左'/'右'/'红'/'蓝'/'朝左'/'朝右'），
只在渲染成文本、或跟回包的 choice 比对时才按语言转成 左右 / left right。

请求量：4 族 × 50 任务 × (none 1 + truth 1 + 4 写法 × 3 长度 = 14) × 2 语言 = 5,600。

用法：python3 exp_icl_rules.py run [--smoke]   —— 断点续跑，结果写 icl_rules_log.json；
                                                    --smoke 只跑每族第 0 个任务（相当于每格 1 题），
                                                    这些请求的 key 和全量跑时完全一样，不会被浪费。
      python3 exp_icl_rules.py show              —— 不发请求，打印几个完整请求体，供人工核对措辞。
      python3 exp_icl_rules.py report             —— 只读日志出表。
"""
# 让本脚本从任意目录都能找到仓库根部的 jevkit.py 和同目录的其他 exp_icl_*.py
import sys as _sys, pathlib as _pathlib
_sys.path[:0] = [str(_pathlib.Path(__file__).resolve().parent), str(_pathlib.Path(__file__).resolve().parent.parent)]
import json, math, os, random, sys, threading
from concurrent.futures import ThreadPoolExecutor
from functools import lru_cache

HERE = os.path.dirname(os.path.abspath(__file__))
LOG = os.path.join(HERE, 'icl_rules_log.json')
LOCK = threading.Lock()

FAMILIES = ['color', 'thresh', 'parity', 'arrow']
DIRECTIONS = ['pos', 'neg']   # 正 / 反
TASKS = 50                    # 每族任务数（25 正 25 反）
HIST_LEN = 64
C_LENS = [4, 16, 64]
FORMATS = ['raw', 'raw_instr', 'mapped', 'grouped']
CONDS = [('none', 0), ('truth', 0)] + [(f, n) for f in FORMATS for n in C_LENS]

RULE_DESC = {
    ('color', 'pos'): {'zh': '红色按左键，蓝色按右键', 'en': 'red -> press left, blue -> press right'},
    ('color', 'neg'): {'zh': '红色按右键，蓝色按左键', 'en': 'red -> press right, blue -> press left'},
    ('thresh', 'pos'): {'zh': '数字大于等于 50 按右键，否则按左键', 'en': 'number >= 50 -> press right, otherwise press left'},
    ('thresh', 'neg'): {'zh': '数字大于等于 50 按左键，否则按右键', 'en': 'number >= 50 -> press left, otherwise press right'},
    ('parity', 'pos'): {'zh': '单数按左键，双数按右键', 'en': 'odd number -> press left, even number -> press right'},
    ('parity', 'neg'): {'zh': '单数按右键，双数按左键', 'en': 'odd number -> press right, even number -> press left'},
    ('arrow', 'pos'): {'zh': '箭头朝哪边就按哪边（顺着箭头按）', 'en': 'press whichever side the arrow points to (follow the arrow)'},
    ('arrow', 'neg'): {'zh': '箭头朝哪边就按另一边（和箭头方向相反）', 'en': 'press the side opposite the arrow (against the arrow)'},
}

Q_RULE_ZH = ('你在玩一个猜规则的卡牌游戏。每轮翻开一张牌，牌上有颜色、数字和箭头，你要按左键或右键。'
             '有一条隐藏规则决定按哪边才对，规则一直不变，但没人告诉你。state 里有之前各轮的记录（如果有的话）。'
             '看当前这张牌，选按哪个键才对。')
RAW_INSTR_ZH = ('记录里的按键是随机按的，不要模仿按键，只看对错；先根据对错推断隐藏规则'
                '（可能跟颜色、数字大小、单双、箭头有关），再判断当前这张牌。')
Q_RULE_EN = ('You are playing a rule-guessing card game. Each round a card is revealed with a color, '
             'a number, and an arrow, and you must press the left or right key. A hidden rule (always the same, '
             'never told to you) decides which key is correct. The state may include a record of previous rounds, '
             'if any. Look at the current card and choose the correct key.')
RAW_INSTR_EN = ('The keys in the record were pressed at random — do not imitate them, only look at right/wrong. '
                'First infer the hidden rule from the right/wrong pattern (it may relate to color, number size, '
                'odd/even, or the arrow), then judge the current card.')
Q_TEXT = {
    'zh': {False: Q_RULE_ZH, True: Q_RULE_ZH + RAW_INSTR_ZH},
    'en': {False: Q_RULE_EN, True: Q_RULE_EN + ' ' + RAW_INSTR_EN},
}

CRIT_PAIRS = {
    'zh': [('左', '按左键'), ('右', '按右键')],
    'en': [('left', 'Press the left key.'), ('right', 'Press the right key.')],
}
KEY = {
    'history': {'zh': '历史', 'en': 'history'},
    'hint': {'zh': '提示', 'en': 'hint'},
    'current_card': {'zh': '当前牌', 'en': 'current_card'},
}
TRUTH_TMPL = {'zh': '规则是：%s。', 'en': 'The rule is: %s.'}
NONE_TEXT = {'zh': '（还没有任何记录）', 'en': 'No records yet.'}
COLOR_EN = {'红': 'red', '蓝': 'blue'}
ARROW_EN = {'朝左': 'pointing left', '朝右': 'pointing right'}


def flip(side):
    return '右' if side == '左' else '左'


def side_lang(side, lang):
    if lang == 'zh':
        return side
    return 'left' if side == '左' else 'right'


def card_text(c, lang):
    if lang == 'zh':
        return '%s色、数字 %d、箭头%s' % (c['color'], c['number'], c['arrow'])
    return 'color %s, number %d, arrow %s' % (COLOR_EN[c['color']], c['number'], ARROW_EN[c['arrow']])


def random_card(rng):
    return {'color': rng.choice(['红', '蓝']), 'number': rng.randint(1, 99), 'arrow': rng.choice(['朝左', '朝右'])}


def rand_parity(rng, odd):
    while True:
        n = rng.randint(1, 99)
        if (n % 2 == 1) == odd:
            return n


def base_answer(family, card):
    """"正"方向下这张牌该按哪边（"反"方向就是把它翻过来）。"""
    if family == 'color':
        return '左' if card['color'] == '红' else '右'
    if family == 'thresh':
        return '右' if card['number'] >= 50 else '左'
    if family == 'parity':
        return '左' if card['number'] % 2 else '右'
    if family == 'arrow':
        return '左' if card['arrow'] == '朝左' else '右'
    raise ValueError(family)


def rule_answer(family, direction, card):
    b = base_answer(family, card)
    return b if direction == 'pos' else flip(b)


def balanced_labels(seed, values, counts):
    pool = []
    for v, c in zip(values, counts):
        pool += [v] * c
    random.Random(seed).shuffle(pool)
    return pool


@lru_cache(maxsize=None)
def task_labels(family):
    directions = balanced_labels('rules|dir|%s' % family, ['pos', 'neg'], [25, 25])
    answers = balanced_labels('rules|ans|%s' % family, ['左', '右'], [25, 25])
    matches = balanced_labels('rules|match|%s' % family, [True, False], [25, 25])
    return directions, answers, matches


def gen_test_card(rng, family, direction, target_answer, target_match, hist_set):
    """在满足"答案=target_answer"（且非 arrow 族还要满足"是否顺箭头=target_match"）的前提下，
    随机生成一张不在 hist_set 里的测试牌。"""
    required_base = target_answer if direction == 'pos' else flip(target_answer)
    for _ in range(5000):
        if family == 'color':
            color = '红' if required_base == '左' else '蓝'
            number = rng.randint(1, 99)
        elif family == 'thresh':
            color = rng.choice(['红', '蓝'])
            number = rng.randint(50, 99) if required_base == '右' else rng.randint(1, 49)
        elif family == 'parity':
            color = rng.choice(['红', '蓝'])
            number = rand_parity(rng, odd=(required_base == '左'))
        elif family == 'arrow':
            color = rng.choice(['红', '蓝'])
            number = rng.randint(1, 99)
        else:
            raise ValueError(family)
        if family == 'arrow':
            arrow = '朝左' if required_base == '左' else '朝右'
        else:
            side_for_match = target_answer if target_match else flip(target_answer)
            arrow = '朝左' if side_for_match == '左' else '朝右'
        card = {'color': color, 'number': number, 'arrow': arrow}
        triple = (card['color'], card['number'], card['arrow'])
        if triple in hist_set:
            continue
        assert rule_answer(family, direction, card) == target_answer
        if family != 'arrow':
            assert (base_answer('arrow', card) == target_answer) == target_match
        return card
    raise RuntimeError('无法为 %s/%s 生成不重复测试牌' % (family, direction))


def make_task(family, i, direction, target_answer, target_match):
    rng = random.Random('rules|task|%s|%d' % (family, i))
    hist = []
    for _ in range(HIST_LEN):
        c = random_card(rng)
        pressed = rng.choice(['左', '右'])
        correct = pressed == rule_answer(family, direction, c)
        hist.append({'card': c, 'pressed': pressed, 'correct': correct})
    hist_set = {(h['card']['color'], h['card']['number'], h['card']['arrow']) for h in hist}
    cur = gen_test_card(rng, family, direction, target_answer, target_match, hist_set)
    return hist, cur


@lru_cache(maxsize=None)
def build_task(family, i):
    directions, answers, matches = task_labels(family)
    direction, target_answer = directions[i], answers[i]
    target_match = None if family == 'arrow' else matches[i]
    hist, cur = make_task(family, i, direction, target_answer, target_match)
    return direction, target_answer, target_match, hist, cur


def render_raw(hist, lang):
    lines = []
    for i, h in enumerate(hist):
        if lang == 'zh':
            lines.append('第 %d 轮：%s → 按了%s → %s' % (
                i + 1, card_text(h['card'], 'zh'), side_lang(h['pressed'], 'zh'), '对' if h['correct'] else '错'))
        else:
            lines.append('Round %d: %s -> pressed %s -> %s' % (
                i + 1, card_text(h['card'], 'en'), side_lang(h['pressed'], 'en'), 'correct' if h['correct'] else 'wrong'))
    return '\n'.join(lines)


def render_mapped(hist, lang):
    lines = []
    for i, h in enumerate(hist):
        ck = h['pressed'] if h['correct'] else flip(h['pressed'])
        if lang == 'zh':
            lines.append('第 %d 条：%s → 正确按键%s' % (i + 1, card_text(h['card'], 'zh'), side_lang(ck, 'zh')))
        else:
            lines.append('Item %d: %s -> correct key %s' % (i + 1, card_text(h['card'], 'en'), side_lang(ck, 'en')))
    return '\n'.join(lines)


def render_grouped(hist, lang):
    left, right = [], []
    for h in hist:
        ck = h['pressed'] if h['correct'] else flip(h['pressed'])
        (left if ck == '左' else right).append(card_text(h['card'], lang))
    if lang == 'zh':
        return '按左才对的牌：%s\n按右才对的牌：%s' % ('；'.join(left) if left else '（无）',
                                              '；'.join(right) if right else '（无）')
    return 'Cards where left is correct: %s\nCards where right is correct: %s' % (
        '; '.join(left) if left else '(none)', '; '.join(right) if right else '(none)')


def rule_state(family, direction, hist_n, cur, fmt, lang):
    st = {}
    if fmt == 'none':
        st[KEY['history'][lang]] = NONE_TEXT[lang]
    elif fmt == 'truth':
        st[KEY['hint'][lang]] = TRUTH_TMPL[lang] % RULE_DESC[(family, direction)][lang]
    elif fmt in ('raw', 'raw_instr'):
        st[KEY['history'][lang]] = render_raw(hist_n, lang)
    elif fmt == 'mapped':
        st[KEY['history'][lang]] = render_mapped(hist_n, lang)
    elif fmt == 'grouped':
        st[KEY['history'][lang]] = render_grouped(hist_n, lang)
    else:
        raise ValueError(fmt)
    st[KEY['current_card'][lang]] = card_text(cur, lang)
    return st


def criteria_dict(lang, left_first):
    pairs = CRIT_PAIRS[lang]
    if not left_first:
        pairs = list(reversed(pairs))
    return dict(pairs)


def build_request(family, i, fmt, n, lang):
    direction, target_answer, target_match, hist, cur = build_task(family, i)
    arrow_side = base_answer('arrow', cur)
    left_first = random.Random('rules|order|%s|%d' % (family, i)).random() < 0.5
    crit = criteria_dict(lang, left_first)
    hist_n = hist[:n] if fmt not in ('none', 'truth') else []
    st = rule_state(family, direction, hist_n, cur, fmt, lang)
    instr = Q_TEXT[lang][fmt == 'raw_instr']
    q = {'key': {'type': 'choice', 'instructions': instr, 'criteria': crit}}
    k = 'rules|%s|%d|%s|%d|%s' % (family, i, fmt, n, lang)
    meta = {'family': family, 'direction': direction, 'i': i, 'fmt': fmt, 'n': n, 'lang': lang,
            'answer': target_answer, 'arrow_side': arrow_side}
    return k, st, q, meta


def jobs_rules(smoke=False):
    idxs = [0] if smoke else list(range(TASKS))
    jobs = []
    for family in FAMILIES:
        for i in idxs:
            for lang in ('zh', 'en'):
                for fmt, n in CONDS:
                    jobs.append(build_request(family, i, fmt, n, lang))
    return jobs


def load():
    if os.path.exists(LOG):
        return json.load(open(LOG))
    return {}


def save(log):
    tmp = LOG + '.tmp'
    json.dump(log, open(tmp, 'w'), ensure_ascii=False)
    os.replace(tmp, LOG)


def run_jobs(log, jobs, workers=8, checkpoint=200):
    import jevkit as jev
    todo = [j for j in jobs if j[0] not in log or '_error' in log[j[0]]['resp']]
    print('共 %d 题，待发 %d' % (len(jobs), len(todo)))
    done = [0]

    def one(j):
        k, st, q, meta = j
        r = jev.call(st, q)
        with LOCK:
            log[k] = {'meta': meta, 'resp': r}
            done[0] += 1
            if done[0] % checkpoint == 0:
                save(log)
                print('  已完成 %d/%d，已落盘' % (done[0], len(todo)))

    with ThreadPoolExecutor(max_workers=workers) as ex:
        list(ex.map(one, todo))
    save(log)
    print(jev.spend())


def show_samples():
    examples = [
        ('color', 0, 'raw', 16, 'zh'),
        ('color', 0, 'raw', 16, 'en'),
        ('arrow', 0, 'raw_instr', 4, 'zh'),
        ('thresh', 0, 'mapped', 4, 'en'),
        ('parity', 0, 'grouped', 4, 'zh'),
        ('color', 0, 'truth', 0, 'en'),
        ('arrow', 0, 'none', 0, 'zh'),
    ]
    for family, i, fmt, n, lang in examples:
        k, st, q, meta = build_request(family, i, fmt, n, lang)
        print('=== %s ===' % k)
        print(json.dumps({'state': st, 'questions': q}, ensure_ascii=False, indent=2))
        print('meta:', meta)
        print()


# ---------------- 报告 ----------------
def wilson(x, n, z=1.959963985):
    if n == 0:
        return (0.0, 0.0)
    p = x / n
    denom = 1 + z * z / n
    center = p + z * z / (2 * n)
    margin = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return ((center - margin) / denom, (center + margin) / denom)


def wilson_str(x, n):
    if n == 0:
        return '-'
    lo, hi = wilson(x, n)
    return '%d/%d[%.2f,%.2f]' % (x, n, lo, hi)


def cell():
    return {'acc': 0, 'arrow': 0, 'n': 0}


def report():
    log = load()
    bad = [k for k, v in log.items() if '_error' in v.get('resp', {})]
    print('日志 %d 条，失败 %d 条' % (len(log), len(bad)))
    for k in bad[:20]:
        print('  FAIL', k, log[k]['resp'].get('_error'))

    rows = {}   # (family, fmt, n, lang) -> cell
    dr = {}     # (family, direction) -> cell，汇总全部条件
    dh = {}     # (family, direction) -> cell，只汇总有历史的写法（排除 none 不给历史、truth 直接告诉规则）
    for k, v in log.items():
        if '_error' in v.get('resp', {}):
            continue
        m = v['meta']
        choice = v['resp']['answers']['key']['choice']
        ok = choice == side_lang(m['answer'], m['lang'])
        c = rows.setdefault((m['family'], m['fmt'], m['n'], m['lang']), cell())
        c['n'] += 1
        c['acc'] += ok
        c['arrow'] += choice == side_lang(m['arrow_side'], m['lang'])
        d = dr.setdefault((m['family'], m['direction']), cell())
        d['n'] += 1
        d['acc'] += ok
        if m['fmt'] not in ('none', 'truth'):
            d = dh.setdefault((m['family'], m['direction']), cell())
            d['n'] += 1
            d['acc'] += ok

    print('\n== 各规则族 × 写法 × 长度 × 语言：答对率[Wilson 95%]（瞎猜 50%） / 顺箭头比例 ==')
    for family in FAMILIES:
        for lang in ('zh', 'en'):
            print('-- %s / %s --' % (family, lang))
            for fmt, n in CONDS:
                c = rows.get((family, fmt, n, lang))
                if not c:
                    print('  %-10s n=%-3d 缺失' % (fmt, n))
                    continue
                print('  %-10s n=%-3d 答对 %-18s 顺箭头 %d/%d' % (fmt, n, wilson_str(c['acc'], c['n']), c['arrow'], c['n']))

    print('\n== 非 arrow 三族合计（color+thresh+parity，每格 n=150）==')
    for lang in ('zh', 'en'):
        print('-- %s --' % lang)
        for fmt, n in CONDS:
            acc = sum(rows.get((f, fmt, n, lang), cell())['acc'] for f in ('color', 'thresh', 'parity'))
            arrow = sum(rows.get((f, fmt, n, lang), cell())['arrow'] for f in ('color', 'thresh', 'parity'))
            tot = sum(rows.get((f, fmt, n, lang), cell())['n'] for f in ('color', 'thresh', 'parity'))
            if not tot:
                continue
            print('  %-10s n=%-3d 答对 %-18s 顺箭头 %d/%d' % (fmt, n, wilson_str(acc, tot), arrow, tot))

    print('\n== 按规则族 × 正/反 拆开（汇总全部写法/长度/语言，每格 n=700）==')
    for family in FAMILIES:
        for direction in DIRECTIONS:
            c = dr.get((family, direction), cell())
            print('  %-7s %-4s 答对 %s' % (family, direction, wilson_str(c['acc'], c['n'])))
    print('\n== 同上，只算有历史的写法（排除 none、truth；每格 n=600）==')
    for family in FAMILIES:
        for direction in DIRECTIONS:
            c = dh.get((family, direction), cell())
            print('  %-7s %-4s 答对 %s' % (family, direction, wilson_str(c['acc'], c['n'])))

    print('\n== 测试牌与历史牌重复检查（各长度都应为 0） ==')
    dup_by_len = {n: 0 for n in C_LENS}
    for family in FAMILIES:
        for i in range(TASKS):
            direction, target_answer, target_match, hist, cur = build_task(family, i)
            cur_t = (cur['color'], cur['number'], cur['arrow'])
            for n in C_LENS:
                dup_by_len[n] += sum(1 for h in hist[:n]
                                      if (h['card']['color'], h['card']['number'], h['card']['arrow']) == cur_t)
    print('  200 任务，各长度重复数：%s' % dup_by_len)


def main():
    if len(sys.argv) < 2 or sys.argv[1] not in ('run', 'report', 'show'):
        print(__doc__)
        return
    if sys.argv[1] == 'report':
        report()
        return
    if sys.argv[1] == 'show':
        show_samples()
        return
    smoke = '--smoke' in sys.argv[2:]
    log = load()
    run_jobs(log, jobs_rules(smoke=smoke))
    report()


if __name__ == '__main__':
    main()
