"""보유 종목 리스크 지표: R · CR · E (주문 기능 없음 — 계산과 알림만).

- R  : 1회 위험 단위. 종목별 1R = (평균가 - 처음 손절가) × 수량. 계좌 기준 1R = 자본 × risk_per_trade
- 진행 R: (현재가 - 평균가) ÷ (평균가 - 처음 손절가)  → 3R이면 3
- CR : 지금 손절가 기준 위험 합계 = Σ max(0, 평균가 - 지금 손절가) × 수량  (매수가 기준, 사용자 결정 2026-11-03)
       손절가를 본전(평균가) 이상으로 올리면 그 종목 CR = 0
- E  : 노출도 = 평가금액 합계 ÷ 자본

규칙 (config/account.toml, 사용자 확정 2026-11-03):
- 처음 손절 −8% = 1R
- 3R 도달 → 50% 익절(take_profit_at_3r) + 남은 물량 손절가를 본전으로 (CR 0)
- 3R 이후 → 20일선(trail_ma) 종가 하향 돌파 시 나머지 전략 매도

사용법:
    python3 tools/risk.py                 # 현재가(네이버)로 계산, JSON
    python3 tools/risk.py --size 50000 46000   # 신규 매수 수량 계산: 매수 예정가 50,000, 손절가 46,000
    python3 tools/risk.py --card [--send]      # 포트폴리오 표 그림(reports/오늘/portfolio.png), --send 텔레그램
"""
import argparse
import json
from datetime import datetime

from common import load_toml, positions
from naver_quote import KST
from report_digest import live_prices


def rules():
    a = load_toml("account.toml")
    from common import account_state
    st = account_state()   # 2026-11-18: 계좌 = 시작 1,500만 + 이후 실현 손익 − 비용 (고정 금액 아님)
    return {"capital": st["capital"], "account": st, "risk_per_trade": a["risk_per_trade"], "stop_pct": a["stop_pct"],
            "breakeven_at_r": a.get("breakeven_at_r", 3), "max_open_risk": a.get("max_open_risk", 0.06),
            "take_profit_at_3r": a.get("take_profit_at_3r"), "trail_ma": a.get("trail_ma", 20)}


def ma(code, n):
    """n일 이동평균 (네이버 일봉, 마지막 봉은 장중이면 현재가). 실패하면 None."""
    try:
        import screener
        c = [x["close"] for x in screener.fetch_daily(code)][-n:]
        return round(sum(c) / n) if len(c) == n else None
    except Exception:
        return None


def evaluate(pos=None, prices=None):
    r = rules()
    pos = positions() if pos is None else pos
    pos = [p for p in pos if p.get("book") != "addon"]   # 부록 · 지수 되돌림은 부록 계좌로 따로 (2026-11-18 사용자 요청: 섞이지 않게)
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
        addon = p.get("book") == "addon"   # 부록 · 지수 되돌림 (2026-11-18): 손절가·CR·R 계산 안 함, 다음 날 종가 매도
        cr = 0 if addon else max(0, avg - stop) * qty
        r_mult = None if addon else (round((cur - avg) / unit, 2) if cur and unit > 0 else None)
        target = avg + r["breakeven_at_r"] * unit   # 3R 가격
        row = {"name": p["name"], "code": p["code"], "qty": qty, "avg_price": avg, "price": cur,
               "price_at": prices.get(p["code"], {}).get("at"), "initial_stop": init_stop, "stop": stop,
               "one_r_won": round(unit * qty), "one_r_vs_account": round(unit * qty / one_r_acct, 2),
               "r_multiple": r_mult, "pnl_won": round((cur - avg) * qty) if cur else None,
               "breakeven_price_at_3r": round(target), "to_3r_pct": round((target / cur - 1) * 100, 1) if cur else None,
               "to_stop_pct": round((stop / cur - 1) * 100, 1) if cur else None,
               "cr_won": round(cr), "value_won": round(value)}
        tp = r["take_profit_at_3r"]
        row["take_qty_at_3r"] = int(qty * tp) if tp else None
        row["take_won_at_3r"] = round(int(qty * tp) * (target - avg)) if tp else None
        row["phase"] = "3R 이후 (추세 추종)" if stop >= avg else "초기 (1R 위험)"
        m = ma(p["code"], r["trail_ma"])
        row[f"ma{r['trail_ma']}"] = m
        row["trail_ma"] = r["trail_ma"]
        row["to_ma_pct"] = round((m / cur - 1) * 100, 1) if m and cur else None
        if r_mult is not None and r_mult >= r["breakeven_at_r"] and stop < avg:
            take = f"{row['take_qty_at_3r']}주({int(tp * 100)}%) 익절 + " if tp else ""
            row["alert"] = f"{r['breakeven_at_r']}R 도달 → {take}남은 물량 손절가를 본전 {avg:,}원으로 (지금 {stop:,}원)"
        elif stop >= avg:
            row["note"] = "손절가 본전 이상 → 이 종목 CR 0"
            if m and cur and cur < m:
                row["alert"] = f"{r['trail_ma']}일선({m:,}원) 아래 → 종가로도 이탈하면 나머지 전략 매도"
        if addon:
            row.update(book="addon", bought=p.get("bought"), phase="🧩 부록 · 다음 날 종가 매도", alert=None, cr_won=0, one_r_won=0, one_r_vs_account=0,
                       ret_pct=round((cur / avg - 1) * 100, 2) if cur else None)
            row.pop("note", None)
        rows.append(row)
        total_value += value
        total_cr += cr
    out = {
        "at": datetime.now(KST).strftime("%Y-%m-%d %H:%M"), "source": "현재가 네이버(표시값), 계산 Claude",
        "capital": r["capital"], "one_r_account_won": round(one_r_acct),
        "start_capital": r["account"]["start_capital"], "realized_won": r["account"]["realized_won"], "fees_won": r["account"]["fees_won"],
        "capital_since": r["account"]["since"][:10],
        "total_asset_won": round(r["capital"] + sum((x["pnl_won"] or 0) for x in rows)),   # 총자산 = 계좌(실현 반영) + 평가 손익
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


def card(ev):
    """포트폴리오 표를 HTML → PNG로."""
    from common import ROOT
    from render import html_to_png
    def w(n): return f"{n:,.0f}" if n is not None else "-"
    def cls(n): return "up" if n and n > 0 else "down" if n and n < 0 else ""
    rows = ""
    for p in ev["positions"]:
        pct = (p["price"] / p["avg_price"] - 1) * 100 if p["price"] else None
        bar = max(0, min(100, ((p["r_multiple"] or 0) + 1) / 4 * 100))  # -1R ~ 3R
        rows += (f"<tr><td class=l><b>{p['name']}</b><br><small>{p['code']}</small></td>"
                 f"<td>{p['qty']}</td><td>{w(p['avg_price'])}</td><td><b>{w(p['price'])}</b></td>"
                 f"<td class={cls(pct)}>{w(p['pnl_won'])}<br><small>{pct:+.1f}%</small></td>"
                 f"<td>{w(p['value_won'])}<br><small>{p['value_won']/ev['capital']*100:.1f}%</small></td>"
                 f"<td>{w(p['stop'])}<br><small>{p['to_stop_pct']:+.1f}%</small></td>"
                 f"<td>{w(p['one_r_won'])}<br><small>{p['one_r_vs_account']}R</small></td>"
                 f"<td class={cls(p['r_multiple'])}><b>{p['r_multiple']:+.2f}R</b>"
                 f"<div class=bar><i style='width:{bar:.0f}%'></i></div></td>"
                 f"<td>{w(p['breakeven_price_at_3r'])}<br><small>{p['to_3r_pct']:+.1f}%</small></td>"
                 f"<td>{w(p['cr_won'])}</td></tr>")
    cr_use = ev["CR_pct"] / ev["CR_limit_pct"] * 100
    alerts = "".join(f"<div class=alert>⚠️ {p['name']}: {p['alert']}</div>" for p in ev["positions"] if p.get("alert"))
    if ev.get("warning"):
        alerts += f"<div class=alert>⚠️ {ev['warning']}</div>"
    html = f"""<!doctype html><meta charset=utf-8><style>
body{{font-family:'Noto Sans CJK KR','WenQuanYi Zen Hei',sans-serif;margin:0;padding:18px;background:#fff;color:#1d2433;width:980px}}
h1{{font-size:20px;margin:0 0 4px}} .sub{{color:#6b7280;font-size:12px;margin-bottom:12px}}
.kpi{{display:flex;gap:10px;margin-bottom:12px}} .k{{flex:1;border:1px solid #e5e7eb;border-radius:8px;padding:8px 10px}}
.k span{{font-size:11px;color:#6b7280}} .k b{{display:block;font-size:19px;margin-top:2px}} .k small{{color:#6b7280}}
.gauge{{height:6px;background:#eef0f3;border-radius:3px;margin-top:5px}} .gauge i{{display:block;height:100%;border-radius:3px;background:#2563eb}}
table{{border-collapse:collapse;width:100%;font-size:13px}} th{{background:#f3f4f6;font-size:11px;color:#4b5563;padding:6px 4px;border-bottom:1px solid #d1d5db}}
td{{text-align:right;padding:7px 5px;border-bottom:1px solid #eef0f3;vertical-align:top}} td.l{{text-align:left}} small{{color:#6b7280;font-size:11px}}
.up{{color:#d92d20}} .down{{color:#1d4ed8}} .bar{{height:4px;background:#eef0f3;margin-top:4px}} .bar i{{display:block;height:100%;background:#16a34a}}
.alert{{background:#fff4e5;border:1px solid #f5c26b;padding:6px 10px;border-radius:6px;margin-bottom:8px;font-size:13px}}
.foot{{font-size:11px;color:#6b7280;margin-top:10px;line-height:1.6}}</style>
<h1>💼 포트폴리오 리스크 현황</h1><div class=sub>{ev['at']} 기준 · 현재가 네이버(표시값) · 자본 {w(ev['capital'])}원 · 1R = {w(ev['one_r_account_won'])}원(2%)</div>
{alerts}<div class=kpi>
<div class=k><span>E 노출도</span><b>{ev['E_pct']}%</b><small>투자 {w(ev['invested_won'])} / 현금 {w(ev['capital']-ev['invested_won'])}</small></div>
<div class=k><span>CR 현재 위험 (매수가 기준)</span><b>{w(ev['CR_won'])}원</b><small>{ev['CR_pct']}% · {ev['CR_in_R']}R / 한도 {ev['CR_limit_pct']}%</small><div class=gauge><i style='width:{min(100,cr_use):.0f}%'></i></div></div>
<div class=k><span>새로 걸 수 있는 위험</span><b>{w(ev['room_for_new_risk_won'])}원</b><small>약 {ev['room_for_new_risk_won']/ev['one_r_account_won']:.1f}R</small></div>
<div class=k><span>평가손익 합계</span><b class={cls(sum(p['pnl_won'] or 0 for p in ev['positions']))}>{w(sum(p['pnl_won'] or 0 for p in ev['positions']))}원</b><small>보유 {len(ev['positions'])}종목</small></div></div>
<table><tr><th>종목</th><th>수량</th><th>평균가</th><th>현재가</th><th>평가손익</th><th>평가금액<br>(비중)</th><th>손절가<br>(거리)</th><th>1R 금액</th><th>진행 R<br>(−1R~3R)</th><th>3R 가격<br>(본전 올림)</th><th>CR</th></tr>{rows}</table>
<div class=foot>규칙: 처음 손절 −8% = 1R · 3R 도달 시 손절가를 본전으로 올림 → 그 종목 CR 0 · CR 한도 6%(동시 손절 최대 90만 원)<br>주문 기능 없음 — 계산과 알림만. 판단은 본인이 합니다.</div>"""
    day = ev["at"][:10]
    out = ROOT / "reports" / day
    out.mkdir(parents=True, exist_ok=True)
    (out / "portfolio.html").write_text(html, encoding="utf-8")
    png = out / "portfolio.png"
    ok = html_to_png(out / "portfolio.html", png, 1016, 330 + 62 * len(ev["positions"]) + 40 * bool(alerts))
    return png if ok else None


def main():
    p = argparse.ArgumentParser(description="R·CR·E 리스크 지표")
    p.add_argument("--size", nargs=2, type=float, metavar=("매수가", "손절가"))
    p.add_argument("--card", action="store_true", help="포트폴리오 표 그림 만들기")
    p.add_argument("--send", action="store_true", help="--card 그림을 텔레그램으로")
    a = p.parse_args()
    if a.size:
        print(json.dumps(size(*a.size), ensure_ascii=False, indent=1))
        return
    ev = evaluate()
    if a.card:
        png = card(ev)
        ev["card"] = str(png) if png else "그림 만들기 실패 (크롬 없음)"
        if png and a.send:
            from telegram_send import send_photo
            send_photo(png, f"💼 포트폴리오 리스크 현황 {ev['at']} · E {ev['E_pct']}% · CR {ev['CR_pct']}% ({ev['CR_in_R']}R / 한도 6%)")
            ev["sent"] = True
    print(json.dumps(ev, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
