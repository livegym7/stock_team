#!/usr/bin/env python3
"""실적·밸류에이션 (2026-11-13 사용자 확정). 토큰 0, 주문 기능 없음.

  python3 tools/fundamentals.py update [--budget 120] [--all]   # 네이버 재무(분기 6·연간 4, 마지막은 컨센서스) 받기
  python3 tools/fundamentals.py show --stock 005930

받는 것: 매출·영업이익·지배순이익·영업이익률·ROE·EPS·PER·PBR·부채비율·주당배당금 (네이버 증권, 비공식)
저장   : data/cache/fund/코드.json (깃허브 배포가 캐시로 이어 씀)
기록   : data/cache/fund/_est.json  — 날마다 올해 EPS·영업이익 컨센서스 (추정치 변화 1개월용)
         data/cache/fund/_sur.json  — 컨센서스(E)였던 분기가 실제로 바뀌면 '발표 직전 예상 vs 실제' (네이버 기준 서프라이즈·쇼크)
받는 주기: 실적 시즌(1/20~3/20, 4/20~5/25, 7/20~8/25, 10/20~11/25)은 하루, 그 밖은 7일 지난 것부터.
web_build가 build_web()으로 D.fund(종목별 압축 숫자)·D.fund_sur(최근 60일 서프라이즈)를 만든다.
판정: 영업이익 실제가 예상보다 +10%↑ 서프라이즈, −10%↓ 쇼크, 그 사이 부합. 참고용 — 매매 규칙 아님.
"""
import argparse, json, sys, time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import CACHE, DATA, http_get  # noqa: E402
from strategy_prep import KST  # noqa: E402

FUND = CACHE / "fund"
URL = "https://m.stock.naver.com/api/stock/{}/finance/{}"
KEYS = {"매출액": "sales", "영업이익": "op", "지배주주순이익": "net", "영업이익률": "opm", "ROE": "roe", "EPS": "eps",
        "PER": "per", "PBR": "pbr", "부채비율": "debt", "주당배당금": "dps"}
SEASON = [((1, 20), (3, 20)), ((4, 20), (5, 25)), ((7, 20), (8, 25)), ((10, 20), (11, 25))]
THRESH = 10.0


def _num(v):
    try:
        return float(str(v).replace(",", ""))
    except Exception:
        return None


def _load(p, default):
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return default


def in_season(d):
    md = (d.month, d.day)
    return any(a <= md <= b for a, b in SEASON)


def fetch(code):
    out = {}
    for kind in ("quarter", "annual"):
        try:
            d = json.loads(http_get(URL.format(code, kind))).get("financeInfo") or {}
        except Exception:
            return None
        if not d.get("trTitleList"):   # 재무 정보가 없는 종목(일부 지주·신규 상장)
            continue
        heads = [(t["key"], t["title"].rstrip("."), t.get("isConsensus") == "Y") for t in d.get("trTitleList") or []]
        rows = {KEYS[r["title"]]: r.get("columns") or {} for r in d.get("rowList") or [] if r.get("title") in KEYS}
        out[kind] = [{"p": t, "e": e, **{k: _num((rows.get(k) or {}).get(key, {}).get("value")) for k in KEYS.values()}}
                     for key, t, e in heads]
        time.sleep(0.12)
    return out if out.get("quarter") or out.get("annual") else None


def targets(all_=True):
    import new_highs
    codes = {k: v["name"] for k, v in new_highs.universe_info().items()} if all_ else {}
    try:
        from common import positions
        for p in positions():
            codes.setdefault(p["code"], p["name"])
    except Exception:
        pass
    try:
        for k, v in json.loads((DATA / "companies.json").read_text(encoding="utf-8")).items():
            codes.setdefault(k, v.get("name", k))
    except Exception:
        pass
    return codes


def _fy(annual):
    return next((a for a in annual if a["e"]), None)


def update(all_=True, budget=None, workers=4):
    FUND.mkdir(parents=True, exist_ok=True)
    now = datetime.now(KST)
    today = now.strftime("%Y-%m-%d")
    cut = (now - timedelta(days=1 if in_season(now) else 7)).isoformat(timespec="seconds")
    tg = targets(all_)

    def age(c):
        return _load(FUND / f"{c}.json", {}).get("at", "")
    todo = sorted((c for c in tg if age(c) < cut), key=age)
    est, sur = _load(FUND / "_est.json", {}), _load(FUND / "_sur.json", {})
    t0, res = time.time(), {"new": 0, "upd": 0, "fail": 0, "skipped": 0, "surprise_found": 0}

    def one(code):
        if budget and time.time() - t0 > budget:
            return code, "skip", None
        return code, "ok", fetch(code)
    with ThreadPoolExecutor(workers) as ex:
        for code, st, d in ex.map(one, todo):
            if st == "skip":
                res["skipped"] += 1
                continue
            if not d:
                res["fail"] += 1
                continue
            f = FUND / f"{code}.json"
            old = _load(f, {})
            # 컨센서스였던 분기가 실제가 되면: 발표 직전 예상 vs 실제
            oq = {q["p"]: q for q in old.get("quarter") or [] if q.get("e")}
            for q in d.get("quarter") or []:
                o = oq.get(q["p"])
                if o and not q["e"] and o.get("op") and q.get("op") is not None and o["op"] > 0:
                    sur[f"{code}:{q['p']}"] = {"code": code, "name": tg.get(code, code), "p": q["p"], "op": q["op"], "op_est": o["op"],
                                               "sales": q.get("sales"), "sales_est": o.get("sales"),
                                               "diff": round((q["op"] / o["op"] - 1) * 100, 1), "at": today, "est_at": (old.get("at") or "")[:10]}
                    res["surprise_found"] += 1
            fy = _fy(d.get("annual") or [])
            if fy:
                h = est.setdefault(code, {})
                h[today] = [fy["p"], fy.get("eps"), fy.get("op")]
                for k in sorted(h)[:-130]:
                    del h[k]
            f.write_text(json.dumps({"code": code, "name": tg.get(code, code), "at": now.isoformat(timespec="seconds"), **d},
                                    ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
            res["upd" if old else "new"] += 1
    (FUND / "_est.json").write_text(json.dumps(est, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    old_cut = (now - timedelta(days=200)).strftime("%Y-%m-%d")
    sur = {k: v for k, v in sur.items() if v.get("at", "") >= old_cut}
    (FUND / "_sur.json").write_text(json.dumps(sur, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    return res | {"targets": len(tg), "todo": len(todo), "season": in_season(now), "sec": round(time.time() - t0)}


def revision(h, days=28):
    """올해 EPS 컨센서스 변화(%) — 같은 연도끼리, days일 전(가장 가까운 기록)과 비교."""
    if not h:
        return None
    ds = sorted(h)
    last = h[ds[-1]]
    cut = (datetime.strptime(ds[-1], "%Y-%m-%d") - timedelta(days=days)).strftime("%Y-%m-%d")
    base = [d for d in ds if d <= cut and h[d][0] == last[0]]
    if not base:
        return None
    b = h[base[-1]]
    if not b[1] or not last[1] or b[1] <= 0:
        return None
    return round((last[1] / b[1] - 1) * 100, 1)


def verdict(diff):
    return None if diff is None else "서프라이즈" if diff >= THRESH else "쇼크" if diff <= -THRESH else "부합"


def build_web():
    """D.fund = {코드: {q: [[기간, E여부, 매출, 영업이익, 영업이익률]...], a: [[기간, E, 매출, 영업이익, EPS, PER, ROE, 주당배당, PBR]...],
                        pbr, debt, rev(EPS 추정 1개월 %), at}} · D.fund_sur = 최근 60일 네이버 기준 서프라이즈 목록."""
    if not FUND.exists():
        return {}, []
    est = _load(FUND / "_est.json", {})
    out = {}
    r = lambda v, n=1: None if v is None else round(v, n)  # noqa: E731
    for f in FUND.glob("[0-9A-Z]*.json"):
        d = _load(f, None)
        if not d:
            continue
        Q, A = d.get("quarter") or [], d.get("annual") or []
        la = [q for q in Q if not q["e"]]
        out[d["code"]] = {"q": [[q["p"], 1 if q["e"] else 0, r(q["sales"], 0), r(q["op"], 0), r(q["opm"])] for q in Q],
                          "a": [[a["p"], 1 if a["e"] else 0, r(a["sales"], 0), r(a["op"], 0), r(a["eps"], 0), r(a["per"]), r(a["roe"]), r(a["dps"], 0), r(a["pbr"])] for a in A],
                          "pbr": la[-1]["pbr"] if la else None, "debt": la[-1]["debt"] if la else None,
                          "rev": revision(est.get(d["code"])), "at": (d.get("at") or "")[:10]}
    cut = (datetime.now(KST) - timedelta(days=60)).strftime("%Y-%m-%d")
    sur = sorted((v | {"verdict": verdict(v["diff"])} for v in _load(FUND / "_sur.json", {}).values() if v.get("at", "") >= cut),
                 key=lambda v: v["at"], reverse=True)
    return out, sur


def main():
    ap = argparse.ArgumentParser(description="실적·밸류에이션: 네이버 재무·컨센서스 받기 (토큰 0)")
    sp = ap.add_subparsers(dest="cmd", required=True)
    u = sp.add_parser("update"); u.add_argument("--budget", type=int); u.add_argument("--mine", action="store_true", help="보유·기업 카드 종목만")
    s = sp.add_parser("show"); s.add_argument("--stock", required=True)
    a = ap.parse_args()
    if a.cmd == "update":
        print(json.dumps(update(not a.mine, a.budget), ensure_ascii=False))
    else:
        d = _load(FUND / f"{a.stock}.json", None)
        if not d:
            raise SystemExit("캐시 없음 — 먼저 update")
        print(json.dumps({"at": d["at"], "quarter": d["quarter"][-3:], "annual": d["annual"],
                          "rev_1m": revision(_load(FUND / "_est.json", {}).get(a.stock))}, ensure_ascii=False))


if __name__ == "__main__":
    main()
