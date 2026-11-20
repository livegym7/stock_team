"""검증실: 깡토 돌파 규칙을 과거 일봉에 대입해 성적을 낸다 (백테스트) + 감시 목록 성적표.

규칙 (config/account.toml · screener.RULES 그대로):
- 진입 신호: 그날까지 공통 관문 7개(정배열 일봉·주봉, RS 70↑, 고점 −50% 이내, 시총, 거래대금 100억↑, 1stage 50%↑)
  — 돌파는 1개 미달 허용(시총·거래대금·RS는 필수), 포켓피봇은 7/7 (2026-11-03)
  + 셋업(A~E, F) 있는 베이스의 기준가를 종가로 넘고 거래량이 50일 평균의 1.5배↑ (= "돌파")
  또는 포켓 피봇(G). 진입가 = 신호일 종가.
- 처음 손절 −8%(1R). 장중 저가가 닿으면 손절가(갭이면 시가)에 나감.
- 3R(+24%) 닿으면 50% 익절, 남은 물량 손절가를 본전으로.
- 그 뒤 20일선을 종가로 깨면 나머지 매도 (본전 손절도 유지).
- 같은 종목은 앞 거래가 끝나기 전 새 신호를 받지 않음. 수수료·세금·슬리피지는 넣지 않음.

한계 (화면에도 표시): 지금 시총 2천억↑ 종목만 대상(생존 편향), 시총 관문은 지금 값, 일봉만 써서 장중 순서는 모름(같은 날 3R과 손절이 다 닿으면 손절로 봄).

사용법:
    python3 tools/backtest.py              # 전 종목(약 1,100개, 3년치 일봉) → data/backtest/latest.json
    python3 tools/backtest.py --limit 100  # 빠른 확인
    python3 tools/backtest.py --scorecard  # 감시 목록 성적표만 (data/bus/*/screener.json 이후 흐름)
"""
import argparse
import json
import statistics
import time
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from pathlib import Path

import screener as S
from common import CACHE, DATA, http_get, load_toml
from naver_quote import KST
from universe import load as load_universe

OUT = DATA / "backtest"
LONG = CACHE / "daily_long"


def fetch_long(code, years=3.3):
    """3년여 일봉 (하루 한 번 캐시)."""
    path = LONG / f"{code}.json"
    today = datetime.now(KST).strftime("%Y%m%d")
    if path.exists():
        d = json.loads(path.read_text())
        if d.get("day") == today:
            return d["rows"]
    start = (datetime.now(KST) - timedelta(days=int(365 * years))).strftime("%Y%m%d")
    raw = None
    for attempt in range(3):
        try:
            raw = http_get(S.SISE, {"symbol": code, "requestType": 1, "timeframe": "day",
                                    "startTime": start, "endTime": today}).decode("utf-8", "replace")
            break
        except Exception:
            time.sleep(2)
    if raw is None:
        return []
    import re
    rows = []
    for line in re.findall(r"\[\"(\d{8})\",\s*([^\]]+)\]", raw):
        o, h, l, c, v = [float(x) for x in line[1].split(",")[:5]]
        if o and h and l and c:
            rows.append({"date": line[0], "open": o, "high": h, "low": l, "close": c, "volume": v})
    LONG.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"day": today, "rows": rows}))
    return rows


ETF_BRANDS = ("KODEX", "TIGER", "RISE", "ACE", "SOL", "KBSTAR", "HANARO", "PLUS", "KoAct", "TIME", "ARIRANG", "KIWOOM",
              "1Q", "BNK", "WON", "TRUSTON", "UNICORN", "FOCUS", "VITA", "마이티", "히어로즈", "파워", "에셋플러스", "TREX", "DAISHIN")


def is_etf(name):
    """ETF·ETN과 우선주·스팩·리츠 (개별 성장주가 아닌 것)."""
    import re
    return name.upper().startswith(tuple(b.upper() for b in ETF_BRANDS)) or bool(
        re.search(r"ETN|우$|우B$|우\(|스팩|리츠|액티브|채권|머니마켓|인프라$|리얼티$", name))


def rules():
    a = load_toml("account.toml")
    return {"one_r": S.RULES["one_r"], "take_r": a.get("breakeven_at_r", 3), "take_pct": a.get("take_profit_at_3r", 0.5),
            "trail_ma": a.get("trail_ma", 20)}


def simulate(rows, i, R):
    """i일 종가 진입 → 규칙대로 청산. 결과 R과 청산일."""
    entry = rows[i]["close"]
    unit = entry * R["one_r"]
    stop = entry - unit
    target = entry + R["take_r"] * unit
    c = [r["close"] for r in rows]
    took, realized, left = False, 0.0, 1.0
    for j in range(i + 1, len(rows)):
        r = rows[j]
        if r["low"] <= stop:  # 손절(또는 본전) — 갭 하락이면 시가
            px = min(r["open"], stop)
            realized += left * (px - entry) / unit
            return {"r": round(realized, 2), "exit": r["date"], "days": j - i, "how": "본전 청산" if took else "손절", "took": took}
        if not took and r["high"] >= target:
            px = max(r["open"], target)
            realized += R["take_pct"] * (px - entry) / unit
            left -= R["take_pct"]
            took, stop = True, entry
        if took and j >= R["trail_ma"]:
            ma = sum(c[j - R["trail_ma"] + 1:j + 1]) / R["trail_ma"]
            if c[j] < ma:
                realized += left * (c[j] - entry) / unit
                return {"r": round(realized, 2), "exit": r["date"], "days": j - i, "how": f"{R['trail_ma']}일선 이탈", "took": True}
    last = rows[-1]["close"]
    realized += left * (last - entry) / unit
    return {"r": round(realized, 2), "exit": None, "days": len(rows) - 1 - i, "how": "보유 중(평가)", "took": took}


def scan(stock, rows, rs_at, bench_ok, R, ia_at=None, require_ia=True):
    """한 종목의 과거 신호와 거래. require_ia면 돌파는 인더스트리 액션(업종 동반 상승)일 때만."""
    trades, busy_until = [], -1
    v = [r["volume"] for r in rows]
    h = [r["high"] for r in rows]
    c = [r["close"] for r in rows]
    for i in range(260, len(rows)):
        if i <= busy_until:
            continue
        vol50 = sum(v[i - 50:i]) / 50
        if not vol50 or c[i] <= c[i - 1]:
            continue
        brk = c[i] > max(h[i - 5:i]) and v[i] >= S.RULES["breakout_vol"] * vol50
        downs = [v[k] for k in range(i - 10, i) if c[k] < c[k - 1]]
        ma10 = sum(c[i - 9:i + 1]) / 10
        pp = downs and v[i] > max(downs) and 0.97 <= c[i] / ma10 <= 1.05
        if not (brk or pp):
            continue
        hist = rows[max(0, i - 400):i + 1]
        rs = rs_at(rows[i]["date"], stock["code"])
        checks, extra = S.gate(hist, stock, rs)
        prev = S.analyze(hist[:-1])
        base = prev.get("base")
        stage1 = base["stage1_pct"] if base else prev.get("run_pct", 0)
        checks["1stage 상승"] = stage1 >= S.RULES["min_stage1"]
        miss = [k for k, ok in checks.items() if not ok]
        must_ok = not any(k in miss for k in S.RULES.get("gate_must", ()))
        gate_brk = must_ok and len(miss) <= S.RULES.get("gate_allow_miss", 0)        # 돌파: 미달 허용
        gate_pp = must_ok and len(miss) <= S.RULES.get("gate_allow_miss_pp", 0)      # 포켓피봇: 따로
        if not (gate_brk or gate_pp):
            continue
        setups = [s for s in prev.get("setups", []) if s in "ABCDEF"]
        kind = None
        ia = ia_at(stock["code"], rows[i]["date"]) if ia_at else {"ia": "확인 불가"}
        brk_ok = base and setups and c[i] > prev.get("handle_high", base["pivot"]) and v[i] >= S.RULES["breakout_vol"] * vol50
        mode = S.RULES.get("breakout_mode", "base")          # base: 베이스 기준가 돌파 / d55: 55일 신고가 돌파 / both
        nd = S.RULES.get("breakout_days", 55)
        brk55 = c[i] > max(h[i - nd:i]) and v[i] >= S.RULES["breakout_vol"] * vol50
        ia_ok = not require_ia or ia["ia"] == "동반 상승"
        if gate_brk and ia_ok and brk_ok and mode in ("base", "both"):
            kind = "돌파"
        elif gate_brk and ia_ok and brk55 and mode in ("d55", "both"):
            kind = f"{nd}일 신고가 돌파"
        elif gate_pp and pp:
            kind = "포켓피봇"
        if not kind:
            continue
        res = simulate(rows, i, R)
        trades.append({**ia, "gate_miss": miss, "stock": stock["name"], "code": stock["code"], "date": rows[i]["date"], "entry": c[i], "kind": kind,
                       "setups": setups, "rs": rs, "vol_ratio": round(v[i] / vol50, 2), "market_ok": bench_ok.get(rows[i]["date"]),
                       **res})
        busy_until = i + res["days"]
    return trades


def stats(ts):
    if not ts:
        return {"n": 0}
    rs = [t["r"] for t in ts]
    wins = [x for x in rs if x > 0]
    loss = [x for x in rs if x <= 0]
    eq, peak, mdd, streak, worst = 0, 0, 0, 0, 0
    for x in [t["r"] for t in sorted(ts, key=lambda t: t["exit"] or "99999999")]:
        eq += x; peak = max(peak, eq); mdd = min(mdd, eq - peak)
        streak = streak + 1 if x <= 0 else 0; worst = max(worst, streak)
    return {"n": len(ts), "win_rate": round(len(wins) / len(ts) * 100, 1), "avg_r": round(statistics.mean(rs), 2),
            "avg_win": round(statistics.mean(wins), 2) if wins else 0, "avg_loss": round(statistics.mean(loss), 2) if loss else 0,
            "payoff": round(abs(statistics.mean(wins) / statistics.mean(loss)), 2) if wins and loss and statistics.mean(loss) else None,
            "profit_factor": round(sum(wins) / abs(sum(loss)), 2) if loss and sum(loss) else None,
            "total_r": round(sum(rs), 1), "reach_3r_pct": round(sum(t["took"] for t in ts) / len(ts) * 100, 1),
            "avg_days": round(statistics.mean(t["days"] for t in ts), 1), "max_dd_r": round(mdd, 1), "max_loss_streak": worst}


def run_backtest(limit=None, workers=4):
    t0 = time.time()
    R = rules()
    uni = [s for s in load_universe()["stocks"]
           if (s.get("market_cap_eok") or 0) >= S.RULES["min_mcap_eok"] and not is_etf(s["name"])
           and s.get("market") not in ("KONEX", "2")]  # ETF·ETN·코넥스 제외
    if limit:
        uni = sorted(uni, key=lambda s: -s["market_cap_eok"])[:limit]

    def one(s):
        rows = fetch_long(s["code"])
        time.sleep(0.15)
        return s, rows
    with ThreadPoolExecutor(workers) as ex:
        data = [x for x in ex.map(one, uni) if len(x[1]) >= 300]
    # 날짜별 RS 백분위 (12M 20% / 6M 30% / 3M 50%)
    raw = defaultdict(dict)
    for s, rows in data:
        c = [r["close"] for r in rows]
        for i in range(250, len(rows)):
            raw[rows[i]["date"]][s["code"]] = 0.2 * (c[i] / c[i - 249] - 1) + 0.3 * (c[i] / c[i - 125] - 1) + 0.5 * (c[i] / c[i - 62] - 1)
    ranks = {}
    for d, m in raw.items():
        order = sorted(m.values())
        n = len(order)
        import bisect
        ranks[d] = {k: round(bisect.bisect_right(order, x) / n * 99) for k, x in m.items()}
    rs_at = lambda d, code: ranks.get(d, {}).get(code)
    # 시장 국면: 코스피 지수 종가가 20일선 위인가 (2026-11-05 기준 변경을 2026-11-20에 반영, 옛 값은 KODEX 200)
    try:
        import sector_etf
        bench = sector_etf.daily("KOSPI", "코스피", 900)["rows"]
    except Exception:
        bench = fetch_long("069500")
    bc = [r["close"] for r in bench]
    bench_ok = {bench[i]["date"]: bc[i] > sum(bc[i - 19:i + 1]) / 20 for i in range(19, len(bench))}
    # 인더스트리 액션: 신호일에 같은 업종(사용자 분류 custom → 없으면 네이버 업종, 시총 2천억↑)이 함께 올랐나
    chg = {s["code"]: {rows[i]["date"]: rows[i]["close"] / rows[i - 1]["close"] - 1 for i in range(1, len(rows))} for s, rows in data}
    from sector_map import custom_map
    cmap = custom_map()
    ind_of = {s["code"]: (cmap.get(s["code"]) or "네이버:" + s["industry"]) for s, _ in data}
    by_ind = defaultdict(list)
    for code, g in ind_of.items():
        by_ind[g].append(code)

    def ia_at(code, day):
        xs = [chg[c][day] for c in by_ind[ind_of[code]] if c != code and day in chg[c]]
        label, share, med = S.industry_action(xs)
        return {"ia": label, "ia_group": ind_of[code], "ia_peers": len(xs), "ia_up_share": share, "ia_median": med}

    trades, loose = [], []
    for s, rows in data:
        trades += scan(s, rows, rs_at, bench_ok, R, ia_at, require_ia=True)
        loose += scan(s, rows, rs_at, bench_ok, R, ia_at, require_ia=False)
    trades.sort(key=lambda t: t["date"])
    closed = [t for t in trades if t["exit"]]
    by = lambda key: {k: stats([t for t in closed if key(t) == k]) for k in sorted({key(t) for t in closed}, key=str)}
    setup_stats = {}
    for s in "ABCDEF":
        setup_stats[s] = stats([t for t in closed if t["kind"] == "돌파" and s in t["setups"]])
    eq, curve = 0, []
    for t in sorted(closed, key=lambda t: t["exit"]):
        eq += t["r"]
        curve.append([t["exit"], round(eq, 2)])
    period = (min(t["date"] for t in trades), max(t["date"] for t in trades)) if trades else (None, None)
    out = {
        "made_at": datetime.now(KST).strftime("%Y-%m-%d %H:%M"), "seconds": round(time.time() - t0),
        "universe": len(data), "period": period, "rules": {**R, "breakout_vol": S.RULES["breakout_vol"], "max_giveback": S.RULES["max_giveback"],
                  "gate": f"돌파 관문 {S.RULES['gate_allow_miss']}개 미달 허용(필수: {', '.join(S.RULES['gate_must'])}) · 포켓피봇 7/7"},
        "source": "네이버 일봉(수정주가, 비공식) · 계산 Claude",
        "limits": ["지금 시총 2천억↑ 종목만 대상(사라진 종목 빠짐 → 성적이 좋게 나올 수 있음)", "시총 관문은 지금 값으로 판단",
                   "일봉만 사용: 같은 날 3R과 손절이 함께 닿으면 손절로 처리", "수수료·세금·슬리피지 미반영", "진입은 신호일 종가(장중 돌파가보다 불리할 수 있음)"],
        "all": stats(closed), "open_trades": len(trades) - len(closed),
        "ia_required": True,
        "compare_without_ia": {"all": stats([t for t in loose if t["exit"]]),
                               "breakout": stats([t for t in loose if t["exit"] and t["kind"] == "돌파"])},
        "by_kind": by(lambda t: t["kind"]), "by_setup": setup_stats,
        "by_market": {("지수 20일선 위" if k else "지수 20일선 아래"): v for k, v in by(lambda t: bool(t["market_ok"])).items()},
        "by_year": by(lambda t: t["date"][:4]),
        "by_ia": by(lambda t: t["ia"]),
        "by_kind_ia": {k: stats([t for t in loose if t["exit"] and t["kind"] + " · " + t["ia"].split("(")[0] == k])
                       for k in sorted({t["kind"] + " · " + t["ia"].split("(")[0] for t in loose})},
        "by_ia_market": by(lambda t: t["ia"].split("(")[0] + " · " + ("지수 20일선 위" if t["market_ok"] else "지수 20일선 아래")),
        "ia_rule": "인더스트리 액션(돌파 필수) = 신호일에 같은 업종(사용자 분류 custom, 없으면 네이버 업종 · 시총 2천억↑) 종목의 40% 이상이 +2%↑ 또는 업종 중앙값 +1.5%↑. 아래 '업종 동반/나 홀로' 줄은 조건 없이 잡은 신호를 나눠 본 비교",
        "by_exit": dict(Counter(t["how"] for t in closed)),
        "r_hist": dict(sorted(Counter(max(-2, min(6, round(t["r"]))) for t in closed).items())),
        "curve": curve[::max(1, len(curve) // 200)] + curve[-1:],
        "recent": trades[-40:][::-1],
        "best": sorted(closed, key=lambda t: -t["r"])[:8],
        "worst": sorted(closed, key=lambda t: t["r"])[:10],
    }
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "latest.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    return out


def scorecard():
    """지난 감시 목록 종목이 그 뒤 실제로 기준가를 넘었는지, 넘었다면 3R까지 갔는지."""
    R = rules()
    rows_out = []
    for f in sorted((DATA / "bus").glob("*/screener.json")):
        d = json.loads(f.read_text(encoding="utf-8"))
        day = d.get("as_of")
        for x in d.get("watch", []):
            lv = x.get("levels") or {}
            if not lv.get("breakout"):
                continue
            daily = [r for r in S.fetch_daily(x["code"]) if r["date"] > day]
            hit = next((i for i, r in enumerate(daily) if r["close"] > lv["breakout"]), None)
            item = {"list_day": day, "stock": x["stock"], "code": x["code"], "pivot": lv["breakout"], "setups": x.get("setups", []),
                    "days_after": len(daily), "broke": hit is not None}
            if hit is not None:
                entry = daily[hit]["close"]
                res = simulate([{"date": "", "open": entry, "high": entry, "low": entry, "close": entry, "volume": 0}] + daily[hit + 1:], 0, R)
                item.update({"break_day": daily[hit]["date"], "entry": entry, "result_r": res["r"], "how": res["how"]})
            else:
                item["max_up_pct"] = round((max((r["high"] for r in daily), default=x["close"]) / x["close"] - 1) * 100, 1)
                item["low_vs_stop"] = bool(daily and min(r["low"] for r in daily) <= lv["stop_1r"])
            rows_out.append(item)
    sig = []   # 실제 신호(셋업 + 거래량 + 업종 동행을 모두 갖춘 날) — 규칙 재검토 조건 '신호 30건'을 세는 곳 (2026-11-20)
    for f in sorted((DATA / "bus").glob("*/screener.json")):
        d = json.loads(f.read_text(encoding="utf-8"))
        if (d.get("as_of") or "") >= "20261103":
            sig += [{"day": d.get("as_of"), "stock": x.get("stock"), "code": x.get("code"), "setups": x.get("setups", [])} for x in d.get("signals", [])]
    out = {"signals": sig[::-1], "signals_n": len(sig), "signals_target": 30, "signals_since": "2026-11-03",
           "made_at": datetime.now(KST).strftime("%Y-%m-%d %H:%M"), "lists": len(list((DATA / "bus").glob("*/screener.json"))),
           "rows": rows_out[::-1], "broke": sum(r["broke"] for r in rows_out), "total": len(rows_out)}
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "scorecard.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    return out


def main():
    p = argparse.ArgumentParser(description="검증실: 백테스트 · 감시 목록 성적표")
    p.add_argument("--limit", type=int, help="시총 상위 n개만 (빠른 확인)")
    p.add_argument("--scorecard", action="store_true")
    a = p.parse_args()
    if a.scorecard:
        o = scorecard()
        print(json.dumps({k: o[k] for k in ("made_at", "lists", "total", "broke")}, ensure_ascii=False))
        return
    o = run_backtest(a.limit)
    scorecard()
    print(json.dumps({k: o[k] for k in ("made_at", "seconds", "universe", "period", "all", "by_kind", "by_market", "open_trades")},
                     ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
