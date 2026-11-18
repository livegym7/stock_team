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
  const codes = [...new Set((u.searchParams.get("codes") || "").split(",").filter(c => /^\d{6}$/.test(c)))].slice(0, 400);   // 셋업 보드 같은 업종 종목(장중 인더스트리 액션)까지 받으려고 200 → 400 (2026-11-18)
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
  // 시가·고가·저가·거래량 = 오늘 캔들용 (2026-11-16)
  st.forEach(d => ((d && d.datas) || []).forEach(x => { out.quotes[x.itemCode] = { price: num(x.closePrice), change_pct: num(x.fluctuationsRatio), at: (x.localTradedAt || "").slice(0, 16), open: num(x.openPrice), high: num(x.highPrice), low: num(x.lowPrice), vol: num(x.accumulatedTradingVolume) }; }));
  // 최근 5일 투자자별 순매수 (2026-11-13): ?trend=005930 → 외국인·기관·개인 수량 + 종가 (네이버 투자자별 매매동향)
  const tc = u.searchParams.get("trend");
  if (tc && /^\d{6}$/.test(tc)) {
    const t = await j(`https://m.stock.naver.com/api/stock/${tc}/trend?pageSize=5`);
    out.trend = ((Array.isArray(t) ? t : []) || []).map(x => [x.bizdate, num(x.foreignerPureBuyQuant), num(x.organPureBuyQuant), num(x.individualPureBuyQuant), num(x.closePrice)]).reverse();
  }
  // 거래대금 상위 100 (2026-11-13): ?top=1 이면 코스피·코스닥 거래대금 순위를 합쳐 ETF·ETN·스팩·우선주·리츠 제외
  if (u.searchParams.get("top") === "1") {
    const pages = await Promise.all(["KOSPI", "KOSDAQ"].flatMap(m => [1, 2].map(p => j(`https://m.stock.naver.com/api/stocks/priceTop/${m}?page=${p}&pageSize=100`).then(d => ({ m, d })))));
    const plain = s => { const n = s.stockName || ""; return s.stockEndType == "stock" && !n.includes("스팩") && !n.includes("리츠") && !n.includes("(전환)") && !(/(우|우B|우C)$/.test(n) && n.length > 2); };
    const rows = [];
    pages.forEach(({ m, d }) => ((d && d.stocks) || []).filter(plain).forEach(x => rows.push({ code: x.itemCode, name: x.stockName, market: m, price: num(x.closePrice), chg: num(x.fluctuationsRatio),
      value_eok: Math.round((num(x.accumulatedTradingValue) || 0) / 100), cap_eok: num(x.marketValue), at: (x.localTradedAt || "").slice(0, 16).replace("T", " ") })));
    const seen = new Set();
    out.top = rows.sort((a, b) => b.value_eok - a.value_eok).filter(r => !seen.has(r.code) && seen.add(r.code)).slice(0, 100);
  }
  return new Response(JSON.stringify(out), { headers: { "content-type": "application/json; charset=utf-8", "cache-control": "no-store" } });
}
