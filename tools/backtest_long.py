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


def run(years=5, limit=None, with_delisted=True, workers=6, portfolio=False):
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
            for t in B.scan(s, rows, rs_at, bench_ok, R, ia_at, require_ia=True, cap_at=cap_at, all_signals=True):
                if s.get("delisted") and not t["exit"]:
                    t["exit"], t["how"] = rows[-1]["date"], "상장폐지까지 보유"
                sa = sector_at(t["code"], t["date"])
                cand.append({**{k: t.get(k) for k in ("code", "stock", "date", "kind", "rs", "r", "exit", "be", "how", "market_ok", "vol_ratio", "ia_group")},
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
    (DATA / "backtest" / "long.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
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
    (DATA / "backtest" / "long_portfolio.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
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
    (DATA / "backtest" / "long_zone.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    return {k: out[k] for k in ("made_at", "signals", "by_kind", "seconds")}


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="긴 기간 백테스트 (상장폐지 종목 포함 · 그날 시총) — 비교 자료")
    ap.add_argument("--years", type=float, default=5)
    ap.add_argument("--limit", type=int)
    ap.add_argument("--no-delisted", action="store_true")
    ap.add_argument("--portfolio", action="store_true", help="계좌 하나를 실제처럼 굴리는 시뮬레이션 (동시 위험 6% · 고르는 순서 비교) → data/backtest/long_portfolio.json")
    ap.add_argument("--zone", action="store_true", help="기준가 돌파와 매물대 돌파 비교 → data/backtest/long_zone.json")
    a = ap.parse_args()
    res = run_zone(a.years, not a.no_delisted) if a.zone else run_portfolio(a.years, not a.no_delisted) if a.portfolio else run(a.years, a.limit, not a.no_delisted)
    print(json.dumps(res, ensure_ascii=False, indent=1))
