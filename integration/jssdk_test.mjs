import { TypeSafeClient, noul, choice, score } from "@typesafe-ai/sdk";

// 官方 SDK，只改 key 和 baseURL，指向 OpenRouter
const client = new TypeSafeClient({
  apiKey: process.env.OPENROUTER_API_KEY ?? process.env.API_KEY_OPENROUTER,
  baseURL: "https://openrouter.ai/api",
});
console.log("client.baseURL =", client.baseURL);

const t0 = Date.now();
const res = await client.systemOne({
  model: "jev-1.13",
  state: {
    ticket: "付款以后页面变成空白，换了两个浏览器仍然如此。",
    tier: "enterprise",
  },
  questions: {
    is_bug: noul("这是否属于软件故障？"),
    dept: choice("哪个团队最适合处理？", { billing: null, frontend: null, account: null }),
    urgency: score("有多紧急？", ["可以等", "本周处理", "立即处理"]),
  },
});
console.log("elapsed:", Date.now() - t0, "ms");
console.log(JSON.stringify(res, null, 2));
