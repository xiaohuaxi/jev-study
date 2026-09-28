"""Jev 老虎机第四轮（补测，2026-09-27）：换奖励种子检验第三轮 8 钮"抽样胜过 ε 随机"站不站得住、功劳在哪，并复测探索提示。

为什么补：
1. bandit3 的 8 钮里，"按 Jev 给的概率抽"比同样多的 ε=5% 随机多 5.55 分（区间 0.43–10.67）。但抽样的试探
   有两个特点叠在一起：(A) 跟着局面走——首选按错时 Jev 的概率更分散，离开首选更多；(B) 集中在前期——
   约一半偏离落在前 20 轮，而 ε 随机均匀摊在 80 轮里。现有对照组里没有一组"同样的时间表、但跟局面无关"
   的随机，分不清 5.55 分里 A、B 各占多少。这里补一组"按时间表随机"：
     均摊 − 时间表 = 时间表与偏离去向都相同时，状态信号本身值多少（A）；
     时间表 − ε 随机 = 光靠试探集中在前期值多少（B）。
   （实测结果：新种子上抽样 − ε 只有 +1.8，区间跨 0，第三轮的 5.55 分没复现；时间表随机和 ε 一样，
    前期多试一分没多拿；均摊 − 时间表 +3.0，区间擦着 0，而且均摊组每局多偏离约 1.7 次，两组试探量
    不一样多，不能全算成局面信号。见 learning/README.md 第一节第四轮。）
2. "只加探索提示，4 钮取最高项后 20 轮 62% → 78%"只是 40 局里多锁对 6 局（8 对 2，McNemar p≈0.11），同一句
   提示配上总轮数（长期目标 + 探索提示）只有 65%。Jev 对同一输入几乎确定，取最高项组每局的走向基本由奖励
   种子和问句决定，同一批种子重跑没有意义，必须换奖励种子复测。

两组实验都用新奖励种子：局号 40–239（200 局），与 bandit2/bandit3 的局号 0–39 不重叠，奖励随机数也换了
种子前缀（'B4|A|局号'、'B4|B|局号'）。最好按钮按局号均衡：第 i 局最好 = 按钮表[i % 臂数]（8 钮各当 25 次，
4 钮各当 50 次）。同一实验内各组共用同一局号的同一份奖励，可逐局配对。

A  8 钮 A–H，最好 0.75 / 其余 0.25，80 轮 × 200 局，原问法（与 bandit3 H8 逐字一致），五组：
   argmax  取回包 choice
   sample  按回包 probabilities（归一化）抽
   eps05   每轮以 5% 概率改成 8 个按钮里均匀随机按一个（可能正好抽到首选），否则取 choice
   flat    均摊：以首选的归一化概率按首选，否则在其余 7 个按钮里均匀挑（与 bandit3 flat 同一写法）
   sched   按时间表随机：取回包 choice，但每轮以一个事先固定、只随轮次变的概率离开首选，离开时在其余
           7 个按钮里均匀挑。概率表照 bandit3 8 钮均摊组实测的每 10 轮偏离率定：
           1–10 轮 10.0%，11–20 轮 8.25%，21–30 轮 3.25%，31–40 轮 2.5%，41–50 轮 1.5%，51–60 轮 2.0%，
           61–70 轮 2.5%，71–80 轮 2.75%（每局期望约 3.3 次）。随机数用只与局号绑定的独立种子 'B4sched|局号'。
B  4 钮 A–D，最好 0.75 / 其余 0.25，80 轮 × 200 局，全部取回包 choice，三组问法：
   orig    原问法（= bandit2 Q_ORIG = bandit3 question(4,'orig')）
   hint    只加探索提示（= bandit3 question(4,'hint')，HINT 写法）
   long    长期目标 + 探索提示（= bandit2 Q_LONG_TMPL，每轮填当前轮数与剩余轮数）
state 写法统一 raw（"第 k 轮：按了 X，得 N 分"，首轮"（还没有任何记录）"），用 bandit3.raw_state，
与 bandit2 的 bandit_state(...,'raw'/'none') 逐字一致。

请求量：A 5×200×80 = 80,000；B 3×200×80 = 48,000；合计 128,000（跑满 200 局时）。
报告里的数字只用局号 40–199（每组 160 局，即 run A / run B 加 --max-run 200），合计 102,400。
本地基线（不请求 API，同一份奖励）：thompson、greedy_init（先每钮试一次再按均值最高），复用 bandit3.sim。

用法：python3 -B exp_icl_bandit4.py smoke [轮数]        —— 每组 1 局少量轮次，不落盘；核对问句与 state 逐字一致
      python3 -B exp_icl_bandit4.py run [A|B] [--workers N] [--max-run 120] [--until 03:40]
                                                           —— 断点续跑（以局为单位），每局跑完即落盘；先跑 B 三组与 A 的
                                                              时间表/ε/均摊，A 的抽样/取最高项放后；同档内按局号从小到大；
                                                              --max-run 只跑局号 < N，--until 到点不再开新局
      python3 -B exp_icl_bandit4.py report                 —— 只读日志出表
日志写同目录 icl_bandit4_log.json（*_log.json 被 .gitignore 排除）。
"""
# 让本脚本从任意目录都能找到仓库根部的 jevkit.py 和同目录的其他 exp_icl_*.py
import sys as _sys, pathlib as _pathlib
_sys.path[:0] = [str(_pathlib.Path(__file__).resolve().parent), str(_pathlib.Path(__file__).resolve().parent.parent)]
import json, math, os, random, statistics, sys, threading
from concurrent.futures import ThreadPoolExecutor

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import exp_icl_bandit as ob
import exp_icl_bandit2 as b2
import exp_icl_bandit3 as b3

HERE = os.path.dirname(os.path.abspath(__file__))
LOG = os.path.join(HERE, 'icl_bandit4_log.json')
LOCK = threading.Lock()

RUN_IDS = list(range(40, 240))
ROUNDS = 80
PG, PB = 0.75, 0.25
EPS = b3.EPS
TAIL = 20
# 第 1–10、11–20、…、71–80 轮离开首选的概率
SCHED = [0.10, 0.0825, 0.0325, 0.025, 0.015, 0.02, 0.025, 0.0275]

EXPS = {
    # 名: (臂数, 分组 [(问法, 动作)], bandit3 里同参数的设置名——供 sim 复用)
    'A': (8, [('orig', 'argmax'), ('orig', 'sample'), ('orig', 'eps05'), ('orig', 'flat'), ('orig', 'sched')], 'H8'),
    'B': (4, [('orig', 'argmax'), ('hint', 'argmax'), ('long', 'argmax')], 'SPLIT'),
}
for _k, _g, _s in EXPS.values():
    assert b3.SETTINGS[_s][:4] == (_k, PG, PB, ROUNDS)


def names_of(exp):
    return b3.arms(EXPS[exp][0])


def best_of(exp, run):
    n = names_of(exp)
    return n[run % len(n)]


def draws_of(exp, run):
    k = EXPS[exp][0]
    rng = random.Random('B4|%s|%d' % (exp, run))
    return [[rng.random() for _ in range(k)] for _ in range(ROUNDS)]


def question(exp, qfmt, rnd):
    k = EXPS[exp][0]
    if qfmt == 'long':
        assert k == 4
        return b2.online_question('long', rnd)
    return b3.question(k, qfmt, rnd, ROUNDS)


def key_of(exp, qfmt, action, run):
    return '%s|%s|%s|%d' % (exp, qfmt, action, run)


def load():
    return json.load(open(LOG)) if os.path.exists(LOG) else {}


def save(log):
    tmp = LOG + '.tmp'
    with open(tmp, 'w') as f:
        json.dump(log, f, ensure_ascii=False)
    os.replace(tmp, LOG)


def pick(action, ans, names, prng, srng, rnd):
    top = ans['choice']
    if action == 'argmax':
        return top
    if action == 'sample':
        return b3.sample_choice(ans['probabilities'], names, prng)
    if action == 'eps05':
        return prng.choice(names) if prng.random() < EPS else top
    if action == 'flat':
        pt = max(0.0, min(1.0, ans['probabilities'].get(top, 0.0) / (sum(max(0.0, v) for v in ans['probabilities'].values()) or 1.0)))
        return top if prng.random() < pt else prng.choice([x for x in names if x != top])
    if action == 'sched':
        # 每轮固定抽两次随机数，保证时间表随机的走向只由局号和轮次决定
        u, v = srng.random(), srng.random()
        if u < SCHED[(rnd - 1) // 10]:
            others = [x for x in names if x != top]
            return others[int(v * len(others))]
        return top
    raise ValueError(action)


def game(exp, qfmt, action, run, log, n_rounds=ROUNDS, persist=True, verbose=False):
    import jevkit as jev
    names = names_of(exp)
    key = key_of(exp, qfmt, action, run)
    if persist and key in log and not log[key].get('error'):
        return
    best = best_of(exp, run)
    draws = draws_of(exp, run)
    prng = random.Random('B4samp|%s|%s|%s|%d' % (exp, qfmt, action, run))
    srng = random.Random('B4sched|%d' % run)
    crit = {a: '按按钮 ' + a for a in names}
    hist, steps = [], []
    for t in range(n_rounds):
        rnd = t + 1
        st = b3.raw_state(hist)
        q = {'button': {'type': 'choice', 'instructions': question(exp, qfmt, rnd), 'criteria': crit}}
        if verbose and rnd <= 2:
            print('---- %s 第 %d 轮请求 ----' % (key, rnd))
            print(json.dumps({'state': st, 'questions': q}, ensure_ascii=False, indent=1))
        r = jev.call(st, q)
        if '_error' in r:
            if persist:
                with LOCK:
                    log[key] = {'error': r['_error'], 'steps': steps}
                    save(log)
            else:
                print('ERROR', key, r['_error'])
            return
        ans = r['answers']['button']
        a = pick(action, ans, names, prng, srng, rnd)
        rew = 1 if draws[t][names.index(a)] < (PG if a == best else PB) else 0
        hist.append((a, rew))
        steps.append({'t': rnd, 'a': a, 'r': rew, 'choice': ans['choice'], 'p': ans['probabilities'],
                      'cost': r.get('usage', {}).get('cost', 0.0), 'model': r.get('model')})
    if persist:
        with LOCK:
            log[key] = {'best': best, 'steps': steps}
            save(log)
    else:
        print('%s best=%s  %s' % (key, best, ' '.join('%s%s%d' % (s['choice'], s['a'] if s['a'] != s['choice'] else '', s['r']) for s in steps)))
        print('   cost=%.6f model=%s p1=%s' % (sum(s['cost'] for s in steps), steps[0]['model'], steps[0]['p']))


def check_texts():
    """问句与 state 与旧脚本逐字一致的自检。"""
    for rnd in (1, 5, 80):
        assert question('A', 'orig', rnd) == b3.question(8, 'orig', rnd, 80)
        assert question('B', 'orig', rnd) == b2.Q_ORIG == ob.Q_BANDIT
        assert question('B', 'hint', rnd) == b3.base_q(4) + b3.HINT + '选下一轮按哪个按钮，目标是尽量多得分。'
        assert question('B', 'long', rnd) == b2.Q_LONG_TMPL % (rnd, 80 - rnd)
        assert b3.HINT in question('B', 'long', rnd)
    h = [('A', 1), ('C', 0), ('B', 1)]
    assert b3.raw_state(h) == ob.bandit_state(h, 'raw', 'A')
    assert b3.raw_state([]) == ob.bandit_state([], 'none', 'A')
    print('问句与 state 自检通过。A 原问法：%s' % question('A', 'orig', 1))
    print('B hint：%s' % question('B', 'hint', 1))
    print('B long 第 5 轮：%s' % question('B', 'long', 5))


def smoke(n_rounds=6):
    import jevkit as jev
    check_texts()
    for exp, (k, groups, _) in EXPS.items():
        for qfmt, action in groups:
            game(exp, qfmt, action, RUN_IDS[0], {}, n_rounds=n_rounds, persist=False,
                 verbose=(action in ('argmax',) and qfmt in ('orig', 'long')))
    print(jev.spend())


# 先跑的一档：B 三组，A 的时间表、ε、均摊；A 的按概率抽、取最高项放后。同档内按局号从小到大，
# 保证中途停下时每组完成的都是从 40 起的连续局号，可配对。
FIRST = {('B', 'orig', 'argmax'), ('B', 'hint', 'argmax'), ('B', 'long', 'argmax'),
         ('A', 'orig', 'sched'), ('A', 'orig', 'eps05'), ('A', 'orig', 'flat')}


def run(which, workers=8, max_run=None, until=None):
    """max_run：只跑局号 < max_run；until：'HH:MM'，到点后不再开新局（已开的跑完）。"""
    import datetime, jevkit as jev
    check_texts()
    log = load()
    ids = [i for i in RUN_IDS if max_run is None or i < max_run]
    jobs = [(e, q, a, i) for e in which for q, a in EXPS[e][1] for i in ids]
    jobs.sort(key=lambda j: ((j[0], j[1], j[2]) not in FIRST, j[3]))
    todo = [j for j in jobs if not (key_of(*j) in log and not log[key_of(*j)].get('error'))]
    stop_at = None
    if until:
        hh, mm = map(int, until.split(':'))
        now = datetime.datetime.now()
        stop_at = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
        if stop_at <= now:
            stop_at += datetime.timedelta(days=1)
    print('共 %d 局，待跑 %d，并发 %d，截止 %s' % (len(jobs), len(todo), workers, stop_at), flush=True)
    done = [0]

    def one(j):
        if stop_at and datetime.datetime.now() >= stop_at:
            return
        game(*j, log)
        with LOCK:
            done[0] += 1
            if done[0] % 50 == 0:
                print('  已完成 %d/%d  %s' % (done[0], len(todo), jev.spend()), flush=True)

    with ThreadPoolExecutor(max_workers=workers) as ex:
        list(ex.map(one, todo))
    print(jev.spend(), flush=True)


# ---------------- 统计 ----------------
def mean_ci(xs):
    m = statistics.mean(xs)
    return m, (1.96 * statistics.stdev(xs) / math.sqrt(len(xs)) if len(xs) > 1 else 0.0)


def mcnemar_exact(b, c):
    n = b + c
    if n == 0:
        return 1.0
    k = min(b, c)
    p = 2 * sum(math.comb(n, i) for i in range(k + 1)) / 2 ** n
    return min(1.0, p)


def summarize(steps, best):
    hits = [s['a'] == best for s in steps]
    dev = [s['a'] != s['choice'] for s in steps]
    return {
        'late': sum(hits[-TAIL:]) / TAIL,
        'score': sum(s['r'] for s in steps),
        'tried': len({s['a'] for s in steps}),
        'dev': sum(dev),
        'dev10': [sum(dev[i * 10:(i + 1) * 10]) for i in range(ROUNDS // 10)],
        # 锁对：后 20 轮回包首选全是最好按钮（取最高项组即后 20 轮全按最好）
        'lock': all(s['choice'] == best for s in steps[-TAIL:]),
        'lock_a': all(s['a'] == best for s in steps[-TAIL:]),
    }


def group_rows(log, exp, qfmt, action):
    out = {}
    for i in RUN_IDS:
        v = log.get(key_of(exp, qfmt, action, i))
        if v and not v.get('error') and len(v['steps']) == ROUNDS:
            out[i] = summarize(v['steps'], v['best'])
    return out


def print_row(name, per, with_dev=True):
    xs = list(per.values())
    lm, lc = mean_ci([x['late'] for x in xs])
    sm, sc = mean_ci([x['score'] for x in xs])
    tried = statistics.mean(x['tried'] for x in xs)
    line = '  %-16s n=%-3d 后20轮 %4.1f%% [按局 %4.1f-%4.1f] | 总分 %5.2f±%.2f | 试过 %.2f 钮' % (
        name, len(xs), 100 * lm, 100 * max(0, lm - lc), 100 * min(1, lm + lc), sm, sc, tried)
    if 'lock' in xs[0]:
        line += ' | 锁对 %d（后20轮全按最好 %d）' % (sum(x['lock'] for x in xs), sum(x['lock_a'] for x in xs))
    print(line)
    if with_dev and 'dev' in xs[0]:
        tot = sum(x['dev'] for x in xs)
        segs = [sum(x['dev10'][j] for x in xs) for j in range(ROUNDS // 10)]
        print('  %-16s 偏离首选 %d 次 = %.2f%% 轮次；每 10 轮：%s；前 20 轮占 %.0f%%' % (
            '', tot, 100 * tot / (len(xs) * ROUNDS), ' '.join('%d' % s for s in segs),
            100 * (segs[0] + segs[1]) / tot if tot else 0))


def paired(name, a, b, field='score'):
    common = sorted(set(a) & set(b))
    d = [a[i][field] - b[i][field] for i in common]
    m, ci = mean_ci(d)
    print('  %-26s %+6.2f  [%+.2f, %+.2f]  (n=%d, 差的标准差 %.1f)' % (name, m, m - ci, m + ci, len(d), statistics.stdev(d)))


def paired_lock(name, a, b):
    common = sorted(set(a) & set(b))
    bb = sum(1 for i in common if a[i]['lock'] and not b[i]['lock'])
    cc = sum(1 for i in common if b[i]['lock'] and not a[i]['lock'])
    print('  %-26s 前者对后者错 %d，反之 %d，精确 McNemar p=%.3f' % (name, bb, cc, mcnemar_exact(bb, cc)))


def baselines(exp, ids):
    k, _, s3 = EXPS[exp]
    res = {}
    for pol in ('thompson', 'greedy_init'):
        per = {}
        for i in ids:
            best, out = b3.sim(s3, pol, i, draws=draws_of(exp, i), best=best_of(exp, i))
            hits = [o['a'] == best for o in out]
            per[i] = {'late': sum(hits[-TAIL:]) / TAIL, 'score': sum(o['r'] for o in out), 'tried': len({o['a'] for o in out})}
        res[pol] = per
    return res


def report():
    log = load()
    steps = [s for v in log.values() for s in v['steps']]
    cost = sum(s.get('cost', 0.0) for s in steps)
    models = sorted({s.get('model') for s in steps if s.get('model')})
    errs = [k for k, v in log.items() if v.get('error')]
    print('日志 %d 局，请求（成功落盘的轮次）%d 次，花费 $%.4f，出错局 %d，模型 %s' % (len(log), len(steps), cost, len(errs), models))
    names = {'argmax': '取最高项', 'sample': '按概率抽', 'eps05': 'ε=5% 随机', 'flat': '均摊', 'sched': '按时间表随机',
             'orig': '原问法', 'hint': '只加探索提示', 'long': '长期目标+提示'}
    for exp, (k, groups, _) in EXPS.items():
        print('\n== 实验 %s：%d 钮，最好 %.2f / 其余 %.2f，%d 轮，局号 %d–%d ==' % (exp, k, PG, PB, ROUNDS, RUN_IDS[0], RUN_IDS[-1]))
        G = {}
        for qfmt, action in groups:
            per = group_rows(log, exp, qfmt, action)
            label = names[action] if exp == 'A' else names[qfmt]
            if per:
                G[qfmt if exp == 'B' else action] = per
                print_row(label, per, with_dev=(exp == 'A'))
        ids = sorted(set().union(*[set(p) for p in G.values()])) if G else RUN_IDS
        print('  （Jev 各组按各自完成的局算；配对只用两组都完成的同局号；基线用这 %d 个局号：%d–%d）' % (len(ids), ids[0], ids[-1]))
        bl = baselines(exp, ids)
        for pol, per in bl.items():
            print_row('基线 ' + pol, per, with_dev=False)
        print('  同局配对总分差（前者 − 后者，均值 [近似 95%]）：')
        pairs = ([('flat', 'sched'), ('sched', 'eps05'), ('sample', 'sched'), ('sample', 'eps05'), ('sample', 'argmax'),
                  ('flat', 'eps05'), ('sample', 'flat')] if exp == 'A' else
                 [('hint', 'orig'), ('long', 'orig'), ('hint', 'long')])
        for x, y in pairs:
            if x in G and y in G:
                paired('%s − %s' % (names[x], names[y]), G[x], G[y])
        if exp == 'A' and 'sample' in G:
            paired('%s − 基线 thompson' % names['sample'], G['sample'], bl['thompson'])
        if exp == 'B':
            print('  锁对局数配对：')
            for x, y in pairs:
                if x in G and y in G:
                    paired_lock('%s vs %s' % (names[x], names[y]), G[x], G[y])
            if 'orig' in G:
                paired('%s − 基线 thompson' % names['orig'], G['orig'], bl['thompson'])


def main():
    if len(sys.argv) < 2 or sys.argv[1] not in ('smoke', 'run', 'report'):
        print(__doc__); return
    cmd, rest = sys.argv[1], sys.argv[2:]
    if cmd == 'smoke':
        smoke(int(rest[0]) if rest else 6)
        return
    if cmd == 'run':
        opts = {'--workers': 8, '--max-run': None, '--until': None}
        for o in list(opts):
            if o in rest:
                j = rest.index(o); opts[o] = rest[j + 1]; rest = rest[:j] + rest[j + 2:]
        run(rest or list(EXPS), int(opts['--workers']),
            int(opts['--max-run']) if opts['--max-run'] else None, opts['--until'])
    report()


if __name__ == '__main__':
    main()
