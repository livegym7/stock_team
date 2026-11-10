"""매매 기록(일지). 산 것·판 것을 기록하면 config/positions.toml(보유 종목)을 자동으로 고치고, 거래마다 R·규칙 준수를 남긴다.
주문 기능이 아니다 — 이미 HTS에서 한 매매를 '기록'만 한다 (절대 규칙 1).

사용법 (Claude가 대화 "티에프이 39주 76,300에 샀어"를 받아 실행):
    python3 tools/trades.py buy  --name 티에프이 --qty 39 --price 76300 [--stop 70196] [--date 2026-11-03] [--setup A] [--note "돌파"]
    python3 tools/trades.py sell --name 티에프이 --qty 19 --price 101000 [--date ...] [--reason "3R 절반 익절"]
    python3 tools/trades.py stop --name 티에프이 --stop 76300            # 손절가 올림(본전 등)
    python3 tools/trades.py list                                            # 일지·성적 요약
기록: data/trades/trades.jsonl (한 줄 = 한 번의 매수/매도/손절가 변경)
"""
import argparse
import json
import re
from collections import defaultdict
from datetime import datetime

from common import DATA, ROOT, load_toml
from naver_quote import KST

LOG = DATA / "trades" / "trades.jsonl"
POS = ROOT / "config" / "positions.toml"


def rules():
    a = load_toml("account.toml")
    return {"stop_pct": a.get("stop_pct", 0.08), "be_r": a.get("breakeven_at_r", 3), "capital": a.get("capital"),
            "risk": a.get("risk_per_trade", 0.02)}


def code_of(name):
    from universe import load
    for s in load()["stocks"]:
        if s["name"] == name:
            return s["code"]
    raise SystemExit(f"종목 이름을 찾을 수 없습니다: {name}")


def read_log():
    if not LOG.exists():
        return []
    return [json.loads(l) for l in LOG.read_text(encoding="utf-8").splitlines() if l.strip()]


def append(ev):
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(json.dumps(ev, ensure_ascii=False) + "\n")


def write_positions(pos):
    head = [l for l in POS.read_text(encoding="utf-8").splitlines() if l.startswith("#")] if POS.exists() else []
    out = head + [""]
    for p in pos:
        out += ["[[positions]]", f'name = "{p["name"]}"', f'code = "{p["code"]}"', f"qty = {int(p['qty'])}",
                f"avg_price = {round(p['avg_price'])}", f"initial_stop = {round(p['initial_stop'])}   # 처음 손절가 = 1R 기준",
                f"stop = {round(p['stop'])}", ""]
    POS.write_text("\n".join(out), encoding="utf-8")


def load_pos():
    return [dict(p) for p in load_toml("positions.toml").get("positions", [])]


def buy(a):
    r = rules()
    code = a.code or code_of(a.name)
    pos = load_pos()
    p = next((x for x in pos if x["code"] == code), None)
    stop = a.stop or round(a.price * (1 - r["stop_pct"]))
    if p:   # 추가 매수: 평균가 다시 계산, 처음 손절가는 새 평균가 기준으로 (손절가가 더 높으면 유지)
        tot = p["qty"] + a.qty
        avg = (p["avg_price"] * p["qty"] + a.price * a.qty) / tot
        p.update(qty=tot, avg_price=round(avg), initial_stop=round(min(p["initial_stop"], avg * (1 - r["stop_pct"]))),
                 stop=max(p["stop"], round(min(p["initial_stop"], avg * (1 - r["stop_pct"])))))
    else:
        pos.append({"name": a.name, "code": code, "qty": a.qty, "avg_price": a.price, "initial_stop": stop, "stop": stop})
    write_positions(pos)
    ev = {"type": "buy", "date": a.date, "name": a.name, "code": code, "qty": a.qty, "price": a.price, "stop": stop,
          "setup": a.setup, "note": a.note, "at": datetime.now(KST).isoformat(timespec="seconds")}
    # 규칙 점검: 손절폭·위험 금액
    one_r = (a.price - stop) * a.qty
    ev["risk_won"] = round(one_r)
    ev["risk_pct_of_account"] = round(one_r / r["capital"] * 100, 2) if r["capital"] else None
    ev["checks"] = {"손절폭 8% 이내": (a.price - stop) / a.price <= r["stop_pct"] + 0.001,
                    "1R ≤ 계좌 2%": one_r <= r["capital"] * r["risk"] * 1.05 if r["capital"] else None}
    append(ev)
    return ev


def sell(a):
    code = a.code or code_of(a.name)
    pos = load_pos()
    p = next((x for x in pos if x["code"] == code), None)
    if not p:
        raise SystemExit(f"보유 종목에 {a.name}이 없습니다")
    if a.qty > p["qty"]:
        raise SystemExit(f"보유 {p['qty']}주보다 많이 팔 수 없습니다")
    risk_per_share = p["avg_price"] - p["initial_stop"]
    r_mult = round((a.price - p["avg_price"]) / risk_per_share, 2) if risk_per_share > 0 else None
    ev = {"type": "sell", "date": a.date, "name": p["name"], "code": code, "qty": a.qty, "price": a.price, "reason": a.reason,
          "avg_price": p["avg_price"], "initial_stop": p["initial_stop"], "stop_then": p["stop"], "r": r_mult,
          "pnl_won": round((a.price - p["avg_price"]) * a.qty), "at": datetime.now(KST).isoformat(timespec="seconds")}
    # 규칙 점검: 손절가 아래에서 늦게 판 것인지(−1R보다 더 잃음), 3R 전에 판 이유
    ev["checks"] = {"손절가 지킴(−1.1R보다 덜 잃음)": r_mult is None or r_mult >= -1.1}
    p["qty"] -= a.qty
    pos = [x for x in pos if x["qty"] > 0]
    write_positions(pos)
    append(ev)
    return ev


def move_stop(a):
    code = a.code or code_of(a.name)
    pos = load_pos()
    p = next((x for x in pos if x["code"] == code), None)
    if not p:
        raise SystemExit("보유 종목이 아닙니다")
    old = p["stop"]; p["stop"] = a.stop
    write_positions(pos)
    ev = {"type": "stop", "date": a.date, "name": p["name"], "code": code, "from": old, "to": a.stop, "note": a.note,
          "at": datetime.now(KST).isoformat(timespec="seconds")}
    append(ev)
    return ev


def summary():
    """거래 단위(종목별 매수~전량 매도)로 묶어 R·손익·규칙 준수를 계산."""
    log = read_log()
    open_, done = defaultdict(lambda: {"buys": [], "sells": [], "stops": []}), []
    for ev in log:
        t = open_[ev["code"]]
        t["name"] = ev["name"]
        {"buy": t["buys"], "sell": t["sells"], "stop": t["stops"]}[ev["type"]].append(ev)
        held = sum(b["qty"] for b in t["buys"]) - sum(s["qty"] for s in t["sells"])
        if ev["type"] == "sell" and held == 0:
            done.append(dict(t, code=ev["code"])); open_.pop(ev["code"])
    trades = []
    for t in done:
        cost = sum(b["qty"] * b["price"] for b in t["buys"]); qty = sum(b["qty"] for b in t["buys"])
        risk = sum((b["price"] - b["stop"]) * b["qty"] for b in t["buys"])
        pnl = sum(s["pnl_won"] for s in t["sells"])
        trades.append({"name": t["name"], "code": t["code"], "open": t["buys"][0]["date"], "close": t["sells"][-1]["date"],
                       "qty": qty, "avg": round(cost / qty), "pnl_won": pnl, "r": round(pnl / risk, 2) if risk > 0 else None,
                       "setup": t["buys"][0].get("setup"), "exits": [f"{s['qty']}주 {s['price']:,} ({s.get('reason') or '-'})" for s in t["sells"]],
                       "rule_ok": all(all(v is not False for v in e.get("checks", {}).values()) for e in t["buys"] + t["sells"])})
    rs = [x["r"] for x in trades if x["r"] is not None]
    stats = {"n": len(trades), "win": sum(1 for r in rs if r > 0), "avg_r": round(sum(rs) / len(rs), 2) if rs else None,
             "sum_r": round(sum(rs), 2) if rs else 0, "pnl_won": sum(x["pnl_won"] for x in trades),
             "rule_ok": sum(1 for x in trades if x["rule_ok"])}
    return {"stats": stats, "closed": sorted(trades, key=lambda x: x["close"], reverse=True),
            "open": [{"name": t["name"], "code": c, "events": t["buys"] + t["sells"] + t["stops"]} for c, t in open_.items()],
            "log": log[-50:][::-1]}


def _kospi_regime_by_date():
    """날짜 → 코스피 20일선 위/아래 (그날 신호등 대용). 네이버 일봉(비공식)."""
    try:
        import sector_etf
        rows = sector_etf.daily("KOSPI", "코스피", 400)["rows"]
    except Exception:
        return {}
    out, closes = {}, []
    for r in rows:
        closes.append(r["close"])
        if len(closes) >= 20:
            ma = sum(closes[-20:]) / 20
            out[f"{r['date'][:4]}-{r['date'][4:6]}-{r['date'][6:]}"] = "green" if r["close"] > ma else "red"
    return out


def review():
    """매매 복기 (토큰 0): 연속 손절 묶음, 같은 날 몰아 매수, 규칙 준수율, 신호등(진입일 코스피 20일선)별 R, 배울 점 자동 문장.
    숫자는 data/trades/trades.jsonl 기준. 판단은 사용자가 한다."""
    s = summary()
    closed = sorted(s["closed"], key=lambda x: (x["close"], x["open"]))
    regime = _kospi_regime_by_date()
    for t in closed:
        t["regime_at_entry"] = regime.get(t["open"])
        t["hold_days"] = (datetime.fromisoformat(t["close"]) - datetime.fromisoformat(t["open"])).days
    rs = [t["r"] for t in closed if t["r"] is not None]
    # 연속 손실 (마감일 순)
    streaks, cur = [], []
    for t in closed:
        if t["r"] is not None and t["r"] < 0:
            cur.append(t)
        else:
            if len(cur) >= 2:
                streaks.append(cur)
            cur = []
    if len(cur) >= 2:
        streaks.append(cur)
    cur_streak = len(cur)
    clusters = defaultdict(list)   # 같은 날 매수
    for t in closed:
        clusters[t["open"]].append(t)
    same_day = [{"date": d, "names": [t["name"] for t in ts], "sum_r": round(sum(t["r"] or 0 for t in ts), 2)} for d, ts in clusters.items() if len(ts) >= 2]
    by_regime = {}
    for k in ("green", "red", None):
        xs = [t["r"] for t in closed if t.get("regime_at_entry") == k and t["r"] is not None]
        if xs:
            by_regime[k or "unknown"] = {"n": len(xs), "avg_r": round(sum(xs) / len(xs), 2), "win": sum(1 for r in xs if r > 0)}
    worse = [t for t in closed if t["r"] is not None and t["r"] < -1.1]   # 손절가보다 더 잃음(갭·지연)
    lessons = []
    if streaks:
        L = max(streaks, key=len)
        lessons.append(f"연속 손절 {len(L)}건 ({L[0]['close']}~{L[-1]['close']}, 합계 {round(sum(t['r'] for t in L), 2)}R). 연속 손실 뒤에는 포지션 수를 줄이는지 점검.")
    for c in same_day:
        lessons.append(f"{c['date']} 같은 날 {len(c['names'])}종목 매수({', '.join(c['names'])}) → 합계 {c['sum_r']}R. 같은 날 몰아 사면 시장 하락 하루에 CR이 한 번에 현실이 됨.")
    if worse:
        lessons.append(f"손절가보다 더 잃은 거래 {len(worse)}건 ({', '.join(t['name'] + ' ' + str(t['r']) + 'R' for t in worse)}). 갭하락·늦은 체결 — 실적·이벤트 전 보유 여부와 장 시작 직후 대응을 점검.")
    if by_regime.get("red") and by_regime["red"]["n"] >= 2:
        lessons.append(f"코스피 20일선 아래(🔴)에서 진입한 {by_regime['red']['n']}건 평균 {by_regime['red']['avg_r']}R. 국면이 나쁠 때 결과가 나쁜지 계속 세어 본다(규칙 재검토 2027-01 재료).")
    exp = round(sum(rs) / len(rs), 2) if rs else None
    return {"at": datetime.now(KST).strftime("%Y-%m-%d %H:%M"), "n": len(closed), "win_rate": round(sum(1 for r in rs if r > 0) / len(rs) * 100) if rs else None,
            "expectancy_r": exp, "sum_r": round(sum(rs), 2) if rs else 0, "pnl_won": sum(t["pnl_won"] for t in closed),
            "max_loss_streak": max((len(x) for x in streaks), default=cur_streak), "current_loss_streak": cur_streak,
            "rule_ok_pct": round(sum(1 for t in closed if t["rule_ok"]) / len(closed) * 100) if closed else None,
            "worse_than_stop": len(worse), "same_day_clusters": same_day, "by_regime": by_regime,
            "avg_hold_days": round(sum(t["hold_days"] for t in closed) / len(closed), 1) if closed else None,
            "trades": closed[::-1][:20], "lessons": lessons,
            "source": "data/trades/trades.jsonl · 신호등 = 진입일 코스피 종가 vs 20일선(네이버 일봉, 비공식) · 숫자만, 판단은 사용자"}


def main():
    p = argparse.ArgumentParser(description="매매 기록 (주문 기능 아님)")
    sub = p.add_subparsers(dest="cmd", required=True)
    today = datetime.now(KST).strftime("%Y-%m-%d")
    for c in ("buy", "sell"):
        s = sub.add_parser(c); s.add_argument("--name", required=True); s.add_argument("--code")
        s.add_argument("--qty", type=int, required=True); s.add_argument("--price", type=float, required=True)
        s.add_argument("--date", default=today)
        if c == "buy":
            s.add_argument("--stop", type=float); s.add_argument("--setup"); s.add_argument("--note")
        else:
            s.add_argument("--reason")
    s = sub.add_parser("stop"); s.add_argument("--name", required=True); s.add_argument("--code"); s.add_argument("--stop", type=float, required=True)
    s.add_argument("--date", default=today); s.add_argument("--note")
    sub.add_parser("list")
    sub.add_parser("review", help="매매 복기 요약 (연속 손절·같은 날 매수·규칙 준수·신호등별 R)")
    sub.add_parser("seed", help="지금 보유 종목을 일지의 시작 기록으로 (한 번만)")
    a = p.parse_args()
    for k in ("price", "stop"):   # 120000.0 → 120000
        v = getattr(a, k, None)
        if isinstance(v, float) and v == int(v):
            setattr(a, k, int(v))
    if a.cmd == "buy":
        print(json.dumps(buy(a), ensure_ascii=False, indent=1))
    elif a.cmd == "sell":
        print(json.dumps(sell(a), ensure_ascii=False, indent=1))
    elif a.cmd == "stop":
        print(json.dumps(move_stop(a), ensure_ascii=False, indent=1))
    elif a.cmd == "review":
        print(json.dumps(review(), ensure_ascii=False, indent=1)); return
    elif a.cmd == "seed":
        if read_log():
            raise SystemExit("이미 기록이 있습니다")
        for x in load_pos():
            append({"type": "buy", "date": "2026-11-02", "name": x["name"], "code": x["code"], "qty": x["qty"], "price": x["avg_price"],
                    "stop": x["initial_stop"], "setup": None, "note": "일지 시작 시점 보유분(매수일 확인 필요)", "seed": True,
                    "at": datetime.now(KST).isoformat(timespec="seconds"), "checks": {}})
        print(json.dumps(summary(), ensure_ascii=False, indent=1))
    else:
        print(json.dumps(summary(), ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
