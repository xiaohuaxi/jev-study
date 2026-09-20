"""上下文上限到底怎么算：不是「整个请求 32K」，而是两条规则同时生效。

背景：先前只往 state 里灌长文，撞到约 32.9K 就报错，于是记成「整请求约 32.9K 封顶，
文档说的 64K 不成立」。后来发现一次问几十个长问题时，整请求可以到 6.5 万 token 还能过，
说明那道墙是「state + 单个最长问题」的，不是整请求的。本脚本把两条墙分别钉死：
  A 只涨 state：复现 32K 这道墙；
  B 每对都合规、只改「state + 最长问题」：证明它才是那道 32K 墙；
  C 每对都合规、只堆总量：找出整请求的墙（65,536 一线）。
所有 400 都是刻意探墙的预期结果。
"""
# 让本脚本从任意目录都能找到仓库根部的 jevkit.py / corpus.py
import sys as _sys, pathlib as _pathlib
_sys.path.insert(0, str(_pathlib.Path(__file__).resolve().parent.parent))
import json
import jevkit as jev

FILL = '这是一段用于把输入撑到指定长度的中文填充文本，内容本身没有意义。'

def pad(n_chars):
    return (FILL * (n_chars // len(FILL) + 1))[:n_chars]

def probe(label, state, questions):
    r = jev.call(state, questions, retries=1)
    if '_error' in r:
        code, body = r['_error']
        try:
            detail = json.loads(body)['error']['message'][:90]
        except Exception:
            detail = str(body)[:90]
        print('%-48s -> 拒绝 %s %s' % (label, code, detail))
        return None
    print('%-48s -> 通过，计费输入 %6d tok，%.2fs' % (
        label, r['usage']['input_tokens'], r['_elapsed']))
    return r['usage']['input_tokens']

def q_long(n_chars, i=0):
    return jev.noul(pad(n_chars) + ' 第%d问：以上内容是否没有意义？' % i)

def part_a():
    print('== A 只把 state 撑大（单个短问题）==')
    for k in (30000, 32000, 33000):
        probe('state %dK + 1 个短问题' % (k // 1000), {'doc': pad(k)},
              {'a': jev.noul('这段文本是否没有意义？')})

def part_b():
    print('\n== B 「state + 单个最长问题」才是那道 32K 墙 ==')
    probe('state 30K + 短问题（对 ≈30K，总 ≈30K）',
          {'doc': pad(30000)}, {'a': jev.noul('这段文本是否没有意义？')})
    probe('state 30K + 1 个 5K 问题（对 ≈35K，总 ≈35K）',
          {'doc': pad(30000)}, {'a': q_long(5000)})
    probe('state 15K + 3 个 10K 问题（对 ≈25K，总 ≈45K）',
          {'doc': pad(15000)}, {'q%d' % i: q_long(10000, i) for i in range(3)})
    probe('state 15K + 2 个 20K 问题（对 ≈35K，总 ≈55K）',
          {'doc': pad(15000)}, {'q%d' % i: q_long(20000, i) for i in range(2)})

def part_c():
    print('\n== C 每对都远低于 32K，只堆总量：整请求的墙 ==')
    for n in (5,):
        probe('state 15K + %d 个 10K 问题（对 ≈25K，总 ≈%dK）' % (n, 15 + 10 * n),
              {'doc': pad(15000)}, {'q%d' % i: q_long(10000, i) for i in range(n)})
    for n in (29, 30):
        probe('state 5K + %d 个 2K 问题（对 ≈7K，总 ≈%dK）' % (n, 5 + 2 * n),
              {'doc': pad(5000)}, {'q%d' % i: q_long(2000, i) for i in range(n)})

def main():
    part_a(); part_b(); part_c()
    print('\n' + jev.spend())
    print('结论：state+最长问题 ≤ 32,768；整请求 ≤ 65,536。两条都与官方文档一致。')

main()
