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

  python3 tools/backtest_long.py [--years 5] [--limit 300] [--no-delisted]     # 신호를 모두 샀다고 본 성적 → data/backtest/long.json
  python3 tools/backtest_long.py --portfolio                                   # 계좌 하나를 실제처럼(동시 위험 6%) → data/backtest/long_portfolio.json
  python3 tools/backtest_long.py --zone                                        # 기준가 돌파 vs 매물대 돌파 → data/backtest/long_zone.json
  python3 tools/backtest_long.py --fund --years 10                             # 그때 발표돼 있던 실적으로 펀더 점수별 비교 → data/backtest/long_fund_10y.json (DART 받기 1~2시간)
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


def _sfx(years):
    return "" if years == 5 else f"_{years:g}y"      # 5년이 기본 파일, 다른 기간은 long_10y.json처럼 따로


def fetch(code, years):
    path = (DIR if years == 5 else CACHE / f"daily_long{years:g}") / f"{code}.json"     # 기간별로 캐시 폴더를 따로 (5년 캐시를 덮어쓰지 않게)
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
    path.parent.mkdir(parents=True, exist_ok=True)
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


def run(years=5, limit=None, with_delisted=True, workers=6, portfolio=False, loose_ia=False):
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

    wide_of, by_wide = {}, defaultdict(list)
    if loose_ia:
        import csv
        with open(Path(__file__).resolve().parent.parent / "config" / "sector_map.csv", encoding="utf-8-sig") as f:
            for r in csv.DictReader(f):
                if r["티커"] in ind_of and r.get("wi26"):
                    wide_of[r["티커"]] = r["wi26"]; by_wide[r["wi26"]].append(r["티커"])

    def ia_at(code, day):
        if code not in ind_of:
            return {"ia": "확인 불가", "ia_group": "상장폐지(업종 분류 없음)", "ia_peers": 0, "ia_up_share": None, "ia_median": None}
        xs = [chg[c][day] for c in by_ind[ind_of[code]] if c != code and day in chg[c] and (cap_on(c, day) or 0) >= MIN]
        label, share, med = S.industry_action(xs)
        out = {"ia": label, "ia_group": ind_of[code], "ia_peers": len(xs), "ia_up_share": share, "ia_median": med}
        if loose_ia:                   # 넓은 업종(sector_map.csv의 wi26 열, 예: 반도체 162종목)으로도 판정 — 세부 업종이 3~4종목뿐인 대형주 비교용
            w = wide_of.get(code)
            ws = [chg[c][day] for c in by_wide.get(w, []) if c != code and day in chg[c] and (cap_on(c, day) or 0) >= MIN]
            out["ia_wide"], out["ia_wide_n"] = S.industry_action(ws)[0], len(ws)
        return out

    if portfolio:                      # 계좌 시뮬레이션: 보유 여부와 상관없이 뜬 신호를 모두 모아 넘긴다
        # 그날의 주도 업종 순위 (2026-11-23 사용자 요청): 주도 섹터 레이더(sector_radar.score_on, 가격·거래대금만)를 5거래일마다 다시 계산.
        # 그날 시총 2천억↑ 종목끼리, 업종 분류는 지금 기준. 신호에는 '그날 이전 가장 가까운 계산일'의 순위를 붙인다(앞날 자료 안 씀).
        import sector_radar
        rd = {s["code"]: {"rows": rows, "idx": {r["date"]: i for i, r in enumerate(rows)}, "group": ind_of[s["code"]], "name": s["name"]}
              for s, rows in data if s["code"] in ind_of}
        bdays = [r["date"] for r in bench]
        snaps, snap_days = {}, []
        for d in bdays[::5]:
            sub = {c: v for c, v in rd.items() if d in v["idx"] and (cap_on(c, d) or 0) >= MIN}
            sc = sector_radar.score_on(sub, d)
            if sc:
                snaps[d] = {x["group"]: (x["rank"], x["score"], len(sc)) for x in sc}
                snap_days.append(d)

        def sector_at(code, day):
            k = bisect.bisect_right(snap_days, day) - 1
            g = (ind_of.get(code) or "").replace("네이버:", "")
            return snaps[snap_days[k]].get(g) if k >= 0 and g else None
        cand = []
        for s, rows in data:
            sh = shares.get(s["code"])
            cap_at = (lambda i, rows=rows, sh=sh: sh * rows[i]["close"] / 1e8) if sh else (lambda i: MIN)
            for t in B.scan(s, rows, rs_at, bench_ok, R, ia_at, require_ia=not loose_ia, cap_at=cap_at, all_signals=True):
                if s.get("delisted") and not t["exit"]:
                    t["exit"], t["how"] = rows[-1]["date"], "상장폐지까지 보유"
                sa = sector_at(t["code"], t["date"])
                cand.append({**{k: t.get(k) for k in ("code", "stock", "date", "kind", "rs", "r", "exit", "be", "how", "market_ok", "vol_ratio", "ia_group", "pp_ok", "cap_eok", "ia", "ia_wide", "ia_wide_n", "ia_peers", "gate_miss", "f_base", "f_55", "f_250", "f_pull", "nobase")},
                             "sec_rank": sa[0] if sa else None, "sec_score": sa[1] if sa else None, "sec_n": sa[2] if sa else None})
        first = (datetime.strptime(last_day, "%Y%m%d") - timedelta(days=int(365 * years))).strftime("%Y%m%d")
        days = sorted({r["date"] for r in bench if r["date"] >= first})
        return [t for t in cand if t["date"] >= first], days, {"all": len(data), "delisted": sum(1 for s, _ in data if s.get("delisted"))}
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
    (DATA / "backtest" / f"long{_sfx(years)}.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    return {k: out[k] for k in ("made_at", "seconds", "period", "universe", "all", "by_year", "by_kind", "by_market", "by_delisted")}


def account(cand, days, order, seed=0, risk=0.02, cr_max=0.06, stop=0.08):
    """계좌 하나를 실제처럼 굴린다: 한 종목 위험 = 계좌의 2%, 본전으로 올리기 전 종목의 위험 합 ≤ 6%(= 동시에 3종목), 현금 한도(빚 없음).
    한 종목 크기 = 위험 ÷ 손절폭 = 계좌의 25%, 3R 익절 뒤에는 절반. 같은 날 신호가 여러 개면 order 순서로 고른다. 손익은 청산일에 한꺼번에 반영(단순화)."""
    import random
    rnd = random.Random(seed)
    key = {"rs": lambda t: (-(t["rs"] or 0), t["code"]),
           "breakout": lambda t: (0 if t["kind"] == "돌파" else 1, -(t["rs"] or 0), t["code"]),
           "random": lambda t: rnd.random()}[order]
    by_day = defaultdict(list)
    for t in cand:
        by_day[t["date"]].append(t)
    eq, peak, mdd, open_, taken, skipped, curve = 1.0, 1.0, 0.0, [], [], 0, []
    size = risk / stop
    for d in days:
        for p in [p for p in open_ if p["exit"] and p["exit"] <= d]:
            eq += p["r"] * p["amt"]
            open_.remove(p)
        peak = max(peak, eq); mdd = min(mdd, eq / peak - 1)
        for t in sorted(by_day.get(d, []), key=key):
            if any(p["code"] == t["code"] for p in open_):
                continue
            at_risk = sum(1 for p in open_ if not (p["be"] and p["be"] <= d))
            used = sum(size * (0.5 if p["be"] and p["be"] <= d else 1.0) for p in open_)
            if (at_risk + 1) * risk > cr_max + 1e-9 or used + size > 1.0 + 1e-9:
                skipped += 1
                continue
            p = {**t, "amt": risk * eq}
            open_.append(p); taken.append(p)
        curve.append([d, round(eq, 4)])
    closed = [p for p in taken if p["exit"]]
    yrs = {}
    for y in sorted({d[:4] for d in days}):
        ys = [c for c in curve if c[0][:4] == y]
        base = next((c[1] for c in reversed(curve) if c[0][:4] < y), 1.0)
        yrs[y] = {"ret_pct": round((ys[-1][1] / base - 1) * 100, 1), "n": sum(1 for p in closed if p["date"][:4] == y),
                  "win_rate": round(sum(1 for p in closed if p["date"][:4] == y and p["r"] > 0) / max(1, sum(1 for p in closed if p["date"][:4] == y)) * 100, 1)}
    n_years = max(0.1, len(days) / 250)
    st = B.stats([{**p, "took": bool(p["be"]), "days": 0} for p in closed]) if closed else {"n": 0}
    return {"order": order, "final": round(eq, 3), "total_ret_pct": round((eq - 1) * 100, 1), "cagr_pct": round((eq ** (1 / n_years) - 1) * 100, 1),
            "max_dd_pct": round(mdd * 100, 1), "taken": len(taken), "skipped": skipped, "win_rate": st.get("win_rate"), "avg_r": st.get("avg_r"),
            "max_loss_streak": st.get("max_loss_streak"), "by_kind": dict(Counter(p["kind"] for p in taken)), "by_year": yrs,
            "curve": curve[::max(1, len(curve) // 250)] + curve[-1:]}


def run_portfolio(years=5, with_delisted=True):
    t0 = time.time()
    cand, days, uni = run(years, None, with_delisted, portfolio=True)
    out = {"made_at": datetime.now(KST).strftime("%Y-%m-%d %H:%M"), "years": years, "period": [days[0], days[-1]], "universe": uni,
           "signals": len(cand), "signals_by_kind": dict(Counter(t["kind"] for t in cand)),
           "assume": "한 종목 위험 2% · 본전으로 올리기 전 위험 합 6%(동시에 3종목) · 종목 크기 계좌의 25%(3R 뒤 절반) · 빚 없음 · 신호일 종가 진입 · 수수료·세금 왕복 0.23% · 손익은 청산일에 반영",
           "variants": [{"name": "RS 높은 순", **account(cand, days, "rs")}, {"name": "돌파 먼저, 그다음 RS 순", **account(cand, days, "breakout")}]}
    # 참고(규칙을 바꿔 본 비교 — 지금 규칙 아님): 포켓피봇을 빼면 / 코스피 20일선 위에서만 사면
    out["what_if"] = []
    for name, f in (("돌파만 (포켓피봇 제외)", lambda t: t["kind"] == "돌파"), ("코스피 20일선 위에서만", lambda t: t["market_ok"]),
                    ("돌파만 + 코스피 20일선 위", lambda t: t["kind"] == "돌파" and t["market_ok"])):
        c = [t for t in cand if f(t)]
        rr = sorted(account(c, days, "random", seed=k)["total_ret_pct"] for k in range(30))
        v = account(c, days, "rs"); v.pop("curve", None)
        out["what_if"].append({"name": name, "signals": len(c), **v, "random_total_ret_pct": {"min": rr[0], "median": rr[15], "max": rr[-1]}})
    st = lambda ts: {k: B.stats([{**t, "took": bool(t["be"]), "days": 0} for t in ts if t["exit"]]).get(k) for k in ("n", "win_rate", "avg_r")}  # noqa: E731
    out["signals_by_year"] = {y: st([t for t in cand if t["date"][:4] == y]) for y in sorted({t["date"][:4] for t in cand})}
    out["signals_by_rs"] = {b: st([t for t in cand if lo <= (t["rs"] or 0) < hi]) for b, lo, hi in (("70~80", 70, 80), ("80~90", 80, 90), ("90~95", 90, 95), ("95 이상", 95, 101))}
    # 주도 업종(그날 레이더 순위)별 신호 성적과, 주도 업종만 샀을 때의 계좌 (참고 비교 — 지금 규칙 아님)
    bucket = lambda t: "분류 없음" if t["sec_rank"] is None else "1~5위" if t["sec_rank"] <= 5 else "6~10위" if t["sec_rank"] <= 10 else "11~20위" if t["sec_rank"] <= 20 else "21위 아래"  # noqa: E731
    order_b = ["1~5위", "6~10위", "11~20위", "21위 아래", "분류 없음"]
    out["sector"] = {"note": "업종 순위 = 주도 섹터 레이더 점수(1개월·1주 상대 강도, 20일선 위 비율, 신고가 비율, 거래대금 쏠림) 순위, 5거래일마다 계산, 그날 시총 2천억↑ 종목·지금 업종 분류",
                     "groups_median": sorted(t["sec_n"] for t in cand if t["sec_n"])[len([t for t in cand if t["sec_n"]]) // 2] if any(t["sec_n"] for t in cand) else None,
                     "all": {b: st([t for t in cand if bucket(t) == b]) for b in order_b},
                     "돌파": {b: st([t for t in cand if t["kind"] == "돌파" and bucket(t) == b]) for b in order_b},
                     "포켓피봇": {b: st([t for t in cand if t["kind"] == "포켓피봇" and bucket(t) == b]) for b in order_b},
                     "by_year_top10": {y: st([t for t in cand if t["date"][:4] == y and (t["sec_rank"] or 99) <= 10]) for y in out["signals_by_year"]},
                     "by_year_rest": {y: st([t for t in cand if t["date"][:4] == y and (t["sec_rank"] or 99) > 10]) for y in out["signals_by_year"]},
                     "account": []}
    top = lambda n: (lambda t: (t["sec_rank"] or 99) <= n)  # noqa: E731
    for name, f in (("주도 업종 1~5위만", top(5)), ("주도 업종 1~10위만", top(10)), ("주도 업종 11위 아래만 (반대 확인)", lambda t: (t["sec_rank"] or 99) > 10),
                    ("돌파만 + 주도 업종 1~10위", lambda t: t["kind"] == "돌파" and top(10)(t)),
                    ("포켓피봇만 + 주도 업종 1~5위", lambda t: t["kind"] == "포켓피봇" and top(5)(t)),
                    ("주도 업종 1~10위 + 코스피 20일선 위", lambda t: top(10)(t) and t["market_ok"])):
        c = [t for t in cand if f(t)]
        rr = sorted(account(c, days, "random", seed=k)["total_ret_pct"] for k in range(30))
        v = account(c, days, "rs"); v.pop("curve", None)
        out["sector"]["account"].append({"name": name, "signals": len(c), **v, "random_total_ret_pct": {"min": rr[0], "median": rr[15], "max": rr[-1]}})
    rs_ = [account(cand, days, "random", seed=k) for k in range(30)]
    med = lambda k: sorted(r[k] for r in rs_)[len(rs_) // 2]  # noqa: E731
    out["random"] = {"name": "아무거나 고름 (30번 평균 — 고르는 순서가 얼마나 중요한지 보는 기준)", "runs": 30,
                     "total_ret_pct": {"min": min(r["total_ret_pct"] for r in rs_), "median": med("total_ret_pct"), "max": max(r["total_ret_pct"] for r in rs_)},
                     "max_dd_pct": {"worst": min(r["max_dd_pct"] for r in rs_), "median": med("max_dd_pct")},
                     "by_year_median": {y: sorted(r["by_year"][y]["ret_pct"] for r in rs_)[15] for y in rs_[0]["by_year"]}}
    out["seconds"] = round(time.time() - t0)
    (DATA / "backtest" / f"long_portfolio{_sfx(years)}.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    for v in out["variants"]:
        v.pop("curve", None)
    return out


def run_zone(years=5, with_delisted=True):
    """기준가 돌파와 매물대 돌파를 나눠 비교 (2026-11-23 사용자 요청, 비교 자료).
    매물대 돌파 = 어제 종가 ≤ 최대 매물대(웹 차트의 빨간 막대: 어제까지 200봉·10칸 중 거래량이 가장 많은 칸) 상단 < 오늘 종가, 거래량 50일 평균의 1.5배↑.
    종목 조건·업종 동반 상승·청산 규칙은 돌파와 같다. 같은 날 기준가도 넘으면 '기준가+매물대 돌파'."""
    t0 = time.time()
    old = S.RULES.get("breakout_mode", "base")
    S.RULES["breakout_mode"] = "zone_cmp"
    try:
        cand, days, uni = run(years, None, with_delisted, portfolio=True)
    finally:
        S.RULES["breakout_mode"] = old
    st = lambda ts: {k: B.stats([{**t, "took": bool(t["be"]), "days": 0} for t in ts if t["exit"]]).get(k) for k in ("n", "win_rate", "avg_r", "payoff", "max_loss_streak")}  # noqa: E731
    kinds = ["돌파", "기준가+매물대 돌파", "매물대 돌파", "포켓피봇"]
    top10 = lambda t: (t["sec_rank"] or 99) <= 10  # noqa: E731
    years_ = sorted({t["date"][:4] for t in cand})
    out = {"made_at": datetime.now(KST).strftime("%Y-%m-%d %H:%M"), "years": years, "period": [days[0], days[-1]], "universe": uni, "signals": len(cand),
           "define": run_zone.__doc__.strip(),
           "by_kind": {k: st([t for t in cand if t["kind"] == k]) for k in kinds},
           "by_kind_year": {k: {y: st([t for t in cand if t["kind"] == k and t["date"][:4] == y]) for y in years_} for k in kinds},
           "by_kind_sector": {k: {"주도 업종 1~10위": st([t for t in cand if t["kind"] == k and top10(t)]), "11위 아래": st([t for t in cand if t["kind"] == k and not top10(t)])} for k in kinds},
           "by_kind_market": {k: {"코스피 20일선 위": st([t for t in cand if t["kind"] == k and t["market_ok"]]), "아래": st([t for t in cand if t["kind"] == k and not t["market_ok"]])} for k in kinds},
           "account": []}
    zone = ("매물대 돌파", "기준가+매물대 돌파")
    base = ("돌파", "기준가+매물대 돌파")
    for name, f in (("지금 규칙 (기준가 돌파 + 포켓피봇)", lambda t: t["kind"] != "매물대 돌파"),
                    ("기준가 돌파만", lambda t: t["kind"] in base), ("매물대 돌파만", lambda t: t["kind"] in zone),
                    ("기준가 또는 매물대 돌파 (포켓피봇 제외)", lambda t: t["kind"] != "포켓피봇"),
                    ("기준가와 매물대를 같은 날 함께 돌파한 것만", lambda t: t["kind"] == "기준가+매물대 돌파"),
                    ("매물대 돌파만 + 주도 업종 1~10위", lambda t: t["kind"] in zone and top10(t)),
                    ("기준가 또는 매물대 돌파 + 주도 업종 1~10위", lambda t: t["kind"] != "포켓피봇" and top10(t))):
        c = [t for t in cand if f(t)]
        rr = sorted(account(c, days, "random", seed=k)["total_ret_pct"] for k in range(30))
        v = account(c, days, "rs"); v.pop("curve", None)
        out["account"].append({"name": name, "signals": len(c), **v, "random_total_ret_pct": {"min": rr[0], "median": rr[15], "max": rr[-1]}})
    out["seconds"] = round(time.time() - t0)
    (DATA / "backtest" / f"long_zone{_sfx(years)}.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    return {k: out[k] for k in ("made_at", "signals", "by_kind", "seconds")}


def run_fund(years=10, with_delisted=True):
    """이익 조건이 차트 신호를 얼마나 살리는가 (2026-11-23 사용자 요청, 비교 자료).
    신호가 뜬 날 이미 발표돼 있던 분기 실적(DART)으로 펀더 점수 0~3을 매겨(tools/dart_fin_hist.py — 추정치가 아니라 발표된 실적, 법정 제출 기한 기준) 신호 성적과 계좌 결과를 나눠 본다.
    신호 종류는 --zone과 같다(기준가 돌파 · 매물대 돌파 · 포켓피봇)."""
    import dart_fin_hist as F
    t0 = time.time()
    cf = CACHE / f"long_cand_zone{_sfx(years)}.json"
    if cf.exists() and time.time() - cf.stat().st_mtime < 3 * 86400:
        o = json.loads(cf.read_text()); cand, days, uni = o["cand"], o["days"], o["uni"]
    else:
        old = S.RULES.get("breakout_mode", "base")
        S.RULES["breakout_mode"] = "zone_cmp"
        try:
            cand, days, uni = run(years, None, with_delisted, portfolio=True)
        finally:
            S.RULES["breakout_mode"] = old
        cf.write_text(json.dumps({"cand": cand, "days": days, "uni": uni}, ensure_ascii=False))
    print(f"신호 {len(cand)}건 · 실적 받기 시작", flush=True)
    need = F.needs([(t["code"], t["date"]) for t in cand])
    print(f"받을 보고서 묶음 {len(need)}개 · 종목-보고서 {sum(len(v) for v in need.values())}쌍", flush=True)
    F.fetch(need, log=lambda m: print(m, flush=True))
    for t in cand:
        sc = F.score_at(t["code"], t["date"])
        t["fp"] = sc["pts"] if sc else None
        bk = (sc or {}).get("book") or {}
        t["bk"] = None if not sc or any(bk.get(k) is None for k in ("sales", "op", "net")) else sum(bool(bk[k]) for k in ("sales", "op", "net"))
        t["bk_net"] = bk.get("net")
    st = lambda ts: {k: B.stats([{**t, "took": bool(t["be"]), "days": 0} for t in ts if t["exit"]]).get(k) for k in ("n", "win_rate", "avg_r", "payoff", "max_loss_streak")}  # noqa: E731
    lab = lambda t: "확인 불가" if t["fp"] is None else f"{t['fp']}점"  # noqa: E731
    labs = ["3점", "2점", "1점", "0점", "확인 불가"]
    ok = lambda t: (t["fp"] or 0) >= 2  # noqa: E731
    brk = lambda t: t["kind"] in ("돌파", "기준가+매물대 돌파")  # noqa: E731
    kinds = ["돌파", "기준가+매물대 돌파", "매물대 돌파", "포켓피봇"]
    years_ = sorted({t["date"][:4] for t in cand})
    out = {"made_at": datetime.now(KST).strftime("%Y-%m-%d %H:%M"), "years": years, "period": [days[0], days[-1]], "universe": uni, "signals": len(cand),
           "define": run_fund.__doc__.strip(), "score": "① 최근 분기 영업이익 전년 대비 +20%↑/흑자전환 ② 영업이익률 1년 전보다 높음 ③ 올해 누적 영업이익 +20%↑/흑자전환 · 펀더 OK = 2점 이상(실전과 같은 문턱)",
           "coverage": dict(Counter(lab(t) for t in cand)),
           "by_score": {b: st([t for t in cand if lab(t) == b]) for b in labs},
           "by_score_kind": {k: {b: st([t for t in cand if t["kind"] == k and lab(t) == b]) for b in labs} for k in kinds},
           "breakout_ok_vs_not": {"기준가 돌파 · 펀더 OK(2점↑)": st([t for t in cand if brk(t) and ok(t)]), "기준가 돌파 · 펀더 0~1점": st([t for t in cand if brk(t) and t["fp"] is not None and not ok(t)])},
           "breakout_ok_by_year": {y: st([t for t in cand if brk(t) and ok(t) and t["date"][:4] == y]) for y in years_},
           "breakout_not_by_year": {y: st([t for t in cand if brk(t) and t["fp"] is not None and not ok(t) and t["date"][:4] == y]) for y in years_},
           "account": []}
    top5 = lambda t: (t["sec_rank"] or 99) <= 5  # noqa: E731
    for name, f in (("지금 규칙 (기준가 돌파 + 포켓피봇)", lambda t: t["kind"] != "매물대 돌파"),
                    ("지금 규칙 + 펀더 OK", lambda t: t["kind"] != "매물대 돌파" and ok(t)),
                    ("기준가 돌파만", brk), ("기준가 돌파만 + 펀더 OK", lambda t: brk(t) and ok(t)),
                    ("기준가 돌파만 + 펀더 0~1점 (반대 확인)", lambda t: brk(t) and t["fp"] is not None and not ok(t)),
                    ("기준가 돌파만 + 펀더 3점", lambda t: brk(t) and t["fp"] == 3),
                    ("기준가 돌파만 + 펀더 OK + 코스피 20일선 위", lambda t: brk(t) and ok(t) and t["market_ok"]),
                    ("기준가 돌파만 + 펀더 OK + 업종 1~5위", lambda t: brk(t) and ok(t) and top5(t)),
                    ("포켓피봇만 + 펀더 OK", lambda t: t["kind"] == "포켓피봇" and ok(t)),
                    ("기준가 또는 매물대 돌파 + 펀더 OK", lambda t: t["kind"] != "포켓피봇" and ok(t))):
        c = [t for t in cand if f(t)]
        rr = sorted(account(c, days, "random", seed=k)["total_ret_pct"] for k in range(30))
        v = account(c, days, "rs"); v.pop("curve", None)
        out["account"].append({"name": name, "signals": len(c), **v, "random_total_ret_pct": {"min": rr[0], "median": rr[15], "max": rr[-1]}})
    # 책 기준 점수 비교 (2026-11-23 사용자 요청): 매출·영업이익·순이익(EPS 대신)이 1년 전 같은 분기보다 늘었는가, 0~3점
    blab = lambda t: "확인 불가" if t["bk"] is None else f"{t['bk']}점"  # noqa: E731
    B3 = [t for t in cand if brk(t)]
    out["book"] = {"score": "최근 분기 ① 매출 ② 영업이익 ③ 순이익(EPS 대신, 주식 수 변화 미반영)이 1년 전 같은 분기보다 늘었는가 · 문턱 없음(흑자이면서 증가)",
                   "coverage": dict(Counter(blab(t) for t in cand)),
                   "breakout_by_score": {b: st([t for t in B3 if blab(t) == b]) for b in labs},
                   "breakout_net_up": {"순이익 증가": st([t for t in B3 if t["bk_net"] is True]), "순이익 감소·적자": st([t for t in B3 if t["bk_net"] is False])},
                   "breakout_old_x_net": {"지금 점수 2점↑ + 순이익 증가": st([t for t in B3 if ok(t) and t["bk_net"] is True]), "지금 점수 2점↑ + 순이익 감소": st([t for t in B3 if ok(t) and t["bk_net"] is False]),
                                          "지금 점수 0~1점 + 순이익 증가": st([t for t in B3 if t["fp"] is not None and not ok(t) and t["bk_net"] is True])},
                   "breakout_3pt_by_year": {y: st([t for t in B3 if t["bk"] == 3 and t["date"][:4] == y]) for y in years_},
                   "breakout_under3_by_year": {y: st([t for t in B3 if t["bk"] is not None and t["bk"] < 3 and t["date"][:4] == y]) for y in years_},
                   "account": []}
    for name, f in (("기준가 돌파만 (기준)", brk),
                    ("기준가 돌파 + 지금 점수 2점↑", lambda t: brk(t) and ok(t)),
                    ("기준가 돌파 + 책 점수 3점(매출·영업이익·순이익 모두 증가)", lambda t: brk(t) and t["bk"] == 3),
                    ("기준가 돌파 + 책 점수 2점↑", lambda t: brk(t) and (t["bk"] or 0) >= 2),
                    ("기준가 돌파 + 책 점수 0~1점 (반대 확인)", lambda t: brk(t) and t["bk"] is not None and t["bk"] <= 1),
                    ("기준가 돌파 + 순이익 증가만", lambda t: brk(t) and t["bk_net"] is True),
                    ("기준가 돌파 + 지금 점수 2점↑ + 순이익 증가 (4항목 방식)", lambda t: brk(t) and ok(t) and t["bk_net"] is True),
                    ("기준가 돌파 + 책 점수 3점 + 코스피 20일선 위", lambda t: brk(t) and t["bk"] == 3 and t["market_ok"]),
                    ("기준가 돌파 + 책 점수 3점 + 업종 1~5위", lambda t: brk(t) and t["bk"] == 3 and top5(t))):
        c = [t for t in cand if f(t)]
        rr = sorted(account(c, days, "random", seed=k)["total_ret_pct"] for k in range(30))
        v = account(c, days, "rs"); v.pop("curve", None)
        out["book"]["account"].append({"name": name, "signals": len(c), **v, "random_total_ret_pct": {"min": rr[0], "median": rr[15], "max": rr[-1]}})
    out["seconds"] = round(time.time() - t0)
    (DATA / "backtest" / f"long_fund{_sfx(years)}.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    return {k: out[k] for k in ("made_at", "signals", "coverage", "by_score", "seconds")}


def run_vol(years=10, with_delisted=True):
    """돌파 거래량 문턱 비교 (2026-11-24 사용자 요청, 비교 자료): 삼성전자·SK하이닉스·삼성전기 같은 초대형 주도주가 기준가를 넘고도 '거래량 1.5배'에 걸려 신호가 거의 없었다.
    거래량 조건 없이 기준가 돌파를 모두 모은 뒤(그날 배수·그날 시총을 적어 둠) 문턱을 1.5 / 1.2 / 1.0 / 없음, 대형주만 완화, 주도 업종·대형주 포켓피봇 추가로 나눠 신호 성적과 계좌를 본다."""
    import dart_fin_hist as F
    t0 = time.time()
    cf = CACHE / f"long_cand_vol{_sfx(years)}.json"
    if cf.exists() and time.time() - cf.stat().st_mtime < 3 * 86400:
        o = json.loads(cf.read_text()); cand, days, uni = o["cand"], o["days"], o["uni"]
    else:
        old = S.RULES["breakout_vol"]
        S.RULES["breakout_vol"] = 0
        try:
            cand, days, uni = run(years, None, with_delisted, portfolio=True)
        finally:
            S.RULES["breakout_vol"] = old
        cf.write_text(json.dumps({"cand": cand, "days": days, "uni": uni}, ensure_ascii=False))
    print(f"신호 {len(cand)}건 · 실적 받기 시작", flush=True)
    F.fetch(F.needs([(t["code"], t["date"]) for t in cand]), log=lambda m: print(m, flush=True))
    for t in cand:
        sc = F.score_at(t["code"], t["date"])
        t["fp"] = sc["pts"] if sc else None
    st = lambda ts: {k: B.stats([{**t, "took": bool(t["be"]), "days": 0} for t in ts if t["exit"]]).get(k) for k in ("n", "win_rate", "avg_r", "payoff")}  # noqa: E731
    vr = lambda t: t["vol_ratio"] or 0  # noqa: E731
    cap = lambda t: t["cap_eok"] or 0  # noqa: E731
    BIG = 50000                                                   # 대형주 = 그날 시총 5조 원 이상
    brk = lambda t, thr=1.5: t["kind"] == "돌파" and vr(t) >= thr  # noqa: E731
    pp = lambda t: t["pp_ok"] and not brk(t)                      # 지금 규칙의 포켓피봇(돌파 신호가 아닌 날)  # noqa: E731
    top5 = lambda t: (t["sec_rank"] or 99) <= 5  # noqa: E731
    V = [("거래량 1.5배 (지금)", lambda t: brk(t)), ("거래량 1.2배", lambda t: brk(t, 1.2)), ("거래량 1.0배(평균 이상)", lambda t: brk(t, 1.0)), ("거래량 조건 없음", lambda t: brk(t, 0)),
         ("대형주(시총 5조↑)만 1.0배, 나머지 1.5배", lambda t: brk(t, 1.0 if cap(t) >= BIG else 1.5)),
         ("대형주(시총 5조↑)만 조건 없음, 나머지 1.5배", lambda t: brk(t, 0 if cap(t) >= BIG else 1.5)),
         ("주도 업종 1~5위만 1.0배, 나머지 1.5배", lambda t: brk(t, 1.0 if top5(t) else 1.5)),
         ("1.5배 + 주도 업종 1~5위 포켓피봇", lambda t: brk(t) or (pp(t) and top5(t))),
         ("1.5배 + 대형주 포켓피봇", lambda t: brk(t) or (pp(t) and cap(t) >= BIG)),
         ("1.5배 + 주도 업종 1~5위의 대형주 포켓피봇", lambda t: brk(t) or (pp(t) and top5(t) and cap(t) >= BIG))]
    ok = lambda t: (t["fp"] or 0) >= 2 and t["market_ok"]  # noqa: E731
    LEAD = {"005930": "삼성전자", "000660": "SK하이닉스", "009150": "삼성전기"}
    two = (datetime.strptime(days[-1], "%Y%m%d") - timedelta(days=730)).strftime("%Y%m%d")
    B_ = [t for t in cand if t["kind"] == "돌파"]
    out = {"made_at": datetime.now(KST).strftime("%Y-%m-%d %H:%M"), "years": years, "period": [days[0], days[-1]], "universe": uni, "define": run_vol.__doc__.strip(),
           "by_vol": {k: st([t for t in B_ if lo <= vr(t) < hi]) for k, lo, hi in (("1.0배 미만", 0, 1.0), ("1.0~1.2배", 1.0, 1.2), ("1.2~1.5배", 1.2, 1.5), ("1.5~2배", 1.5, 2), ("2배 이상", 2, 1e9))},
           "by_vol_big": {k: st([t for t in B_ if cap(t) >= BIG and lo <= vr(t) < hi]) for k, lo, hi in (("1.0배 미만", 0, 1.0), ("1.0~1.5배", 1.0, 1.5), ("1.5배 이상", 1.5, 1e9))},
           "by_vol_top5": {k: st([t for t in B_ if top5(t) and lo <= vr(t) < hi]) for k, lo, hi in (("1.0배 미만", 0, 1.0), ("1.0~1.5배", 1.0, 1.5), ("1.5배 이상", 1.5, 1e9))},
           "pp": {"전체": st([t for t in cand if pp(t)]), "주도 업종 1~5위": st([t for t in cand if pp(t) and top5(t)]), "대형주": st([t for t in cand if pp(t) and cap(t) >= BIG]),
                  "주도 업종 1~5위의 대형주": st([t for t in cand if pp(t) and top5(t) and cap(t) >= BIG])},
           "variants": []}
    for name, f in V:
        for tag, g in (("", lambda t: True), (" + 펀더 2점↑ + 코스피 20일선 위", ok)):
            c = [t for t in cand if f(t) and g(t)]
            rr = sorted(account(c, days, "random", seed=k)["total_ret_pct"] for k in range(30))
            v = account(c, days, "rs"); v.pop("curve", None); v.pop("by_year", None)
            lead = {n: [f"{t['date']} {t['r']:+.1f}R" for t in c if t["code"] == code and t["date"] >= two] for code, n in LEAD.items()}
            out["variants"].append({"name": name + tag, "signals": len(c), "per_signal": st(c), **v, "random_total_ret_pct": {"min": rr[0], "median": rr[15], "max": rr[-1]},
                                    "leaders_2y": {n: len(x) for n, x in lead.items()}, "leaders_2y_list": lead})
    out["seconds"] = round(time.time() - t0)
    (DATA / "backtest" / f"long_vol{_sfx(years)}.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    return {k: out[k] for k in ("made_at", "by_vol", "seconds")}


def run_fwd(years=10, with_delisted=True):
    """컨센서스를 넣으면 얼마나 달라질 수 있나 — 최대치 가늠 (2026-11-24 사용자 요청, 비교 자료).
    과거 시점의 컨센서스는 구할 수 없어서, 신호일 기준 '다음에 발표될 분기의 실제 실적'을 컨센서스 자리에 넣는다. 미래를 미리 본 값이라 실전에서는 불가능하고,
    '컨센서스가 완벽히 맞았다면'의 최대치다(실제 컨센서스는 틀리므로 효과는 이보다 작다). 신호는 지금 규칙의 기준가 돌파(거래량 1.5배 · 세부 업종 동반 상승)."""
    import dart_fin_hist as F
    t0 = time.time()
    o = json.loads((CACHE / f"long_cand_vol{_sfx(years)}.json").read_text()); days, uni = o["days"], o["uni"]
    cand = [t for t in o["cand"] if t["kind"] == "돌파" and (t["vol_ratio"] or 0) >= 1.5]
    sig = [(t["code"], t["date"]) for t in cand]
    need = F.needs(sig)
    for k, v in F.needs_next(sig).items():
        need.setdefault(k, set()).update(v)
    print(f"기준가 돌파 {len(cand)}건 · 실적 받기 시작 ({sum(len(v) for v in need.values())}쌍)", flush=True)
    F.fetch(need, log=lambda m: print(m, flush=True))
    for t in cand:
        a, b = F.score_at(t["code"], t["date"]), F.score_next(t["code"], t["date"])
        t["fp"], t["fn"] = (a["pts"] if a else None), (b["pts"] if b else None)
        bk = (b or {}).get("book") or {}
        t["fn_op"], t["fn_net"] = bk.get("op"), bk.get("net")
    st = lambda ts: {k: B.stats([{**t, "took": bool(t["be"]), "days": 0} for t in ts if t["exit"]]).get(k) for k in ("n", "win_rate", "avg_r", "payoff")}  # noqa: E731
    lab = lambda v: "확인 불가" if v is None else f"{v}점"  # noqa: E731
    labs = ["3점", "2점", "1점", "0점", "확인 불가"]
    okp = lambda t: (t["fp"] or 0) >= 2  # noqa: E731
    okn = lambda t: (t["fn"] or 0) >= 2  # noqa: E731
    LEAD = {"005930": "삼성전자", "000660": "SK하이닉스", "009150": "삼성전기"}
    two = (datetime.strptime(days[-1], "%Y%m%d") - timedelta(days=730)).strftime("%Y%m%d")
    years_ = sorted({t["date"][:4] for t in cand})
    out = {"made_at": datetime.now(KST).strftime("%Y-%m-%d %H:%M"), "years": years, "period": [days[0], days[-1]], "universe": uni, "signals": len(cand), "define": run_fwd.__doc__.strip(),
           "score": "지난 점수 = 신호일에 발표돼 있던 분기 / 앞 점수 = 다음에 발표될 분기(미래 자료). 둘 다 ① 분기 영업이익 +20%↑/흑자전환 ② 영업이익률 개선 ③ 누적 영업이익 +20%↑/흑자전환",
           "by_next": {b: st([t for t in cand if lab(t["fn"]) == b]) for b in labs},
           "by_past": {b: st([t for t in cand if lab(t["fp"]) == b]) for b in labs},
           "cross": {"지난 2점↑ · 앞 2점↑": st([t for t in cand if okp(t) and okn(t)]), "지난 2점↑ · 앞 0~1점(꺾임)": st([t for t in cand if okp(t) and t["fn"] is not None and not okn(t)]),
                     "지난 0~1점 · 앞 2점↑(좋아지는 중)": st([t for t in cand if t["fp"] is not None and not okp(t) and okn(t)]),
                     "지난 0~1점 · 앞 0~1점": st([t for t in cand if t["fp"] is not None and not okp(t) and t["fn"] is not None and not okn(t)])},
           "next_ok_by_year": {y: st([t for t in cand if okn(t) and t["date"][:4] == y]) for y in years_},
           "next_not_by_year": {y: st([t for t in cand if t["fn"] is not None and not okn(t) and t["date"][:4] == y]) for y in years_},
           "variants": []}
    V = [("기준가 돌파만", lambda t: True), ("지난 점수 2점↑ (지금 방식)", okp), ("앞 점수 2점↑ (컨센서스 최대치)", okn), ("앞 점수 3점", lambda t: t["fn"] == 3),
         ("지난 또는 앞 점수 2점↑", lambda t: okp(t) or okn(t)), ("지난 2점↑ 그리고 앞 2점↑", lambda t: okp(t) and okn(t)),
         ("앞 분기 영업이익 증가(문턱 없음)", lambda t: t["fn_op"] is True), ("앞 분기 순이익 증가(문턱 없음)", lambda t: t["fn_net"] is True),
         ("앞 점수 0~1점 (반대 확인)", lambda t: t["fn"] is not None and not okn(t))]
    for name, f in V:
        for tag, g in (("", lambda t: True), (" + 코스피 20일선 위", lambda t: t["market_ok"])):
            c = [t for t in cand if f(t) and g(t)]
            rr = sorted(account(c, days, "random", seed=k)["total_ret_pct"] for k in range(30))
            v = account(c, days, "rs"); v.pop("curve", None); v.pop("by_year", None)
            out["variants"].append({"name": name + tag, "signals": len(c), "per_signal": st(c), **v, "random_total_ret_pct": {"min": rr[0], "median": rr[15], "max": rr[-1]},
                                    "leaders_2y": {n: sum(1 for t in c if t["code"] == code and t["date"] >= two) for code, n in LEAD.items()}})
    out["seconds"] = round(time.time() - t0)
    (DATA / "backtest" / f"long_fwd{_sfx(years)}.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    return {k: out[k] for k in ("made_at", "signals", "by_next", "by_past", "seconds")}


def run_run(years=10, with_delisted=True):
    """쉬지 않고 오르는 종목을 잡는 방법 비교 (2026-11-24 사용자 요청, 비교 자료): 지금 규칙은 '쉬었다가 넘는 자리'만 잡아서 조정 없이 신고가를 이어 가는 구간에는 신호가 없다.
    진입 방식 = 쉬었다가 넘는 돌파(지금) / 55일 신고가 / 52주 신고가 / 달리는 종목의 20일선 눌림 뒤 재상승(최근 5일 안에 20일선 +2%까지 내려왔다가 어제 고가를 넘으며 상승, 52주 고점 −15% 이내).
    관문은 모두 같고(1개 미달 허용), 돌파류는 거래량 1.5배 + 세부 업종 동행, 눌림은 업종 동행만 요구한 것과 조건 없는 것을 함께 본다."""
    import dart_fin_hist as F
    t0 = time.time()
    cf = CACHE / f"long_cand_run{_sfx(years)}.json"
    if cf.exists() and time.time() - cf.stat().st_mtime < 3 * 86400:
        o = json.loads(cf.read_text()); cand, days, uni = o["cand"], o["days"], o["uni"]
    else:
        old = S.RULES.get("breakout_mode", "base")
        S.RULES["breakout_mode"] = "multi"
        try:
            cand, days, uni = run(years, None, with_delisted, portfolio=True, loose_ia=True)
        finally:
            S.RULES["breakout_mode"] = old
        cf.write_text(json.dumps({"cand": cand, "days": days, "uni": uni}, ensure_ascii=False))
    print(f"후보 {len(cand)}건", flush=True)
    vr = lambda t: t["vol_ratio"] or 0  # noqa: E731
    ia = lambda t: t["ia"] == "동반 상승"  # noqa: E731
    bo = lambda t: vr(t) >= 1.5 and ia(t)                        # 돌파류 공통 조건  # noqa: E731
    V = [("쉬었다가 넘는 돌파 (지금)", lambda t: t["f_base"] and bo(t)),
         ("55일 신고가 돌파만", lambda t: t["f_55"] and bo(t)),
         ("52주 신고가 돌파만", lambda t: t["f_250"] and bo(t)),
         ("지금 + 55일 신고가", lambda t: (t["f_base"] or t["f_55"]) and bo(t)),
         ("지금 + 52주 신고가", lambda t: (t["f_base"] or t["f_250"]) and bo(t)),
         ("지금 + 기준가 없는(달리는) 종목의 52주 신고가", lambda t: (t["f_base"] or (t["f_250"] and t["nobase"])) and bo(t)),
         ("20일선 눌림 뒤 재상승만 (업종 동행)", lambda t: t["f_pull"] and ia(t)),
         ("20일선 눌림 뒤 재상승만 (조건 없음)", lambda t: t["f_pull"]),
         ("지금 + 20일선 눌림 뒤 재상승(업종 동행)", lambda t: (t["f_base"] and bo(t)) or (t["f_pull"] and ia(t))),
         ("지금 + 52주 신고가 + 20일선 눌림(업종 동행)", lambda t: ((t["f_base"] or t["f_250"]) and bo(t)) or (t["f_pull"] and ia(t)))]
    used = [t for t in cand if any(f(t) for _, f in V)]
    print(f"조합에 쓰이는 신호 {len(used)}건 · 실적 받기 시작", flush=True)
    F.fetch(F.needs([(t["code"], t["date"]) for t in used]), log=lambda m: print(m, flush=True))
    for t in used:
        sc = F.score_at(t["code"], t["date"])
        t["fp"] = sc["pts"] if sc else None
    st = lambda ts: {k: B.stats([{**t, "took": bool(t["be"]), "days": 0} for t in ts if t["exit"]]).get(k) for k in ("n", "win_rate", "avg_r", "payoff")}  # noqa: E731
    ok = lambda t: (t.get("fp") or 0) >= 2 and t["market_ok"]  # noqa: E731
    LEAD = {"005930": "삼성전자", "000660": "SK하이닉스", "009150": "삼성전기"}
    two = (datetime.strptime(days[-1], "%Y%m%d") - timedelta(days=730)).strftime("%Y%m%d")
    out = {"made_at": datetime.now(KST).strftime("%Y-%m-%d %H:%M"), "years": years, "period": [days[0], days[-1]], "universe": uni, "define": run_run.__doc__.strip(),
           "per_signal": {"쉬었다가 넘는 돌파": st([t for t in used if t["f_base"] and bo(t)]),
                          "55일 신고가(기준가 돌파 아님)": st([t for t in used if t["f_55"] and not t["f_base"] and bo(t)]),
                          "52주 신고가(기준가 돌파 아님)": st([t for t in used if t["f_250"] and not t["f_base"] and bo(t)]),
                          "52주 신고가 · 기준가 없는 달리는 종목": st([t for t in used if t["f_250"] and t["nobase"] and bo(t)]),
                          "20일선 눌림 뒤 재상승 · 업종 동행": st([t for t in used if t["f_pull"] and ia(t)]),
                          "20일선 눌림 뒤 재상승 · 나 홀로": st([t for t in used if t["f_pull"] and not ia(t)]),
                          "20일선 눌림 · 업종 동행 · 거래량 1.5배↑": st([t for t in used if t["f_pull"] and ia(t) and vr(t) >= 1.5])},
           "variants": []}
    for name, f in V:
        for tag, g in (("", lambda t: True), (" + 펀더 2점↑ + 코스피 20일선 위", ok)):
            c = [t for t in used if f(t) and g(t)]
            rr = sorted(account(c, days, "random", seed=k)["total_ret_pct"] for k in range(30))
            v = account(c, days, "rs"); v.pop("curve", None); v.pop("by_year", None)
            out["variants"].append({"name": name + tag, "signals": len(c), "per_signal": st(c), **v, "random_total_ret_pct": {"min": rr[0], "median": rr[15], "max": rr[-1]},
                                    "leaders_2y": {n: sum(1 for t in c if t["code"] == code and t["date"] >= two) for code, n in LEAD.items()}})
    out["seconds"] = round(time.time() - t0)
    (DATA / "backtest" / f"long_run{_sfx(years)}.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    return {k: out[k] for k in ("made_at", "per_signal", "seconds")}


def run_ext(years=10, with_delisted=True):
    """끝물 급등(클라이맥스) 가려내기 비교 (2026-11-25 사용자 요청, 비교 자료): 돌파 신호가 '이미 얼마나 올라온 뒤'에 나왔는지로 나눠 성적을 본다.
    재는 것(모두 신호일 종가 기준) = 60일선 대비 거리 · 60일 저점 대비 상승 폭 · 최근 20일 수익률 · 신호일 하루 상승률 · 신호일 거래량 배수.
    신호 = 지금 규칙(쉬었다가 넘는 돌파 + 거래량 1.5배 + 업종 동행)과, 표본을 늘린 55일 신고가 돌파(같은 조건). 후보는 --run이 만든 것을 그대로 쓴다."""
    t0 = time.time()
    cf = CACHE / f"long_cand_run{_sfx(years)}.json"
    if not cf.exists():
        run_run(years, with_delisted)
    o = json.loads(cf.read_text()); cand, days, uni = o["cand"], o["days"], o["uni"]
    bo = lambda t: (t["vol_ratio"] or 0) >= 1.5 and t["ia"] == "동반 상승"  # noqa: E731
    used = [t for t in cand if (t["f_base"] or t["f_55"]) and bo(t) and t["exit"]]
    rows = {}
    for t in used:
        if t["code"] not in rows:
            r = fetch(t["code"], years); rows[t["code"]] = (r, {x["date"]: i for i, x in enumerate(r)})
        r, ix = rows[t["code"]]; i = ix.get(t["date"])
        if i is None or i < 60:
            continue
        c = r[i]["close"]
        t["x60"] = (c / (sum(x["close"] for x in r[i - 59:i + 1]) / 60) - 1) * 100
        t["up60"] = (c / min(x["low"] for x in r[i - 59:i + 1] if x["low"]) - 1) * 100
        t["ret20"] = (c / r[i - 20]["close"] - 1) * 100
        t["day"] = (c / r[i - 1]["close"] - 1) * 100
    used = [t for t in used if "x60" in t]
    st = lambda ts: {k: B.stats([{**t, "took": bool(t["be"]), "days": 0} for t in ts]).get(k) for k in ("n", "win_rate", "avg_r", "payoff", "reach_3r_pct")}  # noqa: E731
    CUT = {"x60": ("60일선 대비 거리", [10, 20, 30, 50]), "up60": ("60일 저점 대비 상승 폭", [30, 50, 80, 120]), "ret20": ("최근 20일 수익률", [10, 20, 35, 50]),
           "day": ("신호일 하루 상승률", [5, 10, 15, 25]), "vol_ratio": ("신호일 거래량 배수", [2, 3, 5, 8])}
    def table(ts):
        out = {}
        for k, (lab, cuts) in CUT.items():
            b = [-1e9] + cuts + [1e9]
            out[lab] = [{"range": (f"{cuts[0]} 미만" if j == 0 else f"{b[j]} 이상" if j == len(cuts) else f"{b[j]}~{b[j + 1]}"), **st([t for t in ts if b[j] <= (t[k] or 0) < b[j + 1]])} for j in range(len(b) - 1)]
        hot = lambda t: t["up60"] >= 80 and t["day"] >= 10 and (t["vol_ratio"] or 0) >= 3  # noqa: E731
        out["끝물 급등 모양(60일 저점 +80%↑ · 하루 +10%↑ · 거래량 3배↑)"] = {"해당": st([t for t in ts if hot(t)]), "그 밖": st([t for t in ts if not hot(t)])}
        return out
    out = {"made_at": datetime.now(KST).strftime("%Y-%m-%d %H:%M"), "years": years, "period": [days[0], days[-1]], "universe": uni, "define": run_ext.__doc__.strip(),
           "지금 규칙(쉬었다가 넘는 돌파)": table([t for t in used if t["f_base"]]), "55일 신고가 돌파(표본 넓힘)": table([t for t in used if t["f_55"]]),
           "seconds": round(time.time() - t0)}
    (DATA / "backtest" / f"long_ext{_sfx(years)}.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    return out


def _sim_clx(rows, i, R, clx=None, act=None):
    """backtest.simulate와 같은 청산 + '끝물 급등 날'(clx(rows, i, j)가 참인 날)의 행동. act = all(그날 종가에 전부) / half(남은 물량의 절반) / tight(그날부터 5일선 종가 이탈 시 전부)."""
    entry = rows[i]["close"]; unit = entry * R["one_r"]; stop = entry - unit; target = entry + R["take_r"] * unit
    c = [r["close"] for r in rows]
    took, realized, left, tight, hit = False, 0.0, 1.0, False, None
    fee = lambda frac, px: frac * px * R.get("cost", 0.0) / unit  # noqa: E731
    sell = lambda frac, px: frac * (px - entry) / unit - fee(frac, px)  # noqa: E731
    for j in range(i + 1, len(rows)):
        r = rows[j]
        if r["low"] <= stop:
            return {"r": round(realized + sell(left, min(r["open"], stop)), 2), "exit": r["date"], "days": j - i, "took": took, "hit": hit}
        if not took and r["high"] >= target:
            realized += sell(R["take_pct"], max(r["open"], target)); left -= R["take_pct"]; took, stop = True, entry
        if clx and hit is None and clx(rows, i, j):
            hit = r["date"]
            if act == "all":
                return {"r": round(realized + sell(left, c[j]), 2), "exit": r["date"], "days": j - i, "took": took, "hit": hit}
            if act == "half":
                realized += sell(left / 2, c[j]); left /= 2
            if act == "tight":
                tight = True
        ma = lambda n: sum(c[j - n + 1:j + 1]) / n  # noqa: E731
        if (took and c[j] < ma(R["trail_ma"])) or (tight and c[j] < ma(5)):
            return {"r": round(realized + sell(left, c[j]), 2), "exit": r["date"], "days": j - i, "took": took, "hit": hit}
    return {"r": round(realized + sell(left, rows[-1]["close"]), 2), "exit": None, "days": len(rows) - 1 - i, "took": took, "hit": hit}


def run_clx(years=10, with_delisted=True):
    """보유 중 끝물 급등(클라이맥스)이 나오면 파는 것과 지금 규칙대로 드는 것 비교 (2026-11-25 사용자 요청, 비교 자료). 진입은 지금 규칙 신호 그대로, 청산만 바꾼다.
    끝물 급등 날의 정의 두 가지 — 과열형: 종가가 60일선보다 50%↑ 위 + 하루 +10%↑ + 거래량 50일 평균의 3배↑ / 최대 급등형: 산 값보다 20%↑ 오른 상태에서 하루 +10%↑이고 그 상승률과 거래량이 모두 산 뒤 최대(5일 이상 보유).
    행동 세 가지 — 그날 종가에 전부 매도 / 남은 물량의 절반 매도 / 그날부터 5일선 종가 이탈 시 전부 매도. 첫 번째 끝물 급등 날에만 적용한다."""
    t0 = time.time()
    cf = CACHE / f"long_cand_run{_sfx(years)}.json"
    if not cf.exists():
        run_run(years, with_delisted)
    o = json.loads(cf.read_text()); cand, days, uni = o["cand"], o["days"], o["uni"]
    used = [t for t in cand if t["f_base"] and (t["vol_ratio"] or 0) >= 1.5 and t["ia"] == "동반 상승"]
    R = B.rules()
    def hot(rows, i, j):
        if j < 60 or not rows[j - 1]["close"]:
            return False
        c = rows[j]["close"]; v50 = sum(x["volume"] for x in rows[j - 50:j]) / 50
        return c / rows[j - 1]["close"] >= 1.10 and v50 and rows[j]["volume"] >= 3 * v50 and c / (sum(x["close"] for x in rows[j - 59:j + 1]) / 60) >= 1.5
    def peak(rows, i, j):
        if j - i < 5 or not rows[j - 1]["close"]:
            return False
        g = rows[j]["close"] / rows[j - 1]["close"]
        return (rows[j]["close"] >= rows[i]["close"] * 1.2 and g >= 1.10 and rows[j]["volume"] >= max(x["volume"] for x in rows[i:j])
                and all(g >= rows[k]["close"] / rows[k - 1]["close"] for k in range(i + 1, j) if rows[k - 1]["close"]))
    V = [("지금 규칙", None, None)] + [(f"{dn} → {an}", d, a) for dn, d in (("과열형", hot), ("최대 급등형", peak)) for an, a in (("그날 종가 전부 매도", "all"), ("절반 매도", "half"), ("5일선 이탈 시 매도", "tight"))]
    cache, res = {}, {n: [] for n, _, _ in V}
    for t in used:
        if t["code"] not in cache:
            r = fetch(t["code"], years); cache[t["code"]] = (r, {x["date"]: k for k, x in enumerate(r)})
        rows, ix = cache[t["code"]]; i = ix.get(t["date"])
        if i is None:
            continue
        for n, d, a in V:
            res[n].append({**_sim_clx(rows, i, R, d, a), "code": t["code"], "date": t["date"], "market_ok": t["market_ok"]})
    st = lambda ts: {k: B.stats([x for x in ts if x["exit"]]).get(k) for k in ("n", "win_rate", "avg_r", "payoff", "total_r", "avg_days", "max_dd_r")}  # noqa: E731
    base = res["지금 규칙"]
    out = {"made_at": datetime.now(KST).strftime("%Y-%m-%d %H:%M"), "years": years, "period": [days[0], days[-1]], "universe": uni, "define": run_clx.__doc__.strip(), "variants": []}
    for n, d, a in V:
        ts = res[n]; v = {"name": n, **st(ts)}
        if d:
            idx = [k for k, x in enumerate(ts) if x["hit"] and x["exit"] and base[k]["exit"]]
            v["끝물 급등이 나온 거래"] = {"n": len(idx), "이 방식 평균 R": round(sum(ts[k]["r"] for k in idx) / len(idx), 2) if idx else None,
                                   "지금 규칙 평균 R": round(sum(base[k]["r"] for k in idx) / len(idx), 2) if idx else None,
                                   "이 방식이 더 나았던 비율": round(sum(ts[k]["r"] > base[k]["r"] for k in idx) / len(idx) * 100, 1) if idx else None}
        out["variants"].append(v)
    out["seconds"] = round(time.time() - t0)
    (DATA / "backtest" / f"long_clx{_sfx(years)}.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    return out


def run_cons(years=10, with_delisted=True):
    """진짜 컨센서스로 본 펀더 점수 (2026-11-24 사용자 요청, 비교 자료): 신호일에 실제로 나와 있던 증권사 추정치(tools/consensus_hist.py — 월말 기준, 2025-02부터)로
    ① 올해 영업이익 추정치가 작년보다 +20%↑(또는 흑자 전환) ② 올해 EPS 추정치가 작년보다 증가 ③ 올해 영업이익 추정치가 1개월 전보다 상향 — 을 매겨 신호 성적과 계좌를 본다.
    기간이 2025-03부터라 21개월뿐이고 강세장 한 구간이다. 분기 추정치는 과거 기록이 없어 '다음 분기' 대신 '올해' 추정치를 쓴다. 신호는 지금 규칙의 기준가 돌파."""
    import consensus_hist as C
    import dart_fin_hist as F
    t0 = time.time()
    o = json.loads((CACHE / f"long_cand_vol{_sfx(years)}.json").read_text())
    FROM = "20250301"
    days = [d for d in o["days"] if d >= FROM]
    cand = [t for t in o["cand"] if t["kind"] == "돌파" and (t["vol_ratio"] or 0) >= 1.5 and t["date"] >= FROM]
    H = C.load()
    act = {}

    def prev_actual(code, fy):
        if code not in act:
            try:
                act[code] = {a["p"][:4]: a for a in json.loads((CACHE / "fund" / f"{code}.json").read_text()).get("annual") or [] if not a["e"]}
            except Exception:
                act[code] = {}
        return act[code].get(str(fy - 1))
    for t in cand:
        c = C.at(t["code"], t["date"], H)
        a, b = F.score_at(t["code"], t["date"]), F.score_next(t["code"], t["date"])
        t["fp"], t["fn"] = (a["pts"] if a else None), (b["pts"] if b else None)
        t["cs"] = None
        if not c:
            continue
        pa = prev_actual(t["code"], c["fy"]) or {}
        pop = pa.get("op") if pa.get("op") is not None else c.get("prev_op")
        peps = pa.get("eps") if pa.get("eps") is not None else c.get("prev_eps")
        t["c_op"] = None if pop is None else bool((pop <= 0 < c["op"]) or (pop > 0 and c["op"] / pop - 1 >= 0.2))
        t["c_eps"] = None if peps is None or c["eps"] is None else bool(c["eps"] > peps and c["eps"] > 0)
        t["c_up1"] = None if c["op_m1"] is None else c["op_m1"] > 0.5
        t["c_up3"] = None if c["op_m3"] is None else c["op_m3"] > 0.5
        t["c_dn1"] = None if c["op_m1"] is None else c["op_m1"] < -0.5
        t["cs"] = sum(bool(t[k]) for k in ("c_op", "c_eps", "c_up1"))
    st = lambda ts: {k: B.stats([{**t, "took": bool(t["be"]), "days": 0} for t in ts if t["exit"]]).get(k) for k in ("n", "win_rate", "avg_r", "payoff")}  # noqa: E731
    has = lambda t: t["cs"] is not None  # noqa: E731
    yn = lambda k: {"예": st([t for t in cand if has(t) and t.get(k) is True]), "아니오": st([t for t in cand if has(t) and t.get(k) is False])}  # noqa: E731
    out = {"made_at": datetime.now(KST).strftime("%Y-%m-%d %H:%M"), "period": [days[0], days[-1]], "signals": len(cand), "define": run_cons.__doc__.strip(),
           "coverage": {"컨센서스 있음": sum(1 for t in cand if has(t)), "없음": sum(1 for t in cand if not has(t))},
           "has_vs_none": {"컨센서스 있음": st([t for t in cand if has(t)]), "컨센서스 없음": st([t for t in cand if not has(t)])},
           "by_score": {f"{k}점": st([t for t in cand if t["cs"] == k]) for k in (3, 2, 1, 0)},
           "items": {"① 올해 영업이익 추정 +20%↑": yn("c_op"), "② 올해 EPS 추정 증가": yn("c_eps"), "③ 1개월 전보다 상향": yn("c_up1"), "(참고) 3개월 전보다 상향": yn("c_up3"), "(참고) 1개월 전보다 하향": yn("c_dn1")},
           "cross_13": {"①통과 · ③상향": st([t for t in cand if t.get("c_op") and t.get("c_up1")]), "①통과 · ③상향 아님": st([t for t in cand if t.get("c_op") and t.get("c_up1") is False]),
                        "①미달 · ③상향": st([t for t in cand if t.get("c_op") is False and t.get("c_up1")]), "①미달 · ③상향 아님": st([t for t in cand if t.get("c_op") is False and t.get("c_up1") is False])},
           "same_window": {"지난 실적 점수 2점↑": st([t for t in cand if (t["fp"] or 0) >= 2]), "지난 실적 점수 0~1점": st([t for t in cand if t["fp"] is not None and t["fp"] < 2]),
                           "다음 분기 실제(최대치) 2점↑": st([t for t in cand if (t["fn"] or 0) >= 2]), "다음 분기 실제(최대치) 0~1점": st([t for t in cand if t["fn"] is not None and t["fn"] < 2])},
           "variants": []}
    V = [("기준가 돌파만", lambda t: True), ("지난 실적 점수 2점↑ (지금 방식)", lambda t: (t["fp"] or 0) >= 2), ("컨센서스 점수 2점↑", lambda t: (t["cs"] or 0) >= 2), ("컨센서스 점수 3점", lambda t: t["cs"] == 3),
         ("컨센서스 점수 0~1점 (반대 확인)", lambda t: has(t) and t["cs"] <= 1), ("컨센서스 없음만", lambda t: not has(t)),
         ("컨센서스 2점↑ 또는 (컨센서스 없음 + 지난 실적 2점↑)", lambda t: (t["cs"] or 0) >= 2 or (not has(t) and (t["fp"] or 0) >= 2)),
         ("③ 1개월 상향만", lambda t: t.get("c_up1") is True), ("다음 분기 실제 2점↑ (최대치)", lambda t: (t["fn"] or 0) >= 2)]
    for name, f in V:
        for tag, g in (("", lambda t: True), (" + 코스피 20일선 위", lambda t: t["market_ok"])):
            c = [t for t in cand if f(t) and g(t)]
            rr = sorted(account(c, days, "random", seed=k)["total_ret_pct"] for k in range(30))
            v = account(c, days, "rs"); v.pop("curve", None); v.pop("by_year", None)
            out["variants"].append({"name": name + tag, "signals": len(c), "per_signal": st(c), **v, "random_total_ret_pct": {"min": rr[0], "median": rr[15], "max": rr[-1]}})
    out["seconds"] = round(time.time() - t0)
    (DATA / "backtest" / "long_cons.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    return {k: out[k] for k in ("made_at", "signals", "coverage", "by_score", "seconds")}


def run_ia(years=10, with_delisted=True):
    """업종 동반 상승(인더스트리 액션)을 어느 묶음으로 볼 것인가 + 거래량 문턱 (2026-11-24 사용자 요청, 비교 자료).
    삼성전자·SK하이닉스의 세부 업종 '반도체(메모리·대형)'은 4종목뿐이라 나머지 3종목 중 2종목이 +2% 올라야 '동반 상승'이 된다 → 반도체 전체가 오르는 날에도 '나 홀로'로 탈락.
    거래량·업종 조건 없이 기준가 돌파를 모두 모아, 업종 판정을 세부 업종 / 넓은 업종(wi26) / 둘 중 하나 / 없음으로, 거래량을 1.5배 / 대형주만 완화로 나눠 본다."""
    import dart_fin_hist as F
    t0 = time.time()
    cf = CACHE / f"long_cand_ia{_sfx(years)}.json"
    if cf.exists() and time.time() - cf.stat().st_mtime < 3 * 86400:
        o = json.loads(cf.read_text()); cand, days, uni = o["cand"], o["days"], o["uni"]
    else:
        old = S.RULES["breakout_vol"]
        S.RULES["breakout_vol"] = 0
        try:
            cand, days, uni = run(years, None, with_delisted, portfolio=True, loose_ia=True)
        finally:
            S.RULES["breakout_vol"] = old
        cf.write_text(json.dumps({"cand": cand, "days": days, "uni": uni}, ensure_ascii=False))
    cand = [t for t in cand if t["kind"] == "돌파"]
    print(f"기준가 돌파(거래량·업종 조건 없음) {len(cand)}건 · 실적 받기 시작", flush=True)
    F.fetch(F.needs([(t["code"], t["date"]) for t in cand]), log=lambda m: print(m, flush=True))
    for t in cand:
        sc = F.score_at(t["code"], t["date"])
        t["fp"] = sc["pts"] if sc else None
    st = lambda ts: {k: B.stats([{**t, "took": bool(t["be"]), "days": 0} for t in ts if t["exit"]]).get(k) for k in ("n", "win_rate", "avg_r", "payoff")}  # noqa: E731
    vr = lambda t: t["vol_ratio"] or 0  # noqa: E731
    big = lambda t: (t["cap_eok"] or 0) >= 50000  # noqa: E731
    fine = lambda t: t["ia"] == "동반 상승"  # noqa: E731
    wide = lambda t: t.get("ia_wide") == "동반 상승"  # noqa: E731
    IA = [("세부 업종 (지금)", fine), ("넓은 업종", wide), ("세부 또는 넓은 업종", lambda t: fine(t) or wide(t)),
          ("세부 업종, 단 8종목 미만이면 넓은 업종", lambda t: fine(t) if (t.get("ia_peers") or 0) >= 7 else wide(t)), ("업종 조건 없음", lambda t: True)]
    VOL = [("거래량 1.5배", lambda t: vr(t) >= 1.5), ("대형주만 1.0배", lambda t: vr(t) >= (1.0 if big(t) else 1.5))]
    ok = lambda t: (t["fp"] or 0) >= 2 and t["market_ok"]  # noqa: E731
    LEAD = {"005930": "삼성전자", "000660": "SK하이닉스", "009150": "삼성전기"}
    two = (datetime.strptime(days[-1], "%Y%m%d") - timedelta(days=730)).strftime("%Y%m%d")
    V15 = [t for t in cand if vr(t) >= 1.5]
    out = {"made_at": datetime.now(KST).strftime("%Y-%m-%d %H:%M"), "years": years, "period": [days[0], days[-1]], "universe": uni, "define": run_ia.__doc__.strip(),
           "by_ia": {"세부 동반 + 넓은 동반": st([t for t in V15 if fine(t) and wide(t)]), "세부만 동반": st([t for t in V15 if fine(t) and not wide(t)]),
                     "넓은 업종만 동반": st([t for t in V15 if not fine(t) and wide(t)]), "둘 다 아님": st([t for t in V15 if not fine(t) and not wide(t)])},
           "by_ia_big": {"세부 동반": st([t for t in V15 if big(t) and fine(t)]), "넓은 업종만 동반": st([t for t in V15 if big(t) and not fine(t) and wide(t)]),
                         "둘 다 아님": st([t for t in V15 if big(t) and not fine(t) and not wide(t)])},
           "variants": []}
    for vn, vf in VOL:
        for an, af in IA:
            for tag, g in (("", lambda t: True), (" + 펀더 2점↑ + 코스피 20일선 위", ok)):
                c = [t for t in cand if vf(t) and af(t) and g(t)]
                rr = sorted(account(c, days, "random", seed=k)["total_ret_pct"] for k in range(30))
                v = account(c, days, "rs"); v.pop("curve", None); v.pop("by_year", None)
                lead = {n: [f"{t['date']} {t['r']:+.1f}R" for t in c if t["code"] == code and t["date"] >= two] for code, n in LEAD.items()}
                out["variants"].append({"name": f"{vn} · 업종: {an}{tag}", "signals": len(c), "per_signal": st(c), **v, "random_total_ret_pct": {"min": rr[0], "median": rr[15], "max": rr[-1]},
                                        "leaders_2y": {n: len(x) for n, x in lead.items()}, "leaders_2y_list": lead})
    out["seconds"] = round(time.time() - t0)
    (DATA / "backtest" / f"long_ia{_sfx(years)}.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    return {k: out[k] for k in ("made_at", "by_ia", "seconds")}


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="긴 기간 백테스트 (상장폐지 종목 포함 · 그날 시총) — 비교 자료")
    ap.add_argument("--years", type=float, default=5)
    ap.add_argument("--limit", type=int)
    ap.add_argument("--no-delisted", action="store_true")
    ap.add_argument("--portfolio", action="store_true", help="계좌 하나를 실제처럼 굴리는 시뮬레이션 (동시 위험 6% · 고르는 순서 비교) → data/backtest/long_portfolio.json")
    ap.add_argument("--fund", action="store_true", help="발표된 실적으로 매긴 펀더 점수별 비교 → data/backtest/long_fund.json")
    ap.add_argument("--ia", action="store_true", help="업종 동반 상승을 세부 업종/넓은 업종으로 볼 때 비교 → data/backtest/long_ia.json")
    ap.add_argument("--fwd", action="store_true", help="다음 분기 실제 실적을 컨센서스 자리에 넣은 최대치 비교 → data/backtest/long_fwd.json")
    ap.add_argument("--cons", action="store_true", help="진짜 컨센서스(2025-03~)로 매긴 펀더 점수 비교 → data/backtest/long_cons.json")
    ap.add_argument("--run", action="store_true", help="쉬지 않고 오르는 종목 잡기 비교(신고가 돌파·20일선 눌림) → data/backtest/long_run.json")
    ap.add_argument("--clx", action="store_true", help="보유 중 끝물 급등이 나오면 파는 것과 지금 규칙 비교 → data/backtest/long_clx.json")
    ap.add_argument("--ext", action="store_true", help="끝물 급등 가려내기: 돌파 신호를 이미 올라온 폭으로 나눠 비교 → data/backtest/long_ext.json")
    ap.add_argument("--vol", action="store_true", help="돌파 거래량 문턱 비교(1.5/1.2/1.0/없음 · 대형주 완화 · 포켓피봇 추가)")
    ap.add_argument("--zone", action="store_true", help="기준가 돌파와 매물대 돌파 비교 → data/backtest/long_zone.json")
    a = ap.parse_args()
    res = run_clx(a.years, not a.no_delisted) if a.clx else run_ext(a.years, not a.no_delisted) if a.ext else run_run(a.years, not a.no_delisted) if a.run else run_cons(10) if a.cons else run_fwd(a.years, not a.no_delisted) if a.fwd else run_ia(a.years, not a.no_delisted) if a.ia else run_vol(a.years, not a.no_delisted) if a.vol else run_fund(a.years, not a.no_delisted) if a.fund else run_zone(a.years, not a.no_delisted) if a.zone else run_portfolio(a.years, not a.no_delisted) if a.portfolio else run(a.years, a.limit, not a.no_delisted)
    print(json.dumps(res, ensure_ascii=False, indent=1))
