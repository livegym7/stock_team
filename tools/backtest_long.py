#!/usr/bin/env python3
"""긴 기간 백테스트 (비교 자료, 2026-11-23 사용자 요청): 지금 규칙을 5년(기본) 치 일봉에 대입한다.
backtest.py(3년, 지금 시총 2천억↑ 종목만)의 두 가지 약점을 줄인다.
  ① 사라진 종목: DART 회사 코드표에 남아 있는 상장폐지 종목도 넣는다(일봉은 네이버가 상장폐지 종목도 준다).
     상장폐지 종목에서 들고 있던 거래는 마지막 거래일 종가로 끝낸 것으로 친다(정리매매 급락 포함).
  ② 시총: '그날 시총 = 그날 주가 × 주식 수'로 2천억 관문을 판단한다. 주식 수는 지금 상장 종목은 지금 시총 ÷ 지금 주가(증자한 종목은 과거 시총이
     실제보다 크게 나옴), 상장폐지 종목은 DART 사업보고서의 발행 주식 수(마지막 2~3년 안에서 찾음). 못 찾으면 시총 관문을 통과로 두고 거래대금 관문만 쓴다.
  RS 백분위와 '같은 업종 동반 상승'도 그날 시총 2천억↑인 종목끼리만 견준다. 상장폐지 종목은 업종 분류가 없어 동반 상승이 '확인 불가'다
  (→ 돌파 신호가 빠진다. 조건 없이 본 숫자를 loose에 따로 둔다).
남는 한계: 업종 분류는 지금 기준 · 일봉만 사용 · 신호일 종가 진입 · 동시 보유 한도(CR 6%) 없음 · 슬리피지 없음. 수수료·세금은 왕복 0.23% 반영.
**비교 자료일 뿐, 매매 규칙(2027-01-31 또는 실제 신호 30건까지 고정)을 바꾸지 않는다.**

  python3 tools/backtest_long.py [--years 5] [--limit 300] [--no-delisted]     # → data/backtest/long.json
"""
import argparse, bisect, json, os, re, sys, time
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import backtest as B  # noqa: E402
import screener as S  # noqa: E402
from common import CACHE, DATA, http_get  # noqa: E402
from naver_quote import KST  # noqa: E402
from universe import load as load_universe  # noqa: E402

DIR = CACHE / "daily_long5"
NAMES = CACHE / "dart_corp_names.json"      # {종목코드: {corp, name, mod}} — DART corpCode.xml (상장폐지 종목 포함)
SHARES = CACHE / "delisted_shares.json"
SKIP = re.compile(r"스팩|기업인수목적|리츠|인프라|투자회사|유동화|선박투자|사모투자|제\d+호")


def fetch(code, years):
    path = DIR / f"{code}.json"
    today = datetime.now(KST).strftime("%Y%m%d")
    if path.exists():
        d = json.loads(path.read_text())
        if d.get("years") == years and d.get("day", "") >= (datetime.now(KST) - timedelta(days=3)).strftime("%Y%m%d"):
            return d["rows"]
    start = (datetime.now(KST) - timedelta(days=int(365 * (years + 1.25)))).strftime("%Y%m%d")   # 앞 1년여는 이동평균·RS 준비 구간
    raw = None
    for _ in range(3):
        try:
            raw = http_get(S.SISE, {"symbol": code, "requestType": 1, "timeframe": "day", "startTime": start, "endTime": today}).decode("utf-8", "replace")
            break
        except Exception:
            time.sleep(2)
    rows = []
    for line in re.findall(r"\[\"(\d{8})\",\s*([^\]]+)\]", raw or ""):
        try:
            o, h, l, c, v = [float(x) for x in line[1].split(",")[:5]]
        except ValueError:
            continue
        if o and h and l and c:
            rows.append({"date": line[0], "open": o, "high": h, "low": l, "close": c, "volume": v})
    DIR.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"day": today, "years": years, "rows": rows}))
    return rows


def delisted_shares(codes_rows, names):
    """상장폐지 종목의 발행 주식 수 (DART 사업보고서 '주식의 총수', 보통주). 마지막 거래 연도부터 3년 안에서 찾는다."""
    cache = json.loads(SHARES.read_text()) if SHARES.exists() else {}
    if not os.environ.get("DART_API_KEY"):
        return cache
    import dart
    todo = [(c, r) for c, r in codes_rows if c not in cache]
    for n, (code, rows) in enumerate(todo):
        y, got = int(rows[-1]["date"][:4]), None
        for year in (y - 1, y - 2, y):
            try:
                L = dart.api_json("stockTotqySttus.json", corp_code=names[code]["corp"], bsns_year=str(year), reprt_code="11011").get("list", [])
            except SystemExit:
                L = []
            for x in L:
                if "보통" in (x.get("se") or ""):
                    try:
                        got = float(str(x.get("istc_totqy") or x.get("distb_stock_co")).replace(",", ""))
                    except ValueError:
                        got = None
            time.sleep(0.12)
            if got:
                break
        cache[code] = got
        if n % 50 == 49:
            SHARES.write_text(json.dumps(cache))
    SHARES.write_text(json.dumps(cache))
    return cache


def run(years=5, limit=None, with_delisted=True, workers=6):
    t0 = time.time()
    R = B.rules()
    listed = [s for s in load_universe()["stocks"] if not B.is_etf(s["name"]) and s.get("market") not in ("KONEX", "2")]
    have = {s["code"] for s in load_universe()["stocks"]}
    names = json.loads(NAMES.read_text()) if NAMES.exists() else {}
    gone = [{"code": c, "name": v["name"], "industry": "", "market_cap_eok": 0, "delisted": True}
            for c, v in names.items() if c not in have and not SKIP.search(v["name"])] if with_delisted else []
    uni = listed + gone
    if limit:
        uni = sorted(listed, key=lambda s: -s["market_cap_eok"])[:limit] + gone[:limit // 3]

    def one(s):
        rows = fetch(s["code"], years)
        time.sleep(0.08)
        return s, rows
    with ThreadPoolExecutor(workers) as ex:
        data = [x for x in ex.map(one, uni) if len(x[1]) >= 300]
    last_day = max(rows[-1]["date"] for _, rows in data)
    cut = (datetime.strptime(last_day, "%Y%m%d") - timedelta(days=20)).strftime("%Y%m%d")
    data = [(s, rows) for s, rows in data if s.get("delisted") or rows[-1]["date"] >= cut]          # 지금 상장인데 거래가 끊긴 것은 뺌
    dl = [(s["code"], rows) for s, rows in data if s.get("delisted")]
    dsh = delisted_shares(dl, names) if dl else {}
    shares = {}
    for s, rows in data:
        shares[s["code"]] = (dsh.get(s["code"]) if s.get("delisted") else s["market_cap_eok"] * 1e8 / rows[-1]["close"]) or None
    closes = {s["code"]: {r["date"]: r["close"] for r in rows} for s, rows in data}
    MIN = S.RULES["min_mcap_eok"]

    def cap_on(code, day):
        sh, c = shares.get(code), closes[code].get(day)
        return sh * c / 1e8 if sh and c else None

    # 날짜별 RS 백분위: 그날 시총 2천억↑(주식 수 모르면 포함)인 종목끼리
    raw = defaultdict(dict)
    for s, rows in data:
        c, sh = [r["close"] for r in rows], shares.get(s["code"])
        for i in range(250, len(rows)):
            if sh and sh * c[i] / 1e8 < MIN:
                continue
            raw[rows[i]["date"]][s["code"]] = 0.2 * (c[i] / c[i - 249] - 1) + 0.3 * (c[i] / c[i - 125] - 1) + 0.5 * (c[i] / c[i - 62] - 1)
    ranks = {}
    for d, m in raw.items():
        order = sorted(m.values())
        ranks[d] = {k: round(bisect.bisect_right(order, x) / len(order) * 99) for k, x in m.items()}
    rs_at = lambda d, code: ranks.get(d, {}).get(code)  # noqa: E731
    import sector_etf
    bench = sector_etf.daily("KOSPI", "코스피", int(250 * (years + 1.3)))["rows"]
    bc = [r["close"] for r in bench]
    bench_ok = {bench[i]["date"]: bc[i] > sum(bc[i - 19:i + 1]) / 20 for i in range(19, len(bench))}
    chg = {s["code"]: {rows[i]["date"]: rows[i]["close"] / rows[i - 1]["close"] - 1 for i in range(1, len(rows))} for s, rows in data}
    from sector_map import custom_map
    cmap = custom_map()
    ind_of = {s["code"]: (cmap.get(s["code"]) or "네이버:" + s["industry"]) for s, _ in data if not s.get("delisted")}
    by_ind = defaultdict(list)
    for code, g in ind_of.items():
        by_ind[g].append(code)

    def ia_at(code, day):
        if code not in ind_of:
            return {"ia": "확인 불가", "ia_group": "상장폐지(업종 분류 없음)", "ia_peers": 0, "ia_up_share": None, "ia_median": None}
        xs = [chg[c][day] for c in by_ind[ind_of[code]] if c != code and day in chg[c] and (cap_on(c, day) or 0) >= MIN]
        label, share, med = S.industry_action(xs)
        return {"ia": label, "ia_group": ind_of[code], "ia_peers": len(xs), "ia_up_share": share, "ia_median": med}

    trades, loose = [], []
    for s, rows in data:
        sh = shares.get(s["code"])
        cap_at = (lambda i, rows=rows, sh=sh: sh * rows[i]["close"] / 1e8) if sh else (lambda i: MIN)      # 주식 수 모르면 시총 관문 통과로 둠
        for req, out in ((True, trades), (False, loose)):
            ts = B.scan(s, rows, rs_at, bench_ok, R, ia_at, require_ia=req, cap_at=cap_at)
            for t in ts:
                t["delisted"] = bool(s.get("delisted"))
                if s.get("delisted") and not t["exit"]:                 # 상장폐지까지 들고 있던 거래 = 마지막 거래일 종가로 끝
                    t["exit"], t["how"] = rows[-1]["date"], "상장폐지까지 보유"
            out += ts
    first = (datetime.strptime(last_day, "%Y%m%d") - timedelta(days=int(365 * years))).strftime("%Y%m%d")
    trades = sorted([t for t in trades if t["date"] >= first], key=lambda t: t["date"])
    loose = [t for t in loose if t["date"] >= first]
    closed = [t for t in trades if t["exit"]]
    lc = [t for t in loose if t["exit"]]
    by = lambda ts, key: {str(k): B.stats([t for t in ts if key(t) == k]) for k in sorted({key(t) for t in ts}, key=str)}  # noqa: E731
    eq, curve = 0, []
    for t in sorted(closed, key=lambda t: t["exit"]):
        eq += t["r"]
        curve.append([t["exit"], round(eq, 2)])
    n_del = sum(1 for s, _ in data if s.get("delisted"))
    out = {"made_at": datetime.now(KST).strftime("%Y-%m-%d %H:%M"), "seconds": round(time.time() - t0), "years": years,
           "period": [trades[0]["date"], trades[-1]["date"]] if trades else None,
           "universe": {"all": len(data), "listed": len(data) - n_del, "delisted": n_del,
                        "delisted_shares_known": sum(1 for s, _ in data if s.get("delisted") and shares.get(s["code"]))},
           "rules": {**R, "gate": f"돌파 관문 {S.RULES['gate_allow_miss']}개 미달 허용 · 포켓피봇 7/7 · 돌파는 업종 동반 상승 필수"},
           "source": "네이버 일봉(수정주가, 비공식) · 상장폐지 종목 목록·주식 수 DART · 계산 Claude",
           "limits": ["그날 시총 = 그날 주가 × 주식 수(지금 상장 종목은 지금 주식 수로 어림 → 증자한 종목은 과거 시총이 크게 나옴)",
                      "상장폐지 종목은 업종 분류가 없어 '동반 상승' 확인 불가 → 돌파 신호가 빠짐(loose 참고)", "업종 분류는 지금 기준",
                      "일봉만 사용 · 신호일 종가 진입 · 동시 보유 한도 없음 · 슬리피지 없음", "수수료·세금 왕복 0.23% 반영"],
           "all": B.stats(closed), "open_trades": len(trades) - len(closed),
           "by_year": by(closed, lambda t: t["date"][:4]), "by_kind": by(closed, lambda t: t["kind"]),
           "by_market": {("지수 20일선 위" if k == "True" else "지수 20일선 아래"): v for k, v in by(closed, lambda t: bool(t["market_ok"])).items()},
           "by_delisted": {("상장폐지 종목" if k == "True" else "지금 상장 종목"): v for k, v in by(closed, lambda t: t["delisted"]).items()},
           "by_exit": dict(Counter(t["how"] for t in closed)),
           "loose": {"all": B.stats(lc), "by_kind": by(lc, lambda t: t["kind"]), "by_year": by(lc, lambda t: t["date"][:4]),
                     "by_kind_ia": by(lc, lambda t: t["kind"] + " · " + t["ia"]),
                     "by_delisted": {("상장폐지 종목" if k == "True" else "지금 상장 종목"): v for k, v in by(lc, lambda t: t["delisted"]).items()}},
           "curve": curve[::max(1, len(curve) // 300)] + curve[-1:],
           "worst": sorted(closed, key=lambda t: t["r"])[:10], "best": sorted(closed, key=lambda t: -t["r"])[:8]}
    (DATA / "backtest").mkdir(parents=True, exist_ok=True)
    (DATA / "backtest" / "long.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    return {k: out[k] for k in ("made_at", "seconds", "period", "universe", "all", "by_year", "by_kind", "by_market", "by_delisted")}


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="긴 기간 백테스트 (상장폐지 종목 포함 · 그날 시총) — 비교 자료")
    ap.add_argument("--years", type=float, default=5)
    ap.add_argument("--limit", type=int)
    ap.add_argument("--no-delisted", action="store_true")
    a = ap.parse_args()
    print(json.dumps(run(a.years, a.limit, not a.no_delisted), ensure_ascii=False, indent=1))
