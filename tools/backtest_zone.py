"""검증실 비교 2: 거래량을 동반한 '매물대 돌파'를 여러 정의로 다듬어 성적 비교 (2026-11-18 사용자 요청, 토큰 0).

매매 규칙은 고정 — 비교만 한다. 관문(7개, 돌파 1개 미달 허용)·인더스트리 액션(필수)·청산 규칙은 backtest.py와 같다.
매물대 = 최근 1년 거래대금을 가격 24칸에 나눠, 평균의 1.5배 넘는 칸을 이어 붙인 구간. 구간 비중 = 1년 거래대금 중 몫.

정의
  Z1 단순        : 어제 종가 ≤ 매물대 상단 < 오늘 종가, 거래량 50일 평균 1.5배↑ (지난번 정의)
  Z2 큰 매물대    : Z1 + 그 매물대 비중 15%↑ + 거래량 2배↑
  Z3 위가 비어 있음 : Z2 + 돌파 뒤 위쪽에 남은 매물 비중 15% 미만
  Z4 확인 2일     : Z2 + 다음 2거래일 종가가 매물대 상단 위 유지 → 3일째 종가 진입
  Z5 전부        : Z3 + Z4
  (참고) 기존 돌파를 '큰 매물대도 함께 뚫은 것 / 아닌 것', '1년 최대 매물대를 뚫음 / 이미 위 / 아래'로 나눠 본 성적
  P1 1년 최대 매물대 돌파(단독): 어제 종가 ≤ 최대 매물대 상단 < 오늘 종가, 거래량 1.5배↑ (2026-11-18 추가)
  P2 차트 빨간 막대 돌파(단독): 웹 차트 매물대(200봉·10칸·거래량을 종가 칸에)의 최대 칸 상단을 거래량 1.5배로 넘음 (2026-11-18, 셋업 보드 표시 기준)

python3 tools/backtest_zone.py   # → data/backtest/zone.json
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

NB = 24


def zones(rows):
    """[(아래, 위, 비중%)]과 가격→위쪽 비중 함수."""
    lo, hi = min(r["low"] for r in rows), max(r["high"] for r in rows)
    if hi <= lo:
        return [], lambda p: 0
    st = (hi - lo) / NB
    b = [0.0] * NB
    for r in rows:
        a, c = r["low"], r["high"]
        for i in range(max(0, int((a - lo) / st)), min(NB, int((c - lo) / st) + 1)):
            ov = min(c, lo + (i + 1) * st) - max(a, lo + i * st)
            if ov > 0 and c > a:
                b[i] += r["volume"] * (a + c) / 2 * ov / (c - a)
    tot = sum(b) or 1
    avg = tot / NB
    out, cur = [], None
    for i in range(NB):
        if b[i] >= 1.5 * avg:
            if cur and i == cur[1] + 1:
                cur[1] = i
            else:
                cur = [i, i]; out.append(cur)
    Z = [(lo + a * st, lo + (z + 1) * st, sum(b[a:z + 1]) / tot * 100) for a, z in out]
    above = lambda p: sum(b[i] for i in range(NB) if lo + i * st >= p) / tot * 100
    return Z, above


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
    chg = {s["code"]: {rows[i]["date"]: rows[i]["close"] / rows[i - 1]["close"] - 1 for i in range(1, len(rows))} for s, rows in data}
    from sector_map import custom_map
    cmap = custom_map()
    ind_of = {s["code"]: (cmap.get(s["code"]) or "네이버:" + s["industry"]) for s, _ in data}
    by_ind = defaultdict(list)
    for code, g in ind_of.items():
        by_ind[g].append(code)
    ia_ok = lambda code, day: S.industry_action([chg[c][day] for c in by_ind[ind_of[code]] if c != code and day in chg[c]])[0] == "동반 상승"

    T = defaultdict(list)          # 정의별 거래
    busy = defaultdict(dict)       # 정의별·종목별 다음 진입 가능 위치
    for s, rows in data:
        v = [r["volume"] for r in rows]; h = [r["high"] for r in rows]; c = [r["close"] for r in rows]
        for i in range(260, len(rows) - 3):
            vol50 = sum(v[i - 50:i]) / 50
            if not vol50 or c[i] <= c[i - 1] or v[i] < 1.5 * vol50:
                continue
            vr = v[i] / vol50
            hist = rows[max(0, i - 400):i + 1]
            Z, above = zones(hist[-251:-1])
            hit = [z for z in Z if c[i - 1] <= z[1] < c[i]]
            prev = S.analyze(hist[:-1]); base = prev.get("base")
            setups = [x for x in prev.get("setups", []) if x in "ABCDEF"]
            brk = base and setups and c[i] > prev.get("handle_high", base["pivot"])
            if not hit and not brk:
                continue
            rs = ranks.get(rows[i]["date"], {}).get(s["code"])
            checks, _ = S.gate(hist, s, rs)
            stage1 = base["stage1_pct"] if base else prev.get("run_pct", 0)
            checks["1stage 상승"] = stage1 >= S.RULES["min_stage1"]
            miss = [k for k, ok in checks.items() if not ok]
            if any(k in miss for k in S.RULES.get("gate_must", ())) or len(miss) > S.RULES.get("gate_allow_miss", 0):
                continue
            if not ia_ok(s["code"], rows[i]["date"]):
                continue
            big = [z for z in hit if z[2] >= 15]
            top = max((z[1] for z in big), default=None)
            empty = top is not None and above(c[i]) < 15
            hold = top is not None and all(c[i + k] > top for k in (1, 2))
            cand = {"Z1 단순": (bool(hit), 0), "Z2 큰 매물대": (bool(big) and vr >= 2, 0), "Z3 위가 비어 있음": (bool(big) and vr >= 2 and empty, 0),
                    "Z4 확인 2일": (bool(big) and vr >= 2 and hold, 2), "Z5 전부": (bool(big) and vr >= 2 and empty and hold, 2)}
            if Z:
                pz = max(Z, key=lambda z: z[2])   # 1년 최대 매물대
                poc_brk = c[i - 1] <= pz[1] < c[i]
                if poc_brk and vr >= 1.5:
                    cand["P1 1년 최대 매물대 돌파(단독)"] = (True, 0)
                if brk:
                    cand["기존 돌파 · 1년 최대 매물대도 뚫음" if poc_brk else ("기존 돌파 · 이미 최대 매물대 위" if c[i - 1] > pz[1] else "기존 돌파 · 최대 매물대 아래")] = (True, 0)
            mz = S.max_zone(hist[-201:-1])   # 웹 차트 빨간 막대 = 최대 매물대 (2026-11-18 사용자 요청)
            if mz:
                mt = mz["top"]; m_brk = c[i - 1] <= mt < c[i]
                if m_brk and vr >= 1.5:
                    cand["P2 차트 빨간 막대 돌파(단독)"] = (True, 0)
                if brk:
                    cand["기존 돌파 · 차트 빨간 막대도 뚫음" if m_brk else ("기존 돌파 · 이미 차트 빨간 막대 위" if c[i - 1] > mt else "기존 돌파 · 차트 빨간 막대 아래")] = (True, 0)
            if brk:
                cand["기존 돌파"] = (True, 0)
                cand["기존 돌파 · 큰 매물대도 뚫음" if big else "기존 돌파 · 매물대 없음"] = (True, 0)
            for name, (ok, lag) in cand.items():
                j = i + lag
                if not ok or j <= busy[name].get(s["code"], -1):
                    continue
                res = simulate(rows, j, R)
                T[name].append({"code": s["code"], "date": rows[j]["date"], **res})
                busy[name][s["code"]] = j + res["days"]
    order = ["기존 돌파", "기존 돌파 · 차트 빨간 막대도 뚫음", "기존 돌파 · 이미 차트 빨간 막대 위", "기존 돌파 · 차트 빨간 막대 아래", "P2 차트 빨간 막대 돌파(단독)", "기존 돌파 · 1년 최대 매물대도 뚫음", "기존 돌파 · 이미 최대 매물대 위", "기존 돌파 · 최대 매물대 아래", "P1 1년 최대 매물대 돌파(단독)", "기존 돌파 · 큰 매물대도 뚫음", "기존 돌파 · 매물대 없음", "Z1 단순", "Z2 큰 매물대", "Z3 위가 비어 있음", "Z4 확인 2일", "Z5 전부"]
    out = {"made_at": datetime.now(KST).strftime("%Y-%m-%d %H:%M"), "universe": len(data), "seconds": round(time.time() - t0), "rows": []}
    for name in order:
        closed = [t for t in T[name] if t["exit"]]
        st = stats(closed)
        out["rows"].append({"variant": name, "all": st, "by_year": {y: stats([t for t in closed if t["date"][:4] == y]) for y in sorted({t["date"][:4] for t in closed})}})
        print(json.dumps({"variant": name, **{k: st.get(k) for k in ("n", "win_rate", "avg_r", "profit_factor", "total_r", "max_dd_r", "max_loss_streak", "reach_3r_pct")}}, ensure_ascii=False), flush=True)
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "zone.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
