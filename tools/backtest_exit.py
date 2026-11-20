#!/usr/bin/env python3
"""검증실 부록: 손절가를 언제 본전으로 올릴까 (2026-11-20 사용자 질문 — "1.5R·2R까지 올랐다가 손절하는 경우가 많아진다").

  지금 규칙(고정, 2027-01-31까지): 처음 손절 −1R → 3R에 닿으면 절반 익절 + 손절가 본전 → 그 뒤 20일선 종가 이탈 시 나머지.
  책 메모(docs/setups.md): "2R 또는 +18~19%에서 본전 손절로 상향"이 한 단계 더 있음.
  같은 3년 자료·같은 진입 신호로 '본전으로 올리는 시점'만 바꿔 비교한다. **비교 자료일 뿐, 매매 규칙을 바꾸지 않는다.**

  python3 tools/backtest_exit.py [--limit 200]      # → data/backtest/exit_compare.json

한계: backtest.py와 같음(생존 편향·수수료 미반영·일봉만). 일봉이라 같은 날 '2R 도달'과 '본전 이탈'의 순서는 모른다 →
      손절가는 도달한 다음 날부터 올린 것으로 계산(그날 안의 되돌림은 원래 손절가로 판정).
"""
import argparse, json, sys, tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import backtest as B  # noqa: E402
from common import ROOT  # noqa: E402

OUT = ROOT / "data" / "backtest" / "exit_compare.json"
VARIANTS = [
    ("지금 규칙 (3R 전에는 −1R 그대로)", None, 0.0),
    ("2R 닿으면 손절가 본전 (책)", 2.0, 0.0),
    ("1.5R 닿으면 손절가 본전", 1.5, 0.0),
    ("2R 닿으면 손절가 +1R (이익 잠금)", 2.0, 1.0),
    ("1R 닿으면 손절가 본전", 1.0, 0.0),
]


def make_sim(be_at, lock):
    def simulate(rows, i, R):
        entry = rows[i]["close"]; unit = entry * R["one_r"]
        stop = entry - unit; target = entry + R["take_r"] * unit
        c = [r["close"] for r in rows]
        took, moved, realized, left, peak = False, False, 0.0, 1.0, 0.0
        for j in range(i + 1, len(rows)):
            r = rows[j]
            if r["low"] <= stop:
                px = min(r["open"], stop)
                realized += left * (px - entry) / unit
                how = "본전 청산" if took else ("일찍 올린 손절가 청산" if moved else "손절")
                return {"r": round(realized, 2), "exit": r["date"], "days": j - i, "how": how, "took": took, "mfe": round(peak, 2)}
            peak = max(peak, (r["high"] - entry) / unit)
            if not took and r["high"] >= target:
                px = max(r["open"], target)
                realized += R["take_pct"] * (px - entry) / unit
                left -= R["take_pct"]; took, stop = True, max(stop, entry)
            if be_at and not moved and r["high"] >= entry + be_at * unit:
                moved = True; stop = max(stop, entry + lock * unit)   # 다음 날부터 적용
            if took and j >= R["trail_ma"]:
                ma = sum(c[j - R["trail_ma"] + 1:j + 1]) / R["trail_ma"]
                if c[j] < ma:
                    realized += left * (c[j] - entry) / unit
                    return {"r": round(realized, 2), "exit": r["date"], "days": j - i, "how": f"{R['trail_ma']}일선 이탈", "took": True, "mfe": round(peak, 2)}
        realized += left * (rows[-1]["close"] - entry) / unit
        return {"r": round(realized, 2), "exit": None, "days": len(rows) - 1 - i, "how": "보유 중(평가)", "took": took, "mfe": round(peak, 2)}
    return simulate


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--limit", type=int)
    a = ap.parse_args()
    keep_out, keep_sim = B.OUT, B.simulate
    rows = []
    try:
        B.OUT = Path(tempfile.mkdtemp())          # 웹 검증실 파일(latest.json)을 덮어쓰지 않게
        for name, be_at, lock in VARIANTS:
            B.simulate = make_sim(be_at, lock)
            o = B.run_backtest(a.limit)
            closed = [t for t in json.loads((B.OUT / "latest.json").read_text(encoding="utf-8")).get("recent", [])]
            s = o["all"]
            row = {"name": name, "be_at_r": be_at, "lock_r": lock, **{k: s.get(k) for k in
                   ("n", "win_rate", "avg_r", "total_r", "profit_factor", "avg_win", "avg_loss", "reach_3r_pct", "max_dd_r", "max_loss_streak", "avg_days")},
                   "by_exit": o.get("by_exit"), "by_market": {k: {x: v.get(x) for x in ("n", "avg_r", "win_rate")} for k, v in (o.get("by_market") or {}).items()},
                   "by_kind": {k: {x: v.get(x) for x in ("n", "avg_r", "win_rate")} for k, v in (o.get("by_kind") or {}).items()}}
            rows.append(row)
            period, universe = o.get("period"), o.get("universe")
            print(json.dumps({k: row[k] for k in ("name", "n", "win_rate", "avg_r", "total_r", "profit_factor", "reach_3r_pct", "max_dd_r")}, ensure_ascii=False), flush=True)
    finally:
        B.OUT, B.simulate = keep_out, keep_sim
    out = {"made_at": B.datetime.now(B.KST).strftime("%Y-%m-%d %H:%M"), "period": period, "universe": universe, "variants": rows,
           "note": "비교 자료 — 매매 규칙(3R에서 절반 익절 + 본전)은 2027-01-31까지 고정. 손절가는 조건에 닿은 다음 날부터 올린 것으로 계산.",
           "limits": ["지금 시총 2천억↑ 종목만(생존 편향)", "수수료·세금·슬리피지 미반영", "일봉만 사용(같은 날 순서 모름)", "같은 자료로 여러 안을 골라 보는 것이라 실제는 차이가 더 작을 수 있음"],
           "source": "네이버 일봉(수정주가, 비공식) · 계산 Claude"}
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
