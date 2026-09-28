"""Jev 小型 few-shot 文本分类对照：标签是否"看得懂"本身，能不能被示例教会？

背景：以前的 in-context learning 实验都在"讲道理/猜规则"这类任务上测。这个脚本换成
最朴素的文本分类，把"label 本身有没有语义"和"给不给例子、给几个例子"两个变量分开看：
  - named   ：选项键就是真类名（Sports/Finance/Technology/Food/Travel），描述也是类名——
              纯粹考"有没有语义信息 + 例子能不能帮上忙"。
  - opaque  ：选项键是无意义的 L1–L5，描述留一个占位字符串（不泄露真类名）；类名和 L 的
              对应关系只能从随之给出的例子里"学"出来，例子越多信息越足。k=0 时等于纯瞎猜。
  - opaque_desc：和 opaque 用同一套 L1–L5，但不把例子放进 state 的 examples 列表，而是直接
              写进每个选项自己的描述里（"这个标签下的例子是：'…'、'…'"），看"例子摆在哪里"
              （单独一段 vs. 绑在对应选项旁边）有没有差别。k=0 时和 opaque k=0 完全一样，
              没有必要重复测，所以只有 k=1/2/4 三档（对齐事先定下的 1,100 请求量）。

语料：5 类主题（Sports / Finance / Technology / Food / Travel），每类 20 条测试句 + 8 条
示例池句，全部手写、英文、10–25 词、主题清楚不刁钻，测试句与示例池互不重复（脚本末尾
有一次性去重与词数自检，正式运行前跑过一遍）。

随机性（全部用字符串种子的 random.Random，可复现）：
  - 每条测试句自己决定一套"真类名 → L1–L5"的随机排列，种子只挂在句子 id 上（perm|<句子id>），
    和 k、和 named/opaque/opaque_desc 无关——这样同一句测试句在 opaque 与 opaque_desc 两组里
    L 的含义是一致的，可以互相比较。
  - 每个 (句子id, k) 决定一套"每类从示例池抽 k 条"的选择 + 顺序打乱，种子挂 ex|<句子id>|<k>，
    与 named/opaque/opaque_desc 无关——这样同一 k 下，named、opaque、opaque_desc 三组展示的
    是完全相同的例子（只是标签写法不同），谁好谁坏只由"标签怎么呈现"决定，不掺进"抽到的例子
    是不是更典型"这个混淆变量。

state 字段：先 examples（如果这一档有）、后 text（当前要判断的句子），呼应旧脚本"先历史后
当前"的顺序习惯。k=0 时 examples 写成占位字符串 'none given' 而不是省略字段，呼应
exp_icl_bandit.py 里 none 档写显式占位串的做法。opaque_desc 档不出现 examples 字段（例子已经
写进各选项描述里）。

问句固定用中性英文（不出现"用例子学习"之外的提示，不泄露 opaque 组的真类名）：
  "Below is a short piece of text. Which category does it belong to? If example texts are
   given for the categories, use them to learn what each category means, then classify the
   text the same way."

请求量：100 句测试句 ×（named 4 档 + opaque 4 档 + opaque_desc 3 档）= 1,100，与事先的实验设计一致。
指标：每档准确率（n=100，瞎猜 20%），report 给 Wilson 95% 区间。

跟事先写好的实验设计字面相比的几处落地选择（非结论性偏离，记在这里免得以后看日志猜）：
  1. opaque 的选项描述没有留空，写了个占位串 "Category L1"（设计原话"留空或只写类别 L1"
     两个选项都允许）——留空怕个别实现把空字符串当无效输入处理，选了更保险的那个选项。
  2. instructions/criteria 用英文，跟语料语言一致（设计没有规定语言，设计里给的问句
     范例本身也是英文）。
  3. 冒烟阶段选的是 Sports#00 与 Finance#00 两条测试句、全部 11 档 = 22 次真实调用；这些 key
     本来就在全量 1,100 条里，冒烟跑过之后 run 会直接跳过，不会重复计费。

用法：python3 exp_icl_fewshot.py smoke    —— 打印 named/opaque/opaque_desc 各一个完整请求体，
                                              再跑 22 条真实小样本，检查格式和准确率量级正常
      python3 exp_icl_fewshot.py run      —— 断点续跑剩余请求，结果写 icl_fewshot_log.json
      python3 exp_icl_fewshot.py report   —— 只读日志出表
"""
# 让本脚本从任意目录都能找到仓库根部的 jevkit.py 和同目录的其他 exp_icl_*.py
import sys as _sys, pathlib as _pathlib
_sys.path[:0] = [str(_pathlib.Path(__file__).resolve().parent), str(_pathlib.Path(__file__).resolve().parent.parent)]
import json, math, os, random, sys, threading
from concurrent.futures import ThreadPoolExecutor, as_completed

HERE = os.path.dirname(os.path.abspath(__file__))
LOG = os.path.join(HERE, 'icl_fewshot_log.json')
LOCK = threading.Lock()

CATS = ['Sports', 'Finance', 'Technology', 'Food', 'Travel']
LS = ['L1', 'L2', 'L3', 'L4', 'L5']

Q_LABEL = ('Below is a short piece of text. Which category does it belong to? '
           'If example texts are given for the categories, use them to learn what each '
           'category means, then classify the text the same way.')

# ---------------- 语料：每类 20 条测试句 + 8 条示例池句 ----------------
TEST = {
    'Sports': [
        "The soccer team celebrated wildly after scoring the winning goal in the final minute of the match.",
        "She trained every morning before dawn to prepare for the upcoming marathon next spring.",
        "The basketball coach called a timeout to reset his team's defensive strategy in the fourth quarter.",
        "Fans packed the stadium to watch the two rival teams battle for the championship trophy.",
        "The tennis player fought back from two sets down to win the grueling five-set final.",
        "Olympic swimmers broke three world records during the opening days of the summer games.",
        "The rookie quarterback threw for over three hundred yards in his first professional football game.",
        "After a tough loss, the boxer analyzed the match footage to improve his defensive footwork.",
        "The cycling team rode through steep mountain passes on the toughest stage of the race.",
        "Volleyball players dove across the sand court to keep the ball alive during the tiebreaker.",
        "The gymnast landed a perfect vault routine, earning the highest score of the competition.",
        "Coaches praised the young sprinter for shaving half a second off her personal best time.",
        "The hockey goalie made a spectacular save to preserve his team's narrow lead in overtime.",
        "Thousands of runners lined up at dawn for the start of the annual city marathon.",
        "The wrestling match went into extra rounds before the judges finally declared a winner.",
        "A last-second three-pointer sent the basketball game into overtime, stunning the home crowd.",
        "The baseball pitcher threw a no-hitter, retiring twenty-seven batters in a row without a hit.",
        "Injured during preseason training, the striker will miss the opening matches of the new season.",
        "The rowing crew synchronized every stroke perfectly to win the regatta by a narrow margin.",
        "Young athletes gathered at the training camp to learn new techniques from former Olympic champions.",
    ],
    'Finance': [
        "The central bank raised interest rates again to try to control rising inflation this quarter.",
        "Shares of the company surged after it reported earnings far above analyst expectations.",
        "Many young workers are struggling to save for retirement amid stagnant wage growth.",
        "The stock market tumbled sharply after news of unexpectedly weak manufacturing data.",
        "She opened a savings account to start building an emergency fund for unexpected expenses.",
        "The company issued new bonds to raise capital for its planned factory expansion.",
        "Investors grew nervous as the currency continued to weaken against the dollar.",
        "The bank approved his mortgage application after reviewing his credit history and income.",
        "Rising fuel costs pushed the country's trade deficit to its highest level in years.",
        "The startup secured a new round of funding from several venture capital firms.",
        "Analysts warned that household debt levels were climbing faster than incomes.",
        "The pension fund shifted more of its portfolio into government bonds for stability.",
        "A sudden drop in oil prices rattled energy stocks across global markets.",
        "The accountant reconciled the quarterly statements before submitting them to the auditors.",
        "Consumer spending slowed as households cut back amid growing economic uncertainty.",
        "The insurance company raised premiums after a year of unusually large claims.",
        "Gold prices climbed as investors sought safer assets during the market downturn.",
        "The finance minister unveiled a new budget aimed at reducing the national deficit.",
        "Credit card debt among consumers reached a new record high this year.",
        "The merger between the two banks was approved after months of regulatory review.",
    ],
    'Technology': [
        "The new smartphone features a faster processor and a significantly improved camera system.",
        "Engineers released a software update to fix several security vulnerabilities in the app.",
        "The startup unveiled a robot capable of sorting packages twice as fast as before.",
        "Researchers trained a new artificial intelligence model to translate languages in real time.",
        "The company migrated its entire database to a cloud computing platform for scalability.",
        "A critical bug in the operating system caused thousands of devices to crash.",
        "Developers spent weeks debugging the code before finally launching the mobile app.",
        "The chip manufacturer announced a smaller, more energy-efficient processor for laptops.",
        "Hackers exploited a flaw in the website to steal customer login credentials.",
        "The virtual reality headset lets users explore realistic three-dimensional environments from home.",
        "Engineers tested the self-driving car's sensors on a closed course before public trials.",
        "The tech company open-sourced its machine learning framework for other developers to use.",
        "A new wireless standard promises faster internet speeds for connected home devices.",
        "The programmer refactored the codebase to make the application easier to maintain.",
        "Cybersecurity experts warned that the malware could spread quickly through corporate networks.",
        "The drone used onboard cameras and sensors to map the terrain automatically.",
        "Engineers built a prototype battery that charges electric vehicles in under ten minutes.",
        "The app's new interface makes it easier for users to navigate menus.",
        "A data breach exposed the personal information of millions of app users.",
        "The lab unveiled a quantum computing chip capable of solving complex equations quickly.",
    ],
    'Food': [
        "The chef drizzled olive oil over the roasted vegetables before serving them warm.",
        "She kneaded the dough for ten minutes until it became smooth and elastic.",
        "The restaurant's new menu features seasonal ingredients sourced from local farms.",
        "He simmered the tomato sauce slowly to let the flavors develop fully.",
        "The bakery's fresh croissants sell out within an hour of opening every morning.",
        "Grilled salmon paired with lemon butter sauce was the highlight of the dinner.",
        "The recipe calls for two cups of flour, a pinch of salt, and fresh yeast.",
        "Street vendors sold spicy noodles topped with peanuts and fresh herbs.",
        "The soup was seasoned with ginger, garlic, and a splash of soy sauce.",
        "She whisked the eggs vigorously before folding them gently into the batter.",
        "The dessert combined dark chocolate, raspberries, and a dusting of powdered sugar.",
        "Chefs competed to create the most creative dish using only five ingredients.",
        "The barbecue ribs were slow-cooked for hours until the meat fell off the bone.",
        "Fresh basil and mozzarella topped the pizza right before it left the oven.",
        "The farmers market offered ripe tomatoes, crisp lettuce, and fragrant strawberries.",
        "He marinated the chicken overnight in a mixture of herbs and citrus juice.",
        "The souffle rose perfectly in the oven, earning applause from the dinner guests.",
        "A sprinkle of sea salt brought out the sweetness of the caramel.",
        "The curry simmered with coconut milk, turmeric, and a handful of fresh cilantro.",
        "Diners lined up outside the food truck for a taste of the famous tacos.",
    ],
    'Travel': [
        "She booked a flight to Tokyo months in advance to secure a cheaper fare.",
        "The couple spent their honeymoon exploring ancient temples across the Southeast Asian countryside.",
        "Tourists gathered at sunrise to watch the hot air balloons drift over the valley.",
        "He packed light for the trip, bringing only a small backpack and one jacket.",
        "The cruise ship stopped at three different islands during its week-long voyage.",
        "Travelers lined up at the airport to have their passports checked before boarding.",
        "The hiking trail offered stunning views of the coastline from the cliff tops.",
        "They rented a car to drive along the scenic highway toward the national park.",
        "The tour guide led visitors through the old town's narrow cobblestone streets.",
        "After a long flight, the family checked into their hotel and rested before sightseeing.",
        "The train wound slowly through the mountains, offering breathtaking views at every turn.",
        "She collected stamps in her passport from every country she had visited.",
        "The backpackers stayed in a small hostel near the beach for a few nights.",
        "Visitors explored the museum's ancient artifacts before wandering through the botanical gardens.",
        "The pilot announced a slight delay due to weather conditions at the destination airport.",
        "They watched the sunset from a rooftop terrace overlooking the historic old city.",
        "The travel agency arranged a guided tour of the region's famous vineyards.",
        "He missed his connecting flight and had to wait overnight at the airport.",
        "The family spent their vacation snorkeling around the coral reefs near the resort.",
        "Locals recommended a quiet village off the main tourist route for a peaceful stay.",
    ],
}

POOL = {
    'Sports': [
        "The midfielder delivered a perfect pass that led directly to the team's second goal.",
        "Weightlifters strained under the bar as they attempted to break the national record.",
        "The figure skater's flawless performance earned a standing ovation from the entire arena.",
        "After the final whistle, both teams shook hands and exchanged jerseys on the field.",
        "The golfer sank a long putt on the final hole to win the tournament outright.",
        "Fans cheered loudly as the relay team crossed the finish line in first place.",
        "The referee reviewed the replay carefully before awarding the controversial penalty kick.",
        "Local youth leagues held tryouts for the upcoming season of competitive club soccer.",
    ],
    'Finance': [
        "The company's quarterly profit exceeded forecasts, sending its stock price higher.",
        "He diversified his investment portfolio to reduce risk during volatile markets.",
        "The exchange rate fluctuated sharply after the surprise announcement from the treasury.",
        "Small businesses struggled to secure loans as banks tightened lending standards.",
        "The audit revealed several discrepancies in the company's financial statements.",
        "Shareholders voted to approve the proposed dividend increase at the annual meeting.",
        "The hedge fund manager bet heavily against the overvalued technology sector.",
        "Rising interest payments strained the government's already tight annual budget.",
    ],
    'Technology': [
        "The company launched a smartwatch that tracks sleep patterns and heart rate.",
        "Programmers used automated tests to catch bugs before the software shipped.",
        "The server crashed during peak traffic, taking the website offline for hours.",
        "Engineers designed a lighter laptop battery that lasts twice as long.",
        "The AI assistant can now answer questions using real-time search results.",
        "A firmware update improved the router's wireless signal strength significantly.",
        "The gaming console's latest update added support for higher resolution displays.",
        "Developers integrated facial recognition into the app's login screen for security.",
    ],
    'Food': [
        "The pasta was tossed in a creamy garlic sauce with grated parmesan cheese.",
        "She sliced the mango thinly and arranged it neatly on the plate.",
        "The stew simmered on low heat for hours, filling the kitchen with aroma.",
        "Fresh sourdough bread was served warm alongside a bowl of olive oil.",
        "The chef garnished the plate with microgreens and a drizzle of balsamic glaze.",
        "Homemade ice cream was churned slowly to achieve a rich, creamy texture.",
        "The salad combined crisp cucumbers, cherry tomatoes, and a tangy vinaigrette dressing.",
        "Roasted chestnuts were sold from carts on the cold winter streets.",
    ],
    'Travel': [
        "The travelers checked their luggage and headed toward the departure gate early.",
        "She wandered through the market stalls, browsing souvenirs from local artisans.",
        "The ferry crossed the strait, offering passengers a view of the distant coastline.",
        "They camped overnight near the base of the mountain before the sunrise hike.",
        "The resort offered guided snorkeling trips to the nearby coral reef.",
        "His itinerary included visits to three cities across two countries in ten days.",
        "The airline upgraded her seat after a lengthy delay at the connecting airport.",
        "Visitors climbed the ancient tower for a panoramic view of the entire city.",
    ],
}


def choice_q(instr, crit):
    return {'type': 'choice', 'instructions': instr, 'criteria': crit}


def cat_permutation(sentence_id):
    """这条测试句专属的 真类名->L 排列，种子只挂句子 id，和 k/组别无关。"""
    rng = random.Random('perm|' + sentence_id)
    cats = CATS[:]
    rng.shuffle(cats)
    return {c: LS[i] for i, c in enumerate(cats)}


def pick_examples(sentence_id, k):
    """返回 (sel, flat)：sel 是每类选中的 k 条例句，flat 是打乱顺序后的 (类名, 句子) 列表。
    种子挂 (句子id, k)，和 named/opaque/opaque_desc 无关——三组同一 k 下看到的例子完全一样。
    """
    if k == 0:
        return {c: [] for c in CATS}, []
    rng = random.Random('ex|%s|%d' % (sentence_id, k))
    sel = {c: rng.sample(POOL[c], k) for c in CATS}
    flat = [(c, t) for c in CATS for t in sel[c]]
    rng.shuffle(flat)
    return sel, flat


def build_job(cat, idx, group, k):
    sentence = TEST[cat][idx]
    sentence_id = '%s#%02d' % (cat, idx)
    cat2L = cat_permutation(sentence_id)
    l2cat = {v: c for c, v in cat2L.items()}
    sel, flat = pick_examples(sentence_id, k)

    if group == 'named':
        criteria = {c: c for c in CATS}
        state = {}
        state['examples'] = [{'text': t, 'label': c} for c, t in flat] if k else 'none given'
        state['text'] = sentence
        answer = cat
    elif group == 'opaque':
        criteria = {L: 'Category %s' % L for L in LS}
        state = {}
        state['examples'] = [{'text': t, 'label': cat2L[c]} for c, t in flat] if k else 'none given'
        state['text'] = sentence
        answer = cat2L[cat]
    elif group == 'opaque_desc':
        criteria = {}
        for L in LS:
            c = l2cat[L]
            criteria[L] = 'For example: ' + '; '.join('"%s"' % t for t in sel[c])
        state = {'text': sentence}
        answer = cat2L[cat]
    else:
        raise ValueError(group)

    key = '%s|%s|%d|%02d' % (group, cat, k, idx)
    meta = {'group': group, 'cat': cat, 'idx': idx, 'k': k, 'answer': answer}
    questions = {'label': choice_q(Q_LABEL, criteria)}
    return key, state, questions, meta


def build_all_jobs():
    jobs = []
    for cat in CATS:
        for idx in range(len(TEST[cat])):
            for k in (0, 1, 2, 4):
                jobs.append(build_job(cat, idx, 'named', k))
                jobs.append(build_job(cat, idx, 'opaque', k))
            for k in (1, 2, 4):
                jobs.append(build_job(cat, idx, 'opaque_desc', k))
    return jobs


def load():
    if os.path.exists(LOG):
        return json.load(open(LOG))
    return {}


def save(log):
    tmp = LOG + '.tmp'
    json.dump(log, open(tmp, 'w'), ensure_ascii=False)
    os.replace(tmp, LOG)


def run_jobs(log, jobs, workers=8, save_every=200):
    """jobs: [(key, state, questions, meta)]；跳过已成功的 key，失败的重发。每 save_every 条落盘一次。"""
    import jevkit as jev
    todo = [j for j in jobs if j[0] not in log or '_error' in log[j[0]]['resp']]
    print('共 %d 题，待发 %d' % (len(jobs), len(todo)))
    if not todo:
        return

    def one(j):
        k, st, q, meta = j
        r = jev.call(st, q)
        with LOCK:
            log[k] = {'meta': meta, 'resp': r}

    done = 0
    with ThreadPoolExecutor(max_workers=workers) as ex:
        futs = [ex.submit(one, j) for j in todo]
        for f in as_completed(futs):
            f.result()
            done += 1
            if done % save_every == 0:
                with LOCK:
                    save(log)
                print('已完成 %d/%d' % (done, len(todo)))
    save(log)
    print(jev.spend())


# ---------------- 报告 ----------------
def wilson(x, n, z=1.96):
    if n == 0:
        return (0.0, 0.0, 0.0)
    p = x / n
    denom = 1 + z * z / n
    center = (p + z * z / (2 * n)) / denom
    margin = (z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))) / denom
    return (p, max(0.0, center - margin), min(1.0, center + margin))


CELLS = [('named', k) for k in (0, 1, 2, 4)] + [('opaque', k) for k in (0, 1, 2, 4)] + \
        [('opaque_desc', k) for k in (1, 2, 4)]


def report():
    log = load()
    bad = [k for k, v in log.items() if '_error' in v.get('resp', {})]
    print('日志 %d 条，失败 %d 条' % (len(log), len(bad)))
    if bad:
        print('失败 key 示例：', bad[:10])

    rows = {}
    for k, v in log.items():
        if '_error' in v.get('resp', {}):
            continue
        m = v['meta']
        a = v['resp']['answers']['label']
        c = rows.setdefault((m['group'], m['k']), [0, 0])
        c[1] += 1
        c[0] += a['choice'] == m['answer']

    print('\n== d. few-shot 文本分类：各档准确率（n=100，瞎猜 20%）==')
    print('%-12s %3s | %-8s %6s  95%%CI' % ('组', 'k', '正确/n', '准确率'))
    for group, k in CELLS:
        c = rows.get((group, k))
        if not c:
            continue
        x, n = c
        p, lo, hi = wilson(x, n)
        print('%-12s %3d | %-8s %5.1f%%  [%.3f, %.3f]' % (group, k, '%d/%d' % (x, n), p * 100, lo, hi))


# ---------------- 冒烟 ----------------
def smoke():
    jobs = build_all_jobs()
    by_key = {j[0]: j for j in jobs}
    print('== 完整请求体检查（不发请求）==')
    for group in ('named', 'opaque', 'opaque_desc'):
        k = 2 if group != 'opaque_desc' else 2
        key = '%s|Sports|%d|00' % (group, k)
        _, st, q, meta = by_key[key]
        print('\n--- %s ---' % key)
        print('meta =', json.dumps(meta, ensure_ascii=False))
        print('state =', json.dumps(st, ensure_ascii=False, indent=2))
        print('questions =', json.dumps(q, ensure_ascii=False, indent=2))

    print('\n== 极小规模真实调用：Sports#00 与 Finance#00，全部 11 档，共 22 题 ==')
    smoke_jobs = []
    for cat in ('Sports', 'Finance'):
        for group, k in CELLS:
            smoke_jobs.append(by_key['%s|%s|%d|00' % (group, cat, k)])
    log = load()
    run_jobs(log, smoke_jobs, workers=8, save_every=200)
    save(log)
    ok = sum(1 for j in smoke_jobs if '_error' not in log[j[0]]['resp'])
    print('冒烟 %d/%d 成功' % (ok, len(smoke_jobs)))
    for j in smoke_jobs[:3]:
        k = j[0]
        r = log[k]['resp']
        print(k, '->', r.get('answers', {}).get('label', r))


def main():
    if len(sys.argv) < 2 or sys.argv[1] not in ('smoke', 'run', 'report'):
        print(__doc__)
        return
    if sys.argv[1] == 'report':
        report()
        return
    if sys.argv[1] == 'smoke':
        smoke()
        return
    log = load()
    run_jobs(log, build_all_jobs())
    report()


if __name__ == '__main__':
    main()
