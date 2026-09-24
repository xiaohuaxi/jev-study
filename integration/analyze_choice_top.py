# -*- coding: utf-8 -*-
"""choice 是不是概率最高的那项：扫仓库各专题目录下的实验日志，只读、不发请求、不 import jevkit（没设 key 也能用）。

    python3 integration/analyze_choice_top.py              # 扫仓库各级目录下的 *_log.json / *_log.jsonl
    python3 integration/analyze_choice_top.py 日志 ...     # 只看指定的日志

凡是日志里同时带 choice 和 probabilities 的回答都算（choice 题型的原始回包；score、noul 不带 choice，自然不算）。
概率按回包的两位小数比较：0.05 和 0.049999999999999996 这类浮点尾数算同一个值。
作废批次的日志（*_void_log.json）默认不算：一步杀那批不是本仓库的脚本跑出来的，读者重跑不出。
日志被 .gitignore 排除、不入库，要先跑对应的实验脚本；没保存原始回包的日志统计为 0 条。

会留下 choice 原始回包的是 games/chess/exp_game_chess_prompt.py 和 games/xiangqi/ 下的实验脚本。
支撑 integration/README.md「几个只有实测才看得到的细节」里概率和、choice 那两条。
"""
import collections, glob, json, os, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def load(path):
    with open(path, encoding='utf-8') as f:
        if path.endswith('.jsonl'):
            for line in f:
                if line.strip():
                    yield json.loads(line)
        else:
            yield json.load(f)


def answers(o):
    """递归找出所有 {choice, probabilities} 对象。"""
    if isinstance(o, dict):
        if isinstance(o.get('choice'), str) and isinstance(o.get('probabilities'), dict) and o['probabilities']:
            yield o
        for v in o.values():
            yield from answers(v)
    elif isinstance(o, list):
        for v in o:
            yield from answers(v)


BUCKETS = ((5, '2–5'), (10, '6–10'), (20, '11–20'), (40, '21–40'), (255, '41–255'))


def bucket(n):
    return next(name for top, name in BUCKETS if n <= top)


def main():
    tot = collections.Counter()
    close = collections.Counter()      # 头两档只差 0.01 的回答，按概率和分：{和: [条数, choice 落在下档的条数]}
    close_low = collections.Counter()
    gaps = collections.Counter()
    by_n = collections.defaultdict(collections.Counter)   # 按选项数分组的概率和
    print('%-36s %6s %8s %8s %8s' % ('日志', '回答', '唯一最高', '并列最高', '低于最高'))
    files = sys.argv[1:] or sorted(p for pat in ('*_log.json', '*_log.jsonl')
                                   for p in glob.glob(os.path.join(ROOT, '**', pat), recursive=True)
                                   if '_void_' not in os.path.basename(p))
    for fp in files:
        c = collections.Counter()
        for rec in load(fp):
            for a in answers(rec):
                p = {k: round(float(v), 2) for k, v in a['probabilities'].items()}
                ch = a['choice']
                assert ch in p, (fp, ch)
                top = max(p.values())
                s = round(sum(p.values()), 2)
                c['n'] += 1
                tot['sum %.2f' % s] += 1
                by_n[bucket(len(p))][s] += 1
                if p[ch] == top:
                    c['uniq' if list(p.values()).count(top) == 1 else 'tie'] += 1
                else:
                    c['low'] += 1
                    gaps[round(top - p[ch], 2)] += 1
                    tot['low sum %.2f' % s] += 1
                below = sorted({v for v in p.values() if v < top}, reverse=True)
                if below and round(top - below[0], 2) == 0.01:
                    close[s] += 1
                    close_low[s] += p[ch] == below[0]
        if c['n']:
            print('%-36s %6d %8d %8d %8d' % (os.path.basename(fp), c['n'], c['uniq'], c['tie'], c['low']))
            tot['files'] += 1
            tot.update({k: v for k, v in c.items()})
    n = tot['n']
    print('\n%d 份日志、%d 条 choice 回答：choice 是唯一最高项 %d 条，落在并列最高里 %d 条，低于最高项 %d 条（%.2f%%）' % (
        tot['files'], n, tot['uniq'], tot['tie'], tot['low'], 100.0 * tot['low'] / n))
    print('低于最高项时差多少（两位小数）：%s' % dict(sorted(gaps.items())))
    for s in sorted(close):
        print('头两档只差 0.01、概率和 %.2f：%d 条，choice 落在下档 %d 条（%.1f%%）' % (s, close[s], close_low[s], 100.0 * close_low[s] / close[s]))
    allc, alll = sum(close.values()), sum(close_low.values())
    print('头两档只差 0.01 合计 %d 条，choice 落在下档 %d 条（%.1f%%）' % (allc, alll, 100.0 * alll / allc))
    print('全部回答的概率和：%s；低于最高项那些的概率和：%s' % (
        {k[4:]: v for k, v in tot.items() if k.startswith('sum ')}, {k[8:]: v for k, v in tot.items() if k.startswith('low sum ')}))
    for _, name in BUCKETS:
        c = by_n[name]; t = sum(c.values())
        if t:
            print('选项 %-6s 的回答 %5d 条，概率和为 0.99 的 %4d 条（%.1f%%）' % (name, t, c[0.99], 100.0 * c[0.99] / t))


if __name__ == '__main__':
    main()
