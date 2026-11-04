"""시황 데이터 (분석 중심 트레이딩룸용). 모두 숫자 수집이라 Claude 사용량 0.

    python3 tools/market_pulse.py pulse     # 시장 온도계: 코스피·코스닥 투자자별 순매수(억 원)·프로그램·오른/내린 종목 수·52주 신고가/신저가 수,
                                            #   업종·테마 등락, 상승·하락 상위 종목 (네이버, 장중 실시간)
    python3 tools/market_pulse.py flows     # 수급 추적: 시총 상위 300종목 외국인·기관 순매수(금액 추정)·연속 매수일·업종별 합계,
                                            #   업종 수익률(1일·5일·20일) (네이버 종목별 투자자 동향, 장 마감 뒤 확정)
    python3 tools/market_pulse.py econ      # 경제지표 결과: 실제치 vs 예상치 (TradingView 경제 캘린더, 지난 7일 ~ 앞으로 7일)

결과는 data/market/에 저장하고 JSON으로 출력한다. 출처: 네이버 증권(비공식), TradingView(비공식).
"""
import argparse
import json
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import DATA, http_get  # noqa: E402

KST = timezone(timedelta(hours=9))
OUT = DATA / "market"
API = "https://m.stock.naver.com/api"


def get(url, params=None):
    return json.loads(http_get(url, params, timeout=15, retries=2))


def num(s):
    """'+10,667' → 10667.0 / 'N/A' → None"""
    if s is None:
        return None
    s = str(s).replace(",", "").replace("%", "").strip()
    try:
        return float(s)
    except ValueError:
        return None


def plain(name):
    """우선주·스팩·ETF 같은 것 빼기"""
    return not (name.endswith(("우", "우B", "우C")) or "스팩" in name or "(전환)" in name)


# ---------------- 1) 시장 온도계 ----------------
def market_one(m):
    it = get(f"{API}/index/{m}/integration")
    bs = get(f"{API}/index/{m}/basic")
    d, pg, ud = it.get("dealTrendInfo") or {}, it.get("programTrendInfo") or {}, it.get("upDownStockInfo") or {}
    tv = next((x["value"] for x in it.get("totalInfos", []) if x["code"] == "accumulatedTradingValue"), None)
    hi = get(f"{API}/stocks/high52week/{m}", {"page": 1, "pageSize": 1}).get("totalCount")
    lo = get(f"{API}/stocks/low52week/{m}", {"page": 1, "pageSize": 1}).get("totalCount")
    return {
        "market": m, "name": bs.get("stockName"), "price": num(bs.get("closePrice")), "change_pct": num(bs.get("fluctuationsRatio")),
        "status": bs.get("marketStatus"), "at": (bs.get("localTradedAt") or "")[:16].replace("T", " "),
        "deal_date": d.get("bizdate"),
        "individual_eok": num(d.get("personalValue")), "foreign_eok": num(d.get("foreignValue")), "institution_eok": num(d.get("institutionalValue")),
        "program_eok": num(pg.get("indexTotalReal")),
        "trading_value_eok": round(num(re.sub(r"[^\d,]", "", tv or "")) / 100) if tv and num(re.sub(r"[^\d,]", "", tv)) else None,  # 백만 → 억
        "up": int(num(ud.get("riseCount")) or 0) + int(num(ud.get("upperCount")) or 0), "upper": int(num(ud.get("upperCount")) or 0),
        "down": int(num(ud.get("fallCount")) or 0) + int(num(ud.get("lowerCount")) or 0), "lower": int(num(ud.get("lowerCount")) or 0),
        "flat": int(num(ud.get("steadyCount")) or 0), "high52": hi, "low52": lo,
    }


def groups(kind):
    out, page = [], 1
    while True:
        d = get(f"{API}/stocks/{kind}", {"page": page, "pageSize": 100})
        out += d.get("groups") or []
        if page * 100 >= (d.get("totalCount") or 0):
            break
        page += 1
    return [{"no": g["no"], "name": g["name"], "change_pct": num(g.get("changeRate")), "n": g.get("totalCount"),
             "up": g.get("riseCount"), "down": g.get("fallCount")} for g in out]


def movers(min_cap_eok=1000):
    rows = []
    for side in ("up", "down"):
        for m in ("KOSPI", "KOSDAQ"):
            for s in get(f"{API}/stocks/{side}/{m}", {"page": 1, "pageSize": 100}).get("stocks") or []:
                cap = num(s.get("marketValue"))   # 억 원
                if s.get("stockEndType") != "stock" or not plain(s["stockName"]) or not cap or cap < min_cap_eok:
                    continue
                rows.append({"name": s["stockName"], "code": s["itemCode"], "market": m, "price": num(s.get("closePrice")),
                             "change_pct": num(s.get("fluctuationsRatio")), "value_eok": round((num(s.get("accumulatedTradingValue")) or 0) / 100),
                             "cap_eok": cap, "limit": (s.get("compareToPreviousPrice") or {}).get("name") in ("UPPER_LIMIT", "LOWER_LIMIT")})
    up = sorted([r for r in rows if (r["change_pct"] or 0) > 0], key=lambda r: -r["change_pct"])[:20]
    down = sorted([r for r in rows if (r["change_pct"] or 0) < 0], key=lambda r: r["change_pct"])[:20]
    return up, down


def pulse():
    now = datetime.now(KST)
    mk = [market_one(m) for m in ("KOSPI", "KOSDAQ")]
    ind, th = groups("industry"), groups("theme")
    up, down = movers()
    ind.sort(key=lambda g: -(g["change_pct"] or 0))
    th = sorted([t for t in th if (t["n"] or 0) >= 4], key=lambda g: -(g["change_pct"] or 0))
    res = {"at": now.strftime("%Y-%m-%d %H:%M"), "markets": mk, "industries": ind, "themes_up": th[:12], "themes_down": th[-12:][::-1],
           "movers_up": up, "movers_down": down, "source": "네이버 증권(비공식) · 시간외(NXT) 시세가 섞일 수 있음"}
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "pulse_latest.json").write_text(json.dumps(res, ensure_ascii=False), encoding="utf-8")
    day = (OUT / "days")
    day.mkdir(exist_ok=True)
    (day / f"{now:%Y-%m-%d}.json").write_text(json.dumps({k: res[k] for k in ("at", "markets")} | {"industries": ind}, ensure_ascii=False), encoding="utf-8")
    return res


# ---------------- 2) 수급 추적 ----------------
def stock_trend(code):
    try:
        rows = get(f"{API}/stock/{code}/trend", {"pageSize": 21})
    except Exception:
        return None
    out = []
    for r in rows:
        c = num(r.get("closePrice"))
        out.append({"date": r["bizdate"], "close": c, "f": num(r.get("foreignerPureBuyQuant")) or 0,
                    "i": num(r.get("organPureBuyQuant")) or 0, "hold": num(r.get("foreignerHoldRatio"))})
    return out


def streak(vals):
    """최근부터 같은 방향(순매수 +, 순매도 −)이 며칠 이어졌나. +면 연속 매수일, −면 연속 매도일"""
    if not vals or vals[0] == 0:
        return 0
    sgn, n = (1 if vals[0] > 0 else -1), 0
    for v in vals:
        if v * sgn > 0:
            n += 1
        else:
            break
    return n * sgn


def flows(n=300, max_age_h=3):
    cache = OUT / "flows_latest.json"
    if cache.exists() and time.time() - cache.stat().st_mtime < max_age_h * 3600:
        return json.loads(cache.read_text(encoding="utf-8"))
    from sector_map import custom_map
    from universe import load as load_universe
    uni = sorted([s for s in load_universe()["stocks"] if plain(s["name"]) and s.get("market_cap_eok")],
                 key=lambda s: -s["market_cap_eok"])[:n]
    with ThreadPoolExecutor(6) as ex:
        trends = list(ex.map(lambda s: stock_trend(s["code"]), uni))
    cmap = custom_map()
    stocks, last_date = [], None
    for s, tr in zip(uni, trends):
        if not tr or not tr[0]["close"]:
            continue
        last_date = max(last_date or "", tr[0]["date"])
        eok = lambda q, c: q * c / 1e8   # noqa: E731 (수량 × 종가 = 금액 추정, 억 원)
        f1, i1 = eok(tr[0]["f"], tr[0]["close"]), eok(tr[0]["i"], tr[0]["close"])
        f5 = sum(eok(r["f"], r["close"] or 0) for r in tr[:5])
        i5 = sum(eok(r["i"], r["close"] or 0) for r in tr[:5])
        cl = [r["close"] for r in tr if r["close"]]
        ret = lambda k: round((cl[0] / cl[k] - 1) * 100, 2) if len(cl) > k and cl[k] else None   # noqa: E731
        grp = cmap.get(s["code"]) or s.get("industry") or "기타"
        stocks.append({"name": s["name"], "code": s["code"], "group": grp, "cap_eok": s["market_cap_eok"], "date": tr[0]["date"],
                       "f1": round(f1), "i1": round(i1), "f5": round(f5), "i5": round(i5),
                       "f_streak": streak([r["f"] for r in tr]), "i_streak": streak([r["i"] for r in tr]),
                       "r1": ret(1), "r5": ret(5), "r20": ret(20), "hold": tr[0]["hold"]})
    stocks = [x for x in stocks if x["date"] == last_date]   # 같은 날짜 기준만
    agg = {}
    for x in stocks:
        g = agg.setdefault(x["group"], {"group": x["group"], "n": 0, "f1": 0, "i1": 0, "f5": 0, "i5": 0, "cap": 0, "r1w": 0, "r5w": 0, "r20w": 0, "names": []})
        g["n"] += 1
        for k in ("f1", "i1", "f5", "i5"):
            g[k] += x[k]
        g["cap"] += x["cap_eok"]
        for k, rk in (("r1w", "r1"), ("r5w", "r5"), ("r20w", "r20")):
            g[k] += (x[rk] or 0) * x["cap_eok"]
        g["names"].append(x["name"])
    sectors = []
    for g in agg.values():
        cap = g.pop("cap") or 1
        r1, r5, r20 = g.pop("r1w"), g.pop("r5w"), g.pop("r20w")
        sectors.append({**g, "r1": round(r1 / cap, 2), "r5": round(r5 / cap, 2), "r20": round(r20 / cap, 2), "names": g["names"][:5]})
    sectors.sort(key=lambda g: -(g["f1"] + g["i1"]))
    top = lambda k, rev=True, m=12: sorted(stocks, key=lambda x: x[k], reverse=rev)[:m]   # noqa: E731
    res = {"at": datetime.now(KST).strftime("%Y-%m-%d %H:%M"), "date": last_date, "n": len(stocks),
           "foreign_buy": top("f1"), "foreign_sell": top("f1", False), "inst_buy": top("i1"), "inst_sell": top("i1", False),
           "both_buy": sorted([x for x in stocks if x["f1"] > 0 and x["i1"] > 0], key=lambda x: -(x["f1"] + x["i1"]))[:12],
           "f_streak": sorted([x for x in stocks if x["f_streak"] >= 3], key=lambda x: (-x["f_streak"], -x["f5"]))[:15],
           "i_streak": sorted([x for x in stocks if x["i_streak"] >= 3], key=lambda x: (-x["i_streak"], -x["i5"]))[:15],
           "sectors": sectors, "stocks": stocks,
           "source": f"네이버 종목별 투자자 동향(비공식) · 시총 상위 {n}종목 · 금액 = 순매수 수량 × 종가 (추정) · {last_date} 기준"}
    OUT.mkdir(parents=True, exist_ok=True)
    cache.write_text(json.dumps(res, ensure_ascii=False), encoding="utf-8")
    return res


# ---------------- 6) 경제지표 결과 ----------------
KEY_EVENTS = re.compile(r"CPI|PPI|PCE|Non ?Farm|Nonfarm|Unemployment|Jobless|JOLT|Interest Rate|Fed |FOMC|GDP|Retail Sales|ISM|PMI|"
                        r"Consumer Confidence|Michigan|Payrolls|Inflation|Industrial Production|Trade Balance|Exports YoY|Durable", re.I)
KO_EXTRA = [(r"Core Inflation Rate YoY", "근원 물가(전년비)"), (r"Core Inflation Rate MoM", "근원 물가(전월비)"), (r"Core PCE", "근원 PCE 물가"),
            (r"Inflation Rate YoY", "물가상승률(전년비)"), (r"Inflation Rate MoM", "물가상승률(전월비)"), (r"^Interest Rate$", "기준금리"),
            (r"Balance of Trade", "무역수지"), (r"Chicago PMI", "시카고 PMI"), (r"Nonfarm Productivity", "비농업 생산성"),
            (r"Non ?Farm Payrolls", "비농업 고용"), (r"ADP Employment", "ADP 민간 고용"), (r"Initial Jobless Claims", "신규 실업수당 청구"),
            (r"Fed Interest Rate Decision", "미국 기준금리 결정"), (r"Interest Rate Decision", "기준금리 결정"), (r"JOLTs Job Openings", "구인 건수(JOLTS)"),
            (r"Michigan Consumer Sentiment", "미시간대 소비심리"), (r"Exports YoY", "수출(전년비)"), (r"Imports YoY", "수입(전년비)"),
            (r"Durable Goods Orders", "내구재 주문"), (r"ISM Services PMI", "ISM 서비스업 지수"), (r"ISM Manufacturing PMI", "ISM 제조업 지수"),
            (r"GDP Growth Rate", "GDP 성장률"), (r"Retail Sales MoM", "소매판매(전월비)"), (r"PCE Price Index", "PCE 물가"),
            (r"Unemployment Rate", "실업률"), (r"Producer Price|PPI", "PPI(생산자물가)"), (r"Consumer Price Index|CPI", "CPI(소비자물가)")]
NATION = {"US": "🇺🇸", "KR": "🇰🇷", "CN": "🇨🇳", "JP": "🇯🇵", "EU": "🇪🇺"}


def ko_name(t):
    for pat, ko in KO_EXTRA:
        if re.search(pat, t, re.I):
            return ko
    try:
        from calendar_fetch import ko_title
        return ko_title(t)
    except Exception:
        return t


def econ(back=7, ahead=7):
    now = datetime.now(timezone.utc)
    d = json.loads(http_get("https://economic-calendar.tradingview.com/events", {
        "from": (now - timedelta(days=back)).strftime("%Y-%m-%dT00:00:00.000Z"),
        "to": (now + timedelta(days=ahead)).strftime("%Y-%m-%dT23:59:59.000Z"), "countries": "US,KR,CN,JP,EU"},
        timeout=20, retries=2, headers={"Origin": "https://www.tradingview.com", "User-Agent": "Mozilla/5.0"}))
    rows = []
    for x in d.get("result") or []:
        imp, title = x.get("importance", -1), x.get("title", "")
        if imp < 1 and not (imp >= 0 and x.get("country") in ("US", "KR") and KEY_EVENTS.search(title)):
            continue
        if re.search(r"Auction|Bill|Speech|Speaks|Holiday|Stock Change|Crude", title, re.I) and imp < 1:
            continue
        a, f, p = x.get("actual"), x.get("forecast"), x.get("previous")
        unit = x.get("unit") or ""
        scale = x.get("scale") or ""
        surprise = None
        if a is not None and f is not None:
            surprise = "above" if a > f else "below" if a < f else "inline"
        at = datetime.fromisoformat(x["date"].replace("Z", "+00:00")).astimezone(KST)
        rows.append({"at": at.strftime("%Y-%m-%d %H:%M"), "country": x.get("country"), "flag": NATION.get(x.get("country"), ""),
                     "title": title, "ko": ko_name(title), "importance": imp, "actual": a, "forecast": f, "previous": p,
                     "unit": unit, "scale": scale, "surprise": surprise, "done": a is not None})
    rows.sort(key=lambda r: r["at"])
    res = {"at": datetime.now(KST).strftime("%Y-%m-%d %H:%M"), "events": rows,
           "source": "TradingView 경제 캘린더(비공식) · 예상치는 시장 컨센서스"}
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "econ_latest.json").write_text(json.dumps(res, ensure_ascii=False), encoding="utf-8")
    return res


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("cmd", choices=["pulse", "flows", "econ"])
    ap.add_argument("--force", action="store_true", help="flows 캐시(3시간) 무시")
    a = ap.parse_args()
    if a.cmd == "pulse":
        r = pulse()
        print(json.dumps({k: r[k] for k in ("at", "markets")} | {"top_industries": r["industries"][:5], "movers_up": r["movers_up"][:5]}, ensure_ascii=False, indent=1))
    elif a.cmd == "flows":
        r = flows(max_age_h=0 if a.force else 3)
        print(json.dumps({k: r[k] for k in ("at", "date", "n", "source")} | {"sectors": r["sectors"][:6], "foreign_buy": r["foreign_buy"][:5]}, ensure_ascii=False, indent=1))
    else:
        r = econ()
        print(json.dumps([e for e in r["events"] if e["done"]][-10:], ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
