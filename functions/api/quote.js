// Balance Lab 시세 중계 (Cloudflare Pages Function, 2026-11-13 사용자 확정)
// 화면이 열려 있는 동안 1분마다 부름 → 네이버(비공식) 현재가를 받아 그대로 돌려줌. Claude 토큰 0, 주문 기능 없음, 키 없음.
// 같은 주소라 Cloudflare Access 로그인 잠금이 그대로 적용된다.
// GET /api/quote?codes=005930,000660&flows=1
const H = { "User-Agent": "Mozilla/5.0", "Referer": "https://finance.naver.com/" };
const num = s => { const v = parseFloat(String(s ?? "").replace(/,/g, "")); return isNaN(v) ? null : v; };
async function j(url) {
  try { const r = await fetch(url, { headers: H, cf: { cacheTtl: 30, cacheEverything: true } }); return r.ok ? await r.json() : null; }
  catch (e) { return null; }
}
export async function onRequestGet({ request }) {
  const u = new URL(request.url);
  const codes = [...new Set((u.searchParams.get("codes") || "").split(",").filter(c => /^\d{6}$/.test(c)))].slice(0, 80);
  const chunks = []; for (let i = 0; i < codes.length; i += 40) chunks.push(codes.slice(i, i + 40));
  const flows = u.searchParams.get("flows") === "1";
  const reqs = [j("https://polling.finance.naver.com/api/realtime/domestic/index/KOSPI,KOSDAQ"),
    ...chunks.map(c => j("https://polling.finance.naver.com/api/realtime/domestic/stock/" + c.join(",")))];
  if (flows) reqs.push(j("https://m.stock.naver.com/api/index/KOSPI/integration"), j("https://m.stock.naver.com/api/index/KOSDAQ/integration"));
  const res = await Promise.all(reqs);
  const ix = res[0], st = res.slice(1, 1 + chunks.length), fl = flows ? res.slice(1 + chunks.length) : [];
  const now = new Date(Date.now() + 9 * 3600e3).toISOString().slice(0, 16).replace("T", " ");
  const out = { at: now, source: "네이버(비공식) 현재가 · 화면 열림 중 1분", markets: [], quotes: {} };
  ((ix && ix.datas) || []).forEach((x, i) => {
    const m = { market: x.itemCode, price: num(x.closePrice), change_pct: num(x.fluctuationsRatio), open: num(x.openPrice), high: num(x.highPrice), low: num(x.lowPrice),
      status: x.marketStatus == "OPEN" ? "OPEN" : "CLOSE", at: (x.localTradedAt || "").slice(0, 16).replace("T", " ") };
    const d = fl.find((f, k) => (k == 0 ? "KOSPI" : "KOSDAQ") == x.itemCode);
    const t = d && d.dealTrendInfo;
    if (t) Object.assign(m, { individual_eok: num(t.personalValue), foreign_eok: num(t.foreignValue), institution_eok: num(t.institutionalValue) });
    const ud = d && d.upDownStockInfo;
    if (ud) Object.assign(m, { up: (num(ud.riseCount) || 0) + (num(ud.upperCount) || 0), upper: num(ud.upperCount) || 0, down: (num(ud.fallCount) || 0) + (num(ud.lowerCount) || 0), lower: num(ud.lowerCount) || 0, flat: num(ud.steadyCount) || 0 });
    out.markets.push(m);
  });
  st.forEach(d => ((d && d.datas) || []).forEach(x => { out.quotes[x.itemCode] = { price: num(x.closePrice), change_pct: num(x.fluctuationsRatio), at: (x.localTradedAt || "").slice(0, 16) }; }));
  return new Response(JSON.stringify(out), { headers: { "content-type": "application/json; charset=utf-8", "cache-control": "no-store" } });
}
