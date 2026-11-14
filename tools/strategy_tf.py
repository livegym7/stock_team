#!/usr/bin/env python3
"""테크노펀더멘탈 · 탑다운 주간 보고서 (2026-11-14 사용자 확정 형식).

흐름: 매크로 → 시황·국면 → 수급 → 업종(이익 × 추세) → 종목(펀더 필터 → 기술 트리거) → 보유·성적
숫자·그림·점수는 이 도구가 만든다(토큰 0). 해석 글(narrative)은 /strategy-report 가 data/strategy/tf/narr_날짜.json 에
쓰고, 없으면 숫자로 만든 기본 문장을 쓴다.

  python3 tools/strategy_tf.py prep              # 숫자 모으기 → data/strategy/tf/prep_날짜.json (+ 해석 칸 기본값 출력)
  python3 tools/strategy_tf.py narr-template     # 해석 JSON 기본값(자동 문장) 출력 → Claude가 고쳐서 narr_날짜.json 으로 저장
  python3 tools/strategy_tf.py tg                # 토요일 텔레그램 요약 → reports/날짜/strategy_tg.md
  python3 tools/strategy_tf.py render            # prep + narr → reports/날짜/strategy_tf.html + data/strategy/tf/latest.json(웹 조각)

펀더 점수(3): 최근 분기 영업이익 YoY +20%↑/흑자전환 · 영업이익률 1년 전보다 높음 · 올해 영업이익 +20%↑(E, 없으면 최근 2분기 합)
기술 점수(3): RS 80↑ · 기준가 10% 안 + 빠진 조건 없음 · 업종 동행(인더스트리 액션)
펀더 점수는 순서를 정하는 참고다. 매매 규칙(docs/rules.md)은 2027-01-31까지 고정. 주문 기능 없음.
"""
import argparse, glob, html, json, subprocess, sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import CACHE, DATA, ROOT  # noqa: E402
from strategy_prep import KST  # noqa: E402

TF = DATA / "strategy" / "tf"
E = html.escape
MACRO = [("^GSPC", "S&P 500"), ("^SOX", "필라델피아 반도체"), ("^TNX", "미 10년물 금리"), ("KRW=X", "원/달러"), ("CL=F", "WTI 원유"), ("^VIX", "VIX"), ("EWY", "EWY(한국 ETF)")]
XQ, YQ = 20, 65   # 업종 분류 문턱: 올해 영업이익 +20% · 강도 65


def _j(p, d=None):
    try:
        return json.loads(Path(p).read_text(encoding="utf-8"))
    except Exception:
        return d


# ---------------------------------------------------------------- 숫자 모으기
def _daily():
    out = {}
    for f in (CACHE / "daily").glob("*.json"):
        try:
            rows = json.loads(f.read_text())["rows"]
        except Exception:
            continue
        if len(rows) >= 60:
            out[f.stem] = rows
    return out


def _fund():
    out = {}
    for f in (CACHE / "fund").glob("[0-9A-Z]*.json"):
        d = _j(f)
        if d:
            out[d["code"]] = d
    return out


def macro():
    out = []
    for sym, nm in MACRO:
        try:
            j = json.loads(subprocess.run([sys.executable, str(ROOT / "tools" / "us_quote.py"), "daily", "--symbol", sym, "--days", "30"],
                                          capture_output=True, text=True, timeout=60).stdout)
            rows = [r for r in j["results"][0]["rows"] if r.get("close") is not None]
            c = [r["close"] for r in rows]
            out.append({"sym": sym, "name": nm, "now": c[-1], "w1": c[-6] if len(c) > 5 else None, "m1": c[0], "date": rows[-1]["date"]})
        except Exception as e:
            out.append({"sym": sym, "name": nm, "err": str(e)[:80]})
    return out


def regime_block(daily):
    k = daily["KOSPI"]
    dd = [{"date": b["date"], "chg": round((b["close"] / a["close"] - 1) * 100, 2)}
          for a, b in zip(k[-26:-1], k[-25:]) if b["close"] < a["close"] * 0.998 and b["volume"] > a["volume"]]
    cl = [r["close"] for r in k]
    m20 = sum(cl[-20:]) / 20
    return {"kospi": [[r["date"], r["close"]] for r in k[-120:]], "dist_days": dd, "close": cl[-1], "gap20": round((cl[-1] / m20 - 1) * 100, 1),
            "slope20": round((m20 / (sum(cl[-25:-5]) / 20) - 1) * 100, 1), "date": k[-1]["date"]}


def breadth(daily, uni):
    codes = [c for c in uni if c in daily]
    idx = {c: {r["date"]: i for i, r in enumerate(daily[c])} for c in codes}
    out = []
    for d in [r["date"] for r in daily["KOSPI"][-60:]]:
        n = a50 = a20 = nh = nl = 0
        for c in codes:
            rows = daily[c]; i = idx[c].get(d)
            if i is None or i < 60:
                continue
            seg = rows[max(0, i - 249):i + 1]; cl = [r["close"] for r in seg]; x = cl[-1]; n += 1
            a50 += x > sum(cl[-50:]) / 50; a20 += x > sum(cl[-20:]) / 20
            nh += rows[i]["high"] >= max(r["high"] for r in seg); nl += rows[i]["low"] <= min(r["low"] for r in seg)
        if n:
            out.append({"date": d, "n": n, "a50": round(a50 / n * 100, 1), "a20": round(a20 / n * 100, 1), "nh": nh, "nl": nl})
    return out


def _fa_la(d):
    A = (d or {}).get("annual") or []
    return next((a for a in A if a["e"]), None), next((a for a in reversed(A) if not a["e"]), None)


def fscore(d, px):
    if not d:
        return None
    Q = [q for q in d.get("quarter") or [] if not q["e"] and q.get("op") is not None]
    fa, la = _fa_la(d)
    pts, why, yoy, opg = 0, [], None, None
    if Q:
        lq = Q[-1]; yq = next((q for q in Q if q["p"] == str(int(lq["p"][:4]) - 1) + lq["p"][4:]), None)
        if yq is not None:
            if yq["op"] <= 0 < lq["op"]:
                yoy = "흑전"; pts += 1; why.append("최근 분기 흑자전환")
            elif yq["op"] > 0:
                yoy = round((lq["op"] / yq["op"] - 1) * 100)
                if yoy >= 20:
                    pts += 1; why.append(f"최근 분기 영업이익 {yoy:+d}%")
            if lq.get("opm") is not None and yq.get("opm") is not None and lq["opm"] > yq["opm"]:
                pts += 1; why.append(f"영업이익률 {yq['opm']:.1f}→{lq['opm']:.1f}%")
    if fa and la and fa.get("op") is not None and la.get("op") is not None:
        if la["op"] <= 0 < fa["op"]:
            opg = "흑전"; pts += 1; why.append("올해 흑자전환(E)")
        elif la["op"] > 0:
            opg = round((fa["op"] / la["op"] - 1) * 100)
            if opg >= 20:
                pts += 1; why.append(f"올해 영업이익 {opg:+d}%(E)")
    elif len(Q) >= 6:
        a = sum(q["op"] for q in Q[-2:]); b = sum(q["op"] for q in Q[-6:-4])
        if b > 0 and a / b - 1 >= .2:
            pts += 1; why.append("최근 2분기 합 +20%↑(컨센서스 없음)")
    per = px / fa["eps"] if fa and fa.get("eps") and fa["eps"] > 0 and px else None
    return {"pts": pts, "why": why, "yoy": yoy, "opg": opg, "per": round(per, 1) if per else None,
            "q": [[q["p"], q["sales"], q["op"], q["opm"]] for q in Q[-6:]], "consensus": bool(fa and fa.get("op") is not None)}


def prep():
    import new_highs
    now = datetime.now(KST)
    daily, fund, uni = _daily(), _fund(), new_highs.universe_info()
    px = {c: r[-1]["close"] for c, r in daily.items()}
    P = {"made_at": now.strftime("%Y-%m-%d %H:%M"), "date": now.strftime("%Y-%m-%d")}
    P["macro"] = macro()
    P["regime"] = regime_block(daily)
    P["breadth"] = breadth(daily, uni)
    pulse = _j(DATA / "market" / "pulse_latest.json", {}) or {}
    P["market"] = next((m for m in pulse.get("markets", []) if m.get("market") == "KOSPI"), {})
    # 수급: 일별 + 업종 5일
    days = {}
    for p in sorted(glob.glob(str(DATA / "market" / "days" / "*.json")))[-14:]:
        m = next((m for m in (_j(p, {}) or {}).get("markets", []) if m.get("market") == "KOSPI"), None)
        if m and m.get("deal_date"):
            days[m["deal_date"]] = {"date": m["deal_date"], "f": m.get("foreign_eok"), "i": m.get("institution_eok"), "p": m.get("individual_eok"), "chg": m.get("change_pct")}
    P["days"] = sorted(days.values(), key=lambda d: d["date"])[-8:]
    flows = _j(DATA / "market" / "flows_latest.json", {}) or {}
    P["flow_sectors"] = [s for s in flows.get("sectors", []) if s.get("f5") is not None]
    P["flows_src"] = flows.get("source", "")
    fl_stock = {x["code"]: x for x in flows.get("stocks", [])}
    # 업종: 레이더(기술) × 이익(펀더)
    rad = _j(DATA / "radar" / "latest.json", {}) or {}
    grp = {}
    for code, s in uni.items():
        grp.setdefault(s["group"] or "기타", []).append((code, s))
    fg = {}
    for g, L in grp.items():
        ope = opl = num = den = n = 0
        for code, s in L:
            fa, la = _fa_la(fund.get(code))
            if fa and la and fa.get("op") is not None and la.get("op") is not None:
                ope += fa["op"]; opl += la["op"]; n += 1
                if px.get(code) and fa.get("eps") and fa["eps"] > 0:
                    num += s["cap"]; den += s["cap"] * fa["eps"] / px[code]
        fg[g] = {"n_fund": n, "opg": round((ope / opl - 1) * 100, 1) if opl > 0 and n >= 2 else None, "per": round(num / den, 1) if den else None}
    fs = {x["group"]: x for x in flows.get("sectors", [])}
    hist = rad.get("history") or []
    r4 = hist[-5]["ranks"] if len(hist) >= 5 else {}
    P["matrix"] = [{"group": g["group"], "rank": g["rank"], "score": g["score"], "n": g["n"], "breadth": g["breadth_pct"], "nh": g["newhigh_pct"],
                    "rank4": r4.get(g["group"]), "leaders": [l["name"] for l in g["leaders"][:3]], **fg.get(g["group"], {}),
                    "f5": (fs.get(g["group"]) or {}).get("f5"), "i5": (fs.get(g["group"]) or {}).get("i5")} for g in rad.get("groups", [])]
    P["radar_as_of"] = rad.get("as_of")
    # 종목: 감시 목록 + 펀더 점수
    scf = sorted(glob.glob(str(DATA / "bus" / "*" / "screener.json")))
    sc = _j(scf[-1], {}) if scf else {}
    cal = _j(DATA / "strategy" / "prep" / f"{P['date']}.json", {}) or {}
    cal = cal.get("calendar") or []
    seen, board = set(), []
    for key in ("watch", "running"):
        for r in sc.get(key, []):
            if r["code"] in seen:
                continue
            seen.add(r["code"])
            lv, b = r.get("levels") or {}, r.get("base") or {}
            bo, st = lv.get("breakout"), lv.get("stop_1r")
            f = fscore(fund.get(r["code"]), px.get(r["code"]))
            dist = lv.get("distance_pct")
            tech = (1 if (r["rs"] or 0) >= 80 else 0) + (1 if dist is not None and dist <= 10 and not r["missing"] else 0) + (1 if r["ia"] == "동반 상승" else 0)
            ev = next((c for c in cal if c.get("code") == r["code"]), None)
            x = fl_stock.get(r["code"]) or {}
            cl = [q["close"] for q in daily.get(r["code"], [])]
            board.append({"name": r["stock"], "code": r["code"], "group": r["group"], "rs": r["rs"], "close": r["close"], "pool": r["pool"], "list": key,
                          "breakout": bo, "dist": dist, "stop": st, "qty": int(300000 // (bo - st)) if bo and st and bo > st else None,
                          "base_days": b.get("days"), "depth": b.get("depth_pct"), "dry": b.get("vol_dryup"), "ia": r["ia"], "missing": r["missing"],
                          "event": (ev["date"][5:] + " " + ev["name"][:16]) if ev else None, "fs": f, "tech": tech, "f5": x.get("f5"), "i5": x.get("i5"),
                          "gap20": round((cl[-1] / (sum(cl[-20:]) / 20) - 1) * 100, 1) if len(cl) >= 20 else None,
                          "r1m": round((cl[-1] / cl[-22] - 1) * 100, 1) if len(cl) > 22 else None})
    P["board"] = board
    P["screener"] = {"as_of": sc.get("as_of"), "count": sc.get("count"), "signals": len(sc.get("signals", [])), "file": scf[-1].split("data/")[-1] if scf else None}
    # 보유 · 성적
    from common import positions
    pos = []
    for p in positions():
        cl = [q["close"] for q in daily.get(p["code"], [])]
        if not cl:
            continue
        ist = p.get("initial_stop") or p.get("stop"); risk = p["avg_price"] - ist; m20 = sum(cl[-20:]) / 20
        pos.append({"name": p["name"], "code": p["code"], "qty": p["qty"], "avg": p["avg_price"], "stop": p.get("stop"), "price": cl[-1],
                    "r": round((cl[-1] - p["avg_price"]) / risk, 2) if risk > 0 else None, "r3": p["avg_price"] + 3 * risk,
                    "to3": round((p["avg_price"] + 3 * risk) / cl[-1] * 100 - 100, 1), "ma20": round(m20), "to_ma20": round((m20 / cl[-1] - 1) * 100, 1),
                    "to_stop": round((p["stop"] / cl[-1] - 1) * 100, 1)})
    P["positions"] = pos
    try:
        P["review"] = json.loads(subprocess.run([sys.executable, str(ROOT / "tools" / "trades.py"), "review"], capture_output=True, text=True, timeout=60).stdout)
    except Exception:
        P["review"] = {}
    P["calendar"] = cal[:12]
    st = _j(DATA / "strategy" / "latest.json", {}) or {}
    P["themes"] = [{"id": t["id"], "name": t["name"], "stage": t.get("stage")} for t in st.get("themes", [])]
    P["scenarios"] = st.get("scenarios") or []
    P["regime_title"] = (st.get("regime") or {}).get("title", "")
    TF.mkdir(parents=True, exist_ok=True)
    (TF / f"prep_{P['date']}.json").write_text(json.dumps(P, ensure_ascii=False), encoding="utf-8")
    return P


def core_list():
    """매일 갱신용 핵심 후보(2026-11-14, 1차 개선): 최신 감시 목록 + 실적 캐시로 펀더·기술 점수만 (네트워크 없음, 몇 초).
    web_build가 매번 부르고, 웹 '오늘'·장중 알림(site/core.json)이 쓴다."""
    fund = _fund()
    scf = sorted(glob.glob(str(DATA / "bus" / "*" / "screener.json")))
    sc = _j(scf[-1], {}) if scf else {}
    prevfs = {}
    if len(fund) < 100:   # 실적 캐시가 없는 곳(예약 대화 컨테이너): 커밋된 지난 주간 지면의 펀더 점수로 대신
        pf = sorted(TF.glob("prep_*.json"))
        prevfs = {b["code"]: b.get("fs") for b in ((_j(pf[-1], {}) or {}).get("board") or [])} if pf else {}
    items = []
    for r in sc.get("watch", []):
        lv, b = r.get("levels") or {}, r.get("base") or {}
        f = fscore(fund.get(r["code"]), r.get("close")) if fund.get(r["code"]) else prevfs.get(r["code"])
        dist = lv.get("distance_pct")
        tech = (1 if (r["rs"] or 0) >= 80 else 0) + (1 if dist is not None and dist <= 10 and not r["missing"] else 0) + (1 if r["ia"] == "동반 상승" else 0)
        fp = (f or {}).get("pts", 0)
        note = "베이스 짧고 얕음(확인 필요)" if (b.get("days") or 99) < 10 and (b.get("depth_pct") or 99) < 3 else ""
        items.append({"code": r["code"], "name": r["stock"], "group": r["group"], "rs": r["rs"], "close": r["close"], "breakout": lv.get("breakout"),
                      "stop": lv.get("stop_1r"), "dist": dist, "fp": fp, "tech": tech, "why": (f or {}).get("why") or [], "ia": r["ia"] == "동반 상승",
                      "pool": r["pool"], "core": fp >= 2 and tech >= 2, "note": note})
    items.sort(key=lambda x: (not x["core"], -x["fp"], x["dist"] if x["dist"] is not None else 99))
    return {"as_of": sc.get("as_of"), "made_at": datetime.now(KST).strftime("%Y-%m-%d %H:%M"), "items": items[:20],
            "n_core": sum(1 for x in items if x["core"]), "rule": "핵심 = 펀더 2/3↑ + 기술 2/3↑ (펀더: 분기 이익·이익률·올해 이익 / 기술: RS 80↑·기준가 10% 안·업종 동행)"}


def topdown_brief():
    """체크포인트용 탑다운 요약(2026-11-14 1차, 토큰 0·몇 초): 국면(분산일·20일선) · 시장 폭 · 업종 분류(지난 주간 지면) · 핵심 후보 거리."""
    out = {}
    try:
        k = json.loads((CACHE / "daily" / "KOSPI.json").read_text())["rows"]
        out["regime"] = {kk: v for kk, v in regime_block({"KOSPI": k}).items() if kk != "kospi"}
        out["regime"]["dist_days_n"] = len(out["regime"]["dist_days"])
    except Exception as e:
        out["regime_error"] = type(e).__name__
    fs = sorted(TF.glob("prep_*.json"))
    if fs:
        P = _j(fs[-1], {}) or {}
        MT = sorted([m for m in P.get("matrix", []) if m.get("opg") is not None and (m.get("n_fund") or 0) >= 3], key=lambda m: m["rank"])
        out["sectors_week"] = {"as_of": P.get("date"), **{q: [f"{m['group']}({m['rank']}위, 이익 {m['opg']:+.0f}%)" for m in MT if quad(m) == q][:4] for q in ("리더", "모멘텀만", "기다림")}}
        out["breadth_week"] = {k: v for k, v in ((P.get("breadth") or [{}])[-1]).items() if k not in ("nh", "nl")}   # 신고가·신저가 수는 네이버 시장 집계 하나만 씀(⑫)
    c = core_list()
    out["core"] = [{k: x[k] for k in ("name", "group", "breakout", "dist", "fp", "tech", "note")} for x in c["items"] if x["core"]][:6]
    out["core_rule"] = c["rule"]
    return out


def rally(k):
    """랠리 시도·팔로스루 (오닐 방식 단순화): 최근 30거래일 최저 종가 뒤 첫 상승일부터 센 날짜 · 4일째부터 +1.5%↑ + 거래량 증가 = 팔로스루."""
    c = [x["close"] for x in k[-40:]]; v = [x["volume"] for x in k[-40:]]; d = [x["date"] for x in k[-40:]]
    lo = min(range(len(c) - 30, len(c)), key=lambda i: c[i])
    st = next((i for i in range(lo + 1, len(c)) if c[i] > c[i - 1]), None)
    ftd = None
    if st is not None:
        for i in range(st + 3, len(c)):
            if (c[i] / c[i - 1] - 1) * 100 >= 1.5 and v[i] > v[i - 1]:
                ftd = d[i]
    return {"low_date": d[lo], "low": c[lo], "day": (len(c) - st) if st is not None else 0, "start": d[st] if st is not None else None, "ftd": ftd}


def breadth_fast(daily, uni, days=60):
    """시장 폭(50·20일선 위 비율) — 누적합으로 빠르게. 신고가·신저가 수는 네이버 시장 집계를 쓰므로 계산하지 않는다(⑫)."""
    dates = [r["date"] for r in daily["KOSPI"][-days:]]
    cnt = {d: [0, 0, 0] for d in dates}
    for c in uni:
        rows = daily.get(c)
        if not rows or len(rows) < 60:
            continue
        cl = [r["close"] for r in rows]; pre = [0]
        for x in cl:
            pre.append(pre[-1] + x)
        pos = {r["date"]: i for i, r in enumerate(rows)}
        for d in dates:
            i = pos.get(d)
            if i is None or i < 50:
                continue
            m50 = (pre[i + 1] - pre[i - 49]) / 50; m20 = (pre[i + 1] - pre[i - 19]) / 20
            z = cnt[d]; z[0] += 1; z[1] += cl[i] > m50; z[2] += cl[i] > m20
    return [{"date": d, "n": z[0], "a50": round(z[1] / z[0] * 100, 1), "a20": round(z[2] / z[0] * 100, 1)} for d, z in cnt.items() if z[0]]


def daily_market():
    """웹 '시장'(탑다운) 탭·'오늘' 국면 추적판용 (2026-11-14 2차): prep의 시장 부분만 매일. 해석 글 없음."""
    import new_highs
    daily, fund, uni = _daily(), _fund(), new_highs.universe_info()
    px = {c: r[-1]["close"] for c, r in daily.items()}
    P = {"made_at": datetime.now(KST).strftime("%Y-%m-%d %H:%M")}
    P["macro"] = macro()
    P["regime"] = regime_block(daily); P["rally"] = rally(daily["KOSPI"])
    P["breadth"] = breadth_fast(daily, uni)
    days = {}
    for p in sorted(glob.glob(str(DATA / "market" / "days" / "*.json")))[-14:]:
        m = next((m for m in (_j(p, {}) or {}).get("markets", []) if m.get("market") == "KOSPI"), None)
        if m and m.get("deal_date"):
            days[m["deal_date"]] = {"date": m["deal_date"], "f": m.get("foreign_eok"), "i": m.get("institution_eok"), "p": m.get("individual_eok"), "chg": m.get("change_pct")}
    P["days"] = sorted(days.values(), key=lambda d: d["date"])[-8:]
    flows = _j(DATA / "market" / "flows_latest.json", {}) or {}
    P["flow_sectors"] = [s for s in flows.get("sectors", []) if s.get("f5") is not None]; P["flows_src"] = flows.get("source", "")
    rad = _j(DATA / "radar" / "latest.json", {}) or {}
    grp = {}
    for code, s in uni.items():
        grp.setdefault(s["group"] or "기타", []).append((code, s))
    fg = {}
    for g, L in grp.items():
        ope = opl = num = den = n = 0
        for code, s in L:
            fa, la = _fa_la(fund.get(code))
            if fa and la and fa.get("op") is not None and la.get("op") is not None:
                ope += fa["op"]; opl += la["op"]; n += 1
                if px.get(code) and fa.get("eps") and fa["eps"] > 0:
                    num += s["cap"]; den += s["cap"] * fa["eps"] / px[code]
        fg[g] = {"n_fund": n, "opg": round((ope / opl - 1) * 100, 1) if opl > 0 and n >= 2 else None, "per": round(num / den, 1) if den else None}
    fs = {x["group"]: x for x in flows.get("sectors", [])}; hist = rad.get("history") or []; r4 = hist[-5]["ranks"] if len(hist) >= 5 else {}
    P["matrix"] = [{"group": g["group"], "rank": g["rank"], "score": g["score"], "n": g["n"], "breadth": g["breadth_pct"], "rank4": r4.get(g["group"]),
                    **fg.get(g["group"], {}), "f5": (fs.get(g["group"]) or {}).get("f5"), "i5": (fs.get(g["group"]) or {}).get("i5")} for g in rad.get("groups", [])]
    P["radar_as_of"] = rad.get("as_of")
    return P


def market_fragments(P):
    """'시장' 탭 4칸 HTML 조각 + '오늘' 추적판 숫자. 그림은 주간 지면과 같은 함수."""
    N = auto_narr({**P, "board": [], "calendar": [], "scenarios": []})
    lb = P["breadth"][-1] if P["breadth"] else {"a50": 0, "a20": 0, "n": 0, "date": ""}
    dd = len(P["regime"]["dist_days"]); DY = P["days"]; f5 = sum((d["f"] or 0) for d in DY[-5:]); i5 = sum((d["i"] or 0) for d in DY[-5:])
    mrow = []
    for m in P["macro"]:
        if "err" in m or not m.get("w1"):
            continue
        if m["sym"] == "^TNX":
            now = f'{m["now"]:.2f}%'; a = (m["now"] - m["w1"]) * 100; b = (m["now"] - m["m1"]) * 100; d1, dm = f"{a:+.0f}bp", f"{b:+.0f}bp"
        else:
            now = w(m["now"], 2 if m["now"] < 1000 else 0); a = (m["now"] / m["w1"] - 1) * 100; b = (m["now"] / m["m1"] - 1) * 100; d1, dm = pc(a), pc(b)
        mrow.append(f'<tr><td class="l">{E(m["name"])}</td><td><b>{now}</b></td><td class="{cls(a)}">{d1}</td><td class="{cls(b)}">{dm}</td><td class="l"><small>{E(m.get("date", ""))}</small></td></tr>')
    impl = "".join(f'<tr><td class="l">{E(a)}</td><td><span class="tag {c}">{E(b)}</span></td><td class="l wrap">{E(t)}</td></tr>' for a, b, t, c in N.get("impl") or [])
    FS = sorted(P["flow_sectors"], key=lambda s: -((s["f5"] or 0) + (s["i5"] or 0)))
    frow = lambda L: "".join(f'<tr><td class="l">{E(s["group"])}</td><td class="{cls(s["f5"])}">{eok(s["f5"])}</td><td class="{cls(s["i5"])}">{eok(s["i5"])}</td><td class="{cls(s.get("r5"))}">{pc(s.get("r5"))}</td></tr>' for s in L)  # noqa: E731
    srt = sorted(P["matrix"], key=lambda m: m["rank"]); srow = []
    for m in srt[:20]:
        ch = (m["rank4"] - m["rank"]) if m.get("rank4") else None
        q = quad(m) if m.get("opg") is not None and (m.get("n_fund") or 0) >= 3 else "-"
        qc = {"리더": "pos", "모멘텀만": "warn", "기다림": "neu", "회피": "neg"}.get(q, "neu")
        srow.append(f'<tr><td>{m["rank"]}</td><td class="l"><b>{E(m["group"])}</b></td><td class="{cls(ch)}">{("▲" + str(ch)) if ch and ch > 0 else (("▼" + str(-ch)) if ch and ch < 0 else "-")}</td><td>{m["score"]}</td><td>{m["breadth"]}%</td>'
                    f'<td>{gtxt(m.get("opg"))}</td><td>{m.get("per") or "-"}</td><td class="{cls(m.get("f5"))}">{eok(m.get("f5"))}</td><td class="{cls(m.get("i5"))}">{eok(m.get("i5"))}</td><td>{f"<span class=\"tag {qc}\">{q}</span>" if q != "-" else "-"}</td></tr>')
    T = "<div class=\"tw\"><table>"   # 시장 탭 표는 '숫자 비교표'라 휴대폰에서도 표 (2026-11-14 표·카드 규칙)
    asof = P["regime"]["date"]; R = P["rally"]
    html_ = {
        "macro": f'<div class="fig"><div class="ft"><span>표</span>글로벌 지표 — 최근 · 1주 · 1개월</div>{T}<tr><th class="l">지표</th><th>최근</th><th>1주</th><th>1개월</th><th class="l">기준일</th></tr>{"".join(mrow)}</table></div><div class="src">출처: Yahoo Finance(비공식, 지연 가능) · {E(P["made_at"])} 받음</div></div>'
                 f'<div class="fig"><div class="ft"><span>표</span>매크로 → 업종 연결 (자동 규칙 문장)</div>{T}<tr><th class="l">변화</th><th>방향</th><th class="l">무엇에 영향</th></tr>{impl}</table></div><div class="src">1주 변화로 만든 규칙 문장입니다 · 해석은 주간 보고서(토)</div></div>',
        "regime": f'<div class="fig"><div class="ft"><span>그림</span>코스피 120거래일 · ▼ 분산일 · 점선 20일선</div>{chart_kospi(P)}<div class="src">분산일 = 종가 −0.2%↓ + 거래량 전날보다 많음(25거래일 {dd}개) · 랠리 시도 {R["day"]}일째(저점 {md(R["low_date"])}) · 팔로스루 {md(R["ftd"]) if R["ftd"] else "아직"} · 출처: 네이버 코스피 일봉(비공식) {md(asof)}</div></div>'
                  f'<div class="fig"><div class="ft"><span>그림</span>시장 폭 — 50일선·20일선 위 종목 비율</div>{chart_breadth(P)}<div class="leg"><span><i style="background:var(--acc)"></i>50일선 위 {lb["a50"]:.0f}%</span><span><i style="background:var(--ink3)"></i>20일선 위 {lb["a20"]:.0f}%</span></div><div class="src">시총 2천억↑ {lb["n"]}종목 · 출처: 네이버 일봉(비공식) 계산</div></div>',
        "flows": f'<div class="fig"><div class="ft"><span>그림</span>코스피 투자자별 순매수(억 원) · 아래 = 그날 코스피 등락</div>{chart_flows(P)}<div class="leg"><span><i style="background:var(--acc)"></i>외국인</span><span><i style="background:var(--warn)"></i>기관</span><span><i style="background:var(--ink3)"></i>개인</span><span>5일 합 외국인 {f5/10000:+.2f}조 · 기관 {i5/10000:+.2f}조</span></div><div class="src">출처: 네이버 시황(비공식)</div></div>'
                 f'<div class="two"><div class="fig"><div class="ft"><span>표</span>5일 순매수 상위 업종(억)</div>{T}<tr><th class="l">업종</th><th>외국인</th><th>기관</th><th>5일</th></tr>{frow(FS[:8])}</table></div></div><div class="fig"><div class="ft"><span>표</span>5일 순매도 상위 업종(억)</div>{T}<tr><th class="l">업종</th><th>외국인</th><th>기관</th><th>5일</th></tr>{frow(FS[-8:][::-1])}</table></div></div></div><div class="src">{E(P.get("flows_src") or "")}</div>',
        "sectors": f'<div class="fig"><div class="ft"><span>그림</span>업종 테크노펀더멘탈 지도 — 이익(가로) × 추세(세로)</div>{chart_matrix(P)}<div class="src">가로 = 올해 영업이익 컨센서스 업종 합 증가율 · 세로 = 주도 섹터 레이더 점수({md(P.get("radar_as_of") or asof)}) · 출처: 네이버 재무·컨센서스(비공식)</div></div>'
                   f'<div class="fig"><div class="ft"><span>표</span>업종 스코어 — 강도 상위 20</div>{T}<tr><th>순위</th><th class="l">업종</th><th>4주</th><th>강도</th><th>20일선 위</th><th>올해 영업이익</th><th>PER(E)</th><th>외국인 5일</th><th>기관 5일</th><th>분류</th></tr>{"".join(srow)}</table></div><div class="src">분류: 이익 +{XQ}%↑ / 강도 {YQ}↑ (리더 · 모멘텀만 · 기다림 · 회피) · 컨센서스 있는 종목 3개 미만 업종은 “-”</div></div>'}
    lt, _ = light(P)
    track = {"light": lt, "gap20": P["regime"]["gap20"], "slope20": P["regime"]["slope20"], "dist": dd, "rally_day": R["day"], "rally_low": R["low_date"], "ftd": R["ftd"],
             "a50": lb["a50"], "a20": lb["a20"], "f5": f5, "i5": i5, "as_of": asof}
    return {"made_at": P["made_at"], "css": TOKENS_WEB + CSS, "html": html_, "track": track}


# ---------------------------------------------------------------- 분류 · 기본 해석
def quad(m):
    o, s = m.get("opg"), m["score"]
    lead = o is not None and o >= XQ
    return "리더" if lead and s >= YQ else "모멘텀만" if s >= YQ else "기다림" if lead else "회피"


def cat(b):
    f = (b["fs"] or {}).get("pts", 0)
    if b["list"] == "running":
        return 4, "달리는 중 · 첫 눌림 대기", "neu"
    if f >= 2 and b["tech"] >= 2:
        return 0, "핵심 후보", "pos"
    if f >= 2:
        return 1, "펀더 OK·기술 대기", "neu"
    if b["tech"] >= 2:
        return 2, "기술만 · 펀더 미확인", "warn"
    return 3, "제외", "neg"


def light(P):
    g = P["regime"]["gap20"]; s = P["regime"]["slope20"]
    return ("초록", "pos") if g > 0 and s > 0 else ("노랑", "warn") if g > 0 or s > 0 else ("빨강", "neg")


def _mac(P, sym):
    return next((m for m in P["macro"] if m["sym"] == sym and "err" not in m), None)


def auto_narr(P):
    """숫자만으로 만든 기본 해석(토큰 0). Claude가 narr_날짜.json으로 덮어쓴다."""
    MT = [m for m in P["matrix"] if m.get("opg") is not None and (m.get("n_fund") or 0) >= 3]
    leaders = [m for m in MT if quad(m) == "리더"]; mom = [m for m in MT if quad(m) == "모멘텀만"]; wait = sorted([m for m in MT if quad(m) == "기다림"], key=lambda m: m["rank"])
    core = sorted([b for b in P["board"] if cat(b)[0] == 0], key=lambda b: (-(b["fs"] or {}).get("pts", 0), -b["tech"], -(b["rs"] or 0)))
    lt, _ = light(P)
    lnames = "·".join(m["group"] for m in leaders[:3]) or "없음"
    tnx, krw, wti, sox, vix = (_mac(P, s) for s in ("^TNX", "KRW=X", "CL=F", "^SOX", "^VIX"))
    impl = []
    if tnx and tnx.get("w1"):
        d = (tnx["now"] - tnx["w1"]) * 100
        impl.append([f"미 10년물 {tnx['now']:.2f}% ({d:+.0f}bp/1주)", "부담" if d > 5 else "우호" if d < -5 else "중립",
                     "금리가 오르면 PER이 높은 성장주(반도체 장비·바이오)에 부담입니다. 은행·보험엔 우호적입니다." if d > 5 else "금리 하락은 성장주 밸류에이션에 우호적입니다.", "neg" if d > 5 else "pos" if d < -5 else "neu"])
    if krw and krw.get("w1"):
        d = (krw["now"] / krw["w1"] - 1) * 100
        impl.append([f"원/달러 {krw['now']:,.0f}원 ({d:+.1f}%/1주)", "우호" if d < -0.5 else "부담" if d > 0.5 else "중립",
                     "원화 강세는 외국인 환차익 기대로 순매수에 우호적입니다." if d < 0 else "원화 약세는 외국인 매도 압력이 될 수 있습니다. 수출주 채산성엔 우호적입니다.", "pos" if d < -0.5 else "neg" if d > 0.5 else "neu"])
    if wti and wti.get("w1"):
        d = (wti["now"] / wti["w1"] - 1) * 100
        impl.append([f"WTI {wti['now']:.1f}달러 ({d:+.1f}%/1주)", "우호(항공·화학)" if d < 0 else "부담(항공)", "유가 하락은 항공·화학 원가에 우호적입니다." if d < 0 else "유가 상승은 정유엔 우호, 항공엔 부담입니다.", "pos" if d < 0 else "neu"])
    if sox and sox.get("w1"):
        d1 = (sox["now"] / sox["w1"] - 1) * 100; dm = (sox["now"] / sox["m1"] - 1) * 100
        impl.append([f"필라델피아 반도체 {d1:+.1f}%/1주 (1개월 {dm:+.1f}%)", "반등" if d1 > 0 else "약세", "미국 반도체 흐름은 국내 반도체 장비·테스트로 이어지는 경우가 많습니다.", "pos" if d1 > 0 else "neg"])
    if vix and vix.get("w1"):
        impl.append([f"VIX {vix['now']:.1f} ({vix['w1']:.1f}→)", "우호" if vix["now"] < vix["w1"] else "부담", "변동성이 내려가면 위험 선호가 돌아옵니다." if vix["now"] < vix["w1"] else "변동성 상승은 위험 회피 신호입니다.", "neu"])
    deep = core[0] if core else None
    warns = [b for b in P["board"] if (b["fs"] or {}).get("pts", 0) <= 1 and (b["tech"] >= 2 or b["list"] == "running") and b["fs"]]
    warns = sorted(warns, key=lambda b: (b["fs"]["pts"], -b["tech"]))[:3]
    lb = P["breadth"][-1] if P["breadth"] else {}
    dd = len(P["regime"]["dist_days"])
    return {
        "title": f"{lnames} — 이익이 받쳐 주는 곳에서 추세를 기다립니다" if lt != "초록" else f"{lnames} — 이익과 추세가 겹치는 곳에 집중합니다",
        "sub": f"신호등 {lt}, 분산일 {dd}개입니다. 이익 증가와 업종 추세가 겹치는 리더 업종은 {lnames}입니다. 감시 목록에서 펀더와 기술 조건을 함께 갖춘 핵심 후보는 {len(core)}종목입니다.",
        "call": f"신호등이 {lt}입니다. " + ("노란불이 켜지면 핵심 후보의 첫 베이스 돌파부터 봅니다." if lt == "빨강" else "핵심 후보의 기준가 돌파 + 업종 동행을 확인합니다."),
        "macro_view": "중립", "desk": [], "todo": [f"핵심 후보 {len(core)}종목의 거래량 마름 확인", "팔로스루(코스피 +1.5%↑ + 거래량 증가) 여부", "보유 종목 3R·20일선 가격 확인"],
        "impl": impl,
        "macro_side": ["한 주 사이 바뀐 지표와 업종 연결은 오른쪽 표와 같습니다."],
        "regime_side": [f"분산일이 25거래일 동안 {dd}개입니다.", f"50일선 위 종목은 {lb.get('a50', 0):.0f}%, 20일선 위는 {lb.get('a20', 0):.0f}%입니다."],
        "flow_side": ["외국인·기관의 일별 순매수와 업종 5일 흐름은 오른쪽과 같습니다."],
        "sector_side": [f"리더(이익 ↑ + 추세 ↑): {', '.join(m['group'] for m in leaders[:4]) or '없음'}입니다.",
                        f"모멘텀만(추세 ↑ · 이익 약함): {', '.join(m['group'] for m in mom[:3]) or '없음'}입니다.",
                        f"기다림(이익 ↑ · 추세 아직): {', '.join(m['group'] for m in wait[:3]) or '없음'}입니다."],
        "deep_code": deep["code"] if deep else None, "deep_side": [], "warns": {b["code"]: "" for b in warns},
        "scenarios": P.get("scenarios") or [], "events": [f"{c['date'][5:]} {c['name']}" for c in P["calendar"][:6]],
    }


# ---------------------------------------------------------------- 그리기
w = lambda v, d=0: "-" if v is None else f"{v:,.{d}f}"  # noqa: E731
pc = lambda v, d=1: "-" if v is None else f"{'+' if v > 0 else ''}{v:.{d}f}%"  # noqa: E731
cls = lambda v: "" if not isinstance(v, (int, float)) else ("up" if v > 0 else "dn" if v < 0 else "")  # noqa: E731
md = lambda d: f"{d[4:6]}/{d[6:]}"  # noqa: E731
eok = lambda v: "-" if v is None else f"{'+' if v > 0 else ''}{v:,.0f}"  # noqa: E731


def gtxt(v):
    if v is None:
        return "-"
    if v == "흑전":
        return '<span class="up">흑자전환</span>'
    if isinstance(v, (int, float)) and abs(v) >= 300:
        return f'<span class="{cls(v)}">{"+300%↑" if v > 0 else "−300%↓"}</span>'
    return f'<span class="{cls(v)}">{pc(v, 0)}</span>'


def _lab(i, n, t, y, W=640):
    return f'<text x="{t}" y="{y}" class="ax" text-anchor="{"start" if i == 0 else "end" if i == n - 1 else "middle"}">'


def chart_kospi(P):
    K = P["regime"]["kospi"]; kv = [c for _, c in K]; n = len(K)
    W, H, L, R, T, B = 640, 190, 48, 14, 12, 22
    lo, hi = min(kv) * .98, max(kv) * 1.02
    x = lambda i: L + i / (n - 1) * (W - L - R); y = lambda v: T + (hi - v) / (hi - lo) * (H - T - B)  # noqa: E731
    ma = [None if i < 19 else sum(kv[i - 19:i + 1]) / 20 for i in range(n)]
    g = [f'<line x1="{L}" x2="{W-R}" y1="{y(v):.1f}" y2="{y(v):.1f}" class="grid"/><text x="{L-6}" y="{y(v)+3:.1f}" class="ax" text-anchor="end">{w(v)}</text>' for v in (lo + (hi - lo) * f for f in (.15, .5, .85))]
    g.append('<path d="' + "".join(("M" if i == 0 else "L") + f"{x(i):.1f} {y(v):.1f}" for i, v in enumerate(kv)) + '" fill="none" stroke="var(--ink)" stroke-width="1.7"/>')
    g.append('<path d="' + "".join(("M" if i == 19 else "L") + f"{x(i):.1f} {y(v):.1f}" for i, v in enumerate(ma) if v) + '" fill="none" stroke="var(--acc)" stroke-width="1.2" stroke-dasharray="4 3"/>')
    dd = {d["date"] for d in P["regime"]["dist_days"]}
    g += [f'<path d="M{x(i):.1f} {y(c)+6:.1f} l-4 7 h8 z" fill="var(--dn)"><title>분산일 {md(d)}</title></path>' for i, (d, c) in enumerate(K) if d in dd]
    g.append(f'<rect x="{x(n-25):.1f}" y="{T}" width="{x(n-1)-x(n-25):.1f}" height="{H-T-B}" fill="var(--acc)" fill-opacity=".06"/><text x="{x(n-25)+4:.1f}" y="{T+11}" class="ax">최근 25거래일</text>')
    g += [_lab(i, n, f"{x(i):.1f}", H - 6) + f"{md(K[i][0])}</text>" for i in (0, n // 2, n - 1)]
    return f'<svg viewBox="0 0 {W} {H}" class="chart" role="img" aria-label="코스피와 분산일">{"".join(g)}</svg>'


def chart_breadth(P):
    BR = P["breadth"]; m = len(BR)
    W, H, L, R, T, B = 640, 160, 48, 14, 12, 22
    x = lambda i: L + i / (m - 1) * (W - L - R); y = lambda v: T + (100 - v) / 100 * (H - T - B)  # noqa: E731
    g = [f'<line x1="{L}" x2="{W-R}" y1="{y(v):.1f}" y2="{y(v):.1f}" class="grid"/><text x="{L-6}" y="{y(v)+3:.1f}" class="ax" text-anchor="end">{v}%</text>' for v in (25, 50, 75)]
    g.append(f'<line x1="{L}" x2="{W-R}" y1="{y(50):.1f}" y2="{y(50):.1f}" class="basel"/>')
    for key, col, sw in (("a20", "--ink3", 1.3), ("a50", "--acc", 2)):
        g.append('<path d="' + "".join(("M" if i == 0 else "L") + f"{x(i):.1f} {y(b[key]):.1f}" for i, b in enumerate(BR)) + f'" fill="none" stroke="var({col})" stroke-width="{sw}"/>')
        g.append(f'<circle cx="{x(m-1):.1f}" cy="{y(BR[-1][key]):.1f}" r="3" fill="var({col})"/><text x="{x(m-1)-4:.1f}" y="{y(BR[-1][key])-6:.1f}" class="vl" text-anchor="end">{BR[-1][key]:.0f}%</text>')
    g += [_lab(i, m, f"{x(i):.1f}", H - 6) + f"{md(BR[i]['date'])}</text>" for i in (0, m // 2, m - 1)]
    return f'<svg viewBox="0 0 {W} {H}" class="chart" role="img" aria-label="시장 폭">{"".join(g)}</svg>'


def chart_flows(P):
    DY = P["days"]; nd = len(DY)
    if not nd:
        return ""
    W, H, L, R, T, B = 640, 210, 52, 14, 16, 40
    mx = max([abs(v) for d in DY for v in (d["f"], d["i"], d["p"]) if v is not None] or [1])
    bw = (W - L - R) / nd; y0 = T + (H - T - B) / 2; sc = (H - T - B) / 2 / mx
    g = [f'<line x1="{L}" x2="{W-R}" y1="{y0:.1f}" y2="{y0:.1f}" stroke="var(--ink3)" stroke-width=".8"/>']
    step = 10000 if mx > 15000 else 5000 if mx > 6000 else 2000
    v = step
    while v <= mx:
        for s in (v, -v):
            g.append(f'<line x1="{L}" x2="{W-R}" y1="{y0 - s*sc:.1f}" y2="{y0 - s*sc:.1f}" class="grid"/><text x="{L-6}" y="{y0 - s*sc + 3:.1f}" class="ax" text-anchor="end">{s/10000:+.1f}조</text>')
        v += step
    for i, d in enumerate(DY):
        x0 = L + i * bw
        for j, (k, col, nm) in enumerate((("f", "--acc", "외국인"), ("i", "--warn", "기관"), ("p", "--ink3", "개인"))):
            val = d[k] or 0; hh = abs(val) * sc
            g.append(f'<rect x="{x0 + bw*(.12 + j*.26):.1f}" y="{(y0 - hh if val > 0 else y0):.1f}" width="{bw*.24:.1f}" height="{max(hh, .5):.1f}" fill="var({col})" opacity=".85"><title>{md(d["date"])} {nm} {val:,.0f}억</title></rect>')
        c = d.get("chg") or 0
        g.append(f'<text x="{x0 + bw/2:.1f}" y="{H-22}" class="ax" text-anchor="middle">{md(d["date"])}</text><text x="{x0 + bw/2:.1f}" y="{H-8}" class="ax" text-anchor="middle" style="fill:var(--{"up" if c > 0 else "dn"})">{pc(c, 1)}</text>')
    return f'<svg viewBox="0 0 {W} {H}" class="chart" role="img" aria-label="투자자별 순매수">{"".join(g)}</svg>'


def chart_matrix(P):
    MT = [m for m in P["matrix"] if m.get("opg") is not None and (m.get("n_fund") or 0) >= 3]
    W, H, L, R, T, B = 640, 360, 48, 20, 16, 38
    cx = lambda v: L + (max(-40, min(200, v)) + 40) / 240 * (W - L - R)  # noqa: E731
    cy = lambda v: T + (100 - max(30, v)) / 70 * (H - T - B)  # noqa: E731
    g = [f'<rect x="{cx(XQ):.1f}" y="{T}" width="{W-R-cx(XQ):.1f}" height="{cy(YQ)-T:.1f}" fill="var(--acc)" fill-opacity=".07"/>',
         f'<line x1="{cx(XQ):.1f}" x2="{cx(XQ):.1f}" y1="{T}" y2="{H-B}" class="basel"/><line x1="{L}" x2="{W-R}" y1="{cy(YQ):.1f}" y2="{cy(YQ):.1f}" class="basel"/>']
    g += [f'<text x="{cx(v):.1f}" y="{H-B+14}" class="ax" text-anchor="middle">{v:+d}%{"↑" if v == 200 else ""}</text>' for v in (0, 50, 100, 150, 200)]
    g += [f'<text x="{L-6}" y="{cy(v)+3:.1f}" class="ax" text-anchor="end">{v}</text>' for v in (40, 60, 80, 100)]
    g.append(f'<text x="{W-R}" y="{H-4}" class="ax" text-anchor="end">펀더멘털: 올해 영업이익 증가율(컨센서스, 업종 합) →</text><text x="{L+4}" y="{T+10}" class="ax">↑ 기술적: 업종 강도 점수(0~100)</text>')
    g += [f'<text x="{W-R-6}" y="{T+14}" class="quad" text-anchor="end">① 리더 — 이익 ↑ · 추세 ↑</text>', f'<text x="{W-R-6}" y="{cy(YQ)+16:.1f}" class="quad" text-anchor="end">② 기다림 — 이익 ↑ · 추세 아직</text>',
          f'<text x="{L+6}" y="{T+28}" class="quad">③ 모멘텀만 — 추세 ↑ · 이익 약함</text>', f'<text x="{L+6}" y="{H-B-6}" class="quad">④ 회피</text>']
    placed = []
    show = {m["group"] for m in sorted(MT, key=lambda m: m["rank"])[:14]} | {m["group"] for m in MT if quad(m) == "기다림" and m["rank"] <= 25}
    for m in sorted(MT, key=lambda m: m["rank"]):
        X, Y = cx(m["opg"]), cy(m["score"]); lead = quad(m) == "리더"
        g.append(f'<circle cx="{X:.1f}" cy="{Y:.1f}" r="{4 + min(10, m["n"]/3):.1f}" class="{"dot hot" if lead else "dot"}"><title>{E(m["group"])} · 강도 {m["score"]}({m["rank"]}위) · 올해 영업이익 {pc(m["opg"])} · PER(E) {m.get("per")}</title></circle>')
        if m["group"] in show:
            left = X > W - R - 110; ly = Y + 3
            txt = f"{m['group']} {m['rank']}위"; tw = len(txt) * 6.6
            x0, x1 = ((X - 8 - tw), X - 8) if left else (X + 8, X + 8 + tw)
            for _ in range(8):   # 글자 상자가 겹치면 아래로
                if any(abs(ly - py) < 12 and not (x1 < a0 or x0 > a1) for a0, a1, py in placed):
                    ly += 12
            placed.append((x0, x1, ly))
            g.append(f'<text x="{(X-8) if left else (X+8):.1f}" y="{ly:.1f}" class="lbl{" hotl" if lead else ""}" text-anchor="{"end" if left else "start"}">{E(m["group"])} {m["rank"]}위</text>')
    return f'<svg viewBox="0 0 {W} {H}" class="chart" role="img" aria-label="업종 테크노펀더멘탈 지도">{"".join(g)}</svg>'


def chart_quarters(q):
    if not q:
        return ""
    W, H, L, R, T, B = 640, 200, 30, 20, 20, 26
    n = len(q); bw = (W - L - R) / n; mxo = max([x[2] or 0 for x in q] + [1]) * 1.7
    om = [x[3] for x in q if x[3] is not None]; mxm = (max(om) if om else 1) * 1.35 or 1
    g = []
    for i, (p, s_, o, _) in enumerate(q):
        x0 = L + i * bw; hh = max(0, o or 0) / mxo * (H - T - B)
        g.append(f'<rect x="{x0+bw*.25:.1f}" y="{H-B-hh:.1f}" width="{bw*.5:.1f}" height="{hh:.1f}" class="bo"/><text x="{x0+bw/2:.1f}" y="{H-B-hh-4:.1f}" class="vl" text-anchor="middle">{w(o)}억</text><text x="{x0+bw/2:.1f}" y="{H-8}" class="ax" text-anchor="middle">{p[2:4]}.{int(p[5:7])//3}Q</text>')
    pts = [(L + i * bw + bw / 2, T + (1 - (x[3] or 0) / mxm) * (H - T - B) * .32) for i, x in enumerate(q)]
    g.append('<polyline points="' + " ".join(f"{a:.1f},{b:.1f}" for a, b in pts) + '" fill="none" stroke="var(--up)" stroke-width="1.8"/>')
    g += [f'<circle cx="{a:.1f}" cy="{b:.1f}" r="2.6" fill="var(--up)"/><text x="{a:.1f}" y="{b-6:.1f}" class="vl up" text-anchor="middle">{(x[3] or 0):.1f}%</text>' for (a, b), x in zip(pts, q)]
    return f'<svg viewBox="0 0 {W} {H}" class="chart" role="img" aria-label="분기 영업이익">{"".join(g)}</svg>'


CSS = """
.tfr{font-family:var(--f-body);line-height:1.7;color:var(--ink);word-break:keep-all;overflow-wrap:anywhere}
.tfr .page{background:var(--paper);border:1px solid var(--rule);padding:26px 30px;margin:0 0 22px}
.tfr .mast{display:flex;justify-content:space-between;align-items:baseline;gap:12px;border-bottom:3px solid var(--acc);padding-bottom:6px;margin-bottom:16px;flex-wrap:wrap}
.tfr .mast h2{font-size:13px!important;letter-spacing:.08em;color:var(--acc);margin:0!important;font-weight:700}.tfr .mast h2 i{font-style:normal;color:var(--ink3);margin-right:6px}.tfr .mast span{font-size:12px;color:var(--ink3)}
.tfr h1.tt{font-family:var(--f-disp);font-size:27px!important;line-height:1.4;margin:4px 0 10px!important;text-wrap:balance;font-weight:800}
.tfr .sub{color:var(--ink2);font-size:14.5px;max-width:70ch;margin:0}
.tfr .flow{display:flex;flex-wrap:wrap;gap:4px;align-items:center;font-size:12px;color:var(--ink2);margin:10px 0 2px}.tfr .flow span{border:1px solid var(--rule);padding:2px 8px;border-radius:3px}.tfr .flow span.on{border-color:var(--acc);color:var(--acc);font-weight:600}
.tfr .kpis{display:grid;grid-template-columns:repeat(5,minmax(0,1fr));border:1px solid var(--rule);margin:12px 0}
.tfr .kpis div{padding:10px 12px;border-right:1px solid var(--rule)}.tfr .kpis div:last-child{border-right:0}.tfr .kpis span{display:block;font-size:11px;color:var(--ink3)}.tfr .kpis b{font-family:var(--f-num);font-size:16px}.tfr .kpis small{display:block;font-size:11px;color:var(--ink3)}
.tfr .cover,.tfr .sec{display:grid;grid-template-columns:230px minmax(0,1fr);gap:26px}
.tfr .side{font-size:12.5px}.tfr .cover .side{border-right:1px solid var(--rule);padding-right:18px}
.tfr .sec .side{border-top:2px solid var(--ink);padding-top:10px}.tfr .sec .main{border-top:2px solid var(--ink);padding-top:10px;min-width:0}
.tfr .side h4{font-size:11px;letter-spacing:.1em;color:var(--acc);margin:0 0 6px}
.tfr .side p{margin:0 0 10px;color:var(--ink2)}.tfr .side dl{display:grid;grid-template-columns:1fr auto;gap:4px 8px;margin:0 0 14px}.tfr .side dt{color:var(--ink3)}.tfr .side dd{margin:0;text-align:right}
.tfr .cmp{border:1px solid var(--line);border-left:4px solid var(--warn);padding:10px 14px;margin:0 0 14px;font-size:13px}.tfr .cmp>div{margin-top:4px}.tfr .cmp table{margin-top:6px}
.tfr .call{background:var(--acc2);border-left:4px solid var(--acc);padding:12px 16px;margin:0 0 14px}.tfr .call b{display:block;font-size:12px;letter-spacing:.08em;color:var(--acc);margin-bottom:4px}
.tfr .fig{margin:10px 0 4px}.tfr .fig .ft{font-size:12.5px;font-weight:600;margin-bottom:2px}.tfr .fig .ft span{color:var(--acc);margin-right:6px}
.tfr .src{font-size:11px;color:var(--ink3);margin-top:2px}
.tfr .chart{width:100%;height:auto;display:block;max-width:760px}.tfr .chart .grid{stroke:var(--rule);stroke-width:.6}.tfr .chart .basel{stroke:var(--ink3);stroke-width:.8;stroke-dasharray:3 3}
.tfr .chart .ax{font-size:10.5px;fill:var(--ink3);font-family:var(--f-num)}.tfr .chart .lbl{font-size:11px;fill:var(--ink2)}.tfr .chart .hotl{fill:var(--acc);font-weight:700}
.tfr .chart .quad{font-size:10.5px;fill:var(--ink3)}.tfr .chart .dot{fill:var(--ink3);fill-opacity:.28;stroke:var(--ink3);stroke-width:.8}.tfr .chart .dot.hot{fill:var(--acc);fill-opacity:.55;stroke:var(--acc)}
.tfr .chart .bo{fill:var(--acc)}.tfr .chart .vl{font-size:10px;fill:var(--ink2);font-family:var(--f-num)}.tfr .chart .vl.up{fill:var(--up)}
.tfr .leg{font-size:11.5px;color:var(--ink2);display:flex;gap:14px;flex-wrap:wrap}.tfr .leg i{display:inline-block;width:14px;height:3px;vertical-align:middle;margin-right:4px}
.tfr .tw{overflow-x:auto;margin:6px 0}
.tfr table{border-collapse:collapse;width:100%;font-size:12.5px;font-variant-numeric:tabular-nums}
.tfr th{font-size:11px;color:var(--ink3);font-weight:500;text-align:right;padding:5px 6px;border-bottom:1.5px solid var(--ink);white-space:nowrap;background:none}
.tfr td{text-align:right;padding:5px 6px;border-bottom:1px solid var(--rule);white-space:nowrap}.tfr th.l,.tfr td.l{text-align:left}.tfr td small{color:var(--ink3)}.tfr td.wrap{white-space:normal;min-width:220px}
.tfr tr.rdy td{background:var(--acc2)}.tfr td.near{color:var(--acc);font-weight:700}
.tfr .up{color:var(--up)}.tfr .dn{color:var(--dn)}
.tfr .tag{font-size:11px;padding:1px 7px;border-radius:3px;border:1px solid var(--rule);white-space:nowrap}.tfr .tag.pos{color:var(--acc);border-color:var(--acc)}.tfr .tag.neg{color:var(--dn);border-color:var(--dn)}.tfr .tag.neu{color:var(--ink2)}.tfr .tag.warn{color:var(--warn);border-color:var(--warn)}
.tfr .two{display:grid;grid-template-columns:minmax(0,1fr) minmax(0,1fr);gap:20px}
.tfr .box{border:1px solid var(--rule);padding:12px 14px}.tfr .box h4{margin:0 0 6px;font-size:13px}.tfr .box ul{margin:0;padding-left:18px}.tfr .box li{margin-bottom:4px}
.tfr .dots{display:inline-flex;gap:2px}.tfr .dots i{width:8px;height:8px;border-radius:50%;background:var(--rule);display:inline-block}.tfr .dots i.on{background:var(--acc)}
.tfr ol.keys{margin:0;padding-left:18px}.tfr ol.keys li{margin-bottom:6px}
.tfr .disc{font-size:11.5px;color:var(--ink3);line-height:1.6}
@media(max-width:760px){.tfr .page{padding:16px 14px}.tfr .cover,.tfr .sec,.tfr .two{grid-template-columns:minmax(0,1fr);gap:12px}.tfr .cover .side{border-right:0;padding-right:0}.tfr h1.tt{font-size:22px!important}.tfr .kpis{grid-template-columns:repeat(2,minmax(0,1fr))}.tfr .kpis div{border-bottom:1px solid var(--rule)}}
"""
TOKENS_PAGE = """:root{--bg:#f6f7f9;--paper:#fff;--ink:#16202c;--ink2:#3c4a5a;--ink3:#7c8796;--rule:#d9dee5;--acc:#0b5d6b;--acc2:#e3f0f1;--up:#c8323c;--dn:#2f5fb3;--warn:#a46a00;
--f-body:"IBM Plex Sans KR","Apple SD Gothic Neo","Malgun Gothic",system-ui,sans-serif;--f-disp:"Noto Serif KR","Nanum Myeongjo",serif;--f-num:"IBM Plex Mono",ui-monospace,monospace}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){--bg:#0e1319;--paper:#151c24;--ink:#e6ebf1;--ink2:#b5c0cc;--ink3:#7f8b98;--rule:#2a3542;--acc:#5fb7c4;--acc2:#16323a;--up:#ff6b6b;--dn:#6f9cff;--warn:#e0a63a;color-scheme:dark}}
:root[data-theme="dark"]{--bg:#0e1319;--paper:#151c24;--ink:#e6ebf1;--ink2:#b5c0cc;--ink3:#7f8b98;--rule:#2a3542;--acc:#5fb7c4;--acc2:#16323a;--up:#ff6b6b;--dn:#6f9cff;--warn:#e0a63a;color-scheme:dark}
body{background:var(--bg);color:var(--ink);margin:0;padding-block:24px;padding-left:max(16px,env(safe-area-inset-left,0px));padding-right:max(16px,env(safe-area-inset-right,0px))}.tfr{max-width:980px;margin:0 auto}"""
# 웹(Balance Lab) 안에서는 앱 색 토큰을 그대로 따른다
TOKENS_WEB = """.tfr{--paper:var(--panel);--ink:var(--fg);--ink2:var(--muted);--ink3:var(--faint);--rule:var(--line);--acc:var(--accent);--acc2:var(--accent-soft);--dn:var(--down);--warn:var(--warn,#b45309);
--f-body:inherit;--f-disp:inherit;--f-num:ui-monospace,SFMono-Regular,Menlo,monospace}"""


def compare(P):
    """지난 호 대비 (3차 2026-11-14): 국면 · 업종 사분면 변화 · 핵심 후보 들어옴/빠짐 · 지난 호 핵심 후보 1주 성적 vs 코스피. 숫자만(토큰 0)"""
    prev = [f for f in sorted(TF.glob("prep_*.json")) if f.stem[5:] < P["date"]]
    if not prev:
        return {"first": True}
    Q = _j(prev[-1])
    okm = lambda m: m.get("opg") is not None and (m.get("n_fund") or 0) >= 3  # noqa: E731
    pm = {m["group"]: m for m in Q.get("matrix") or [] if okm(m)}
    sec = []
    for m in sorted(P["matrix"], key=lambda m: m["rank"]):
        if not okm(m):
            continue
        o = pm.get(m["group"]); qn = quad(m); qo = quad(o) if o else None
        if qo != qn and (qn in ("리더", "모멘텀만") or qo in ("리더", "모멘텀만")):
            sec.append({"group": m["group"], "before": qo or "—", "now": qn, "rank_before": o["rank"] if o else None, "rank": m["rank"]})
    core_now = {b["code"]: b["name"] for b in P["board"] if cat(b)[0] == 0}
    core_old = {b["code"]: b for b in Q.get("board") or [] if cat(b)[0] == 0}
    now_px = {b["code"]: b.get("close") for b in P["board"]}
    perf = []
    for c, b in core_old.items():
        px = now_px.get(c)
        if px is None:
            rows = (_j(DATA / "cache" / "daily" / f"{c}.json", {}) or {}).get("rows") or []
            px = rows[-1]["close"] if rows else None
        if px and b.get("close"):
            perf.append({"name": b["name"], "ret": round((px / b["close"] - 1) * 100, 1)})
    k0, k1 = Q["regime"].get("close"), P["regime"].get("close")
    l0, _ = light(Q); l1, _ = light(P)
    return {"first": False, "prev_date": Q["date"], "light": [l0, l1], "dist": [len(Q["regime"]["dist_days"]), len(P["regime"]["dist_days"])],
            "sectors": sec[:8], "core_in": [core_now[c] for c in core_now if c not in core_old], "core_out": [b["name"] for c, b in core_old.items() if c not in core_now],
            "core_perf": sorted(perf, key=lambda x: -x["ret"]), "kospi_ret": round((k1 / k0 - 1) * 100, 1) if k0 and k1 else None}


def compare_html(P, core):
    C = compare(P)
    if C["first"]:
        return ('<div class="cmp"><b>지난 호 대비</b> <small>이번 호가 첫 호입니다. 다음 호부터 국면·업종 위치·핵심 후보 변화와 지난 호 핵심 후보의 1주 성적을 여기에 자동으로 적습니다.</small>'
                f'<div><small>🆕 핵심 후보: {E(", ".join(b["name"] for b in core) or "없음")}</small></div></div>')
    qc = {"리더": "pos", "모멘텀만": "warn", "기다림": "neu", "회피": "neg", "—": "neu"}
    rows = "".join(f'<tr><td class="l">{E(x["group"])}</td><td><span class="tag {qc[x["before"]]}">{E(x["before"])}</span></td><td>→</td><td><span class="tag {qc[x["now"]]}"><b>{E(x["now"])}</b></span></td>'
                   f'<td>{x["rank_before"] or "-"}위 → {x["rank"]}위</td></tr>' for x in C["sectors"])
    avg = round(sum(x["ret"] for x in C["core_perf"]) / len(C["core_perf"]), 1) if C["core_perf"] else None
    perf = " · ".join(f'{E(x["name"])} <span class="{cls(x["ret"])}">{pc(x["ret"])}</span>' for x in C["core_perf"][:6])
    return (f'<div class="cmp"><b>지난 호({E(C["prev_date"][5:].replace("-", "/"))}) 대비</b>'
            f'<div><small>국면 {C["light"][0]} → <b>{C["light"][1]}</b> · 분산일 {C["dist"][0]} → <b>{C["dist"][1]}</b> · 코스피 1주 {pc(C["kospi_ret"])}</small></div>'
            + (f'<div class="tw"><table><thead><tr><th class="l">업종</th><th>지난 호</th><th></th><th>이번 호</th><th>강도 순위</th></tr></thead><tbody>{rows}</tbody></table></div>' if rows else '<div><small>업종 위치(리더·모멘텀만) 변화 없음</small></div>')
            + f'<div><small>🎯 핵심 후보 🆕 들어옴: {E(", ".join(C["core_in"]) or "없음")} · ➖ 빠짐: {E(", ".join(C["core_out"]) or "없음")}</small></div>'
            + (f'<div><small>지난 호 핵심 후보 1주: 평균 <b class="{cls(avg)}">{pc(avg)}</b> (코스피 {pc(C["kospi_ret"])}) — {perf}</small></div>' if perf else "")
            + '</div>')


def body(P, N):
    lt, ltc = light(P)
    MT = [m for m in P["matrix"] if m.get("opg") is not None and (m.get("n_fund") or 0) >= 3]
    leaders = [m["group"] for m in sorted(MT, key=lambda m: m["rank"]) if quad(m) == "리더"]
    BD = sorted(P["board"], key=lambda b: (cat(b)[0], b["dist"] if b["dist"] is not None else 99))
    core = [b for b in BD if cat(b)[0] == 0]
    lb = P["breadth"][-1] if P["breadth"] else {"a50": 0, "a20": 0, "n": 0}
    first_low = min(P["breadth"][-20:], key=lambda b: b["a50"]) if P["breadth"] else lb
    DY = P["days"]; f5 = sum((d["f"] or 0) for d in DY[-5:]); i5 = sum((d["i"] or 0) for d in DY[-5:])
    dd = len(P["regime"]["dist_days"]); mk = P.get("market") or {}
    para = lambda L: "".join(f"<p>{x}</p>" for x in (L or []))  # noqa: E731  (해석 글은 Claude가 쓴 짧은 HTML 허용: <b>만)
    # 데스크 의견: narr가 없으면 업종 분류로
    desk = N.get("desk") or ([["시장 노출", {"빨강": "관찰", "노랑": "준비", "초록": "참여"}[lt], {"빨강": "neu", "노랑": "pos", "초록": "pos"}[lt]]]
                             + [[g, "리더", "pos"] for g in leaders[:3]] + [[m["group"], "모멘텀만", "warn"] for m in sorted(MT, key=lambda m: m["rank"]) if quad(m) == "모멘텀만"][:2]
                             + [[m["group"], "기다림", "neu"] for m in sorted(MT, key=lambda m: m["rank"]) if quad(m) == "기다림"][:2])
    # 매크로 표
    mrow = []
    for m in P["macro"]:
        if "err" in m or not m.get("w1"):
            continue
        if m["sym"] == "^TNX":
            now = f'{m["now"]:.2f}%'; a = (m["now"] - m["w1"]) * 100; b = (m["now"] - m["m1"]) * 100; d1, dm = f"{a:+.0f}bp", f"{b:+.0f}bp"
        else:
            now = w(m["now"], 2 if m["now"] < 1000 else 0); a = (m["now"] / m["w1"] - 1) * 100; b = (m["now"] / m["m1"] - 1) * 100; d1, dm = pc(a), pc(b)
        mrow.append(f'<tr><td class="l">{E(m["name"])}</td><td><b>{now}</b></td><td class="{cls(a)}">{d1}</td><td class="{cls(b)}">{dm}</td></tr>')
    impl = "".join(f'<tr><td class="l">{E(a)}</td><td><span class="tag {c}">{E(b)}</span></td><td class="l wrap">{E(t)}</td></tr>' for a, b, t, c in N.get("impl") or [])
    # 수급 업종
    FS = sorted(P["flow_sectors"], key=lambda s: -((s["f5"] or 0) + (s["i5"] or 0)))
    frow = lambda L: "".join(f'<tr><td class="l">{E(s["group"])}</td><td class="{cls(s["f5"])}">{eok(s["f5"])}</td><td class="{cls(s["i5"])}">{eok(s["i5"])}</td><td class="{cls(s.get("r5"))}">{pc(s.get("r5"))}</td></tr>' for s in L)  # noqa: E731
    # 업종 표
    srt = sorted(P["matrix"], key=lambda m: m["rank"])
    pick = srt[:12] + [m for m in srt[12:] if quad(m) == "기다림" and m["rank"] <= 30][:3]
    srow = []
    for m in pick:
        ch = (m["rank4"] - m["rank"]) if m.get("rank4") else None
        q = quad(m); qc = {"리더": "pos", "모멘텀만": "warn", "기다림": "neu", "회피": "neg"}[q]
        srow.append(f'<tr><td>{m["rank"]}</td><td class="l"><b>{E(m["group"])}</b></td><td class="{cls(ch)}">{("▲" + str(ch)) if ch and ch > 0 else (("▼" + str(-ch)) if ch and ch < 0 else "-")}</td><td>{m["score"]}</td><td>{m["breadth"]}%</td>'
                    f'<td>{gtxt(m.get("opg"))}</td><td>{m.get("per") or "-"}</td><td class="{cls(m.get("f5"))}">{eok(m.get("f5"))}</td><td class="{cls(m.get("i5"))}">{eok(m.get("i5"))}</td><td><span class="tag {qc}">{q}</span></td></tr>')
    # 종목 보드
    rank_now = {m["group"]: m["rank"] for m in P["matrix"]}
    dots = lambda k: "".join(f'<i class="{"on" if i < k else ""}"></i>' for i in range(3))  # noqa: E731
    brow = []
    for b in [x for x in BD if x["list"] == "watch"]:
        c0, cn, cc = cat(b); f = b["fs"] or {}
        brow.append(f'<tr class="{"rdy" if c0 == 0 else ""}"><td class="l"><b class="stk">{E(b["name"])}</b>{" 🎯" if b["pool"] else ""}<br><small>{E(b["group"])} · {rank_now.get(b["group"], "-")}위</small></td><td><span class="tag {cc}">{cn}</span></td>'
                    f'<td title="{E(" / ".join(f.get("why") or ["조건 없음"]))}"><span class="dots">{dots(f.get("pts", 0))}</span></td><td><span class="dots">{dots(b["tech"])}</span></td>'
                    f'<td>{gtxt(f.get("yoy"))}</td><td>{gtxt(f.get("opg"))}</td><td>{f.get("per") or "-"}</td><td>{b["rs"]}</td><td><b>{w(b["breakout"])}</b></td>'
                    f'<td class="{"near" if b["dist"] is not None and b["dist"] <= 5 else ""}">{"-" if b["dist"] is None else f"{b["dist"]:.1f}%"}</td><td>{w(b["stop"])}</td><td>{b["qty"] or "-"}주</td>'
                    f'<td>{b["base_days"] or "-"}일·{(b["depth"] or 0):.0f}%</td><td class="{"up" if b["ia"] == "동반 상승" else "dn"}">{"동행" if b["ia"] == "동반 상승" else "나 홀로"}</td><td class="l"><small>{E(b["event"] or "")} {E(", ".join(b["missing"]))}{" 베이스 짧고 얕음(확인 필요)" if (b["base_days"] or 99) < 10 and (b["depth"] or 99) < 3 else ""}</small></td></tr>')
    runrow = "".join(f'<tr><td class="l"><b class="stk">{E(b["name"])}</b>{" 🎯" if b["pool"] else ""}<br><small>{E(b["group"])}</small></td><td>{b["rs"]}</td><td><span class="dots">{dots((b["fs"] or {}).get("pts", 0))}</span></td><td class="up">{pc(b["r1m"])}</td><td>{pc(b["gap20"])}</td>'
                     f'<td class="l"><small>{"20일선과 멀어 추격 위험 · 첫 눌림 뒤 새 베이스 대기" if (b["gap20"] or 0) > 10 else "20일선 근처 · 새 베이스가 생기는지 확인"}</small></td></tr>' for b in BD if b["list"] == "running")
    # 심층
    deep = next((b for b in BD if b["code"] == N.get("deep_code")), core[0] if core else None)
    deep_html = ""
    if deep:
        f = deep["fs"] or {}
        side = N.get("deep_side") or [f"<b>{E(deep['group'])} · RS {deep['rs']} · 펀더 {f.get('pts', 0)}/3 · 기술 {deep['tech']}/3</b>",
                                      "근거: " + E(" · ".join(f.get("why") or [])) + ".",
                                      f"트리거: 기준가 {w(deep['breakout'])}원(현재 {w(deep['close'])}원, {deep['dist']}% 아래), 베이스 {deep['base_days']}일·{(deep['depth'] or 0):.0f}%, 업종 {'동행' if deep['ia'] == '동반 상승' else '나 홀로'}입니다."]
        deep_html = f'''<section class="sec" style="margin-top:16px"><aside class="side"><h4>심층 · {E(deep["name"])}</h4>{para(side)}</aside>
   <div class="main"><div class="fig"><div class="ft"><span>그림 5</span>{E(deep["name"])} 분기 영업이익(억 원)과 영업이익률</div>{chart_quarters(f.get("q"))}<div class="src">출처: 네이버 재무(비공식) · 실제 발표 분기</div></div>'''
    warns = N.get("warns") or {}
    wrow = []
    for code, note in warns.items():
        b = next((x for x in P["board"] if x["code"] == code), None)
        if not b:
            continue
        f = b["fs"] or {}
        note = note or f"펀더 {f.get('pts', 0)}/3 — 최근 분기 영업이익 {gtxt(f.get('yoy'))}, 올해(E) {gtxt(f.get('opg'))}. 기술 조건은 {'충족에 가까움' if b['tech'] >= 2 else '1단계 상승 중'}"
        wrow.append(f'<tr><td class="l"><b class="stk">{E(b["name"])}</b></td><td>{gtxt(f.get("yoy"))}</td><td>{gtxt(f.get("opg"))}</td><td class="l wrap"><small>{note}</small></td></tr>')
    if deep_html:
        deep_html += (f'<h3 style="font-size:14px;margin:14px 0 4px">기술은 좋지만 펀더가 받쳐 주지 않는 종목 — 주의</h3><div class="tw"><table><thead><tr><th class="l">종목</th><th>최근 분기</th><th>올해(E)</th><th class="l">왜 주의하나</th></tr></thead><tbody>{"".join(wrow)}</tbody></table></div>'
                      '<div class="src">규칙상 진입은 가능해도, 테크노펀더 기준으로는 펀더가 확인될 때까지 우선순위를 낮춥니다(규칙 변경 아님, 순서만)</div>' if wrow else "") + "</div></section>"
    pos_rows = "".join(f'<tr><td class="l"><b class="stk">{E(p["name"])}</b></td><td class="{cls(p["r"])}"><b>{p["r"]:+.2f}R</b></td><td>{w(p["price"])}</td><td>{w(p["stop"])} <small>({pc(p["to_stop"])})</small></td><td>{w(p["r3"])} <small>({pc(p["to3"])})</small></td><td>{w(p["ma20"])} <small>({pc(p["to_ma20"])})</small></td>'
                       f'<td class="l wrap"><small>{"3R 도달 시 절반 익절 + 손절가 본전, 이후 20일선 종가 이탈까지 보유" if (p["r"] or 0) > 0 else "손절가 유지"}</small></td></tr>' for p in P["positions"])
    RV = P.get("review") or {}
    avgL = abs(RV.get("expectancy_r") or 1) if not RV.get("win_rate") else 1.0
    scen = "".join(f'<li><b class="{"up" if s.get("name") == "강세" else "dn" if s.get("name") == "약세" else ""}">{E(s.get("name", ""))} {E(str(s.get("prob", "")))}</b> {E(s.get("trigger", ""))} → {E(s.get("implication", ""))}</li>' for s in N.get("scenarios") or [])
    ev = "".join(f"<li>{E(x)}</li>" for x in N.get("events") or [])
    asof = P["regime"]["date"]
    return f'''<div class="tfr">
<article class="page">
 <div class="mast"><h2 data-tl="📄 요약">BALANCE LAB · 테크노펀더멘탈 주간</h2><span>{E(P["date"])} 발간 · 시세 {md(asof)} 종가 · 작성 {E(P["made_at"])}</span></div>
 <h1 class="tt">{E(N.get("title", ""))}</h1>
 <p class="sub">{N.get("sub", "")}</p>
 <div class="flow"><span>매크로</span>→<span>시황·국면</span>→<span>수급</span>→<span>업종</span>→<span class="on">종목(펀더 필터 → 기술 트리거)</span>→<span>보유·성적</span></div>
 <div class="kpis">
  <div><span>매크로</span><b>{E(N.get("macro_view", "중립"))}</b><small>{E(N.get("macro_note", "금리·환율·유가·반도체·VIX"))}</small></div>
  <div><span>국면</span><b class="{ {"neg": "dn", "pos": "up"}.get(ltc, "")}">{lt}</b><small>분산일 {dd} · 50일선 위 {lb["a50"]:.0f}%</small></div>
  <div><span>외국인 5일</span><b class="{cls(f5)}">{f5/10000:+.2f}조</b><small>기관 {i5/10000:+.2f}조 (코스피)</small></div>
  <div><span>리더 업종</span><b style="font-size:13.5px">{E(N.get("leaders_label") or "·".join(leaders[:3]) or "없음")}</b><small>이익 +{XQ}%↑ + 강도 {YQ}↑</small></div>
  <div><span>핵심 후보</span><b>{len(core)}종목</b><small>펀더 2/3↑ + 기술 2/3↑</small></div>
 </div>
 {compare_html(P, core)}
 <div class="cover">
  <aside class="side"><h4>데스크 의견</h4><dl>{"".join(f'<dt>{E(a)}</dt><dd><span class="tag {c}">{E(b)}</span></dd>' for a, b, c in desk)}</dl>
   <h4>이번 주 할 일</h4><p>{" ".join(f"{"①②③④⑤"[i]} {E(t)}" for i, t in enumerate((N.get("todo") or [])[:5]))}</p>
   <h4>작성</h4><p>Balance Lab 전략 데스크 (Claude) · 숫자: strategy_tf · fundamentals · screener · sector_radar</p></aside>
  <div style="min-width:0"><div class="call"><b>한 줄 결론</b>{N.get("call", "")}</div>
   <div class="fig"><div class="ft"><span>그림 1</span>업종 테크노펀더멘탈 지도 — 이익(가로) × 추세(세로)</div>{chart_matrix(P)}
    <div class="src">가로 = 업종 내 시총 2천억↑ 종목의 올해 영업이익 컨센서스 합 ÷ 작년 실제 합 − 1(+200%↑ 오른쪽 끝) · 세로 = 주도 섹터 레이더 점수({md(P.get("radar_as_of") or asof)}) · 원 크기 = 종목 수 · 컨센서스 있는 종목 3개↑ 업종만 · 출처: 네이버 재무·컨센서스(비공식)</div></div></div>
 </div>
</article>
<article class="page">
 <div class="mast"><h2 data-tl="🌐 매크로"><i>STEP 1</i>매크로</h2><span>어느 업종에 유리한가</span></div>
 <section class="sec"><aside class="side">{para(N.get("macro_side"))}</aside><div class="main">
  <div class="fig"><div class="ft"><span>표 1</span>글로벌 지표 — 지금 · 1주 · 1개월</div><div class="tw"><table><thead><tr><th class="l">지표</th><th>최근</th><th>1주</th><th>1개월</th></tr></thead><tbody>{"".join(mrow)}</tbody></table></div><div class="src">출처: Yahoo Finance(비공식, 지연 가능)</div></div>
  <div class="fig"><div class="ft"><span>표 2</span>매크로 → 업종 연결</div><div class="tw"><table><thead><tr><th class="l">변화</th><th>방향</th><th class="l">무엇에 영향</th></tr></thead><tbody>{impl}</tbody></table></div><div class="src">해석 = 데스크 의견(Claude)</div></div>
 </div></section>
</article>
<article class="page">
 <div class="mast"><h2 data-tl="🚦 시황·국면"><i>STEP 2</i>시황·국면</h2><span>신호등 {lt} · {E(P.get("regime_title") or "")}</span></div>
 <section class="sec"><aside class="side">{para(N.get("regime_side"))}</aside><div class="main">
  <div class="fig"><div class="ft"><span>그림 2</span>코스피 120거래일 · ▼ 분산일 · 점선 20일선</div>{chart_kospi(P)}<div class="src">분산일 = 종가 −0.2%↓ + 거래량 전날보다 많음(최근 25거래일 {dd}개) · 20일선 대비 {pc(P["regime"]["gap20"])} · 출처: 네이버 코스피 일봉(비공식)</div></div>
  <div class="fig"><div class="ft"><span>그림 3</span>시장 폭 — 50일선·20일선 위 종목 비율</div>{chart_breadth(P)}
   <div class="leg"><span><i style="background:var(--acc)"></i>50일선 위 {lb["a50"]:.0f}%</span><span><i style="background:var(--ink3)"></i>20일선 위 {lb["a20"]:.0f}%</span><span>20일 최저 {first_low["a50"]:.0f}%({md(first_low["date"])})</span></div><div class="src">시총 2천억↑ {lb["n"]}종목 · 출처: 네이버 일봉(비공식) 계산</div></div>
 </div></section>
</article>
<article class="page">
 <div class="mast"><h2 data-tl="💰 수급"><i>STEP 3</i>수급</h2><span>돈이 들어온 곳, 나간 곳</span></div>
 <section class="sec"><aside class="side">{para(N.get("flow_side"))}</aside><div class="main">
  <div class="fig"><div class="ft"><span>그림 4</span>코스피 투자자별 순매수(억 원) · 아래 = 그날 코스피 등락</div>{chart_flows(P)}
   <div class="leg"><span><i style="background:var(--acc)"></i>외국인</span><span><i style="background:var(--warn)"></i>기관</span><span><i style="background:var(--ink3)"></i>개인</span></div><div class="src">출처: 네이버 시황(비공식)</div></div>
  <div class="two"><div class="fig"><div class="ft"><span>표 3</span>5일 순매수 상위 업종(억)</div><div class="tw"><table><thead><tr><th class="l">업종</th><th>외국인</th><th>기관</th><th>5일</th></tr></thead><tbody>{frow(FS[:6])}</tbody></table></div></div>
   <div class="fig"><div class="ft"><span>표 4</span>5일 순매도 상위 업종(억)</div><div class="tw"><table><thead><tr><th class="l">업종</th><th>외국인</th><th>기관</th><th>5일</th></tr></thead><tbody>{frow(FS[-5:][::-1])}</tbody></table></div></div></div>
  <div class="src">{E(P.get("flows_src") or "")}</div>
 </div></section>
</article>
<article class="page">
 <div class="mast"><h2 data-tl="🏭 업종"><i>STEP 4</i>업종</h2><span>이익(펀더)과 강도(기술)가 겹치는 곳만 '리더'</span></div>
 <section class="sec"><aside class="side">{para(N.get("sector_side"))}</aside><div class="main">
  <div class="fig"><div class="ft"><span>표 5</span>업종 스코어 — 강도 상위 12 + 기다림 업종</div><div class="tw"><table><thead><tr><th>순위</th><th class="l">업종</th><th>4주</th><th>강도</th><th>20일선 위</th><th>올해 영업이익</th><th>PER(E)</th><th>외국인 5일</th><th>기관 5일</th><th>분류</th></tr></thead><tbody>{"".join(srow)}</tbody></table></div>
  <div class="src">강도 = 주도 섹터 레이더(상대 강도·20일선 위 비율·신고가 비율·거래대금) · 올해 영업이익·PER(E) = 네이버 컨센서스 업종 합(비공식) · 수급 = 시총 상위 300(억, 수량×종가 추정) · 분류: 이익 +{XQ}%↑ / 강도 {YQ}↑</div></div>
 </div></section>
</article>
<article class="page">
 <div class="mast"><h2 data-tl="🎯 종목"><i>STEP 5</i>종목 — 펀더 필터 → 기술 트리거</h2><span>감시 목록 {P["screener"].get("count") or "-"}종목 훑기 · 확정 신호 {P["screener"].get("signals", 0)}건 · {md(P["screener"].get("as_of") or asof)}</span></div>
 <p style="margin:0 0 6px;font-size:13px"><b>펀더 점수</b>(3): ① 최근 분기 영업이익 전년 대비 +20%↑ 또는 흑자전환 ② 영업이익률이 1년 전보다 높음 ③ 올해 영업이익 +20%↑(E, 없으면 최근 2분기 합). <b>기술 점수</b>(3): ① RS 80↑ ② 기준가 10% 안 + 빠진 조건 없음 ③ 업종 동행. 점에 마우스를 올리면 근거가 보입니다.</p>
 <div class="tw"><table><thead><tr><th class="l">종목 <small>업종·순위</small></th><th>분류</th><th>펀더</th><th>기술</th><th>최근 분기</th><th>올해(E)</th><th>PER(E)</th><th>RS</th><th>기준가</th><th>거리</th><th>손절가</th><th>1R 수량</th><th>베이스</th><th>업종</th><th class="l">일정·빠진 조건</th></tr></thead><tbody>{"".join(brow)}</tbody></table></div>
 <div class="src">최근 분기·올해(E) = 영업이익 증가율 · 손절가 = 기준가 −8% · 1R 수량 = 30만 원 ÷ (기준가 − 손절가) · 🎯 관찰 풀 · 출처: 감시 목록(screener.py), 네이버 재무·컨센서스(비공식)</div>
 {f'<h3 style="font-size:14px;margin:14px 0 4px">이미 달리는 주도주 — 베이스 없음, 추격하지 않고 첫 눌림을 기다립니다</h3><div class="tw"><table><thead><tr><th class="l">종목</th><th>RS</th><th>펀더</th><th>1개월</th><th>20일선과 거리</th><th class="l">어떻게 보나</th></tr></thead><tbody>{runrow}</tbody></table></div>' if runrow else ""}
 {deep_html}
</article>
<article class="page">
 <div class="mast"><h2 data-tl="💼 보유·성적"><i>STEP 6</i>보유 관리 · 성적표 · 일정</h2><span>추세는 끝까지 · 손실은 1R에서</span></div>
 <div class="tw"><table><thead><tr><th class="l">보유</th><th>R</th><th>현재가</th><th>손절가</th><th>3R 가격</th><th>20일선</th><th class="l">다음 행동</th></tr></thead><tbody>{pos_rows or '<tr><td class="l" colspan="7">보유 종목 없음</td></tr>'}</tbody></table></div>
 <div class="two" style="margin-top:14px">
  <div class="box"><h4>최근 매매 {RV.get("n", 0)}건 성적</h4><ul><li>승률 {RV.get("win_rate", "-")}% · 평균 <b>{(RV.get("expectancy_r") or 0):+.2f}R</b> · 합계 {(RV.get("sum_r") or 0):+.2f}R</li><li>연속 손절 {RV.get("current_loss_streak", 0)}건 · 평균 보유 {RV.get("avg_hold_days", "-")}일</li><li>손절가보다 더 잃은 경우 {RV.get("worse_than_stop", 0)}건 · 같은 날 몰아 산 날 {len(RV.get("same_day_clusters") or [])}번</li><li>승률 30%라면 이긴 매매가 평균 <b>{0.7*avgL/0.3:.1f}R</b>(손실 1R이면 2.3R)을 벌어야 본전</li></ul></div>
  <div class="box"><h4>다음 주 일정 · 시나리오</h4><ul>{ev}{scen}</ul></div>
 </div>
 <p class="disc" style="margin-top:16px">개인 투자 기록용입니다. 매수·매도 권유가 아니며 판단은 본인이 합니다. 기준가·손절가·수량은 고정된 매매 규칙(docs/rules.md, 2027-01-31까지)으로 계산한 숫자입니다. 펀더 점수는 순서를 정하는 참고이며 규칙을 바꾸지 않습니다. 시세·재무는 네이버·Yahoo(비공식), 채널 요약은 2차 자료입니다.</p>
</article>
</div>'''


def render(date=None):
    P = _j(TF / f"prep_{date}.json") if date else None
    if not P:
        fs = sorted(TF.glob("prep_*.json"))
        if not fs:
            raise SystemExit("prep 먼저 실행하세요")
        P = _j(fs[-1])
    N = auto_narr(P)
    user = _j(TF / f"narr_{P['date']}.json", {}) or {}
    N.update({k: v for k, v in user.items() if v not in (None, "", [], {})})
    b = body(P, N)
    page = ("<!doctype html><html lang=\"ko\"><head><meta charset=\"utf-8\"><meta name=\"viewport\" content=\"width=device-width,initial-scale=1,viewport-fit=cover\">"
            f"<title>테크노펀더멘탈 주간 {P['date']}</title><link rel=\"stylesheet\" href=\"https://fonts.googleapis.com/css2?family=IBM+Plex+Sans+KR:wght@400;600;700&family=Noto+Serif+KR:wght@800&family=IBM+Plex+Mono&display=swap\">"
            f"<style>{TOKENS_PAGE}{CSS}</style></head><body>{b}</body></html>")
    rep = ROOT / "reports" / P["date"]; rep.mkdir(parents=True, exist_ok=True)
    (rep / "strategy_tf.html").write_text(page, encoding="utf-8")
    out = {"date": P["date"], "made_at": P["made_at"], "title": N.get("title"), "narr": bool(user), "css": TOKENS_WEB + CSS, "html": b,
           "page": f"reports/{P['date']}/strategy_tf.html"}
    (TF / "latest.json").write_text(json.dumps(out, ensure_ascii=False), encoding="utf-8")
    return {"page": out["page"], "narr": bool(user), "title": out["title"], "core": [x["name"] for x in P["board"] if cat(x)[0] == 0]}


def tg(date=None):
    """토요일 텔레그램 요약(30줄 안팎, 2026-11-14 사용자 요청: 테크노펀더 지면 기준) → reports/날짜/strategy_tg.md"""
    fs = [TF / f"prep_{date}.json"] if date else sorted(TF.glob("prep_*.json"))
    P = _j(fs[-1]); N = auto_narr(P); N.update({k: v for k, v in (_j(TF / f"narr_{P['date']}.json", {}) or {}).items() if v not in (None, "", [], {})})
    import re
    plain = lambda t: re.sub(r"<[^>]+>", "", str(t or ""))  # noqa: E731
    lt, _ = light(P); lb = P["breadth"][-1] if P["breadth"] else {"a50": 0}
    DY = P["days"]; f5 = sum((d["f"] or 0) for d in DY[-5:]); i5 = sum((d["i"] or 0) for d in DY[-5:])
    MT = sorted([m for m in P["matrix"] if m.get("opg") is not None and (m.get("n_fund") or 0) >= 3], key=lambda m: m["rank"])
    byq = lambda q: ", ".join([f"{m['group']}({m['rank']}위)" for m in MT if quad(m) == q][:3]) or "없음"  # noqa: E731
    BD = sorted(P["board"], key=lambda b: (cat(b)[0], b["dist"] if b["dist"] is not None else 99))
    core = [b for b in BD if cat(b)[0] == 0]
    FS = sorted(P["flow_sectors"], key=lambda s: -((s["f5"] or 0) + (s["i5"] or 0)))
    L = [f"📊 테크노펀더 주간 전략 · {P['date'][5:].replace('-', '/')} (시세 {md(P['regime']['date'])} 종가)", "",
         f"💡 {plain(N.get('title'))}", f"→ {plain(N.get('call'))}", ""]
    C = compare(P)
    if not C["first"]:
        sx = ", ".join(f"{x['group']} {x['before']}→{x['now']}" for x in C["sectors"][:3]) or "업종 위치 변화 없음"
        L += [f"🔁 지난 호 대비: 국면 {C['light'][0]}→{C['light'][1]} · 분산일 {C['dist'][0]}→{C['dist'][1]} · {sx}",
              f"   핵심 후보 🆕 {', '.join(C['core_in'][:4]) or '없음'} / ➖ {', '.join(C['core_out'][:4]) or '없음'}", ""]
    L += [
         f"🌐 매크로: {N.get('macro_view', '중립')} — {N.get('macro_note', '')}"]
    L += [f"- {a}: {b}" for a, b, _t, _c in (N.get("impl") or [])[:3]]
    L += ["", f"🚦 국면: 신호등 {lt} · 분산일 {len(P['regime']['dist_days'])}개 · 50일선 위 종목 {lb['a50']:.0f}% · 20일선 대비 {pc(P['regime']['gap20'])}",
          f"💰 수급(코스피 5일): 외국인 {f5/10000:+.2f}조 · 기관 {i5/10000:+.2f}조 · 업종 순매수 상위 {', '.join(s['group'] for s in FS[:2])}", "",
          f"🏭 업종 (이익 × 추세)", f"- 리더: {byq('리더')}", f"- 모멘텀만: {byq('모멘텀만')}", f"- 기다림: {byq('기다림')}", "",
          f"🎯 핵심 후보 {len(core)}종목 (펀더 2/3↑ + 기술 2/3↑, 기준가까지)"]
    L += [f"- {b['name']} 기준가 {w(b['breakout'])}원 ({b['dist']:.1f}%) · 펀더 {(b['fs'] or {}).get('pts', 0)}/3 · 기술 {b['tech']}/3" for b in core[:5]]
    warns = N.get("warns") or {}
    if warns:
        nm = {b["code"]: b["name"] for b in P["board"]}
        L += ["", "⚠️ 기술만 좋고 펀더 미확인: " + ", ".join(nm.get(c, c) for c in warns)]
    if P["positions"]:
        L += ["", "💼 보유"] + [f"- ⭐{p['name']} {p['r']:+.2f}R · 3R {w(p['r3'])}원({pc(p['to3'])}) · 손절 {w(p['stop'])}원" for p in P["positions"]]
    if N.get("events"):
        L += ["", "📅 " + " / ".join(N["events"][:3])]
    L += ["", "자세히: Balance Lab › 전략 › 보고서", "출처: 네이버(비공식)·Yahoo·감시 목록 · 매수·매도 권유 아님 · 매매 규칙 2027-01-31까지 고정"]
    rep = ROOT / "reports" / P["date"]; rep.mkdir(parents=True, exist_ok=True)
    (rep / "strategy_tg.md").write_text("\n".join(L) + "\n", encoding="utf-8")
    return {"file": f"reports/{P['date']}/strategy_tg.md", "lines": len(L)}


def main():
    ap = argparse.ArgumentParser(description="테크노펀더멘탈 · 탑다운 주간 보고서 (숫자 토큰 0)")
    sp = ap.add_subparsers(dest="cmd", required=True)
    sp.add_parser("prep"); sp.add_parser("narr-template"); sp.add_parser("core")
    r = sp.add_parser("render"); r.add_argument("--date")
    t = sp.add_parser("tg"); t.add_argument("--date")
    a = ap.parse_args()
    if a.cmd == "prep":
        P = prep()
        print(json.dumps({"saved": f"data/strategy/tf/prep_{P['date']}.json", "core": [b["name"] for b in P["board"] if cat(b)[0] == 0],
                          "leaders": [m["group"] for m in P["matrix"] if m.get("opg") is not None and (m.get("n_fund") or 0) >= 3 and quad(m) == "리더"],
                          "light": light(P)[0], "dist_days": len(P["regime"]["dist_days"])}, ensure_ascii=False))
    elif a.cmd == "narr-template":
        fs = sorted(TF.glob("prep_*.json"))
        print(json.dumps(auto_narr(_j(fs[-1])), ensure_ascii=False, indent=1))
    elif a.cmd == "core":
        print(json.dumps(core_list(), ensure_ascii=False, indent=1))
    elif a.cmd == "tg":
        print(json.dumps(tg(a.date), ensure_ascii=False))
    else:
        print(json.dumps(render(a.date), ensure_ascii=False))


if __name__ == "__main__":
    main()
