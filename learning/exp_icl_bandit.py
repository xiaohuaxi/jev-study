"""Jev 能不能从 state 里的历史经验学：隐藏规则的多臂老虎机 + 猜规则卡牌。

问题：把"之前玩过的记录"塞进 state，Jev 的选择会不会随记录变长而变好？记录怎么写有没有差别？

A 老虎机（固定历史，一次问一题）
  4 个按钮，中奖概率最好的 0.75、其余 0.25，最好的是哪个每题随机。历史由程序随机生成：
    uniform    每轮等概率随机按（频率不含信息，得分才含信息）
    mislead    六成按某个差按钮（频率指向错的，得分指向对的）
  写法：none（不给历史）/ actions（只有按了什么，不写得分）/ raw（一轮一行，含得分）/
        json（同 raw 的结构化列表）/ summary（程序算好每个按钮按了几次、平均得分）/
        lesson（程序写一句"目前 X 平均得分最高"）/ truth（直接告诉哪个概率最高）
  长度：4 8 16 32 64 128 256，raw 另加 512 1024 1600（每轮约 19 token，1800 轮超 32K 被拒）
  指标：选中真最好 / 选中历史里平均得分最高的（经验最好，并列算中）/ 选中历史里按得最多的

B 老虎机（在线闭环）
  Jev 自己按 40 轮，每轮把自己的记录（raw 或 summary）放进下一轮 state，看越玩越好没有。
  另有 raw_x / summary_x：前 8 轮由适配器代按（每个按钮两次），之后才交给 Jev。
  同时在本地模拟随机、贪心、UCB1 当参照（同一组随机种子）。

C 猜规则卡牌
  每张牌有颜色（红/蓝）、数字（1–99）、箭头（朝左/朝右），按左或右键，隐藏规则决定对错：
    color  红→左 蓝→右        thresh  ≥50→右 否则左
    parity 单数→左 双数→右    anti    箭头朝哪边就按反方向（和直觉相反）
  历史里的按键是随机的，写对错。写法：none / raw / summary（程序按每个特征值统计对错）/ truth
  长度：4 8 16 32 64。指标：新牌上答对率。

用法：python3 exp_icl_bandit.py run [A|B|C ...]   —— 断点续跑，结果写 icl_bandit_log.json
      python3 exp_icl_bandit.py report             —— 只读日志出表
"""
# 让本脚本从任意目录都能找到仓库根部的 jevkit.py 和同目录的其他 exp_icl_*.py
import sys as _sys, pathlib as _pathlib
_sys.path[:0] = [str(_pathlib.Path(__file__).resolve().parent), str(_pathlib.Path(__file__).resolve().parent.parent)]
import json, math, os, random, statistics, sys, threading
from concurrent.futures import ThreadPoolExecutor

HERE = os.path.dirname(os.path.abspath(__file__))
LOG = os.path.join(HERE, 'icl_bandit_log.json')
LOCK = threading.Lock()

ARMS = ['A', 'B', 'C', 'D']
P_GOOD, P_BAD = 0.75, 0.25
TRIALS = 30
LENS = [4, 8, 16, 32, 64, 128, 256]
RAW_EXTRA = [512, 1024, 1600]
FORMATS = ['actions', 'raw', 'json', 'summary', 'lesson']
Q_BANDIT = ('你在玩一个有 4 个按钮（A、B、C、D）的游戏。每轮按一个按钮，可能得 1 分，也可能得 0 分。'
            '每个按钮得分的概率不一样，但没人告诉你哪个高。state 里有之前各轮的记录（如果有的话）。'
            '选下一轮按哪个按钮，目标是尽量多得分。')
CRIT_BANDIT = {a: '按按钮 ' + a for a in ARMS}


def gen_history(rng, best, n, mode):
    bad_fav = rng.choice([a for a in ARMS if a != best])
    hist = []
    for _ in range(n):
        if mode == 'mislead' and rng.random() < 0.6:
            a = bad_fav
        else:
            a = rng.choice(ARMS)
        p = P_GOOD if a == best else P_BAD
        hist.append((a, 1 if rng.random() < p else 0))
    return hist, bad_fav


def stats(hist):
    s = {a: [0, 0] for a in ARMS}
    for a, r in hist:
        s[a][0] += 1; s[a][1] += r
    return s


def emp_best(hist):
    s = stats(hist)
    means = {a: (s[a][1] / s[a][0]) for a in ARMS if s[a][0]}
    if not means:
        return set(ARMS)
    m = max(means.values())
    return {a for a, v in means.items() if abs(v - m) < 1e-9}


def most_freq(hist):
    s = stats(hist)
    m = max(v[0] for v in s.values())
    return {a for a in ARMS if s[a][0] == m}


def bandit_state(hist, fmt, best):
    if fmt == 'none':
        return {'task': '按按钮得分', 'history': '（还没有任何记录）'}
    if fmt == 'truth':
        return {'task': '按按钮得分', 'hint': '已知按钮 %s 得分的概率最高。' % best}
    if fmt == 'actions':
        return {'task': '按按钮得分', 'history': '\n'.join('第 %d 轮：按了 %s' % (i + 1, a) for i, (a, r) in enumerate(hist))}
    if fmt == 'raw':
        return {'task': '按按钮得分', 'history': '\n'.join('第 %d 轮：按了 %s，得 %d 分' % (i + 1, a, r) for i, (a, r) in enumerate(hist))}
    if fmt == 'json':
        return {'task': '按按钮得分', 'history': [{'round': i + 1, 'button': a, 'points': r} for i, (a, r) in enumerate(hist)]}
    s = stats(hist)
    if fmt == 'summary':
        return {'task': '按按钮得分', 'rounds_played': len(hist),
                'per_button': {a: {'times_pressed': s[a][0], 'total_points': s[a][1],
                                   'average_points': round(s[a][1] / s[a][0], 2) if s[a][0] else None}
                               for a in ARMS}}
    if fmt == 'lesson':
        means = {a: s[a][1] / s[a][0] for a in ARMS if s[a][0]}
        top = max(means, key=lambda a: (means[a], s[a][0]))
        others = '、'.join('%s %.2f' % (a, means[a]) for a in ARMS if a in means and a != top)
        return {'task': '按按钮得分', 'lesson': '经验：已经玩了 %d 轮，目前按钮 %s 的平均得分最高（%.2f）；其余：%s。' % (
            len(hist), top, means[top], others or '没按过')}
    raise ValueError(fmt)


def load():
    if os.path.exists(LOG):
        return json.load(open(LOG))
    return {}


def save(log):
    tmp = LOG + '.tmp'
    json.dump(log, open(tmp, 'w'), ensure_ascii=False)
    os.replace(tmp, LOG)


def run_jobs(log, jobs, workers=10):
    """jobs: [(key, state, questions, meta)]；跳过已成功的 key。"""
    import jevkit as jev
    todo = [j for j in jobs if j[0] not in log or '_error' in log[j[0]]['resp']]
    print('共 %d 题，待发 %d' % (len(jobs), len(todo)))

    def one(j):
        k, st, q, meta = j
        r = jev.call(st, q)
        with LOCK:
            log[k] = {'meta': meta, 'resp': r}
    with ThreadPoolExecutor(max_workers=workers) as ex:
        list(ex.map(one, todo))
    save(log)
    print(jev.spend())


# ---------------- A 固定历史 ----------------
def jobs_A():
    jobs = []
    for mode in ('uniform', 'mislead'):
        cells = [(f, n) for f in FORMATS for n in LENS] + [('raw', n) for n in RAW_EXTRA]
        if mode == 'uniform':
            cells += [('none', 0), ('truth', 0)]
        for fmt, n in cells:
            for t in range(TRIALS):
                rng = random.Random('A|%s|%d|%d' % (mode, n, t))   # 同一 (mode,n,t) 各写法用同一份历史
                best = rng.choice(ARMS)
                hist, bad_fav = gen_history(rng, best, n, mode)
                k = 'A|%s|%s|%d|%d' % (mode, fmt, n, t)
                meta = {'mode': mode, 'fmt': fmt, 'n': n, 't': t, 'best': best,
                        'emp': sorted(emp_best(hist)) if n else [], 'freq': sorted(most_freq(hist)) if n else [],
                        'bad_fav': bad_fav}
                jobs.append((k, bandit_state(hist, fmt, best),
                             {'button': {'type': 'choice', 'instructions': Q_BANDIT, 'criteria': CRIT_BANDIT}}, meta))
    return jobs


# ---------------- B 在线闭环 ----------------
ONLINE_RUNS, ONLINE_ROUNDS = 20, 40
ONLINE_FMTS = ('raw', 'summary', 'raw_x', 'summary_x')   # _x：前 8 轮由适配器代为探索


def online_run(fmt, run, log):
    import jevkit as jev
    key = 'B|%s|%d' % (fmt, run)
    if key in log and not log[key].get('error'):
        return
    rng = random.Random('B|%d' % run)
    best = rng.choice(ARMS)
    draws = [[rng.random() for _ in ARMS] for _ in range(ONLINE_ROUNDS)]   # 第 t 轮按各按钮会不会中，预先抽好
    hist, steps = [], []
    base = fmt[:-2] if fmt.endswith('_x') else fmt
    for t in range(ONLINE_ROUNDS):
        if fmt.endswith('_x') and t < 8:      # 适配器代为探索：前 8 轮每个按钮按两次，不问 Jev
            a = ARMS[t % 4]
            rew = 1 if draws[t][ARMS.index(a)] < (P_GOOD if a == best else P_BAD) else 0
            hist.append((a, rew)); steps.append({'a': a, 'r': rew, 'forced': True})
            continue
        st = bandit_state(hist, base if t else 'none', best)
        r = jev.call(st, {'button': {'type': 'choice', 'instructions': Q_BANDIT, 'criteria': CRIT_BANDIT}})
        if '_error' in r:
            with LOCK:
                log[key] = {'error': r['_error'], 'steps': steps}
            return
        a = r['answers']['button']['choice']
        rew = 1 if draws[t][ARMS.index(a)] < (P_GOOD if a == best else P_BAD) else 0
        hist.append((a, rew))
        steps.append({'a': a, 'r': rew, 'p': r['answers']['button']['probabilities']})
    with LOCK:
        log[key] = {'best': best, 'steps': steps, 'fmt': fmt, 'run': run}


def sim_policy(name, run):
    rng = random.Random('B|%d' % run)
    best = rng.choice(ARMS)
    draws = [[rng.random() for _ in ARMS] for _ in range(ONLINE_ROUNDS)]
    prng = random.Random('P|%s|%d' % (name, run))
    hist, out = [], []
    for t in range(ONLINE_ROUNDS):
        s = stats(hist)
        if name == 'random':
            a = prng.choice(ARMS)
        elif name == 'greedy':      # 每个先按一次，之后按平均最高的（并列随机）
            untried = [x for x in ARMS if not s[x][0]]
            a = untried[0] if untried else prng.choice(sorted(emp_best(hist)))
        elif name == 'ucb1':
            untried = [x for x in ARMS if not s[x][0]]
            a = untried[0] if untried else max(ARMS, key=lambda x: s[x][1] / s[x][0] + math.sqrt(2 * math.log(t) / s[x][0]))
        rew = 1 if draws[t][ARMS.index(a)] < (P_GOOD if a == best else P_BAD) else 0
        hist.append((a, rew)); out.append({'a': a, 'r': rew})
    return best, out


# ---------------- C 猜规则 ----------------
RULES = {
    'color': ('红色按左、蓝色按右', lambda c: '左' if c['颜色'] == '红' else '右'),
    'thresh': ('数字大于等于 50 按右，否则按左', lambda c: '右' if c['数字'] >= 50 else '左'),
    'parity': ('单数按左、双数按右', lambda c: '左' if c['数字'] % 2 else '右'),
    'anti': ('箭头朝哪边就按相反的那边', lambda c: '右' if c['箭头'] == '朝左' else '左'),
}
C_LENS = [4, 8, 16, 32, 64]
Q_RULE = ('你在玩一个猜规则的卡牌游戏。每轮翻开一张牌，牌上有颜色、数字和箭头，你要按左键或右键。'
          '有一条隐藏规则决定按哪边才对，规则一直不变，但没人告诉你。state 里有之前各轮的记录（如果有的话）。'
          '看当前这张牌，选按哪个键才对。')
CRIT_RULE = {'左': '按左键', '右': '按右键'}


def card(rng):
    return {'颜色': rng.choice(['红', '蓝']), '数字': rng.randint(1, 99), '箭头': rng.choice(['朝左', '朝右'])}


def card_txt(c):
    return '%s色、数字 %d、箭头%s' % (c['颜色'], c['数字'], c['箭头'])


def rule_state(rule, hist, cur, fmt):
    st = {'current_card': card_txt(cur)}
    if fmt == 'none':
        st['history'] = '（还没有任何记录）'
    elif fmt == 'truth':
        st['hint'] = '规则是：' + RULES[rule][0] + '。'
    elif fmt == 'raw':
        st['history'] = '\n'.join('第 %d 轮：%s → 你按了%s → %s' % (i + 1, card_txt(c), a, '对' if ok else '错')
                                  for i, (c, a, ok) in enumerate(hist))
    elif fmt == 'summary':
        feats = {
            '颜色': lambda c: c['颜色'] + '色',
            '数字大小': lambda c: '≥50' if c['数字'] >= 50 else '<50',
            '数字单双': lambda c: '单数' if c['数字'] % 2 else '双数',
            '箭头': lambda c: '箭头' + c['箭头'],
        }
        tab = {}
        for fname, fn in feats.items():
            rows = {}
            for c, a, ok in hist:
                correct = a if ok else ('右' if a == '左' else '左')
                v = fn(c)
                rows.setdefault(v, {'按左才对': 0, '按右才对': 0})
                rows[v]['按%s才对' % correct] += 1
            tab[fname] = rows
        st['rounds_played'] = len(hist)
        st['stats_by_feature'] = tab
    return st


def jobs_C():
    jobs = []
    for rule in RULES:
        cells = [(f, n) for f in ('raw', 'summary') for n in C_LENS] + [('none', 0), ('truth', 0)]
        for fmt, n in cells:
            for t in range(TRIALS):
                rng = random.Random('C|%s|%d|%d' % (rule, n, t))
                hist = []
                for _ in range(n):
                    c = card(rng); a = rng.choice(['左', '右'])
                    hist.append((c, a, a == RULES[rule][1](c)))
                cur = card(rng)
                k = 'C|%s|%s|%d|%d' % (rule, fmt, n, t)
                meta = {'rule': rule, 'fmt': fmt, 'n': n, 't': t, 'answer': RULES[rule][1](cur),
                        'arrow': '左' if cur['箭头'] == '朝左' else '右'}
                jobs.append((k, rule_state(rule, hist, cur, fmt),
                             {'key': {'type': 'choice', 'instructions': Q_RULE, 'criteria': CRIT_RULE}}, meta))
    return jobs


# ---------------- 报告 ----------------
def pct(x, n):
    return '%d/%d' % (x, n)


def report():
    log = load()
    bad = [k for k, v in log.items() if ('resp' in v and '_error' in v['resp']) or v.get('error')]
    print('日志 %d 条，失败 %d 条' % (len(log), len(bad)))
    # A
    rows = {}
    for k, v in log.items():
        if not k.startswith('A|'):
            continue
        m, a = v['meta'], v['resp']['answers']['button']
        c = rows.setdefault((m['mode'], m['fmt'], m['n']), {'best': 0, 'emp': 0, 'freq': 0, 'pbest': [], 'N': 0, 'fav': 0})
        c['N'] += 1
        c['best'] += a['choice'] == m['best']
        c['emp'] += a['choice'] in m['emp']
        c['freq'] += a['choice'] in m['freq']
        c['fav'] += a['choice'] == m['bad_fav']
        c['pbest'].append(a['probabilities'][m['best']])
    for mode in ('uniform', 'mislead'):
        print('\n== A 老虎机，历史=%s（每格 %d 题；随机猜选中真最好约 25%%）==' % (mode, TRIALS))
        print('%-8s %5s | %-7s %-7s %-7s %-7s | P(真最好)均值' % ('写法', '长度', '真最好', '经验最好', '按得最多', '偏爱差钮'))
        for (md, f, n), c in sorted(rows.items(), key=lambda x: (['none', 'truth'] + FORMATS).index(x[0][1]) * 10000 + x[0][2]):
            if md != mode:
                continue
            print('%-8s %5d | %-7s %-7s %-7s %-7s | %.2f' % (f, n, pct(c['best'], c['N']), pct(c['emp'], c['N']),
                                                          pct(c['freq'], c['N']), pct(c['fav'], c['N']), statistics.mean(c['pbest'])))
    # B
    print('\n== B 在线闭环（%d 局 × %d 轮；每 10 轮一段，数字=该段选中真最好的比例 / 平均得分）==' % (ONLINE_RUNS, ONLINE_ROUNDS))
    def seg(runs):
        out = []
        for s in range(0, ONLINE_ROUNDS, 10):
            hits = [st['a'] == b for b, steps in runs for st in steps[s:s + 10]]
            rs = [st['r'] for b, steps in runs for st in steps[s:s + 10]]
            out.append('%.2f/%.2f' % (sum(hits) / len(hits), sum(rs) / len(rs)))
        return '  '.join(out)
    for fmt in ONLINE_FMTS:
        runs = [(v['best'], v['steps']) for k, v in log.items() if k.startswith('B|%s|' % fmt) and 'best' in v]
        if runs:
            print('Jev-%-10s (%d 局) %s' % (fmt, len(runs), seg(runs)))
            # 行为画像：得分后留下、没得分后换
            stay_w = [(p['a'] == q['a']) for b, steps in runs for p, q in zip(steps, steps[1:]) if p['r'] == 1 and not q.get('forced')]
            stay_l = [(p['a'] == q['a']) for b, steps in runs for p, q in zip(steps, steps[1:]) if p['r'] == 0 and not q.get('forced')]
            distinct = [len(set(s['a'] for s in steps)) for b, steps in runs]
            print('   得分后留在原按钮 %.2f（n=%d）；没得分后留下 %.2f（n=%d）；每局按过的不同按钮数中位 %s' % (
                statistics.mean(stay_w), len(stay_w), statistics.mean(stay_l), len(stay_l), statistics.median(distinct)))
    for name in ('random', 'greedy', 'ucb1'):
        runs = [sim_policy(name, r) for r in range(ONLINE_RUNS)]
        print('%-12s (%d 局) %s' % (name, len(runs), seg(runs)))
    # C
    rows = {}
    for k, v in log.items():
        if not k.startswith('C|'):
            continue
        m, a = v['meta'], v['resp']['answers']['key']
        c = rows.setdefault((m['rule'], m['fmt'], m['n']), [0, 0, 0])
        c[0] += a['choice'] == m['answer']; c[1] += 1; c[2] += a['choice'] == m['arrow']
    print('\n== C 猜规则：新牌答对（每格 %d 题，瞎猜 50%%）；括号里是"照箭头方向按"的比例 ==' % TRIALS)
    for rule in RULES:
        line = []
        for fmt, n in [('none', 0)] + [('raw', n) for n in C_LENS] + [('summary', n) for n in C_LENS] + [('truth', 0)]:
            c = rows.get((rule, fmt, n))
            if c:
                line.append('%s%s %d/%d(%d)' % (fmt, n or '', c[0], c[1], c[2]))
        print('%-7s ' % rule + ' | '.join(line))


def main():
    if len(sys.argv) < 2 or sys.argv[1] not in ('run', 'report'):
        print(__doc__); return
    if sys.argv[1] == 'report':
        report(); return
    parts = sys.argv[2:] or ['A', 'B', 'C']
    log = load()
    if 'A' in parts:
        run_jobs(log, jobs_A())
    if 'C' in parts:
        run_jobs(log, jobs_C())
    if 'B' in parts:
        import jevkit as jev
        runs = [(f, r) for f in ONLINE_FMTS for r in range(ONLINE_RUNS)]
        with ThreadPoolExecutor(max_workers=10) as ex:
            list(ex.map(lambda x: online_run(x[0], x[1], log), runs))
        save(log)
        print(jev.spend())
    report()


if __name__ == '__main__':
    main()
