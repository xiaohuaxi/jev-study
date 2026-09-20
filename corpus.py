# -*- coding: utf-8 -*-
"""12 个客服工单用例，中英平行，标签在构造时即确定（不是公开评测集）。"""

DEPTS_ZH = {"billing": "账单、支付、发票、退款、报价",
            "frontend": "页面显示、渲染、浏览器相关",
            "account": "账号、登录、权限、成员管理",
            "api": "接口调用、集成、webhook"}
DEPTS_EN = {"billing": "billing, payments, invoices, refunds, quotes",
            "frontend": "page display, rendering, browser issues",
            "account": "accounts, login, permissions, member management",
            "api": "API calls, integration, webhooks"}
LV_ZH = ["可以等下个版本", "本周内处理", "正在影响业务需立即处理"]
LV_EN = ["can wait for the next release", "handle within this week",
         "actively hurting the business, handle immediately"]
Q_DEPT_ZH, Q_DEPT_EN = "哪个团队最适合处理这个工单？", "Which team should own this ticket?"
Q_BUG_ZH,  Q_BUG_EN  = "这是否属于软件故障？", "Is this a software defect?"
Q_URG_ZH,  Q_URG_EN  = "这个工单有多紧急？", "How urgent is this ticket?"

# (id, 中文, 英文, 正确部门, 是否故障, 预期紧急档 0-2)
CASES = [
 ("B1", "上个月被重复扣了两笔一模一样的钱，共 1998 元，只下过一个订单。",
        "I was charged twice for the same amount last month, 1998 CNY total, though I only placed one order.",
        "billing", True, 2),
 ("B2", "发票抬头写错了，公司名少了一个字，需要作废重开一张。",
        "The invoice title is wrong, one character is missing from the company name; please void it and reissue.",
        "billing", False, 0),
 ("B3", "我们团队想从专业版升到企业版，想先知道 50 个座位的报价。",
        "Our team wants to move from Pro to Enterprise; we'd like a quote for 50 seats first.",
        "billing", False, 0),
 ("F1", "付款成功后确认页整页空白，Chrome 和 Safari 都能复现，扣款短信已经收到了。",
        "After a successful payment the confirmation page renders entirely blank, reproducible in Chrome and Safari; the charge SMS already arrived.",
        "frontend", True, 2),
 ("F2", "报表页的导出按钮点了没有任何反应，控制台报 undefined is not a function。",
        "The export button on the report page does nothing when clicked; the console says undefined is not a function.",
        "frontend", True, 1),
 ("F3", "在 Safari 上标题和正文的字重叠在一起了，Chrome 上正常，只是不好看。",
        "On Safari the heading and body text overlap each other; Chrome is fine. It only looks bad.",
        "frontend", True, 0),
 ("A1", "我绑定的手机号已经停用了，收不到验证码，现在完全登不进账号，需要人工改绑。",
        "The phone number on my account is deactivated so I can't receive the code and cannot sign in at all; I need it rebound manually.",
        "account", False, 2),
 ("A2", "有个同事已经离职了，要把他在工作区里的所有权限收回来。",
        "A colleague has left the company; please revoke all of their permissions in the workspace.",
        "account", False, 1),
 ("A3", "重置密码的邮件连点三次都没收到，垃圾箱也确认过了，换了邮箱域名同样收不到。",
        "I clicked reset-password three times and never received the email; I checked spam, and another mail domain also gets nothing.",
        "account", True, 1),
 ("P1", "调用下单接口偶发返回 500，大约二十次里有一次，重试就能成功。",
        "The create-order endpoint intermittently returns 500, roughly one in twenty calls; retrying succeeds.",
        "api", True, 1),
 ("P2", "订单状态变更的 webhook 我们这边一直收不到，服务器日志显示根本没有请求进来。",
        "We never receive the order-status webhook; our server logs show no incoming request at all.",
        "api", True, 2),
 ("P3", "想确认一下接口的限流额度是多少，文档上没写清楚每分钟能发多少请求。",
        "I'd like to confirm the rate limit; the docs don't state how many requests per minute are allowed.",
        "api", False, 0),
]

# 中文特有表达：(id, 文本, 要判的事, 我预期的方向)
TRICKY = [
 ("讽刺",   "贵司这响应速度真是快得让人感动，工单提了六天了，感谢感谢。", "这位客户是否对服务不满？", "满意度低=是"),
 ("反问",   "这也算能用？", "这位客户是否对服务不满？", "满意度低=是"),
 ("双重否定", "倒也不能说完全不能用，就是每次都要重试三四遍。", "这位客户是否遇到了产品问题？", "有问题=是"),
 ("委婉拒绝", "方案我们收到了，挺有意思的，回去再研究研究，有需要联系你们。", "这个客户是否倾向于成交？", "倾向不成交=否"),
 ("客套", "非常感谢贵司的支持，我们对当前方案非常满意，后续续约没有问题。", "这个客户是否倾向于成交？", "倾向成交=是"),
 ("网络用语", "这功能真的绝了，yyds，比之前那个好用一百倍", "这条评价是否为正面？", "正面=是"),
 ("错别字", "我帐号登陆不上去了，密码明明是对的，一直说身份验正失败。", "这是否属于登录问题？", "是"),
 ("语音转写", "那个啥 我这个 就是那个付款完了以后 它那个页面就白了 什么都没有 你看这个怎么弄",
            "这是否属于页面显示故障？", "是"),
 ("繁体",   "付款之後確認頁面變成空白，換了兩個瀏覽器仍然如此。", "这是否属于页面显示故障？", "是"),
 ("中英混排", "付款后 confirmation page 直接 blank 了，两个 browser 都 reproduce 了。", "这是否属于页面显示故障？", "是"),
]

# 同一语义的多种写法，测鲁棒性
VARIANTS = [
 ("简体标准", "付款成功后确认页整页空白，换了两个浏览器仍然如此。"),
 ("繁体",     "付款成功後確認頁整頁空白，換了兩個瀏覽器仍然如此。"),
 ("全角标点", "付款成功后确认页整页空白，换了两个浏览器仍然如此！！！"),
 ("带 emoji", "付款成功后确认页整页空白😭 换了两个浏览器仍然如此🙏"),
 ("口语流水", "就是付完钱那个页面它就白了啊 我换了两个浏览器都一样的"),
 ("极简",     "付款后白屏"),
 ("英文",     "After a successful payment the confirmation page is entirely blank; two browsers behave the same."),
]

# token 经济性：同义中英文对照
PAIRS = [
 ("付款成功后确认页整页空白，换了两个浏览器仍然如此。",
  "After a successful payment the confirmation page is entirely blank; two browsers behave the same."),
 ("我想把发票抬头改成公司全名，需要作废重开。",
  "I want the invoice title changed to the full company name; it needs to be voided and reissued."),
 ("调用下单接口偶发返回五百，重试就能成功。",
  "The create-order endpoint intermittently returns a 500; retrying succeeds."),
 ("有个同事离职了，请把他在工作区的全部权限收回。",
  "A colleague has left; please revoke all of their permissions in the workspace."),
 ("这个功能非常好用，比上一版强太多了，强烈推荐。",
  "This feature works really well, far better than the previous version. Strongly recommended."),
]
