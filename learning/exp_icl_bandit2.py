"""Jev 老虎机补测：把"利用（找出并锁定最好按钮）"和"探索"拆开看。

背景：exp_icl_bandit.py 的 B 部分已经测过"在线闭环里 Jev 自己按会不会越玩越好"，
但没有把"怎么问"（问句要不要点破长期目标）和"怎么选"（直接用回包 choice，还是按
probabilities 概率抽）分开看，也没有和标准 bandit 算法（UCB1、Thompson）比过。另外
旧脚本的 mislead 历史里，"偏爱差按钮"的实际概率因为写法疏忽是 70% 不是标注的 60%，
这里顺带修正。

ONLINE 在线部分（40 局 × 80 轮，串行按局跑，按局并行 ≤8 workers）
  最好按钮按局号均衡：第 i 局最好 = ARMS[i % 4]（不是随机抽，保证 40 局里各按钮
  各当 10 次最好）。每局的"每轮每钮中不中奖"提前抽好一份（只看局号，不看组），
  同一局四个组共用同一份奖励，保证组间可比。
  2 问法 × 2 动作 = 4 组，历史写法统一 raw（"第 k 轮：按了 X，得 N 分"），首轮无历史：
    问法 q_orig：沿用 exp_icl_bandit.py 的 Q_BANDIT 原句。
    问法 q_long：额外点破"一共 80 轮，现在第 t 轮（还剩 r 轮），目标是 80 轮总分最高，
                 前期没试过/试得少的按钮也该适当试试"，但不写成"必须每个都试"的指令。
    动作 argmax：下一步按回包里的 choice。
    动作 sample：按回包 probabilities（归一化后）用局内独立的种子抽。
  请求量 4 组 × 40 局 × 80 轮 = 12,800。
  本地基线（纯 Python 模拟，不请求 API，用同一套奖励生成规则）：
    random / always_A / greedy_init（每钮先各试一次，之后按经验均值最高，并列随机）/
    greedy_noinit（首轮固定按 A；此后没试过的按钮按"均值 0"算，不主动找它们试，
                   模拟"不探索的贪心"）/ ucb1 / thompson（Beta(1,1) 后验抽样）。
    跑两版：局号 0–39（和 Jev 四组同一份奖励，直接对照）、局号 0–1999（求稳定均值）。
  report 指标：每 20 轮一段的选中最好比例与平均得分；80 轮累计得分（均值±95% CI）；
    ONLINE 里的比例区间按局算（每局一个比例，40 局求均值±1.96·SD/√局数）：同一局
    连续轮次互相牵连，不能当独立试验算 Wilson，否则区间偏窄；另给同局号配对的
    累计得分差（均值与近似 95% 区间）；
    每局试过的不同按钮数；第 61–80 轮选中最好比例；第 1 轮选择分布；所选项的平均
    概率（仅 Jev 组，来自回包 probabilities[chosen]）；argmax 组里 choice 是否等于
    probabilities 最大项的比例（自检回包一致性）。

FIX 固定历史诊断（mislead 历史，长度 32/128，每格 50 题，最好按钮按题号均衡）
  历史生成：每轮 60% 按"偏爱的差按钮"，40% 从其余三个按钮（不含偏爱差钮）里均匀随机
    ——所以偏爱差钮的实际出现概率正好是 60%（旧脚本 gen_history 的 else 分支是从全部
    4 个按钮里随机，实际会把偏爱差钮的总概率抬到 70%，这里是本脚本要修正的点）。
  同一 (n, 题号) 的历史在四种写法、两种语言间共用一份，保证同格可比。
  写法（中文 4 种 + 英文 2 种，历史内容相同，只翻译文本）：
    raw_orig：raw 历史（每轮一行，含按了什么、得几分）+ 原问句。
    raw_avg：同上历史 + 问句里加一句"比较每个按钮的平均得分（得分次数÷按的次数），
             不要看按的次数或总分"。（仅中文）
    grouped：按按钮分组列原始得分序列（"A：1,0,0,1…"），不算任何统计量。（仅中文）
    summary：程序算好的按钮×（按了几次/总分/平均分）表。（仅中文）
    英文只重做 raw_orig、grouped 两种。
  请求量：中文 4 写法 × 2 长度 × 50 = 400；英文 2 写法 × 2 长度 × 50 = 200；合计 600。
  report 指标：选中真最好、选中历史里经验平均最高（并列算中）、选中偏爱差按钮的比例
    （各给 Wilson 95% 区间）。

公共约定：state/问句用到的随机数全部来自字符串种子的 random.Random，可复现；
  ThreadPoolExecutor ≤8 workers；日志写同目录 icl_bandit2_log.json（已被 .gitignore
  排除），每条日志包含完整回包（含 usage.cost），report 从日志汇总请求数与花费，不依赖
  运行期内存计数，所以单独跑 report 也能看到总花费。

用法：python3 exp_icl_bandit2.py smoke              —— 冒烟（1 局×少量轮 / 每格 1 题），只打印不留痕迹
      python3 exp_icl_bandit2.py run [ONLINE|FIX]   —— 断点续跑（ONLINE 以局为单位、FIX 以题为单位）
      python3 exp_icl_bandit2.py report              —— 只读日志出表
"""
# 让本脚本从任意目录都能找到仓库根部的 jevkit.py 和同目录的其他 exp_icl_*.py
import sys as _sys, pathlib as _pathlib
_sys.path[:0] = [str(_pathlib.Path(__file__).resolve().parent), str(_pathlib.Path(__file__).resolve().parent.parent)]
import json, math, os, random, statistics, sys, threading
from concurrent.futures import ThreadPoolExecutor

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import exp_icl_bandit as ob  # 复用 A/B 部分已有的 ARMS、bandit_state、stats、emp_best 等

HERE = os.path.dirname(os.path.abspath(__file__))
LOG = os.path.join(HERE, 'icl_bandit2_log.json')
LOCK = threading.Lock()

ARMS = ob.ARMS
P_GOOD, P_BAD = ob.P_GOOD, ob.P_BAD
CRIT_BANDIT = ob.CRIT_BANDIT           # {'A': '按按钮 A', ...}
CRIT_BANDIT_EN = {a: 'press button %s' % a for a in ARMS}
bandit_state = ob.bandit_state
stats = ob.stats
emp_best = ob.emp_best

Q_ORIG = ob.Q_BANDIT
Q_ORIG_EN = ('You are playing a game with 4 buttons (A, B, C, D). Each round you press one button, '
             'and may score 1 point or 0 points. Each button has a different, unknown probability of '
             'scoring. The state has the record of previous rounds, if any. Choose which button to '
             'press next, aiming to score as many points as possible.')
Q_AVG = Q_ORIG + '比较每个按钮的平均得分（得分次数 ÷ 按的次数），不要看按的次数或总分。'
Q_LONG_TMPL = (
    '你在玩一个有 4 个按钮（A、B、C、D）的游戏。每轮按一个按钮，可能得 1 分，也可能得 0 分。'
    '每个按钮得分的概率不一样，但没人告诉你哪个高。state 里有之前各轮的记录（如果有的话）。'
    '一共要玩 80 轮，现在是第 %d 轮（还剩 %d 轮）。目标是让这 80 轮的总得分最高。'
    '没试过或试得少的按钮也可能更好，前期适当尝试、摸清各按钮再集中按最好的，通常总分更高。'
    '选下一轮按哪个按钮。')


def load():
    if os.path.exists(LOG):
        return json.load(open(LOG))
    return {}


def save(log):
    tmp = LOG + '.tmp'
    json.dump(log, open(tmp, 'w'), ensure_ascii=False)
    os.replace(tmp, LOG)


def wilson(x, n, z=1.96):
    if n == 0:
        return (0.0, 0.0)
    phat = x / n
    denom = 1 + z * z / n
    center = phat + z * z / (2 * n)
    margin = z * math.sqrt(phat * (1 - phat) / n + z * z / (4 * n * n))
    return (max(0.0, (center - margin) / denom), min(1.0, (center + margin) / denom))


def fmt_pct(x, n):
    if n == 0:
        return 'n=0'
    lo, hi = wilson(x, n)
    return '%d/%d=%.0f%%[%.0f-%.0f]' % (x, n, 100 * x / n, 100 * lo, 100 * hi)


def fmt_run_pct(per_run):
    """per_run：每局 (命中数, 轮数)。总比例照常算，区间按局：每局一个比例，均值±1.96·SD/√局数。"""
    per_run = [(h, n) for h, n in per_run if n]
    x = sum(h for h, _ in per_run)
    n = sum(n for _, n in per_run)
    if n == 0:
        return 'n=0'
    m, ci = mean_ci([h / k for h, k in per_run])
    return '%d/%d=%.0f%%[按局%.0f-%.0f]' % (x, n, 100 * x / n, 100 * max(0.0, m - ci), 100 * min(1.0, m + ci))


def mean_ci(xs):
    n = len(xs)
    if n == 0:
        return (0.0, 0.0)
    m = statistics.mean(xs)
    if n < 2:
        return (m, 0.0)
    return (m, 1.96 * statistics.stdev(xs) / math.sqrt(n))


# ==================== ONLINE 在线部分 ====================
ONLINE_ROUNDS = 80     # 每局轮数，也是 q_long 文本里"一共 80 轮"的固定总数
ONLINE_RUNS = 40
ON_GROUPS = [('orig', 'argmax'), ('orig', 'sample'), ('long', 'argmax'), ('long', 'sample')]
SEG = 20


def online_best(run):
    return ARMS[run % 4]


def online_draws(run):
    rng = random.Random('ON|%d' % run)
    return [[rng.random() for _ in ARMS] for _ in range(ONLINE_ROUNDS)]


def sample_choice(probs, rng):
    items = [(a, max(0.0, probs.get(a, 0.0))) for a in ARMS]
    tot = sum(v for _, v in items)
    if tot <= 0:
        return rng.choice(ARMS)
    r = rng.random() * tot
    acc = 0.0
    for a, v in items:
        acc += v
        if r <= acc:
            return a
    return items[-1][0]


def online_question(qfmt, rnd):
    if qfmt == 'orig':
        return Q_ORIG
    return Q_LONG_TMPL % (rnd, ONLINE_ROUNDS - rnd)


def online_game(qfmt, action, run, log, n_rounds=None, verbose=False, persist=True):
    """跑一整局（串行 n_rounds 轮），跑完/出错都整局写回 log（可选立即落盘）。"""
    import jevkit as jev
    n_rounds = n_rounds or ONLINE_ROUNDS
    key = 'ON|%s|%s|%d' % (qfmt, action, run)
    if persist and key in log and not log[key].get('error'):
        return
    best = online_best(run)
    draws = online_draws(run)
    prng = random.Random('ONsamp|%s|%s|%d' % (qfmt, action, run))
    hist, steps = [], []
    for t in range(n_rounds):
        rnd = t + 1
        instr = online_question(qfmt, rnd)
        st = bandit_state(hist, 'raw' if hist else 'none', best)
        q = {'button': {'type': 'choice', 'instructions': instr, 'criteria': CRIT_BANDIT}}
        if verbose:
            print('---- %s round %d request ----' % (key, rnd))
            print(json.dumps({'state': st, 'questions': q}, ensure_ascii=False, indent=2))
        r = jev.call(st, q)
        if verbose:
            print('---- response ----')
            print(json.dumps(r, ensure_ascii=False, indent=2)[:2000])
        if '_error' in r:
            steps.append({'t': rnd, 'error': r['_error']})
            if persist:
                with LOCK:
                    log[key] = {'error': True, 'steps': steps, 'qfmt': qfmt, 'action': action, 'run': run, 'best': best}
                    save(log)
            return
        ans = r['answers']['button']
        if action == 'argmax':
            a = ans['choice']
        else:
            a = sample_choice(ans['probabilities'], prng)
            if verbose:
                print('sample -> probabilities=%s chosen=%s (model choice=%s)' % (ans['probabilities'], a, ans['choice']))
        rew = 1 if draws[t][ARMS.index(a)] < (P_GOOD if a == best else P_BAD) else 0
        hist.append((a, rew))
        steps.append({'t': rnd, 'a': a, 'r': rew, 'resp': r})
    with LOCK:
        log[key] = {'best': best, 'steps': steps, 'qfmt': qfmt, 'action': action, 'run': run}
        if persist:
            save(log)


def run_online(log, workers=8):
    import jevkit as jev
    games = [(qfmt, action, run) for qfmt, action in ON_GROUPS for run in range(ONLINE_RUNS)]
    todo = [g for g in games if not (('ON|%s|%s|%d' % g) in log and not log['ON|%s|%s|%d' % g].get('error'))]
    print('ONLINE：共 %d 局，待跑 %d' % (len(games), len(todo)))
    with ThreadPoolExecutor(max_workers=workers) as ex:
        list(ex.map(lambda g: online_game(g[0], g[1], g[2], log), todo))
    print(jev.spend())


# ---- 本地基线（不请求 API） ----
BASELINE_POLICIES = ['random', 'always_A', 'greedy_init', 'greedy_noinit', 'ucb1', 'thompson']


def sim_policy(name, run, rounds=None):
    rounds = rounds or ONLINE_ROUNDS
    best = online_best(run)
    draws = online_draws(run)
    prng = random.Random('SIM|%s|%d' % (name, run))
    hist, out = [], []
    for t in range(rounds):
        s = stats(hist)
        if name == 'random':
            a = prng.choice(ARMS)
        elif name == 'always_A':
            a = 'A'
        elif name == 'greedy_init':
            untried = [x for x in ARMS if not s[x][0]]
            a = untried[0] if untried else prng.choice(sorted(emp_best(hist)))
        elif name == 'greedy_noinit':
            if t == 0:
                a = 'A'
            else:
                means = {x: (s[x][1] / s[x][0] if s[x][0] else 0.0) for x in ARMS}
                mx = max(means.values())
                a = prng.choice(sorted(x for x in ARMS if means[x] == mx))
        elif name == 'ucb1':
            untried = [x for x in ARMS if not s[x][0]]
            a = untried[0] if untried else max(ARMS, key=lambda x: s[x][1] / s[x][0] + math.sqrt(2 * math.log(t) / s[x][0]))
        elif name == 'thompson':
            samples = {x: prng.betavariate(1 + s[x][1], 1 + (s[x][0] - s[x][1])) for x in ARMS}
            a = max(samples, key=samples.get)
        else:
            raise ValueError(name)
        rew = 1 if draws[t][ARMS.index(a)] < (P_GOOD if a == best else P_BAD) else 0
        hist.append((a, rew)); out.append({'t': t + 1, 'a': a, 'r': rew})
    return best, out


# ==================== FIX 固定历史诊断 ====================
FIX_LENS = [32, 128]
FIX_TRIALS = 50
FIX_ZH_FMTS = ['raw_orig', 'raw_avg', 'grouped', 'summary']
FIX_EN_FMTS = ['raw_orig', 'grouped']


def gen_mislead(rng, best, n):
    """偏爱差钮 60% 精确概率：60% 按偏爱差钮，40% 从其余三钮（不含偏爱差钮）均匀抽。"""
    bad_fav = rng.choice([a for a in ARMS if a != best])
    others = [a for a in ARMS if a != bad_fav]
    hist = []
    for _ in range(n):
        a = bad_fav if rng.random() < 0.6 else rng.choice(others)
        p = P_GOOD if a == best else P_BAD
        hist.append((a, 1 if rng.random() < p else 0))
    return hist, bad_fav


def grouped_state(hist, lang):
    by = {a: [] for a in ARMS}
    for a, r in hist:
        by[a].append(r)
    if lang == 'zh':
        return {'task': '按按钮得分',
                'history_by_button': {a: (','.join(str(x) for x in by[a]) if by[a] else '（没按过）') for a in ARMS}}
    return {'task': 'press a button to score',
            'history_by_button': {a: (','.join(str(x) for x in by[a]) if by[a] else '(never pressed)') for a in ARMS}}


def raw_state_en(hist):
    if not hist:
        return {'task': 'press a button to score', 'history': '(no records yet)'}
    return {'task': 'press a button to score',
            'history': '\n'.join('Round %d: pressed %s, scored %d point(s).' % (i + 1, a, r) for i, (a, r) in enumerate(hist))}


def fix_state_and_q(lang, fmt, hist, best):
    if lang == 'zh':
        if fmt == 'raw_orig':
            return bandit_state(hist, 'raw', best), Q_ORIG
        if fmt == 'raw_avg':
            return bandit_state(hist, 'raw', best), Q_AVG
        if fmt == 'grouped':
            return grouped_state(hist, 'zh'), Q_ORIG
        if fmt == 'summary':
            return bandit_state(hist, 'summary', best), Q_ORIG
    else:
        if fmt == 'raw_orig':
            return raw_state_en(hist), Q_ORIG_EN
        if fmt == 'grouped':
            return grouped_state(hist, 'en'), Q_ORIG_EN
    raise ValueError((lang, fmt))


def jobs_fix(trials=FIX_TRIALS):
    jobs = []
    for lang, fmts in (('zh', FIX_ZH_FMTS), ('en', FIX_EN_FMTS)):
        for fmt in fmts:
            for n in FIX_LENS:
                for t in range(trials):
                    rng = random.Random('FIX|%d|%d' % (n, t))   # 同一 (n,t) 各写法/语言共用同一份历史
                    best = ARMS[t % 4]
                    hist, bad_fav = gen_mislead(rng, best, n)
                    st, instr = fix_state_and_q(lang, fmt, hist, best)
                    crit = CRIT_BANDIT if lang == 'zh' else CRIT_BANDIT_EN
                    meta = {'lang': lang, 'fmt': fmt, 'n': n, 't': t, 'best': best,
                            'emp': sorted(emp_best(hist)), 'bad_fav': bad_fav}
                    k = 'FIX|%s|%s|%d|%d' % (lang, fmt, n, t)
                    jobs.append((k, st, {'button': {'type': 'choice', 'instructions': instr, 'criteria': crit}}, meta))
    return jobs


def run_jobs(log, jobs, workers=8, flush_every=100):
    import jevkit as jev
    todo = [j for j in jobs if j[0] not in log or '_error' in log[j[0]]['resp']]
    print('FIX：共 %d 题，待发 %d' % (len(jobs), len(todo)))
    done = [0]

    def one(j):
        k, st, q, meta = j
        r = jev.call(st, q)
        with LOCK:
            log[k] = {'meta': meta, 'resp': r}
            done[0] += 1
            if done[0] % flush_every == 0:
                save(log)
    with ThreadPoolExecutor(max_workers=workers) as ex:
        list(ex.map(one, todo))
    save(log)
    print(jev.spend())


# ==================== 报告 ====================
def log_spend(log):
    calls = fail = 0
    cost = 0.0
    for k, v in log.items():
        if k.startswith('FIX|'):
            r = v.get('resp', {})
            if '_error' in r:
                fail += 1
            else:
                calls += 1
                cost += r.get('usage', {}).get('cost', 0.0)
        elif k.startswith('ON|'):
            for st in v.get('steps', []):
                if 'error' in st:
                    fail += 1
                elif 'resp' in st:
                    calls += 1
                    cost += st['resp'].get('usage', {}).get('cost', 0.0)
    return calls, cost, fail


def seg_report(runs, rounds=ONLINE_ROUNDS, seg=SEG):
    out = []
    for s in range(0, rounds, seg):
        per_run = [[(st['a'] == b, st['r']) for st in steps[s:s + seg] if 'a' in st] for b, steps in runs]
        pts = [p for pr in per_run for p in pr]
        n = len(pts)
        rs = sum(r for _, r in pts)
        out.append('%s(%.2f)' % (fmt_run_pct([(sum(1 for h, _ in pr if h), len(pr)) for pr in per_run]),
                                 rs / n if n else 0))
    return '  '.join(out)


def cum_by_run(log, qfmt, action):
    out = {}
    for run in range(ONLINE_RUNS):
        v = log.get('ON|%s|%s|%d' % (qfmt, action, run))
        if v and not v.get('error'):
            out[run] = sum(st['r'] for st in v['steps'] if 'a' in st)
    return out


def paired_report(log):
    """同局号（同一份奖励、同一个最好按钮）配对的累计得分差：均值 ± 1.96·SD/√局数。"""
    print('\n-- 同局号配对的 80 轮累计得分差（前者减后者；近似 95% 区间）--')
    base = {name: {r: sum(st['r'] for st in sim_policy(name, r)[1]) for r in range(ONLINE_RUNS)}
            for name in ('thompson', 'greedy_init', 'random')}
    groups = {'%s-%s' % g: cum_by_run(log, *g) for g in ON_GROUPS}
    pairs = [('orig-sample', 'orig-argmax'), ('long-sample', 'long-argmax'),
             ('long-argmax', 'orig-argmax'), ('long-sample', 'orig-sample'),
             ('orig-sample', 'thompson'), ('long-sample', 'thompson'),
             ('long-sample', 'greedy_init'), ('orig-argmax', 'random')]
    for a, b in pairs:
        xa = groups.get(a) or base.get(a)
        xb = groups.get(b) or base.get(b)
        runs = sorted(set(xa) & set(xb)) if xa and xb else []
        if not runs:
            print('%-12s - %-12s 无数据' % (a, b)); continue
        d = [xa[r] - xb[r] for r in runs]
        m, ci = mean_ci(d)
        print('%-12s - %-12s (%d 局) 差=%+.2f [%.2f, %.2f]' % (a, b, len(runs), m, m - ci, m + ci))


def online_report(log):
    print('\n== ONLINE 在线部分（%d 局 × %d 轮；每 %d 轮一段 = 选中最好[按局区间](平均得分)）==' % (ONLINE_RUNS, ONLINE_ROUNDS, SEG))
    for qfmt, action in ON_GROUPS:
        runs = []
        for run in range(ONLINE_RUNS):
            v = log.get('ON|%s|%s|%d' % (qfmt, action, run))
            if v and not v.get('error'):
                runs.append((v['best'], v['steps']))
        label = 'Jev-%s-%s' % (qfmt, action)
        if not runs:
            print('%-16s 无数据' % label); continue
        print('%-16s (%d 局) %s' % (label, len(runs), seg_report(runs)))
        cum = [sum(st['r'] for st in steps if 'a' in st) for b, steps in runs]
        m, ci = mean_ci(cum)
        distinct = [len(set(st['a'] for st in steps if 'a' in st)) for b, steps in runs]
        last20 = [(sum(1 for st in steps[60:80] if 'a' in st and st['a'] == b),
                   sum(1 for st in steps[60:80] if 'a' in st)) for b, steps in runs]
        r1 = {}
        for b, steps in runs:
            if steps and 'a' in steps[0]:
                r1[steps[0]['a']] = r1.get(steps[0]['a'], 0) + 1
        probs = [st['resp']['answers']['button']['probabilities'].get(st['a'], 0.0) for b, steps in runs for st in steps if 'resp' in st]
        pm, pci = mean_ci(probs)
        print('   累计得分(80轮) 均值=%.2f±%.2f | 不同按钮数 均值=%.2f 中位=%s | 第61-80轮选中最好 %s' % (
            m, ci, statistics.mean(distinct), statistics.median(distinct), fmt_run_pct(last20)))
        print('   第1轮选择分布=%s | 所选项平均概率=%.3f±%.3f' % (
            {a: r1.get(a, 0) for a in ARMS}, pm, pci))
        if action == 'argmax':
            cons = [(st['resp']['answers']['button']['choice'] ==
                     max(st['resp']['answers']['button']['probabilities'], key=st['resp']['answers']['button']['probabilities'].get))
                    for b, steps in runs for st in steps if 'resp' in st]
            print('   argmax 组 choice==概率最大项 的比例 %s' % fmt_pct(sum(cons), len(cons)))

    paired_report(log)

    print('\n-- 本地基线：局号 0-39（与 Jev 四组同一份奖励，直接对照） --')
    for name in BASELINE_POLICIES:
        runs = [sim_policy(name, r) for r in range(ONLINE_RUNS)]
        cum = [sum(st['r'] for st in steps) for b, steps in runs]
        m, ci = mean_ci(cum)
        distinct = [len(set(st['a'] for st in steps)) for b, steps in runs]
        last20 = [(sum(1 for st in steps[60:80] if st['a'] == b), len(steps[60:80])) for b, steps in runs]
        print('%-16s (%d 局) %s' % (name, len(runs), seg_report(runs)))
        print('   累计得分 均值=%.2f±%.2f | 不同按钮数 均值=%.2f 中位=%s | 第61-80轮选中最好 %s' % (
            m, ci, statistics.mean(distinct), statistics.median(distinct), fmt_run_pct(last20)))

    print('\n-- 本地基线：局号 0-1999（求稳定均值，仅给累计得分与后段命中率）--')
    STABLE_RUNS = 2000
    for name in BASELINE_POLICIES:
        runs = [sim_policy(name, r) for r in range(STABLE_RUNS)]
        cum = [sum(st['r'] for st in steps) for b, steps in runs]
        m, ci = mean_ci(cum)
        last20 = [(sum(1 for st in steps[60:80] if st['a'] == b), len(steps[60:80])) for b, steps in runs]
        print('%-16s (%d 局) 累计得分 均值=%.2f±%.2f | 第61-80轮选中最好 %s' % (
            name, len(runs), m, ci, fmt_run_pct(last20)))


def fix_report(log):
    rows = {}
    for k, v in log.items():
        if not k.startswith('FIX|'):
            continue
        if '_error' in v.get('resp', {}):
            continue
        m, a = v['meta'], v['resp']['answers']['button']
        key = (m['lang'], m['fmt'], m['n'])
        c = rows.setdefault(key, {'best': 0, 'emp': 0, 'fav': 0, 'N': 0})
        c['N'] += 1
        c['best'] += a['choice'] == m['best']
        c['emp'] += a['choice'] in m['emp']
        c['fav'] += a['choice'] == m['bad_fav']
    print('\n== FIX 固定历史诊断（mislead，偏爱差钮实际 60%%；每格 %d 题）==' % FIX_TRIALS)
    print('%-4s %-9s %5s | %-16s %-16s %-16s' % ('语言', '写法', '长度', '选中真最好', '选中经验最高', '选中偏爱差钮'))
    order = [('zh', f) for f in FIX_ZH_FMTS] + [('en', f) for f in FIX_EN_FMTS]
    for lang, fmt in order:
        for n in FIX_LENS:
            c = rows.get((lang, fmt, n))
            if not c:
                continue
            print('%-4s %-9s %5d | %-16s %-16s %-16s' % (
                lang, fmt, n, fmt_pct(c['best'], c['N']), fmt_pct(c['emp'], c['N']), fmt_pct(c['fav'], c['N'])))


def report():
    log = load()
    calls, cost, fail = log_spend(log)
    print('日志 %d 条 key | 请求数(从日志汇总) %d | 花费 $%.6f | 失败请求数 %d' % (len(log), calls, cost, fail))
    on_err = [k for k, v in log.items() if k.startswith('ON|') and v.get('error')]
    fix_err = [k for k, v in log.items() if k.startswith('FIX|') and '_error' in v.get('resp', {})]
    if on_err or fix_err:
        print('未完成/失败的 key：ONLINE %d 个，FIX %d 个' % (len(on_err), len(fix_err)))
    online_report(log)
    fix_report(log)


# ==================== 冒烟（不落盘到正式日志） ====================
def smoke():
    print('===== 冒烟：ONLINE，1 局 × 6 轮，4 组都跑 =====')
    for qfmt, action in ON_GROUPS:
        tmp = {}
        online_game(qfmt, action, run=0, log=tmp, n_rounds=6, verbose=True, persist=False)
        v = tmp['ON|%s|%s|0' % (qfmt, action)]
        print('== %s-%s 结果 steps=%s' % (qfmt, action, [(s.get('t'), s.get('a'), s.get('r')) for s in v['steps']]))

    print('\n===== 冒烟：FIX，每格 1 题 =====')
    jobs = jobs_fix(trials=1)
    import jevkit as jev
    for k, st, q, meta in jobs:
        print('---- %s request ----' % k)
        print(json.dumps({'state': st, 'questions': q}, ensure_ascii=False, indent=2))
        r = jev.call(st, q)
        print('resp choice=%s probabilities=%s meta=%s' % (
            r.get('answers', {}).get('button', {}).get('choice'),
            r.get('answers', {}).get('button', {}).get('probabilities'), meta))
    print('\n' + jev.spend())


def main():
    if len(sys.argv) < 2 or sys.argv[1] not in ('run', 'report', 'smoke'):
        print(__doc__); return
    if sys.argv[1] == 'smoke':
        smoke(); return
    if sys.argv[1] == 'report':
        report(); return
    parts = sys.argv[2:] or ['ONLINE', 'FIX']
    log = load()
    if 'FIX' in parts:
        run_jobs(log, jobs_fix())
    if 'ONLINE' in parts:
        run_online(log)
    report()


if __name__ == '__main__':
    main()
