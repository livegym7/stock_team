"""검증실 비교: 주봉 추세 조건·매물대 돌파를 바꿨을 때 성적 비교 (2026-11-18 사용자 요청, 토큰 0).

매매 규칙은 2027-01-31까지 고정 — 이 도구는 '바꾸면 어떻게 되나'를 보는 비교만 하고 규칙을 바꾸지 않는다.
backtest.py와 같은 데이터·청산 규칙·인더스트리 액션을 쓰고, 주봉 관문과 진입 신호만 바꾼다.

비교안
  현행     : 주봉 = 주봉 종가 > 10주선 > 30주선 (정배열) · 진입 = 베이스 기준가 돌파 / 포켓피봇
  30주     : 주봉 = 주봉 종가 > 30주선 이고 30주선이 4주 전보다 1% 넘게 내려가지 않음 (와인스타인 2단계)
  매물대   : 주봉 대신 '종가가 1년 최대 매물대(거래대금 가장 많이 쌓인 가격 칸) 위'
  30주+매물대 : 둘 다
  … + 매물대 돌파 : 위 각각에 '종가가 위쪽 주요 매물대 상단을 거래량 1.5배로 넘는 날'을 돌파 신호로 추가

python3 tools/backtest_variants.py            # → data/backtest/variants.json + 표(JSON) 출력
"""
import bisect
import json
import sys
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import screener as S
from backtest import OUT, fetch_long, is_etf, rules, simulate, stats
from naver_quote import KST
from universe import load as load_universe


def poc_top(rows, bins=12):
    """1년 거래대금 매물대에서 가장 큰 칸의 위쪽 가격."""
    lo, hi = min(r["low"] for r in rows), max(r["high"] for r in rows)
    if hi <= lo:
        return None
    bs = (hi - lo) / bins
    b = [0.0] * bins
    for r in rows:
        b[min(bins - 1, int((r["close"] - lo) / bs))] += r["close"] * r["volume"]
    k = b.index(max(b))
    return lo + (k + 1) * bs


def weekly_ok(hist, mode):
    wc = S.weekly_closes(hist)
    if mode == "cur":
        w10, w30 = S.sma(wc, 10), S.sma(wc, 30)
        return bool(w30 and wc[-1] > w10 > w30)
    w30, w30p = S.sma(wc, 30), S.sma(wc[:-4], 30)
    ok30 = bool(w30 and w30p and wc[-1] > w30 and w30 >= w30p * 0.99)
    pt = poc_top(hist[-250:])
    okp = bool(pt and hist[-1]["close"] > pt)
    return {"w30": ok30, "poc": okp, "w30poc": ok30 and okp}[mode]


def zone_break(hist):
    """어제 종가 ≤ 주요 매물대 상단 < 오늘 종가 인 매물대가 있나 (1년, 거래대금 평균 1.5배↑ 구간)."""
    z = S.volume_zones(hist[-251:-1])
    pc, c = hist[-2]["close"], hist[-1]["close"]
    return any(pc <= top < c for _, top in z)


def scan(stock, rows, rs_at, bench_ok, R, ia_at, wmode, zone):
    trades, busy = [], -1
    v = [r["volume"] for r in rows]; h = [r["high"] for r in rows]; c = [r["close"] for r in rows]
    for i in range(260, len(rows)):
        if i <= busy:
            continue
        vol50 = sum(v[i - 50:i]) / 50
        if not vol50 or c[i] <= c[i - 1]:
            continue
        volok = v[i] >= S.RULES["breakout_vol"] * vol50
        brk = c[i] > max(h[i - 5:i]) and volok
        downs = [v[k] for k in range(i - 10, i) if c[k] < c[k - 1]]
        ma10 = sum(c[i - 9:i + 1]) / 10
        pp = downs and v[i] > max(downs) and 0.97 <= c[i] / ma10 <= 1.05
        hist = rows[max(0, i - 400):i + 1]
        zb = zone and volok and zone_break(hist)
        if not (brk or pp or zb):
            continue
        rs = rs_at(rows[i]["date"], stock["code"])
        checks, _ = S.gate(hist, stock, rs)
        checks["정배열(주봉)"] = weekly_ok(hist, wmode)
        prev = S.analyze(hist[:-1])
        base = prev.get("base")
        stage1 = base["stage1_pct"] if base else prev.get("run_pct", 0)
        checks["1stage 상승"] = stage1 >= S.RULES["min_stage1"]
        miss = [k for k, ok in checks.items() if not ok]
        must_ok = not any(k in miss for k in S.RULES.get("gate_must", ()))
        gate_brk = must_ok and len(miss) <= S.RULES.get("gate_allow_miss", 0)
        gate_pp = must_ok and len(miss) <= S.RULES.get("gate_allow_miss_pp", 0)
        if not (gate_brk or gate_pp):
            continue
        setups = [s for s in prev.get("setups", []) if s in "ABCDEF"]
        ia = ia_at(stock["code"], rows[i]["date"])
        ia_ok = ia["ia"] == "동반 상승"
        brk_ok = base and setups and c[i] > prev.get("handle_high", base["pivot"]) and volok
        kind = None
        if gate_brk and ia_ok and brk_ok:
            kind = "돌파"
        elif gate_brk and ia_ok and zb:
            kind = "매물대 돌파"
        elif gate_pp and pp:
            kind = "포켓피봇"
        if not kind:
            continue
        res = simulate(rows, i, R)
        trades.append({"stock": stock["name"], "code": stock["code"], "date": rows[i]["date"], "kind": kind, "market_ok": bench_ok.get(rows[i]["date"]), **res})
        busy = i + res["days"]
    return trades


def main(workers=4):
    t0 = time.time()
    R = rules()
    uni = [s for s in load_universe()["stocks"] if (s.get("market_cap_eok") or 0) >= S.RULES["min_mcap_eok"]
           and not is_etf(s["name"]) and s.get("market") not in ("KONEX", "2")]
    with ThreadPoolExecutor(workers) as ex:
        data = [x for x in ex.map(lambda s: (s, fetch_long(s["code"])), uni) if len(x[1]) >= 300]
    raw = defaultdict(dict)
    for s, rows in data:
        c = [r["close"] for r in rows]
        for i in range(250, len(rows)):
            raw[rows[i]["date"]][s["code"]] = 0.2 * (c[i] / c[i - 249] - 1) + 0.3 * (c[i] / c[i - 125] - 1) + 0.5 * (c[i] / c[i - 62] - 1)
    ranks = {}
    for d, m in raw.items():
        order = sorted(m.values()); n = len(order)
        ranks[d] = {k: round(bisect.bisect_right(order, x) / n * 99) for k, x in m.items()}
    rs_at = lambda d, code: ranks.get(d, {}).get(code)
    bench = fetch_long("069500"); bc = [r["close"] for r in bench]
    bench_ok = {bench[i]["date"]: bc[i] > sum(bc[i - 19:i + 1]) / 20 for i in range(19, len(bench))}
    chg = {s["code"]: {rows[i]["date"]: rows[i]["close"] / rows[i - 1]["close"] - 1 for i in range(1, len(rows))} for s, rows in data}
    from sector_map import custom_map
    cmap = custom_map()
    ind_of = {s["code"]: (cmap.get(s["code"]) or "네이버:" + s["industry"]) for s, _ in data}
    by_ind = defaultdict(list)
    for code, g in ind_of.items():
        by_ind[g].append(code)

    def ia_at(code, day):
        xs = [chg[c][day] for c in by_ind[ind_of[code]] if c != code and day in chg[c]]
        label, _, _ = S.industry_action(xs)
        return {"ia": label}

    names = {"cur": "현행(10·30주 정배열)", "w30": "30주선 위+안 내려감", "poc": "1년 최대 매물대 위", "w30poc": "30주+매물대"}
    out = {"made_at": datetime.now(KST).strftime("%Y-%m-%d %H:%M"), "universe": len(data), "rows": []}
    for zone in (False, True):
        for wm in ("cur", "w30", "poc", "w30poc"):
            ts = []
            for s, rows in data:
                ts += scan(s, rows, rs_at, bench_ok, R, ia_at, wm, zone)
            closed = [t for t in ts if t["exit"]]
            row = {"variant": names[wm] + (" + 매물대 돌파" if zone else ""), "all": stats(closed), "open": len(ts) - len(closed),
                   "by_kind": {k: stats([t for t in closed if t["kind"] == k]) for k in sorted({t["kind"] for t in closed})},
                   "by_year": {y: stats([t for t in closed if t["date"][:4] == y]) for y in sorted({t["date"][:4] for t in closed})}}
            out["rows"].append(row)
            print(json.dumps({"variant": row["variant"], **{k: row["all"].get(k) for k in ("n", "win_rate", "avg_r", "profit_factor", "total_r", "max_dd_r", "max_loss_streak")}}, ensure_ascii=False), flush=True)
    out["seconds"] = round(time.time() - t0)
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "variants.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
