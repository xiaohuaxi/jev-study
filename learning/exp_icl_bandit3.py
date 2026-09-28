"""Jev 老虎机第三轮（补漏对照，2026-09-26）：抽样的功劳是不是"随便加点随机"就有；难一点还灵不灵；
"长期目标"和"探索提示"各自有没有用。

背景见 exp_icl_bandit2.py 的 ONLINE 部分（4 钮 0.75/0.25、80 轮 × 40 局，原问法取最高项后段 62%、按概率抽 85%）。
这里补三件事，全部在线闭环、历史写法统一 raw（"第 k 轮：按了 X，得 N 分"）：

SPLIT  同一设置（4 钮 0.75/0.25、80 轮、40 局，奖励与 bandit2 同局号共用一份 → 可与 bandit2 四组逐局配对）
  goal·argmax / goal·sample   问句只点明"一共 80 轮、现在第 t 轮、还剩几轮，目标是 80 轮总分最高"，不写探索提示
  hint·argmax / hint·sample   问句只加"没试过或试得少的按钮也可能更好，前期适当尝试……"，不写轮数与长期目标
  orig·eps05                  原问法，回包 choice，但每轮有 5% 概率改成四个按钮里均匀随机按一个（ε-greedy）。
                              bandit2 原问法抽样组实际偏离最高项的轮次是 3.66%，ε=0.05 时偏离率 3.75%，随机量对齐：
                              分得清"按 Jev 的概率抽"和"单纯掺一点随机"。
H8     8 个按钮 A–H，最好 0.75、其余 0.25，80 轮 × 40 局（最好按钮按局号均衡，各当 5 次）：orig·argmax / orig·sample / orig·eps05 / orig·flat（flat 后加）
GAP    4 个按钮，最好 0.6、其余 0.5，200 轮 × 40 局：orig·argmax / orig·sample / orig·eps05
  本地基线（不请求 API，同一份奖励）：random、greedy_init（先每钮试一次再按均值最高）、ucb1、thompson；
  另用局号 0–1999 跑一遍求稳定均值。

请求量：SPLIT 6×40×80=19,200（含后加的 flat）；H8 4×40×80=12,800（含后加的 flat）；GAP 3×40×200=24,000；合计 56,000。
用法：python3 exp_icl_bandit3.py run [SPLIT|H8|GAP] | report
日志写同目录 icl_bandit3_log.json（*_log.json 被 .gitignore 排除），每局跑完即落盘，断点续跑以局为单位。
"""
# 让本脚本从任意目录都能找到仓库根部的 jevkit.py 和同目录的其他 exp_icl_*.py
import sys as _sys, pathlib as _pathlib
_sys.path[:0] = [str(_pathlib.Path(__file__).resolve().parent), str(_pathlib.Path(__file__).resolve().parent.parent)]
import json, math, os, random, statistics, sys, threading
from concurrent.futures import ThreadPoolExecutor

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import exp_icl_bandit2 as b2

HERE = os.path.dirname(os.path.abspath(__file__))
LOG = os.path.join(HERE, 'icl_bandit3_log.json')
LOCK = threading.Lock()
RUNS = 40
EPS = 0.05

LETTERS = 'ABCDEFGH'
SETTINGS = {
    # name: (臂数, 好, 差, 轮数, 分组)
    'SPLIT': (4, 0.75, 0.25, 80, [('goal', 'argmax'), ('goal', 'sample'), ('hint', 'argmax'), ('hint', 'sample'), ('orig', 'eps05'), ('orig', 'flat')]),
    'H8': (8, 0.75, 0.25, 80, [('orig', 'argmax'), ('orig', 'sample'), ('orig', 'eps05'), ('orig', 'flat')]),
    'GAP': (4, 0.6, 0.5, 200, [('orig', 'argmax'), ('orig', 'sample'), ('orig', 'eps05')]),
}
ZH_NUM = {4: '4', 8: '8'}


def arms(k):
    return list(LETTERS[:k])


def base_q(k):
    names = '、'.join(arms(k))
    return ('你在玩一个有 %s 个按钮（%s）的游戏。每轮按一个按钮，可能得 1 分，也可能得 0 分。'
            '每个按钮得分的概率不一样，但没人告诉你哪个高。state 里有之前各轮的记录（如果有的话）。') % (ZH_NUM[k], names)


HINT = '没试过或试得少的按钮也可能更好，前期适当尝试、摸清各按钮再集中按最好的，通常总分更高。'


def question(k, qfmt, rnd, total):
    b = base_q(k)
    if qfmt == 'orig':
        q = b + '选下一轮按哪个按钮，目标是尽量多得分。'
        if k == 4:
            assert q == b2.Q_ORIG, '4 钮原问法必须与 bandit2 逐字一致'
        return q
    if qfmt == 'goal':
        return b + '一共要玩 %d 轮，现在是第 %d 轮（还剩 %d 轮）。目标是让这 %d 轮的总得分最高。选下一轮按哪个按钮。' % (
            total, rnd, total - rnd, total)
    if qfmt == 'hint':
        return b + HINT + '选下一轮按哪个按钮，目标是尽量多得分。'
    raise ValueError(qfmt)


def best_of(setting, run):
    k = SETTINGS[setting][0]
    return arms(k)[run % k]


def draws_of(setting, run):
    k, _, _, rounds, _ = SETTINGS[setting]
    if setting == 'SPLIT':
        return b2.online_draws(run)  # 与 bandit2 ONLINE 同局号同一份奖励
    rng = random.Random('B3|%s|%d' % (setting, run))
    return [[rng.random() for _ in range(k)] for _ in range(rounds)]


def raw_state(hist):
    if not hist:
        return {'task': '按按钮得分', 'history': '（还没有任何记录）'}
    return {'task': '按按钮得分', 'history': '\n'.join('第 %d 轮：按了 %s，得 %d 分' % (i + 1, a, r) for i, (a, r) in enumerate(hist))}


def sample_choice(probs, names, rng):
    items = [(a, max(0.0, probs.get(a, 0.0))) for a in names]
    tot = sum(v for _, v in items)
    if tot <= 0:
        return rng.choice(names)
    r = rng.random() * tot
    acc = 0.0
    for a, v in items:
        acc += v
        if r <= acc:
            return a
    return items[-1][0]


def load():
    return json.load(open(LOG)) if os.path.exists(LOG) else {}


def save(log):
    tmp = LOG + '.tmp'
    json.dump(log, open(tmp, 'w'), ensure_ascii=False)
    os.replace(tmp, LOG)


def game(setting, qfmt, action, run, log):
    import jevkit as jev
    k, pg, pb, rounds, _ = SETTINGS[setting]
    names = arms(k)
    key = '%s|%s|%s|%d' % (setting, qfmt, action, run)
    if key in log and not log[key].get('error'):
        return
    best = best_of(setting, run)
    draws = draws_of(setting, run)
    prng = random.Random('B3samp|%s|%s|%s|%d' % (setting, qfmt, action, run))
    crit = {a: '按按钮 ' + a for a in names}
    hist, steps = [], []
    for t in range(rounds):
        rnd = t + 1
        r = jev.call(raw_state(hist), {'button': {'type': 'choice', 'instructions': question(k, qfmt, rnd, rounds), 'criteria': crit}})
        if '_error' in r:
            with LOCK:
                log[key] = {'error': r['_error'], 'steps': steps}
                save(log)
            return
        ans = r['answers']['button']
        if action == 'argmax':
            a = ans['choice']
        elif action == 'sample':
            a = sample_choice(ans['probabilities'], names, prng)
        elif action == 'flat':
            # 保留 Jev 最高项被抽中的概率，其余概率在其它按钮间均分：看"非最高项之间的排序"有没有用
            top = ans['choice']
            pt = max(0.0, min(1.0, ans['probabilities'].get(top, 0.0) / (sum(max(0.0, v) for v in ans['probabilities'].values()) or 1.0)))
            a = top if prng.random() < pt else prng.choice([x for x in names if x != top])
        elif action == 'eps05':
            a = prng.choice(names) if prng.random() < EPS else ans['choice']
        else:
            raise ValueError(action)
        rew = 1 if draws[t][names.index(a)] < (pg if a == best else pb) else 0
        hist.append((a, rew))
        steps.append({'t': rnd, 'a': a, 'r': rew, 'choice': ans['choice'], 'p': ans['probabilities'],
                      'cost': r.get('usage', {}).get('cost', 0.0), 'model': r.get('model')})
    with LOCK:
        log[key] = {'best': best, 'steps': steps}
        save(log)


def run(which, workers=24):
    import jevkit as jev
    log = load()
    jobs = []
    for s in which:
        for qfmt, action in SETTINGS[s][4]:
            for i in range(RUNS):
                jobs.append((s, qfmt, action, i))
    todo = [j for j in jobs if not ('%s|%s|%s|%d' % j in log and not log['%s|%s|%s|%d' % j].get('error'))]
    print('共 %d 局，待跑 %d' % (len(jobs), len(todo)), flush=True)
    # 长局先跑，免得最后只剩几个 200 轮的局串行拖尾
    todo.sort(key=lambda j: -SETTINGS[j[0]][3])
    with ThreadPoolExecutor(max_workers=workers) as ex:
        list(ex.map(lambda j: game(*j, log), todo))
    print(jev.spend(), flush=True)


# ---------------- 本地基线 ----------------
def sim(setting, policy, run, draws=None, best=None):
    k, pg, pb, rounds, _ = SETTINGS[setting]
    names = arms(k)
    best = best or best_of(setting, run)
    draws = draws or draws_of(setting, run)
    prng = random.Random('B3sim|%s|%s|%d' % (setting, policy, run))
    cnt = {a: 0 for a in names}; tot = {a: 0 for a in names}
    out = []
    for t in range(rounds):
        untried = [a for a in names if not cnt[a]]
        if policy == 'random':
            a = prng.choice(names)
        elif policy == 'greedy_init':
            if untried:
                a = untried[0]
            else:
                mx = max(tot[x] / cnt[x] for x in names)
                a = prng.choice([x for x in names if tot[x] / cnt[x] == mx])
        elif policy == 'ucb1':
            a = untried[0] if untried else max(names, key=lambda x: tot[x] / cnt[x] + math.sqrt(2 * math.log(t) / cnt[x]))
        elif policy == 'thompson':
            smp = {x: prng.betavariate(1 + tot[x], 1 + cnt[x] - tot[x]) for x in names}
            a = max(smp, key=smp.get)
        else:
            raise ValueError(policy)
        rew = 1 if draws[t][names.index(a)] < (pg if a == best else pb) else 0
        cnt[a] += 1; tot[a] += rew
        out.append({'a': a, 'r': rew})
    return best, out


def big_sim(setting, policy, n=2000):
    k, pg, pb, rounds, _ = SETTINGS[setting]
    names = arms(k)
    scores, late = [], []
    tail = rounds // 4
    for i in range(n):
        rng = random.Random('B3big|%s|%d' % (setting, i))
        draws = [[rng.random() for _ in range(k)] for _ in range(rounds)]
        best, out = sim(setting, policy, i, draws=draws, best=names[i % k])
        scores.append(sum(s['r'] for s in out))
        late.append(sum(s['a'] == best for s in out[-tail:]) / tail)
    return statistics.mean(scores), statistics.mean(late)


def mean_ci(xs):
    m = statistics.mean(xs)
    return m, (1.96 * statistics.stdev(xs) / math.sqrt(len(xs)) if len(xs) > 1 else 0.0)


def summarize(steps, best, rounds):
    seg = rounds // 4
    hits = [s['a'] == best for s in steps]
    return {
        'segs': [sum(hits[i * seg:(i + 1) * seg]) / seg for i in range(4)],
        'score': sum(s['r'] for s in steps),
        'tried': len({s['a'] for s in steps}),
    }


def row(name, per_run, rounds):
    segs = [statistics.mean(r['segs'][i] for r in per_run) for i in range(4)]
    late_m, late_ci = mean_ci([r['segs'][3] for r in per_run])
    sc_m, sc_ci = mean_ci([r['score'] for r in per_run])
    tried = statistics.mean(r['tried'] for r in per_run)
    print('  %-26s %s | 后段 %.0f%%[按局 %.0f-%.0f] | 总分 %.1f±%.1f | 试过 %.1f 钮' % (
        name, ' '.join('%3.0f%%' % (100 * x) for x in segs), 100 * late_m, 100 * max(0, late_m - late_ci),
        100 * min(1, late_m + late_ci), sc_m, sc_ci, tried))


def paired(name, a, b):
    """a、b：{局号: 总分}，同局号配对差。"""
    common = sorted(set(a) & set(b))
    d = [a[i] - b[i] for i in common]
    m, ci = mean_ci(d)
    print('  %-44s %+.2f  [%.2f, %.2f]  (n=%d)' % (name, m, m - ci, m + ci, len(d)))


def report():
    log = load()
    b2log = b2.load()
    calls = sum(len(v['steps']) for v in log.values())
    cost = sum(s.get('cost', 0.0) for v in log.values() for s in v['steps'])
    models = {s.get('model') for v in log.values() for s in v['steps']}
    errs = sum(1 for v in log.values() if v.get('error'))
    print('日志 %d 局，请求 %d 次，花费 $%.4f，出错局 %d，模型 %s' % (len(log), calls, cost, errs, models))
    for setting, (k, pg, pb, rounds, groups) in SETTINGS.items():
        print('\n== %s：%d 钮，最好 %.2f / 其余 %.2f，%d 轮 × %d 局；列为每 %d 轮一段选中最好的比例 ==' % (
            setting, k, pg, pb, rounds, RUNS, rounds // 4))
        scores = {}
        for qfmt, action in groups:
            per = []
            sc = {}
            for i in range(RUNS):
                v = log.get('%s|%s|%s|%d' % (setting, qfmt, action, i))
                if not v or v.get('error'):
                    continue
                s = summarize(v['steps'], v['best'], rounds)
                per.append(s); sc[i] = s['score']
            if per:
                row('Jev %s·%s (n=%d)' % (qfmt, action, len(per)), per, rounds)
                scores['%s·%s' % (qfmt, action)] = sc
                if action == 'sample':
                    dev = [s['a'] != max(s['p'], key=s['p'].get) for i in range(RUNS)
                           for s in (log.get('%s|%s|%s|%d' % (setting, qfmt, action, i)) or {}).get('steps', [])]
                    print('    （抽样组偏离最高项的轮次 %.1f%%）' % (100 * statistics.mean(dev)))
        if setting == 'SPLIT':
            for qfmt, action in b2.ON_GROUPS:
                per, sc = [], {}
                for i in range(RUNS):
                    v = b2log.get('ON|%s|%s|%d' % (qfmt, action, i))
                    if not v or v.get('error'):
                        continue
                    st = [{'a': s['a'], 'r': s['r']} for s in v['steps']]
                    s = summarize(st, v['best'], rounds)
                    per.append(s); sc[i] = s['score']
                row('[bandit2] %s·%s' % (qfmt, action), per, rounds)
                scores['%s·%s' % (qfmt, action)] = sc
        for pol in ('random', 'greedy_init', 'ucb1', 'thompson'):
            per, sc = [], {}
            for i in range(RUNS):
                best, out = sim(setting, pol, i)
                s = summarize(out, best, rounds)
                per.append(s); sc[i] = s['score']
            row('基线 %s' % pol, per, rounds)
            scores[pol] = sc
        print('  2000 局稳定值（总分 / 最后 1/4 选中最好）：' + '；'.join(
            '%s %.1f / %.0f%%' % (p, *(lambda r: (r[0], 100 * r[1]))(big_sim(setting, p))) for p in ('random', 'greedy_init', 'ucb1', 'thompson')))
        print('  同局配对总分差（前者 − 后者，均值 [近似 95%]）：')
        pairs = [('orig·sample', 'orig·argmax'), ('orig·eps05', 'orig·argmax'), ('orig·sample', 'orig·eps05'), ('orig·sample', 'orig·flat'), ('orig·flat', 'orig·argmax'),
                 ('orig·sample', 'thompson'), ('orig·argmax', 'random')]
        if setting == 'SPLIT':
            pairs += [('goal·argmax', 'orig·argmax'), ('hint·argmax', 'orig·argmax'), ('long·argmax', 'orig·argmax'),
                      ('goal·sample', 'orig·sample'), ('hint·sample', 'orig·sample'), ('long·sample', 'orig·sample'),
                      ('goal·sample', 'goal·argmax'), ('hint·sample', 'hint·argmax')]
        for x, y in pairs:
            if x in scores and y in scores:
                paired('%s − %s' % (x, y), scores[x], scores[y])


def main():
    if len(sys.argv) < 2 or sys.argv[1] not in ('run', 'report'):
        print(__doc__); return
    if sys.argv[1] == 'run':
        which = sys.argv[2:] or list(SETTINGS)
        run(which)
    report()


if __name__ == '__main__':
    main()
