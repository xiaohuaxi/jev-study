"""规模实测：候选动作能有多少、一次能问多少个问题、超过 255 项怎么办。

对应 文献版调研（未收录本仓库） 的 Wikiracing 一节（255 个候选、官方用两阶段）和
「一次可以顺便判断很多东西」一节。三组测量：
  A 候选项数量 2→255：延迟、计费、以及能不能在一堆无关选项里挑出唯一正确的那个；
  B 同一请求里问 1→N 个问题：延迟涨不涨、每题准确率掉不掉、上限在哪；
  C 超过 255 项：先确认 256 被拒，再实测两阶段（分块选优 + 终选）的代价。
"""
# 让本脚本从任意目录都能找到仓库根部的 jevkit.py / corpus.py
import sys as _sys, pathlib as _pathlib
_sys.path.insert(0, str(_pathlib.Path(__file__).resolve().parent.parent))
import json, os, random, statistics, sys
import jevkit as jev

DOMAINS = ['Volleyball', 'Baroque music', 'Sourdough bread', 'Orchid cultivation',
           'Alpine skiing', 'Coral reef', 'Windmill', 'Tango', 'Sushi', 'Mahogany',
           'Camel', 'Lighthouse', 'Pottery', 'Kite', 'Rugby', 'Saffron', 'Glacier',
           'Bamboo', 'Trombone', 'Tulip', 'Walnut', 'Yak', 'Zeppelin', 'Quilting',
           'Falconry', 'Marathon', 'Accordion', 'Basalt', 'Cider', 'Dhow']
ASPECTS = ['history', 'rules', 'equipment', 'techniques', 'regional variants',
           'notable practitioners', 'economics', 'cultural impact', 'terminology',
           'modern revival']
KS = (1, 4, 16, 64, 128, 200, 256, 300, 500, 900, 1000)  # 最后一档会撞到整请求 64K 的墙
NEEDLE = 'Bletchley Park'
TARGET = 'Alan Turing'

def titles(n):
    """造 n 个互不相同的干扰条目；ASPECTS×DOMAINS 只有 300 组，更多的加一个后缀继续。"""
    out, rnd = [], 0
    while len(out) < n:
        suffix = '' if rnd == 0 else ' (part %d)' % (rnd + 1)
        for a in ASPECTS:
            for d in DOMAINS:
                out.append('%s %s%s' % (d, a, suffix))
                if len(out) >= n: return out
        rnd += 1
    return out

def link_state(n, where):
    """n 个候选（含 1 个正确答案），where ∈ first/middle/last。"""
    ds = titles(n - 1)
    pos = {'first': 0, 'middle': len(ds) // 2, 'last': len(ds)}[where]
    ds = ds[:pos] + [NEEDLE] + ds[pos:]
    crit = {t: t for t in ds}
    st = {'current_page': 'Rubber duck', 'target_page': TARGET,
          'available_links': list(crit.keys())}
    q = {'next_link': jev.choice(
        '选择最有可能通向目标页面 %s 的链接。' % TARGET, crit)}
    return st, q

def part_a():
    print('== A 候选项数量：延迟 / 计费 / 选对率（唯一正确答案是 %s）==' % NEEDLE)
    print('%5s %7s %7s %8s %8s %s' % ('N', '延迟中位', '输入tok', '选对', 'p(正确)', '若选错则选了'))
    for n in (2, 4, 8, 16, 32, 64, 128, 255):
        rs = [jev.call(*link_state(n, 'middle')) for _ in range(3)]
        ok = [r for r in rs if '_error' not in r]
        if not ok:
            print('%5d 全失败 %s' % (n, rs[0].get('_error'))); continue
        picks = [r['answers']['next_link']['choice'] for r in ok]
        ps = [r['answers']['next_link']['probabilities'].get(NEEDLE, 0) for r in ok]
        wrong = [p for p in picks if p != NEEDLE]
        print('%5d %7.2f %7d %8s %8.2f %s' % (
            n, statistics.median([r['_elapsed'] for r in ok]),
            ok[0]['usage']['input_tokens'],
            '%d/%d' % (sum(1 for p in picks if p == NEEDLE), len(picks)),
            statistics.mean(ps), wrong[:2]))
    print('\n-- 正确答案放在候选列表的不同位置（N=255，各 3 次）--')
    for where in ('first', 'middle', 'last'):
        rs = [jev.call(*link_state(255, where)) for _ in range(3)]
        ok = [r for r in rs if '_error' not in r]
        picks = [r['answers']['next_link']['choice'] for r in ok]
        ps = [r['answers']['next_link']['probabilities'].get(NEEDLE, 0) for r in ok]
        print('%-7s 选对 %d/%d，p(正确) 均值 %.2f' % (
            where, sum(1 for p in picks if p == NEEDLE), len(picks), statistics.mean(ps)))

def q_state(k):
    random.seed(7)
    enemies = [{'id': 'E%d' % i, 'bearing_deg': random.choice(range(0, 360, 7))} for i in range(k)]
    st = {'player_facing_deg': 0, 'enemies': enemies}
    qs = {'E%d' % i: jev.noul(
        'state.enemies 里 id 为 E%d 的敌人，其 bearing_deg 是否落在 180 到 360 度之间？' % i)
        for i in range(k)}
    truth = {'E%d' % i: enemies[i]['bearing_deg'] >= 180 for i in range(k)}
    return st, qs, truth

def part_b():
    print('\n== B 一次请求里问多少个问题：延迟 / 计费 / 每题准确率 ==')
    print('%5s %7s %7s %7s %9s %s' % (
        '问题数', '延迟中位', '输入tok', '输出tok', '逐题准确率', '各次答错的题数'))
    for k in KS:
        st, qs, truth = q_state(k)
        rs = [jev.call(st, qs, retries=1) for _ in range(2)]
        ok = [r for r in rs if '_error' not in r]
        if not ok:
            print('%5d 被拒 %s' % (k, str(rs[0].get('_error'))[:150])); continue
        # 逐题准确率四舍五入后很容易显示成 100%，所以把答错的绝对题数一并打出来
        wrong = [[k2 for k2, v in truth.items() if (r['answers'][k2]['noul'] >= 0.5) != v]
                 for r in ok]
        acc = [1 - len(w) / float(k) for w in wrong]
        print('%5d %7.2f %7d %7d %9s %s' % (
            k, statistics.median([r['_elapsed'] for r in ok]),
            ok[0]['usage']['input_tokens'], ok[0]['usage']['output_tokens'],
            '%.1f%% (%d/%d 次成功)' % (100 * statistics.mean(acc), len(ok), len(rs)),
            ['%d/%d' % (len(w), k) for w in wrong]))

def part_c():
    print('\n== C 超过 255 个候选 ==')
    st, q = link_state(256, 'middle')
    r = jev.call(st, q, retries=1)
    print('256 项一次性提交 ->', '成功' if '_error' not in r else r['_error'][1][:160])
    total = 510
    ds = titles(total - 1)
    ds = ds[:total // 2] + [NEEDLE] + ds[total // 2:]
    chunks = [ds[:255], ds[255:]]
    print('两阶段：%d 项拆成 %d 块（%s）' % (total, len(chunks), [len(c) for c in chunks]))
    import time
    t0 = time.time()
    jobs = []
    for i, c in enumerate(chunks):
        crit = {t: t for t in c}
        jobs.append((i, {'current_page': 'Rubber duck', 'target_page': TARGET,
                         'available_links': c},
                     {'best': jev.choice('从这一批链接里挑出最可能通向 %s 的一个。' % TARGET, crit)}))
    res = jev.fan(jobs, workers=2)
    t_stage1 = time.time() - t0
    winners = [res[i]['answers']['best']['choice'] for i in sorted(res) if '_error' not in res[i]]
    crit = {w: w for w in winners}
    r2 = jev.call({'current_page': 'Rubber duck', 'target_page': TARGET,
                   'available_links': winners},
                  {'best': jev.choice('从这几个候选里挑出最可能通向 %s 的一个。' % TARGET, crit)})
    t_all = time.time() - t0
    print('第一阶段并发 %d 次请求 %.2fs，各块胜者 %s' % (len(chunks), t_stage1, winners))
    print('第二阶段终选 %s（%.2fs）；两阶段总耗时 %.2fs，共 %d 次请求' % (
        r2['answers']['best']['choice'] if '_error' not in r2 else r2['_error'],
        r2.get('_elapsed', -1), t_all, len(chunks) + 1))
    print('正确答案 %s 是否胜出: %s' % (NEEDLE, '_error' not in r2 and r2['answers']['best']['choice'] == NEEDLE))

def main():
    part_a(); part_b(); part_c()
    print('\n' + jev.spend())

main()
