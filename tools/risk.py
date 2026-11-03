"""보유 종목 리스크 지표: R · CR · E (주문 기능 없음 — 계산과 알림만).

- R  : 1회 위험 단위. 종목별 1R = (평균가 - 처음 손절가) × 수량. 계좌 기준 1R = 자본 × risk_per_trade
- 진행 R: (현재가 - 평균가) ÷ (평균가 - 처음 손절가)  → 3R이면 3
- CR : 지금 손절가 기준 위험 합계 = Σ max(0, 평균가 - 지금 손절가) × 수량  (매수가 기준, 사용자 결정 2026-11-03)
       손절가를 본전(평균가) 이상으로 올리면 그 종목 CR = 0
- E  : 노출도 = 평가금액 합계 ÷ 자본

규칙 (config/account.toml): breakeven_at_r = 3 → 3R에 닿으면 손절가를 본전으로 올리라고 알림.

사용법:
    python3 tools/risk.py                 # 현재가(네이버)로 계산, JSON
    python3 tools/risk.py --size 50000 46000   # 신규 매수 수량 계산: 매수 예정가 50,000, 손절가 46,000
"""
import argparse
import json
from datetime import datetime

from common import load_toml, positions
from naver_quote import KST
from report_digest import live_prices


def rules():
    a = load_toml("account.toml")
    return {"capital": a["capital"], "risk_per_trade": a["risk_per_trade"], "stop_pct": a["stop_pct"],
            "breakeven_at_r": a.get("breakeven_at_r", 3), "max_open_risk": a.get("max_open_risk", 0.06)}


def evaluate(pos=None, prices=None):
    r = rules()
    pos = positions() if pos is None else pos
    prices = live_prices([p["code"] for p in pos]) if prices is None else prices
    one_r_acct = r["capital"] * r["risk_per_trade"]
    rows, total_value, total_cr = [], 0, 0
    for p in pos:
        avg, qty = p["avg_price"], p["qty"]
        init_stop = p.get("initial_stop") or p.get("stop") or round(avg * (1 - r["stop_pct"]))
        stop = p.get("stop") or init_stop
        unit = avg - init_stop                      # 주당 1R
        cur = prices.get(p["code"], {}).get("price")
        value = cur * qty if cur else avg * qty
        cr = max(0, avg - stop) * qty
        r_mult = round((cur - avg) / unit, 2) if cur and unit > 0 else None
        target = avg + r["breakeven_at_r"] * unit   # 3R 가격
        row = {"name": p["name"], "code": p["code"], "qty": qty, "avg_price": avg, "price": cur,
               "price_at": prices.get(p["code"], {}).get("at"), "initial_stop": init_stop, "stop": stop,
               "one_r_won": round(unit * qty), "one_r_vs_account": round(unit * qty / one_r_acct, 2),
               "r_multiple": r_mult, "pnl_won": round((cur - avg) * qty) if cur else None,
               "breakeven_price_at_3r": round(target), "to_3r_pct": round((target / cur - 1) * 100, 1) if cur else None,
               "to_stop_pct": round((stop / cur - 1) * 100, 1) if cur else None,
               "cr_won": round(cr), "value_won": round(value)}
        if r_mult is not None and r_mult >= r["breakeven_at_r"] and stop < avg:
            row["alert"] = f"{r['breakeven_at_r']}R 도달 → 손절가를 본전 {avg:,}원으로 올릴 때 (지금 {stop:,}원)"
        elif stop >= avg:
            row["note"] = "손절가 본전 이상 → 이 종목 CR 0"
        rows.append(row)
        total_value += value
        total_cr += cr
    out = {
        "at": datetime.now(KST).strftime("%Y-%m-%d %H:%M"), "source": "현재가 네이버(표시값), 계산 Claude",
        "capital": r["capital"], "one_r_account_won": round(one_r_acct),
        "E_pct": round(total_value / r["capital"] * 100, 1), "invested_won": round(total_value),
        "CR_won": round(total_cr), "CR_pct": round(total_cr / r["capital"] * 100, 2),
        "CR_in_R": round(total_cr / one_r_acct, 2),
        "CR_limit_pct": round(r["max_open_risk"] * 100, 1),
        "room_for_new_risk_won": round(max(0, r["capital"] * r["max_open_risk"] - total_cr)),
        "positions": rows,
    }
    if total_cr > r["capital"] * r["max_open_risk"]:
        out["warning"] = f"CR {out['CR_pct']}%가 한도 {out['CR_limit_pct']}%를 넘음"
    return out


def size(entry, stop):
    """신규 매수 가능 수량: 1회 위험 2%와 남은 CR 여유 중 작은 쪽."""
    r = rules()
    ev = evaluate()
    per_share = entry - stop
    if per_share <= 0:
        raise SystemExit("손절가는 매수가보다 낮아야 합니다")
    budget = min(r["capital"] * r["risk_per_trade"], ev["room_for_new_risk_won"])
    qty = int(budget // per_share)
    return {"entry": entry, "stop": stop, "stop_pct": round((stop / entry - 1) * 100, 1),
            "risk_budget_won": round(budget), "qty": qty, "cost_won": qty * entry,
            "cost_vs_capital_pct": round(qty * entry / r["capital"] * 100, 1),
            "price_at_3r": round(entry + 3 * per_share), "note": "주문 기능 없음 — 수량 계산만"}


def main():
    p = argparse.ArgumentParser(description="R·CR·E 리스크 지표")
    p.add_argument("--size", nargs=2, type=float, metavar=("매수가", "손절가"))
    a = p.parse_args()
    print(json.dumps(size(*a.size) if a.size else evaluate(), ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
