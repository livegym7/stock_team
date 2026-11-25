// Balance Lab 시세 중계 (Cloudflare Pages Function, 2026-11-13 사용자 확정)
// 화면이 열려 있는 동안 1분마다 부름 → 네이버(비공식) 현재가를 받아 그대로 돌려줌. Claude 토큰 0, 주문 기능 없음, 키 없음.
// 같은 주소라 Cloudflare Access 로그인 잠금이 그대로 적용된다.
// GET /api/quote?codes=005930,000660&flows=1&world=1&night=1&hot=1
const H = { "User-Agent": "Mozilla/5.0", "Referer": "https://finance.naver.com/" };
const num = s => { const v = parseFloat(String(s ?? "").replace(/,/g, "")); return isNaN(v) ? null : v; };
async function j(url) {
  try { const r = await fetch(url, { headers: H, cf: { cacheTtl: 30, cacheEverything: true } }); return r.ok ? await r.json() : null; }
  catch (e) { return null; }
}
export async function onRequestGet({ request }) {
  const u = new URL(request.url);
  const codes = [...new Set((u.searchParams.get("codes") || "").split(",").filter(c => /^\d{6}$/.test(c)))].slice(0, 600);   // 셋업 보드 같은 업종 종목(장중 인더스트리 액션)까지 받으려고 200 → 400 (2026-11-18)
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
  // 피어 지수 장중 값 (2026-11-24): ?world=1 → 닛케이·대만 가권·상해종합 (네이버 해외 지수, 거래소 규정상 15~20분 지연)
  if (u.searchParams.get("world") === "1") {
    const W = await j("https://polling.finance.naver.com/api/realtime/worldstock/index/.N225,.TWII,.SSEC");
    const SYM = { ".N225": "^N225", ".TWII": "^TWII", ".SSEC": "000001.SS" };
    out.world = {};
    ((W && W.datas) || []).forEach(x => { const s = SYM[x.reutersCode]; if (!s) return;
      out.world[s] = { price: num(x.closePrice), change_pct: num(x.fluctuationsRatio), open: num(x.openPrice), high: num(x.highPrice), low: num(x.lowPrice),
        status: x.marketStatus, at: (x.localTradedAt || "").slice(0, 16), delay: (x.stockExchangeType || {}).delayTime ?? null }; });
  }
  // 나스닥 100 선물 + EWY (2026-11-24): ?night=1 → 장중·장 종료 뒤에도 보는 값. 선물 = 네이버 해외선물(10분 지연), EWY = 야후(정규장 밖이면 시간외 가격, 마지막 정규장 종가 대비)
  if (u.searchParams.get("night") === "1") {
    const kst = t => new Date(t + 9 * 3600e3).toISOString().slice(0, 16).replace("T", " ");
    const [F, E] = await Promise.all([j("https://polling.finance.naver.com/api/realtime/worldstock/futures/NQcv1"), j("https://query1.finance.yahoo.com/v8/finance/chart/EWY?interval=5m&range=1d&includePrePost=true")]);
    out.night = { at: now };
    const x = F && F.datas && F.datas[0];
    if (x) out.night.nq = { price: num(x.closePrice), change_pct: num(x.fluctuationsRatio), status: x.marketStatus, at: x.localTradedAt ? kst(Date.parse(x.localTradedAt)) : "", delay: (x.stockExchangeType || {}).delayTime ?? null };
    try {
      const r = E.chart.result[0], m = r.meta, ts = r.timestamp || [], cl = r.indicators.quote[0].close || [];
      let k = cl.length - 1; while (k >= 0 && !cl[k]) k--;
      if (k >= 0) { const reg = (m.currentTradingPeriod || {}).regular || {}, inreg = ts[k] >= reg.start && ts[k] < reg.end, base = inreg ? m.chartPreviousClose : m.regularMarketPrice;
        out.night.ewy = { price: Math.round(cl[k] * 100) / 100, change_pct: base ? Math.round((cl[k] / base - 1) * 10000) / 100 : null, at: kst(ts[k] * 1000), session: inreg ? "정규장" : "시간외" }; }
    } catch (e) {}
  }
  // 지금 주목받는 종목 (2026-11-24): ?hot=1 → 네이버 검색 상위 30 (업종 묶음·내 목록 꼬리표는 화면이 붙임)
  if (u.searchParams.get("hot") === "1") {
    const T = await j("https://m.stock.naver.com/api/stocks/searchTop/all?page=1&pageSize=30");
    const items = ((T && T.stocks) || []).map((s, i) => ({ rank: i + 1, code: s.itemCode, name: s.stockName, price: num(s.closePrice), chg: num(s.fluctuationsRatio), value_eok: Math.round((num(s.accumulatedTradingValue) || 0) / 100), end: s.stockEndType })).filter(s => s.end == "stock" && s.code);
    if (items.length) out.hot = { made_at: now, items };
  }
  return new Response(JSON.stringify(out), { headers: { "content-type": "application/json; charset=utf-8", "cache-control": "no-store" } });
}
