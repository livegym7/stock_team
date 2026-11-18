"""검증실 부록: 지수 ETF 하루 되돌림 전략 백테스트 (2026-11-18 사용자 요청, 토큰 0).

깡토 글(2026-11-18) '지수이지' 설명을 공개된 범위에서 재구성한 것 — N 값은 비공개라 여러 값으로 격자 시험.
지금 매매 규칙(돌파 추세추종)은 건드리지 않는다. '부록 전략'으로 쓸 만한지 보는 비교 자료일 뿐이다.

규칙 (재구성)
  대상   : KODEX 레버리지(122630) · KODEX 200선물인버스2X(252670) · KODEX 코스닥150레버리지(233740) · KODEX 코스닥150선물인버스(251340)
  IBS    : (종가 − 저가) ÷ (고가 − 저가) < N  → 그날 범위의 바닥 근처에서 끝남
  ATR    : 14일 평균 진폭(종가 대비 %)이 지난 250일 중 상위 M% 안 → 평소보다 많이 흔들리는 시기
  매수   : 신호 날 종가 (실제로는 15:00~15:20, 일봉엔 그 시각 가격이 없어 종가로 대신 → 실제보다 조금 좋게 나옴)
  매도   : 다음 날 종가 (최대 하루 보유). 트레일링 스탑은 장중 데이터가 없어 빼고 계산
  자금   : 같은 날 신호가 k개면 계좌를 k등분, 매일 복리
  비용   : 왕복 0.10%(수수료+슬리피지, ETF는 매도세 없음) 기본 · 보수적으로 0.23%도 계산

python3 tools/backtest_ibs.py          # → data/backtest/ibs.json + 요약 출력
"""
import json
import re
import statistics
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from common import CACHE, DATA, http_get
from naver_quote import KST

SISE = "https://api.finance.naver.com/siseJson.naver"
OUT = DATA / "backtest"
ETF = {"122630": "코스피 레버리지", "252670": "코스피 인버스2X", "233740": "코스닥 레버리지", "251340": "코스닥 인버스"}
IBS_GRID = [0.1, 0.15, 0.2, 0.25, 0.3]
ATR_GRID = [0, 50, 70, 80, 90]          # 상위 몇 % 이상 (0 = 조건 없음). 70 = 지난 250일 중 상위 30%
COSTS = [0.0, 0.001, 0.0023]


def fetch(code, years=11):
    path = CACHE / "daily_ibs" / f"{code}.json"
    today = datetime.now(KST).strftime("%Y%m%d")
    if path.exists():
        d = json.loads(path.read_text())
        if d.get("day") == today:
            return d["rows"]
    start = (datetime.now(KST) - timedelta(days=int(365 * years))).strftime("%Y%m%d")
    for _ in range(3):
        try:
            raw = http_get(SISE, {"symbol": code, "requestType": 1, "timeframe": "day", "startTime": start, "endTime": today}).decode("utf-8", "replace")
            break
        except Exception:
            time.sleep(2)
    rows = []
    for line in re.findall(r"\[\"(\d{8})\",\s*([^\]]+)\]", raw):
        o, h, l, c, v = [float(x) for x in line[1].split(",")[:5]]
        if o and h and l and c:
            rows.append({"date": line[0], "open": o, "high": h, "low": l, "close": c})
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"day": today, "rows": rows}))
    return rows


def features(rows):
    """날짜별 IBS·ATR 상위 %·다음 날 수익률."""
    out = {}
    tr = []
    for i, r in enumerate(rows):
        pc = rows[i - 1]["close"] if i else r["close"]
        tr.append(max(r["high"], pc) - min(r["low"], pc))
        if i < 14 + 250 or i + 1 >= len(rows):
            continue
        atrp = [sum(tr[k - 13:k + 1]) / 14 / rows[k]["close"] for k in range(i - 249, i + 1)]
        rank = sum(1 for x in atrp if x <= atrp[-1]) / len(atrp) * 100
        rng = r["high"] - r["low"]
        out[r["date"]] = {"ibs": (r["close"] - r["low"]) / rng if rng > 0 else 0.5, "atr_rank": rank,
                          "next": rows[i + 1]["close"] / r["close"] - 1, "next_date": rows[i + 1]["date"]}
    return out


def regime(kospi):
    """코스피 역배열(전일 종가 < 20 < 60 < 120일선)·🔴(종가 < 20일선) 날짜."""
    c = [r["close"] for r in kospi]
    rev, red = set(), set()
    for i in range(120, len(kospi)):
        m = lambda n: sum(c[i - n + 1:i + 1]) / n
        if c[i] < m(20) < m(60) < m(120):
            rev.add(kospi[i]["date"])
        if c[i] < m(20):
            red.add(kospi[i]["date"])
    return rev, red


def run(F, ibs, atr, cost, days=None):
    dates = sorted({d for f in F.values() for d in f})
    eq, peak, mdd, trades, rets, active = 1.0, 1.0, 0.0, [], [], 0
    by_year = {}
    for d in dates:
        if days is not None and d not in days:
            continue
        sig = [(code, f[d]) for code, f in F.items() if d in f and f[d]["ibs"] < ibs and f[d]["atr_rank"] >= atr]
        if not sig:
            continue
        active += 1
        r = sum(x["next"] - cost for _, x in sig) / len(sig)
        for code, x in sig:
            trades.append(x["next"] - cost)
        eq *= 1 + r; rets.append(r)
        peak = max(peak, eq); mdd = min(mdd, eq / peak - 1)
        y = d[:4]; by_year[y] = by_year.get(y, 1.0) * (1 + r)
    if not trades:
        return {"n": 0}
    win = [t for t in trades if t > 0]; loss = [t for t in trades if t <= 0]
    streak = cur = 0
    for r in rets:
        cur = cur + 1 if r <= 0 else 0; streak = max(streak, cur)
    return {"n": len(trades), "days": active, "total_pct": round((eq - 1) * 100, 1), "mdd_pct": round(mdd * 100, 1),
            "win_rate": round(len(win) / len(trades) * 100, 1), "avg_pct": round(statistics.mean(trades) * 100, 3),
            "pf": round(sum(win) / -sum(loss), 2) if loss and sum(loss) < 0 else None,
            "worst_day_pct": round(min(rets) * 100, 2), "loss_streak": streak,
            "by_year": {y: round((v - 1) * 100, 1) for y, v in sorted(by_year.items())}}


def board(n_recent=15):
    """부록 현황판 데이터 (2026-11-18, 토큰 0): 웹이 1분 시세로 오늘 IBS·ATR 순위·코스피 20일선을 다시 계산할 재료.
    어제까지 확정된 일봉만 넣는다(오늘 봉은 웹이 현재가로 만듦)."""
    today = datetime.now(KST).strftime("%Y%m%d")
    out = {"made_at": datetime.now(KST).strftime("%Y-%m-%d %H:%M"), "params": {"ibs": 0.2, "atr": 70, "frac": 0.3, "cost": 0.001}, "etfs": [], "recent": []}
    kos = [r for r in fetch("KOSPI") if r["date"] < today]
    kc = [r["close"] for r in kos]
    out["kospi"] = {"date": kos[-1]["date"], "close": kc[-1], "sum19": sum(kc[-19:]), "ma20": sum(kc[-20:]) / 20, "ma60": sum(kc[-60:]) / 60, "ma120": sum(kc[-120:]) / 120}
    rev, red = regime(kos)
    for code, name in ETF.items():
        rows = [r for r in fetch(code) if r["date"] < today]
        tr = []
        for i, r in enumerate(rows):
            pc = rows[i - 1]["close"] if i else r["close"]
            tr.append(max(r["high"], pc) - min(r["low"], pc))
        hist = [sum(tr[k - 13:k + 1]) / 14 / rows[k]["close"] for k in range(len(rows) - 249, len(rows))]
        last = rows[-1]; rng = last["high"] - last["low"]
        out["etfs"].append({"code": code, "name": name, "date": last["date"], "prev_close": last["close"], "high": last["high"], "low": last["low"],
                            "tr13": [round(x, 2) for x in tr[-13:]], "atr_hist": sorted(round(x, 6) for x in hist),
                            "ibs": round((last["close"] - last["low"]) / rng, 3) if rng > 0 else None,
                            "atr_rank": round(sum(1 for x in hist if x <= hist[-1]) / len(hist) * 100)})
    F = {c: features(fetch(c)) for c in ETF}
    sig = []
    for c, f in F.items():
        for d, v in f.items():
            if v["ibs"] < 0.2 and v["atr_rank"] >= 70:
                sig.append({"date": d, "code": c, "name": ETF[c], "ibs": round(v["ibs"], 2), "atr_rank": round(v["atr_rank"]),
                            "red": d in red, "next_pct": round(v["next"] * 100, 2), "exit_date": v["next_date"]})
    out["recent"] = sorted(sig, key=lambda x: x["date"], reverse=True)[:n_recent]
    try:
        out["stats"] = json.loads((OUT / "ibs.json").read_text(encoding="utf-8")).get("appendix")
    except Exception:
        out["stats"] = None
    return out


def main():
    t0 = time.time()
    F = {code: features(fetch(code)) for code in ETF}
    kospi = fetch("KOSPI")
    rev, red = regime(kospi)
    first = max(min(f) for f in F.values())          # 4종 모두 있는 날부터 (공정 비교)
    F = {c: {d: v for d, v in f.items() if d >= first} for c, f in F.items()}
    grid = []
    for ib in IBS_GRID:
        for at in ATR_GRID:
            s = run(F, ib, at, 0.001)
            grid.append({"ibs": ib, "atr": at, **{k: s.get(k) for k in ("n", "total_pct", "mdd_pct", "win_rate", "avg_pct", "pf", "loss_streak")}})
    base = (0.2, 70)
    detail = {}
    for name, days in (("전체", None), ("코스피 역배열 날", rev), ("코스피 20일선 아래(🔴)", red), ("코스피 20일선 위", {d for f in F.values() for d in f} - red)):
        detail[name] = {f"비용 {c * 100:.2f}%": run(F, *base, c, days) for c in COSTS}
    per = {ETF[c]: run({c: F[c]}, *base, 0.001) for c in ETF}
    # 부록 후보 (2026-11-18): 코스피 20일선 아래(🔴)에서만 · 레버리지만 비교 · 2026 제외 · 계좌 일부(20·30·50%)만 쓸 때
    L = {c: F[c] for c in ("122630", "233740")}
    pick = lambda s: {k: s.get(k) for k in ("n", "total_pct", "mdd_pct", "win_rate", "avg_pct", "pf", "worst_day_pct", "loss_streak", "by_year")}
    appendix = {f"{nm} · {dn}": pick(run(FF, *base, 0.001, days)) for nm, FF in (("4종", F), ("레버리지만", L))
                for dn, days in (("전체", None), ("🔴", red), ("역배열", rev))}
    appendix["4종 · 🔴 · 2026 제외"] = pick(run(F, *base, 0.001, {d for d in red if d < "20260101"}))
    for frac in (0.2, 0.3, 0.5):
        G = {c: {d: dict(v, next=v["next"] * frac) for d, v in f.items()} for c, f in F.items()}
        appendix[f"4종 · 🔴 · 계좌 {int(frac * 100)}%만"] = pick(run(G, *base, 0.001 * frac, red))
    k = [r for r in kospi if r["date"] >= first]
    out = {"made_at": datetime.now(KST).strftime("%Y-%m-%d %H:%M"), "from": first, "to": k[-1]["date"], "seconds": round(time.time() - t0),
           "note": "깡토 '지수이지' 공개 설명 재구성 · N 비공개라 격자 · 종가 진입(실제 15:00~15:20) · 트레일링 스탑 없음 · 비교 자료, 매매 규칙 아님",
           "base": {"ibs": base[0], "atr": base[1]}, "kospi_bh_pct": round((k[-1]["close"] / k[0]["close"] - 1) * 100, 1),
           "grid": grid, "detail": detail, "per_etf": per, "appendix": appendix}
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "ibs.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps({k: out[k] for k in ("from", "to", "kospi_bh_pct", "base")}, ensure_ascii=False))
    for g in grid:
        print(json.dumps(g, ensure_ascii=False))
    print(json.dumps(detail, ensure_ascii=False, indent=1))
    print(json.dumps(per, ensure_ascii=False))
    print(json.dumps(appendix, ensure_ascii=False))


if __name__ == "__main__":
    if sys.argv[1:2] == ["board"]:
        print(json.dumps(board(), ensure_ascii=False)[:2000])
    else:
        main()
