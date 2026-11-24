#!/usr/bin/env python3
"""테크노펀더멘탈 · 탑다운 주간 보고서 (2026-11-14 사용자 확정 형식).

흐름: 매크로 → 시황·국면 → 수급 → 업종(이익 × 추세) → 종목(펀더 필터 → 기술 트리거) → 보유·성적
숫자·그림·점수는 이 도구가 만든다(토큰 0). 해석 글(narrative)은 /strategy-report 가 data/strategy/tf/narr_날짜.json 에
쓰고, 없으면 숫자로 만든 기본 문장을 쓴다.

  python3 tools/strategy_tf.py prep              # 숫자 모으기 → data/strategy/tf/prep_날짜.json (+ 해석 칸 기본값 출력)
  python3 tools/strategy_tf.py narr-template     # 해석 JSON 기본값(자동 문장) 출력 → Claude가 고쳐서 narr_날짜.json 으로 저장
  python3 tools/strategy_tf.py tg                # 토요일 텔레그램 요약 → reports/날짜/strategy_tg.md
  python3 tools/strategy_tf.py render            # prep + narr → reports/날짜/strategy_tf.html + data/strategy/tf/latest.json(웹 조각)

펀더 점수(2026-11-24): 이익(다음 분기 영업이익 추정 +20%↑/흑자전환) · EPS(올해 추정 증가) · 기대(올해 영업이익 추정치 한 달 전보다 상향) = 추정 점수 3점. 컨센서스 없으면 발표 점수 2점. 핵심 후보에서 빼는 것은 펀더 0점(추정·발표 모두)
기술 점수(3): RS 80↑ · 기준가 10% 안 + 빠진 조건 없음 · 업종 동행(인더스트리 액션)
펀더 점수는 순서를 정하는 참고다. 매매 규칙(docs/rules.md)은 2027-01-31까지 고정. 주문 기능 없음.
"""
import argparse, glob, html, json, re, subprocess, sys
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import CACHE, DATA, ROOT  # noqa: E402
from strategy_prep import KST  # noqa: E402

TF = DATA / "strategy" / "tf"
E = html.escape
MACRO = [("^GSPC", "S&P 500"), ("^IXIC", "나스닥"), ("^SOX", "필라델피아 반도체"), ("^TNX", "미 10년물 금리"), ("DX-Y.NYB", "달러인덱스"), ("KRW=X", "원/달러"), ("CL=F", "WTI 원유"), ("^VIX", "VIX"),
         ("^N225", "일본 닛케이225"), ("000001.SS", "중국 상해종합"), ("^TWII", "대만 가권"), ("EWY", "EWY(한국 ETF)")]   # 2026-11-15 나스닥·달러·일본·중국·대만 추가
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
            j = json.loads(subprocess.run([sys.executable, str(ROOT / "tools" / "us_quote.py"), "daily", "--symbol", sym, "--days", "90"],
                                          capture_output=True, text=True, timeout=60).stdout)
            rows = [r for r in j["results"][0]["rows"] if r.get("close") is not None]
            c = [r["close"] for r in rows]
            out.append({"sym": sym, "name": nm, "now": c[-1], "w1": c[-6] if len(c) > 5 else None, "m1": c[-22] if len(c) > 22 else c[0], "date": rows[-1]["date"],
                        "c60": [round(x, 4) for x in c[-60:]]})   # 60일 일봉 종가 = 추이 미니 차트 · 60일 위치 (2026-11-15)
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


_REV = {}


def _rev(code, fa):
    """올해 영업이익 추정치가 한 달쯤 전(25일 넘게 지난 가장 가까운 기록)보다 얼마나 바뀌었나(%). 기록: 날마다 쌓는 data/cache/fund/_est.json 먼저, 없으면 월말 기록 data/consensus/hist.json."""
    if not fa or not fa.get("op") or fa["op"] <= 0:
        return None
    if not _REV:
        _REV["est"] = _j(CACHE / "fund" / "_est.json", {}) or {}
        _REV["hist"] = _j(DATA / "consensus" / "hist.json", {}) or {}
    now = datetime.now(KST)
    cut = (now - timedelta(days=25)).strftime("%Y-%m-%d")
    base = None
    e = _REV["est"].get(code) or {}
    old = [d for d in sorted(e) if d <= cut and e[d][0] == fa["p"] and e[d][2]]
    if old:
        base = (old[-1], e[old[-1]][2])
    else:
        s = (_REV["hist"].get(code) or {}).get(fa["p"][:4])
        if s:
            k = [i for i, d in enumerate(s["d"]) if d <= cut.replace("-", "") and s["op"][i]]
            if k:
                d = s["d"][k[-1]]
                base = (f"{d[:4]}-{d[4:6]}-{d[6:]}", s["op"][k[-1]])
    if not base or base[1] <= 0 or base[0] < (now - timedelta(days=70)).strftime("%Y-%m-%d"):
        return None
    return {"from": base[0], "pct": round((fa["op"] / base[1] - 1) * 100, 1)}


def fscore(d, px):
    """펀더 점수 (2026-11-24 사용자 확정, 표시·순서용 — 매매 규칙 아님). 서로 다른 것을 묻는 세 항목:
      이익 = 다음 분기 영업이익 추정치가 1년 전 같은 분기보다 +20%↑(또는 흑자 전환)
      EPS  = 올해 EPS 추정치가 작년보다 증가
      기대 = 올해 영업이익 추정치가 한 달 전보다 상향(+0.5%↑)
    type "E"(추정 점수, 3점 만점) = 다음 분기 컨센서스가 있는 종목. 없으면 type "A"(발표 점수, 2점 만점: 최근 발표 분기의 영업이익 +20%↑ · EPS 증가) — 참고용이고 감점하지 않는다.
    근거(10년·21개월 비교 자료, docs/decisions.md 2026-11-24): 지난 실적 점수는 신호 성적을 못 가름 · 진짜 컨센서스로는 0점만 뚜렷이 나쁨 · 컨센서스 없는 종목은 나쁘지 않음 → 점수 높낮이로 줄 세우지 않고, 핵심 후보에서 빼는 것은 펀더 0점뿐(fok — 추정·발표 모두, 2026-11-24 사용자 확정)."""
    if not d:
        return None
    Qa = [q for q in d.get("quarter") or [] if q.get("op") is not None]
    Q = [q for q in Qa if not q["e"]]
    est = next((q for q in Qa if q["e"]), None)
    fa, la = _fa_la(d)
    yago = lambda q: next((x for x in Qa if x["p"] == str(int(q["p"][:4]) - 1) + q["p"][4:]), None)  # noqa: E731

    def grow(cur, tag):
        base = yago(cur)
        if not base:
            return None, "1년 전 분기 자료 없음", None
        if base["op"] <= 0 < cur["op"]:
            return True, f"{cur['p']} 영업이익 흑자 전환 ({tag})", "흑전"
        if base["op"] > 0:
            g = round((cur["op"] / base["op"] - 1) * 100)
            return g >= 20, f"{cur['p']} 영업이익 {g:+d}% ({tag})", g
        return False, f"{cur['p']} 영업이익 적자 ({tag})", None
    items, yoy, opg = [], None, None
    if Q:
        _, _, yoy = grow(Q[-1], "발표")
    if fa and la and fa.get("op") is not None and la.get("op") is not None:
        opg = "흑전" if la["op"] <= 0 < fa["op"] else round((fa["op"] / la["op"] - 1) * 100) if la["op"] > 0 else None
    if est:
        ok, t, _ = grow(est, "추정")
        items.append({"k": "이익", "ok": ok, "t": t})
        if fa and la and fa.get("eps") is not None and la.get("eps") is not None:
            items.append({"k": "EPS", "ok": bool(fa["eps"] > la["eps"] and fa["eps"] > 0), "t": f"올해 EPS {la['eps']:,.0f} → {fa['eps']:,.0f}원 (추정)"})
        else:
            items.append({"k": "EPS", "ok": None, "t": "올해 EPS 추정치 없음"})
        rv = _rev(d.get("code"), fa)
        if rv:
            items.append({"k": "기대", "ok": rv["pct"] >= 0.5, "t": f"올해 영업이익 추정치 {rv['from'][5:].replace('-', '/')}보다 {rv['pct']:+.1f}%"})
        else:
            items.append({"k": "기대", "ok": None, "t": "추정치 변화 기록 없음"})
        typ = "E"
    else:
        typ = "A"
        if Q:
            ok, t, _ = grow(Q[-1], "발표")
            items.append({"k": "이익", "ok": ok, "t": t})
            b = yago(Q[-1])
            if b and Q[-1].get("eps") is not None and b.get("eps") is not None:
                items.append({"k": "EPS", "ok": bool(Q[-1]["eps"] > b["eps"] and Q[-1]["eps"] > 0), "t": f"{Q[-1]['p']} 분기 EPS {b['eps']:,.0f} → {Q[-1]['eps']:,.0f}원 (발표)"})
            else:
                items.append({"k": "EPS", "ok": None, "t": "EPS 자료 없음"})
        else:
            items += [{"k": "이익", "ok": None, "t": "실적 자료 없음"}, {"k": "EPS", "ok": None, "t": "EPS 자료 없음"}]
    pts = sum(1 for i in items if i["ok"])
    per = px / fa["eps"] if fa and fa.get("eps") and fa["eps"] > 0 and px else None
    return {"pts": pts, "max": len(items), "type": typ, "items": items, "why": [("✓ " if i["ok"] else "— " if i["ok"] is None else "✗ ") + i["t"] for i in items],
            "yoy": yoy, "opg": opg, "per": round(per, 1) if per else None,
            "q": [[q["p"], q["sales"], q["op"], q["opm"]] for q in Q[-6:]], "consensus": bool(fa and fa.get("op") is not None)}


def fok(f):
    """핵심 후보에서 빼지 않는가 (2026-11-24 사용자 확정): 펀더 0점(추정·발표 모두)이면 뺀다. 실적 자료가 아예 없는 종목은 중립(통과). 옛 형식(type 없음)은 예전 기준 2점↑."""
    if not f:
        return True
    if "type" not in f:
        return f.get("pts", 0) >= 2
    return f["pts"] > 0


def prep():
    import new_highs
    now = datetime.now(KST)
    daily, fund, uni = _daily(), _fund(), new_highs.universe_info()
    px = {c: r[-1]["close"] for c, r in daily.items()}
    P = {"made_at": now.strftime("%Y-%m-%d %H:%M"), "date": now.strftime("%Y-%m-%d")}
    P["macro"] = macro()
    try:   # 수출·메모리 현물가·유동성 (2026-11-20 사용자 확정, tools/macro_extra.py)
        import macro_extra
        P["macro_extra"] = macro_extra.build()
    except Exception as e:
        P["macro_extra"] = {"error": str(e)[:120]}
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
    # 장중 인더스트리 액션 재료 (2026-11-18 사용자 요청): 같은 업종 종목(시총 2천억↑, 큰 순 30개)과 50일 평균 거래량
    #   → 웹이 1분 시세로 '동행/나 홀로'와 거래량 배수를 장중에 다시 계산 (판정 규칙은 screener.industry_action과 같음)
    peers_of, grp_of = {}, {}
    try:
        from universe import load as _uni
        from sector_map import custom_map
        from screener import RULES as _R
        cmap = custom_map()
        U = [u for u in _uni()["stocks"] if (u.get("market_cap_eok") or 0) >= _R["min_mcap_eok"] and u.get("market") not in ("KONEX", "2")]
        for u in sorted(U, key=lambda u: -(u.get("market_cap_eok") or 0)):
            g = cmap.get(u["code"]) or "네이버:" + (u.get("industry") or "")
            grp_of[u["code"]] = g
            peers_of.setdefault(g, []).append(u["code"])
    except Exception:
        pass

    def _vol50(code):
        try:
            rows = json.loads((CACHE / "daily" / f"{code}.json").read_text())["rows"]
            v = [x["volume"] for x in rows[-50:]]
            return round(sum(v) / len(v)) if v else None
        except Exception:
            return None
    items = []
    for r in sc.get("watch", []):
        lv, b = r.get("levels") or {}, r.get("base") or {}
        f = fscore(fund.get(r["code"]), r.get("close")) if fund.get(r["code"]) else prevfs.get(r["code"])
        dist = lv.get("distance_pct")
        tech = (1 if (r["rs"] or 0) >= 80 else 0) + (1 if dist is not None and dist <= 10 and not r["missing"] else 0) + (1 if r["ia"] == "동반 상승" else 0)
        fp = (f or {}).get("pts", 0)
        note = "베이스 짧고 얕음(확인 필요)" if (b.get("days") or 99) < 10 and (b.get("depth_pct") or 99) < 3 else ""
        mz = r.get("max_zone")
        if not mz:   # 감시 목록이 아직 옛 형식이면 일봉 캐시로 계산 (있을 때만)
            try:
                from screener import max_zone
                mz = max_zone(json.loads((CACHE / "daily" / f"{r['code']}.json").read_text())["rows"])
            except Exception:
                mz = None
        g = grp_of.get(r["code"])
        items.append({"code": r["code"], "peers": [c for c in peers_of.get(g, []) if c != r["code"]][:30], "vol50": _vol50(r["code"]), "name": r["stock"], "zone_top": (mz or {}).get("top"), "zone_pct": (mz or {}).get("pct"), "group": r["group"], "rs": r["rs"], "close": r["close"], "breakout": lv.get("breakout"),
                      "stop": lv.get("stop_1r"), "dist": dist, "fp": fp, "tech": tech, "why": (f or {}).get("why") or [], "ia": r["ia"] == "동반 상승",
                      "ftype": (f or {}).get("type"), "fmax": (f or {}).get("max", 3), "fitems": (f or {}).get("items"), "fbad": not fok(f),
                      "pool": r["pool"], "core": fok(f) and tech >= 2, "note": note})
    items.sort(key=lambda x: (not x["core"], x["fbad"], x["ftype"] != "E", -x["fp"], x["dist"] if x["dist"] is not None else 99))
    return {"as_of": sc.get("as_of"), "made_at": datetime.now(KST).strftime("%Y-%m-%d %H:%M"), "items": items[:20],
            "n_core": sum(1 for x in items if x["core"]), "rule": "핵심 = 기술 2/3↑ + 펀더 0점 아님 (펀더: 다음 분기 이익·올해 EPS·추정치 상향, 추정치 없으면 발표 실적 / 기술: RS 80↑·기준가 10% 안·업종 동행)"}


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
    out["core"] = [{k: x[k] for k in ("name", "group", "breakout", "dist", "fp", "fmax", "ftype", "tech", "note")} for x in c["items"] if x["core"]][:6]
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


def adr(daily, days=60, win=20):
    """ADR(등락비율) 20일 = 최근 20거래일 오른 종목 수 합 ÷ 내린 종목 수 합 × 100 (2026-11-15 사용자 요청).
    코스피 종목(일봉 캐시가 있는 시총 2천억↑)만 — 코스피 지수와 겹쳐 비교. 120↑ 과열 · 75↓ 침체."""
    from universe import load as _uni
    kos = {x["code"] for x in _uni()["stocks"] if x.get("market") == "KOSPI"}
    dates = [r["date"] for r in daily["KOSPI"][-(days + win):]]
    cnt = {d: [0, 0] for d in dates}; n = 0
    for c, rows in daily.items():
        if c not in kos:
            continue
        n += 1
        for i in range(1, len(rows)):
            d = rows[i]["date"]
            if d in cnt:
                if rows[i]["close"] > rows[i - 1]["close"]:
                    cnt[d][0] += 1
                elif rows[i]["close"] < rows[i - 1]["close"]:
                    cnt[d][1] += 1
    kc = {r["date"]: r["close"] for r in daily["KOSPI"]}
    out = []
    for i in range(win - 1, len(dates)):
        a = sum(cnt[d][0] for d in dates[i - win + 1:i + 1]); b = sum(cnt[d][1] for d in dates[i - win + 1:i + 1])
        out.append({"date": dates[i], "adr": round(a / max(b, 1) * 100, 1), "up": cnt[dates[i]][0], "dn": cnt[dates[i]][1], "kospi": kc.get(dates[i])})
    return {"n": n, "rows": out[-days:]}


def daily_market():
    """웹 '시장'(탑다운) 탭·'오늘' 국면 추적판용 (2026-11-14 2차): prep의 시장 부분만 매일. 해석 글 없음."""
    import new_highs
    daily, fund, uni = _daily(), _fund(), new_highs.universe_info()
    px = {c: r[-1]["close"] for c, r in daily.items()}
    P = {"made_at": datetime.now(KST).strftime("%Y-%m-%d %H:%M")}
    P["macro"] = macro()
    P["regime"] = regime_block(daily); P["rally"] = rally(daily["KOSPI"])
    P["breadth"] = breadth_fast(daily, uni, days=120)   # 국면·시장 폭 그림 모두 120거래일 (2026-11-15 사용자 요청)
    P["adr"] = adr(daily, days=120)
    P["kospi40"] = [{"date": r["date"], "close": r["close"], "volume": r["volume"]} for r in daily["KOSPI"][-13:]]
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
        c60 = m.get("c60") or []
        sp, posv = "", None
        if len(c60) >= 5:
            lo_, hi_ = min(c60), max(c60); n_ = len(c60); sw, sh = 120, 28
            pts = " ".join(f"{2+i*(sw-4)/(n_-1):.1f},{2+(hi_-v)/((hi_-lo_) or 1)*(sh-4):.1f}" for i, v in enumerate(c60))
            col = "var(--up)" if c60[-1] >= c60[0] else "var(--dn)"
            sp = f'<svg width="{sw}" height="{sh}" viewBox="0 0 {sw} {sh}" class="spk"><polyline points="{pts}" fill="none" stroke="{col}" stroke-width="1.4"/><circle cx="{sw-2}" cy="{2+(hi_-c60[-1])/((hi_-lo_) or 1)*(sh-4):.1f}" r="2.2" fill="{col}"/></svg>'
            posv = (c60[-1] - lo_) / ((hi_ - lo_) or 1) * 100
        pos = f'<span class="pbar"><i style="left:{posv:.0f}%"></i></span><small>{posv:.0f}%</small>' if posv is not None else "-"
        mrow.append(f'<tr><td class="l">{E(m["name"])}</td><td class="l">{sp}</td><td><b>{now}</b></td><td class="{cls(a)}">{d1}</td><td class="{cls(b)}">{dm}</td><td class="l nw">{pos}</td><td class="l"><small>{E(m.get("date", ""))}</small></td></tr>')
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
        "macro": f'<div class="fig"><div class="ft"><span>표</span>글로벌 지표 — 최근 · 1주 · 1개월</div>{T}<tr><th class="l">지표</th><th class="l">추이 (60일 일봉)</th><th>최근</th><th>1주</th><th>1개월</th><th class="l">60일 위치</th><th class="l">기준일</th></tr>{"".join(mrow)}</table></div><div class="src">추이 = 최근 60거래일 종가(오른쪽 점 = 마지막) · 60일 위치 = 60일 최저 0% ~ 최고 100% 중 지금 · 출처: Yahoo Finance(비공식, 지연 가능) · {E(P["made_at"])} 받음</div></div>'
                 f'<div class="fig"><div class="ft"><span>표</span>매크로 → 업종 연결 (자동 규칙 문장)</div>{T}<tr><th class="l">변화</th><th>방향</th><th class="l">무엇에 영향</th></tr>{impl}</table></div><div class="src">1주 변화로 만든 규칙 문장입니다 · 해석은 주간 보고서(토)</div></div>',
        "regime": ftd_html(P) + f'<div class="fig"><div class="ft"><span>그림</span>코스피 120거래일 · ▼ 분산일 · 점선 20일선</div>{chart_kospi(P)}<div class="src">분산일 = 종가 −0.2%↓ + 거래량 전날보다 많음(25거래일 {dd}개) · 랠리 시도 {R["day"]}일째(저점 {md(R["low_date"])}) · 팔로스루 {md(R["ftd"]) if R["ftd"] else "아직"} · 출처: 네이버 코스피 일봉(비공식) {md(asof)}</div></div>'
                  f'<div class="fig"><div class="ft"><span>그림</span>시장 폭 — 50일선·20일선 위 종목 비율 · 120거래일</div>{chart_breadth(P)}<div class="leg"><span><i style="background:var(--acc)"></i>50일선 위 {lb["a50"]:.0f}%</span><span><i style="background:var(--ink3)"></i>20일선 위 {lb["a20"]:.0f}%</span></div><div class="src">시총 2천억↑ {lb["n"]}종목 · 출처: 네이버 일봉(비공식) 계산</div></div>',
        "flows": f'<div class="fig"><div class="ft"><span>그림</span>코스피 투자자별 순매수(억 원) · 아래 = 그날 코스피 등락</div>{chart_flows(P)}<div class="leg"><span><i style="background:var(--acc)"></i>외국인</span><span><i style="background:var(--warn)"></i>기관</span><span><i style="background:var(--ink3)"></i>개인</span><span>5일 합 외국인 {f5/10000:+.2f}조 · 기관 {i5/10000:+.2f}조</span></div><div class="src">출처: 네이버 시황(비공식)</div></div>'
                 f'<div class="two"><div class="fig"><div class="ft"><span>표</span>5일 순매수 상위 업종(억)</div>{T}<tr><th class="l">업종</th><th>외국인</th><th>기관</th><th>5일</th></tr>{frow(FS[:8])}</table></div></div><div class="fig"><div class="ft"><span>표</span>5일 순매도 상위 업종(억)</div>{T}<tr><th class="l">업종</th><th>외국인</th><th>기관</th><th>5일</th></tr>{frow(FS[-8:][::-1])}</table></div></div></div><div class="src">{E(P.get("flows_src") or "")}</div>',
        "sectors": f'<div class="fig"><div class="ft"><span>그림</span>업종 테크노펀더멘탈 지도 — 이익(가로) × 추세(세로)</div>{chart_matrix(P)}<div class="src">가로 = 올해 영업이익 컨센서스 업종 합 증가율 · 세로 = 주도 섹터 레이더 점수({md(P.get("radar_as_of") or asof)}) · 출처: 네이버 재무·컨센서스(비공식)</div></div>'
                   f'<div class="fig"><div class="ft"><span>표</span>업종 스코어 — 강도 상위 20</div>{T}<tr><th>순위</th><th class="l">업종</th><th>4주</th><th>강도</th><th>20일선 위</th><th>올해 영업이익</th><th>PER(E)</th><th>외국인 5일</th><th>기관 5일</th><th>분류</th></tr>{"".join(srow)}</table></div><div class="src">분류: 이익 +{XQ}%↑ / 강도 {YQ}↑ (리더 · 모멘텀만 · 기다림 · 회피) · 컨센서스 있는 종목 3개 미만 업종은 “-”</div></div>'}
    AD = (P.get("adr") or {}).get("rows") or []
    if AD:
        la = AD[-1]
        html_["regime"] += (f'<div class="fig"><div class="ft"><span>그림</span>ADR(20일 등락비율) 120거래일 — 파란 선 · 점선 = 코스피 지수(오른쪽 눈금)</div>{chart_adr(P)}'
                            f'<div class="leg"><span><i style="background:var(--acc)"></i>ADR {la["adr"]:.0f}</span><span><i style="background:var(--ink3)"></i>코스피 {la["kospi"]:,.0f}</span><span>오늘 오름 {la["up"]} · 내림 {la["dn"]}</span></div>'
                            f'<div class="src">ADR = 최근 20거래일 오른 종목 수 합 ÷ 내린 종목 수 합 × 100 · 코스피 종목 중 일봉이 있는 시총 2천억↑ {P["adr"]["n"]}종목 기준(시장 전체 아님) · 120↑ 과열 · 75↓ 침체(바닥권) · 출처: 네이버 일봉(비공식)</div></div>')
    lt, _ = light(P)
    track = {"light": lt, "gap20": P["regime"]["gap20"], "slope20": P["regime"]["slope20"], "dist": dd, "rally_day": R["day"], "rally_low": R["low_date"], "ftd": R["ftd"],
             "a50": lb["a50"], "a20": lb["a20"], "f5": f5, "i5": i5, "as_of": asof,
             "adr": AD[-1]["adr"] if AD else None, "adr_prev": AD[-6]["adr"] if len(AD) > 5 else None}
    return {"made_at": P["made_at"], "css": TOKENS_WEB + CSS, "html": html_, "track": track}


# ---------------------------------------------------------------- 분류 · 기본 해석
def quad(m):
    o, s = m.get("opg"), m["score"]
    lead = o is not None and o >= XQ
    return "리더" if lead and s >= YQ else "모멘텀만" if s >= YQ else "기다림" if lead else "회피"


def cat(b):
    ok = fok(b["fs"])
    if b["list"] == "running":
        return 4, "달리는 중 · 첫 눌림 대기", "neu"
    if ok and b["tech"] >= 2:
        return 0, "핵심 후보", "pos"
    if ok:
        return 1, "기술 대기", "neu"
    if b["tech"] >= 2:
        return 2, "기술만 · 펀더 0점", "warn"
    return 3, "제외", "neg"


def light(P):
    """국면 신호등 — common.regime_light 한 정의(20일선 위 + 정배열). 코스피 종가 120개로 다시 계산 (2026-11-20 통일)."""
    from common import regime_light_from_closes
    lt = regime_light_from_closes([x[1] for x in P["regime"].get("kospi") or []])
    return {"green": ("초록", "pos"), "yellow": ("노랑", "warn"), "red": ("빨강", "neg")}[lt]


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
    warns = [b for b in P["board"] if not fok(b["fs"]) and (b["tech"] >= 2 or b["list"] == "running") and b["fs"]]
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


def chart_adr(P):
    A = (P.get("adr") or {}).get("rows") or []
    if len(A) < 5:
        return ""
    m = len(A); W, H, L, R, T, B = 640, 190, 44, 52, 12, 22
    lo = min(60, min(x["adr"] for x in A) - 5); hi = max(130, max(x["adr"] for x in A) + 5)
    kc = [x["kospi"] for x in A if x.get("kospi")]; klo, khi = min(kc), max(kc)
    x = lambda i: L + i / (m - 1) * (W - L - R); y = lambda v: T + (hi - v) / (hi - lo) * (H - T - B)  # noqa: E731
    yk = lambda v: T + (khi - v) / ((khi - klo) or 1) * (H - T - B)  # noqa: E731
    g = [f'<rect x="{L}" y="{y(hi):.1f}" width="{W-L-R}" height="{y(120)-y(hi):.1f}" fill="var(--up)" opacity=".07"/>',
         f'<rect x="{L}" y="{y(75):.1f}" width="{W-L-R}" height="{y(lo)-y(75):.1f}" fill="var(--dn)" opacity=".07"/>']
    g += [f'<line x1="{L}" x2="{W-R}" y1="{y(v):.1f}" y2="{y(v):.1f}" class="{"basel" if v == 100 else "grid"}"/><text x="{L-6}" y="{y(v)+3:.1f}" class="ax" text-anchor="end">{v}</text>' for v in (75, 100, 120)]
    g.append('<path d="' + "".join(("M" if i == 0 else "L") + f"{x(i):.1f} {yk(a['kospi']):.1f}" for i, a in enumerate(A) if a.get("kospi")) + '" fill="none" stroke="var(--ink3)" stroke-width="1.3" stroke-dasharray="4 3"/>')
    g += [f'<text x="{W-R+6}" y="{yk(v)+3:.1f}" class="ax">{v:,.0f}</text>' for v in (khi, klo)]
    g.append('<path d="' + "".join(("M" if i == 0 else "L") + f"{x(i):.1f} {y(a['adr']):.1f}" for i, a in enumerate(A)) + '" fill="none" stroke="var(--acc)" stroke-width="2"/>')
    g.append(f'<circle cx="{x(m-1):.1f}" cy="{y(A[-1]["adr"]):.1f}" r="3.5" fill="var(--acc)"/><text x="{x(m-1)-6:.1f}" y="{y(A[-1]["adr"])-7:.1f}" class="vl" text-anchor="end">{A[-1]["adr"]:.0f}</text>')
    g.append(f'<text x="{L+4}" y="{y(hi)+11:.1f}" class="ax">과열 120↑</text><text x="{L+4}" y="{y(lo)-4:.1f}" class="ax">침체 75↓</text>')
    g += [_lab(i, m, f"{x(i):.1f}", H - 6) + f"{md(A[i]['date'])}</text>" for i in (0, m // 2, m - 1)]
    return f'<svg viewBox="0 0 {W} {H}" class="chart" role="img" aria-label="ADR과 코스피">{"".join(g)}</svg>'


def ftd_html(P):
    """FTD(팔로스루) 판정 카드 — 오닐 방식 단순화 (2026-11-15)"""
    R = P["rally"]; K = P.get("kospi40") or []
    if R.get("ftd"):
        st, col = f'✅ 팔로스루 확인 — {md(R["ftd"])}', "var(--ok,#15803d)"
    elif not R.get("start"):
        st, col = "— 랠리 시도 없음 (저점 갱신 중)", "var(--ink3)"
    elif R["day"] < 4:
        st, col = f'⏳ 랠리 시도 {R["day"]}일째 — 4일째부터 판정', "var(--warn)"
    elif R["day"] <= 7:
        st, col = f'⏳ 랠리 시도 {R["day"]}일째 — 팔로스루 대기', "var(--warn)"
    else:
        st, col = f'⚠️ 랠리 시도 {R["day"]}일째 — 7일 안에 팔로스루 없음(힘 약함)', "var(--warn)"
    cells = "".join(f'<td class="{cls(K[i]["close"] / K[i-1]["close"] - 1)}">{md(K[i]["date"])}<br>{pc((K[i]["close"] / K[i-1]["close"] - 1) * 100)}<br><small>{"거래↑" if K[i]["volume"] > K[i-1]["volume"] else "거래↓"}</small></td>' for i in range(1, len(K)))
    return (f'<div class="ftdc" style="border-left-color:{col}"><div class="k">FTD 판정 · 코스피</div><div class="st">{st}</div>'
            f'<div class="d">저점 {md(R["low_date"])} 종가 {R["low"]:,.0f}' + (f' · 시도 시작 {md(R["start"])}' if R.get("start") else "") +
            ' · 조건: 시도 4일째부터 코스피 <b>+1.5%↑ + 거래량 전날보다 많음</b> · 실패: 저점 종가 아래</div>'
            + (f'<div class="tw"><table class="ktab"><tr>{cells}</tr></table></div>' if cells else "") + '</div>')


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


def title_html(t):
    """제목: '—' 앞은 큰 제목, 뒤는 작은 둘째 줄 (한 줄에 다 넣으면 잘림)."""
    a, _, b = str(t).partition(" — ")
    return f'<h1 class="tt">{E(a)}</h1>' + (f'<p class="tt2">{E(b)}</p>' if b else "")


def sub_html(t):
    """요약 글: 한 문장 한 줄 (docs/brief-style.md). 괄호 안의 마침표에서는 끊지 않는다."""
    parts, buf, depth = [], "", 0
    for ch in str(t):
        buf += ch
        depth += ch == "("; depth -= ch == ")" and depth > 0
        if ch == "." and depth == 0 and buf.rstrip().endswith(("다.", "요.")):
            parts.append(buf.strip()); buf = ""
    if buf.strip():
        parts.append(buf.strip())
    return '<ul class="sub">' + "".join(f"<li>{x}</li>" for x in parts) + "</ul>"


def leaders_html(t):
    """리더 칸: '큰 줄기:'(옛 말) 머리말은 라벨로 올리고, 항목은 한 줄에 하나씩."""
    t = re.sub(r"^\s*큰\s*(줄기|스트림|띔)\s*[:：]\s*", "", str(t))
    items = [x.strip() for x in re.split(r"\s*[·,]\s*", t) if x.strip()]
    return '<b class="txt k-a">' + "".join(f"<i>{E(x)}</i>" for x in items) + "</b>"



CSS = """
.tfr{font-family:var(--f-body);line-height:1.7;color:var(--ink);word-break:keep-all;overflow-wrap:anywhere}
.tfr .page{background:var(--paper);border:1px solid var(--rule);padding:26px 30px;margin:0 0 22px}
.tfr .mast{display:flex;justify-content:space-between;align-items:baseline;gap:12px;border-bottom:3px solid var(--acc);padding-bottom:6px;margin-bottom:16px;flex-wrap:wrap}
.tfr .mast h2{font-size:13px!important;letter-spacing:.08em;color:var(--acc);margin:0!important;font-weight:700}.tfr .mast h2 i{font-style:normal;color:var(--ink3);margin-right:6px}.tfr .mast span{font-size:12px;color:var(--ink3)}
.tfr h1.tt{font-family:var(--f-disp);font-size:26px!important;line-height:1.35;margin:4px 0 4px!important;font-weight:800;white-space:normal}
.tfr .tt2{font-size:16px;font-weight:600;color:var(--ink2);line-height:1.5;margin:0 0 12px}
.tfr ul.sub{list-style:none;padding:0;margin:0;color:var(--ink2);font-family:var(--f-body);font-size:14px!important;line-height:1.75!important;letter-spacing:0;margin:0!important}.tfr ul.sub li{padding-left:14px;position:relative;margin:2px 0}.tfr ul.sub li:before{content:"";position:absolute;left:2px;top:.8em;width:4px;height:4px;border-radius:50%;background:var(--acc)}
.tfr .flow{display:flex;flex-wrap:wrap;gap:4px;align-items:center;font-size:12px;color:var(--ink2);margin:10px 0 2px}.tfr .flow span{border:1px solid var(--rule);padding:2px 8px;border-radius:3px}.tfr .flow span.on{border-color:var(--acc);color:var(--acc);font-weight:600}
.tfr .kpis{display:grid;grid-template-columns:repeat(5,minmax(0,1fr));border:1px solid var(--rule);margin:12px 0}
.tfr .kpis div{padding:12px 14px;border-right:1px solid var(--rule)}.tfr .kpis div:last-child{border-right:0}.tfr .kpis span{display:block;font-size:12px;color:var(--ink3);margin-bottom:2px}.tfr .kpis b{display:block;font-family:var(--f-body);font-variant-numeric:tabular-nums;font-size:18px;font-weight:700;line-height:1.35}.tfr ul.xnews{list-style:none;margin:6px 0 0;padding:0;font-size:12.5px;color:var(--ink2)}.tfr ul.xnews li{padding:2px 0;border-bottom:1px dotted var(--rule)}.tfr ul.xnews small{color:var(--ink3);margin-right:6px}
.tfr .kpis b.k-r{color:#d92d20}.tfr .kpis b.k-y{color:#c98a00}.tfr .kpis b.k-g{color:#12925a}.tfr .kpis b.k-o{color:#d9730d}.tfr .kpis b.k-a{color:#6b4fd8}
.tfr .kpis b.txt{font-size:14.5px;line-height:1.5}.tfr .kpis b.txt i{font-style:normal;display:block}.tfr .kpis small{display:block;font-size:12px;color:var(--ink3);line-height:1.5;margin-top:3px}
.tfr .cover,.tfr .sec{display:grid;grid-template-columns:230px minmax(0,1fr);gap:26px}
.tfr .side{font-size:12.5px}.tfr .cover .side{border-right:1px solid var(--rule);padding-right:18px}
.tfr .sec .side{border-top:2px solid var(--ink);padding-top:10px}.tfr .sec .main{border-top:2px solid var(--ink);padding-top:10px;min-width:0}
.tfr .side h4{font-size:11px;letter-spacing:.1em;color:var(--acc);margin:0 0 6px}
.tfr .side p{margin:0 0 10px;color:var(--ink2)}.tfr .side dl{display:grid;grid-template-columns:1fr auto;gap:4px 8px;margin:0 0 14px}.tfr .side dt{color:var(--ink3)}.tfr .side dd{margin:0;text-align:right}
/* 2026-11-20 사용자 확정: 좁은 옆 단(230px)을 없애고 한 단으로 — 해설은 그림 위 넓은 상자, 그림마다 '읽는 법' */
.tfr .cover,.tfr .sec{grid-template-columns:minmax(0,1fr)!important;gap:12px!important}
.tfr .sec .side{border-top:2px solid var(--ink);padding:12px 16px;background:var(--acc2);font-size:14px;line-height:1.8;max-width:none}
.tfr .sec .side p{margin:0 0 8px;color:var(--ink);max-width:78ch}.tfr .sec .side::before{content:"해설";display:block;font-size:11px;letter-spacing:.1em;color:var(--acc);font-weight:700;margin-bottom:4px}
.tfr .sec .main{border-top:0!important;padding-top:4px}
.tfr .side .sx{display:grid;grid-template-columns:118px minmax(0,1fr);gap:4px 16px;padding:9px 0;border-top:1px solid color-mix(in srgb,var(--acc) 22%,transparent)}.tfr .side .sx:first-of-type{border-top:0;padding-top:2px}
.tfr .side .sx .lb{font-weight:700;color:var(--acc);font-size:13px;line-height:1.6;padding-top:1px}.tfr .side .sx .lb:empty+ul{}.tfr .side .sx.head{display:block;font-size:14.5px;padding:2px 0 8px}
.tfr .side .sx ul{list-style:none;margin:0;padding:0}.tfr .side .sx li{position:relative;padding-left:12px;margin:0 0 5px;line-height:1.7;color:var(--ink)}.tfr .side .sx li:last-child{margin-bottom:0}.tfr .side .sx li:before{content:"";position:absolute;left:1px;top:.78em;width:4px;height:4px;border-radius:50%;background:var(--ink3)}
.tfr .side small.cite{color:var(--ink3);font-size:12px;white-space:normal}
@media(max-width:760px){.tfr .side .sx{grid-template-columns:1fr;gap:2px}.tfr .side .sx .lb:empty{display:none}}
.tfr .two2{display:grid;grid-template-columns:minmax(0,1.15fr) minmax(0,1fr);gap:14px;margin:0 0 14px}@media(max-width:820px){.tfr .two2{grid-template-columns:minmax(0,1fr)}.tfr table.desk td:last-child{white-space:normal}}
.tfr .box{border:1px solid var(--rule);border-radius:6px;padding:12px 14px}.tfr .box h4{font-size:12px;letter-spacing:.08em;color:var(--acc);margin:0 0 8px}.tfr .box h4 small{color:var(--ink3);font-weight:400;letter-spacing:0;margin-left:6px}
.tfr table.desk{width:100%;border-collapse:collapse}.tfr table.desk td{padding:6px 0;border-bottom:1px dashed var(--rule);font-size:13.5px;vertical-align:middle}.tfr table.desk td:first-child{text-align:left}.tfr table.desk td:last-child{text-align:right;white-space:nowrap}.tfr table.desk tr:last-child td{border-bottom:0}
.tfr ol.todo{margin:0;padding-left:20px}.tfr ol.todo li{font-size:13.5px;line-height:1.7;margin:0 0 6px;color:var(--ink)}
.tfr .how{font-size:12.5px;line-height:1.65;color:var(--ink2);background:color-mix(in srgb,var(--rule) 35%,transparent);border-radius:4px;padding:7px 10px;margin:4px 0 8px}.tfr .how b{color:var(--ink)}
.tfr .rtm{font-size:13.5px!important;line-height:1.8}.tfr .rtm p{margin:0 0 6px}
.tfr .spk{display:block}.tfr .pbar{position:relative;display:inline-block;width:64px;height:6px;border-radius:3px;background:linear-gradient(90deg,var(--dn),var(--rule),var(--up));opacity:.85;margin-right:6px;vertical-align:middle}.tfr .pbar i{position:absolute;top:-3px;width:3px;height:12px;background:var(--ink);border-radius:2px;transform:translateX(-1px)}.tfr td.nw{white-space:nowrap}
.tfr .ftdc{border:1px solid var(--rule);border-left:4px solid var(--warn);border-radius:8px;padding:10px 12px;margin:0 0 14px}.tfr .ftdc .k{font-size:11.5px;color:var(--ink3)}.tfr .ftdc .st{font-size:16px;font-weight:700;margin:2px 0}.tfr .ftdc .d{font-size:12px;color:var(--ink2)}
.tfr .ktab td{text-align:center;font-size:11px;padding:4px 3px;white-space:nowrap}
.tfr .rtm{border:1px solid var(--rule);border-left:4px solid var(--up);padding:10px 14px;margin:0 0 14px;font-size:12.5px}.tfr .rtm b.h{display:block;font-size:12px;letter-spacing:.06em;color:var(--up);margin-bottom:4px}
.tfr .ctg{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:10px}@media(max-width:600px){.tfr .ctg{grid-template-columns:1fr}}
.tfr .ctc{border:1px solid var(--rule);border-radius:8px;padding:10px 12px;font-size:12.5px}.tfr .ctc .n{font-weight:700}.tfr .ctc ul{margin:6px 0 4px 18px;padding:0}.tfr .ctc li{margin:2px 0}
.tfr .ctc .x2{font-size:11.5px;color:var(--ink2);margin-top:3px}.tfr .ctc .x2 b{font-weight:600}.tfr .ctc .x small{color:var(--ink3)}
.tfr .ctc .x{font-size:12px;border-top:1px dashed var(--rule);padding-top:5px;margin-top:5px}.tfr .ctc .x b{color:var(--up)}
.tfr .cmp{border:1px solid var(--rule);border-left:4px solid var(--warn);padding:10px 14px;margin:0 0 14px;font-size:13px}.tfr .cmp>div{margin-top:4px}.tfr .cmp table{margin-top:6px}
.tfr .call{background:var(--acc2);border-left:4px solid var(--acc);padding:12px 16px;margin:0 0 14px}.tfr .call b.h{display:block;font-size:12px;letter-spacing:.08em;color:var(--acc);margin-bottom:4px}.tfr .call{font-size:15px;line-height:1.8}
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


def red_team_html(N):
    """공통 상자 (2026-11-15 사용자 확정 A안): 반론가 요약 — 반론 개수·확신도 조정·'틀렸다면 이유' 3줄"""
    R = N.get("red_team") or {}
    if not R:
        return ""
    ch = "".join(f"{E(c[0])} {c[1]}→{c[2]}" + (f"({E(c[3])})" if len(c) > 3 and c[3] else "") + " · " for c in R.get("conviction_changes") or [])
    pm = "".join(f"<div>{'①②③④⑤'[i]} {E(x)}</div>" for i, x in enumerate((R.get("premortem") or [])[:3]))
    return (f'<div class="rtm"><b class="h">반론가 · {E(R.get("by") or "보조 에이전트(따로 검토)")}</b>'
            f'<div>반론 <b>{R.get("n_against", "-")}개</b> · 확신도 내림 <b>{len(R.get("conviction_changes") or [])}건</b>{(" — " + ch.rstrip(" · ")) if ch else ""}</div>'
            + (f'<div style="margin-top:4px"><b>4주 뒤 틀렸다면 가장 그럴듯한 이유</b></div>{pm}' if pm else "") + '</div>')


def counter_html(N, items, title):
    """반론 카드 (A안): items = [(키(코드·업종명), 이름, 부제)], N['counter'][키] = {against:[..], invalid:'..'}"""
    C = N.get("counter") or {}
    cards = []
    for key, name, sub in items:
        c = C.get(key) or C.get(name)
        if not c:
            continue
        li = "".join(f"<li>{E(x)}</li>" for x in (c.get("against") or [])[:3])
        # 깨지는 조건: 펀더(먼저) · 가격(보조) · 언제 확인 (2026-11-15 사용자 지적: 기술 조건만이면 빈약)
        inv_f, inv_p = c.get("invalid_f"), c.get("invalid_p") or (c.get("invalid") if not c.get("invalid_f") else None)
        x = ""
        if inv_f:
            x += f'<div class="x"><b>깨지는 조건 · 펀더</b> {E(inv_f)}' + (f' <small>({E(c.get("watch_when"))})</small>' if c.get("watch_when") else "") + '</div>'
        if inv_p:
            x += f'<div class="x2"><b>{"가격" if inv_f else "깨지는 조건"}</b> {E(inv_p)}</div>'
        # sub는 이 코드가 만든 짧은 HTML(색 표시)이라 이스케이프하지 않음
        cards.append(f'<div class="ctc"><span class="n">{E(name)}</span> <span class="tag neu">{sub}</span><ul>{li}</ul>{x}</div>')
    if not cards:
        return ""
    return f'<h3 style="font-size:14px;margin:14px 0 6px">⚖️ {title} — 반대 근거 + 깨지는 조건</h3><div class="ctg">{"".join(cards)}</div>'


_SRC = re.compile(r"출처|Yahoo|TradingView|한국은행|산업통상|금융투자협회|DRAMeXchange|채널 요약|개인 의견|네이버|컨센서스|증권|리서치|\d{1,2}/\d{1,2}")


def _cite(sn):
    """맨 바깥 괄호 가운데 출처로 보이는 것만 작고 흐리게 (괄호 안 괄호도 한 덩어리로)."""
    out, depth, st = "", 0, 0
    for i, ch in enumerate(sn):
        if ch == "(":
            if depth == 0:
                out += sn[st:i]; st = i
            depth += 1
        elif ch == ")" and depth:
            depth -= 1
            if depth == 0:
                g = sn[st:i + 1]
                out += f'<small class="cite">{g}</small>' if _SRC.search(g) else g
                st = i + 1
    return out + sn[st:]


def _sentences(t):
    """한 문장 한 줄로 끊기: 괄호·따옴표 안의 마침표에서는 끊지 않고, '…습니다(출처).'처럼 출처 괄호가 붙은 문장도 끊는다."""
    out, buf, depth, q = [], "", 0, False
    for i, ch in enumerate(t):
        buf += ch
        if ch == "(":
            depth += 1
        elif ch == ")" and depth:
            depth -= 1
        elif ch in "'‘’":
            q = (not q) if ch == "'" else (ch == "‘")
        if ch == "." and depth == 0 and not q and t[i + 1:i + 2] in ("", " "):
            core = re.sub(r"\s*\((?:[^()]|\([^()]*\))*\)\.$", ".", buf.rstrip())   # 끝의 출처 괄호를 떼고 어미 확인
            if core.endswith(("다.", "요.", "까.")):
                out.append(buf.strip()); buf = ""
    if buf.strip():
        out.append(buf.strip())
    return out


def side_html(L):
    rows = []
    for x in L or []:
        x = str(x)
        if re.fullmatch(r"\s*<b>.*</b>\s*", x, re.S):
            rows.append(["head", x, []]); continue
        m = re.match(r"\s*<b>([^<]{1,24})</b>\s*[—–-]\s*(.*)$", x, re.S)
        lab, body = (m.group(1), m.group(2)) if m else ("", x)
        li = [f"<li>{_cite(sn)}</li>" for sn in _sentences(body)]
        if not lab and rows and rows[-1][0] != "head":
            rows[-1][2] += li            # 라벨 없는 문단은 앞 칸에 이어 붙임
        else:
            rows.append(["row", lab, li])
    return "".join(f'<div class="sx head">{b}</div>' if k == "head" else f'<div class="sx"><div class="lb">{E(b)}</div><ul>{"".join(li)}</ul></div>' for k, b, li in rows)


def _mon(p):
    m = {"Jan": 1, "Feb": 2, "Mar": 3, "Apr": 4, "May": 5, "Jun": 6, "Jul": 7, "Aug": 8, "Sep": 9, "Oct": 10, "Nov": 11, "Dec": 12}.get(str(p)[:3])
    return f"{m}월" if m else str(p)


def extra_html(P):
    """매크로 보강 표: 한국 수출 · 메모리 현물가 · 유동성 (tools/macro_extra.py). 재료가 없으면 빈칸."""
    X = P.get("macro_extra") or {}
    num = lambda v, d=1: "-" if v is None else f"{v:,.{d}f}"          # noqa: E731
    sg = lambda v, u="%": "-" if v is None else f"{v:+.1f}{u}"         # noqa: E731
    out = []
    ex = (X.get("exports") or {}).get("rows") or []
    if ex:
        per = [r["period"] for r in ex[0]["series"][-6:]]
        rows = ""
        for r in ex:
            m = {x["period"]: x for x in r["series"]}
            cells = "".join(f'<td class="{cls(m[p_]["actual"]) if p_ in m else ""}">{num(m[p_]["actual"]) if p_ in m else "-"}</td>' for p_ in per)
            la = r["last"]; gap = None if la.get("forecast") is None else la["actual"] - la["forecast"]
            rows += f'<tr><td class="l">{E(r["name"])}</td>{cells}<td>{num(la.get("forecast"))}</td><td class="{cls(gap)}">{sg(gap, "")}</td><td class="l"><small>{E(r.get("next") or "")}</small></td></tr>'
        news = "".join(f'<li><small>{E(n["time"][5:10])}</small> {E(n["title"])}</li>' for n in ((X.get("export_news") or {}).get("items") or [])[:6])
        out.append(f'<div class="fig"><div class="ft"><span>표 1-2</span>한국 수출 — 최근 6개월 (실제 · 예상 대비)</div><div class="tw"><table><thead><tr><th class="l">지표</th>{"".join(f"<th>{E(_mon(p_))}</th>" for p_ in per)}<th>최근 예상</th><th>예상 대비</th><th class="l">다음 발표</th></tr></thead><tbody>{rows}</tbody></table></div>'
                   + (f'<ul class="xnews">{news}</ul>' if news else "")
                   + f'<div class="src">월간 수치 = {E((X.get("exports") or {}).get("source", ""))} · 아래 줄 = 10일 단위·품목별 수출 관련 뉴스 제목(2차 자료, 구글 뉴스)</div></div>')
    mem = (X.get("memory") or {}).get("rows") or []
    if mem:
        rows = "".join(f'<tr><td class="l">{E(r["name"])}</td><td><b>{num(r["usd"], 2)}</b></td><td class="{cls(r["chg_pct"])}">{sg(r["chg_pct"])}</td><td class="{cls(r["w1_pct"])}">{sg(r["w1_pct"])}</td><td class="{cls(r["m1_pct"])}">{sg(r["m1_pct"])}</td></tr>' for r in mem)
        out.append(f'<div class="fig"><div class="ft"><span>표 1-3</span>메모리 현물가 — D램 · 낸드 (달러)</div><div class="tw"><table><thead><tr><th class="l">품목</th><th>평균가</th><th>직전 대비</th><th>1주</th><th>1개월</th></tr></thead><tbody>{rows}</tbody></table></div>'
                   f'<div class="src">{E((X.get("memory") or {}).get("source", ""))} · 사이트 갱신 {E((X.get("memory") or {}).get("updated", ""))} · 현물가는 소량 거래 가격이라 대형 계약 가격(고정거래가)과 다를 수 있음</div></div>')
    liq = (X.get("liquidity") or {}).get("rows") or []
    if liq:
        rows = "".join(f'<tr><td class="l">{E(r["name"])}</td><td><b>{num(r["now"])}</b></td><td class="{cls(r.get("d1"))}">{sg(r.get("d1"), "")}</td><td class="{cls(r.get("m1_pct"))}">{sg(r.get("m1_pct"))}</td><td class="l nw">' + (f'<span class="pbar"><i style="left:{r["pos_1y"]:.0f}%"></i></span><small>{r["pos_1y"]:.0f}%</small>' if r.get("pos_1y") is not None else "-") + f'</td><td class="l"><small>{E(r["read"])}</small></td></tr>' for r in liq)
        a = str((X.get("liquidity") or {}).get("as_of") or "")
        out.append(f'<div class="fig"><div class="ft"><span>표 1-4</span>유동성 — 예탁금 · 신용잔고 · 반대매매</div><div class="tw"><table><thead><tr><th class="l">지표</th><th>지금</th><th>전일 대비</th><th>1개월</th><th class="l">1년 위치</th><th class="l">뜻</th></tr></thead><tbody>{rows}</tbody></table></div>'
                   f'<div class="src">{E((X.get("liquidity") or {}).get("source", ""))} · 기준 {E(a[4:6] + "/" + a[6:8] if len(a) == 8 else a)}</div></div>')
    return "".join(out)



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
    para = side_html   # 해설: 왼쪽 라벨(무엇이·왜…) + 오른쪽 한 문장 한 줄, 출처 괄호는 작게 (2026-11-20 사용자 요청)
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
 {title_html(N.get("title", ""))}
 {sub_html(N.get("sub", ""))}
 <div class="flow"><span>매크로</span>→<span>시황·국면</span>→<span>수급</span>→<span>업종</span>→<span class="on">종목(펀더 필터 → 기술 트리거)</span>→<span>보유·성적</span></div>
 <div class="kpis">
  <div><span>매크로</span><b class="{"k-g" if "우호" in str(N.get("macro_view")) else "k-o" if "부담" in str(N.get("macro_view")) or "경계" in str(N.get("macro_view")) else ""}">{E(N.get("macro_view", "중립"))}</b><small>{E(N.get("macro_note", "금리·환율·유가·반도체·VIX"))}</small></div>
  <div><span>국면</span><b class="{ {"neg": "k-r", "pos": "k-g", "warn": "k-y"}.get(ltc, "")}">● {lt}</b><small>분산일 {dd} · 50일선 위 {lb["a50"]:.0f}%</small></div>
  <div><span>외국인 5일</span><b class="{cls(f5)}">{f5/10000:+.2f}조</b><small>기관 {i5/10000:+.2f}조 (코스피)</small></div>
  <div><span>{"큰 스트림" if "스트림" in polish(str(N.get("leaders_label") or "")) or "줄기" in str(N.get("leaders_label") or "") else "리더 업종"}</span>{leaders_html(N.get("leaders_label") or "·".join(leaders[:3]) or "없음")}<small>이익 +{XQ}%↑ + 강도 {YQ}↑</small></div>
  <div><span>핵심 후보</span><b>{len(core)}종목</b><small>기술 2/3↑ + 펀더 0점 아님</small></div>
 </div>
 {compare_html(P, core)}
 <div class="cover">
  <div style="min-width:0"><div class="call"><b class="h">한 줄 결론</b>{N.get("call", "")}</div>
   <div class="two2"><div class="box"><h4>데스크 의견 <small>스트림마다 지금 판정</small></h4><table class="desk">{"".join(f'<tr><td>{E(a)}</td><td><span class="tag {c}">{E(b)}</span></td></tr>' for a, b, c in desk)}</table></div>
    <div class="box"><h4>이번 주 할 일</h4><ol class="todo">{"".join(f"<li>{E(t)}</li>" for t in (N.get("todo") or [])[:5])}</ol></div></div>
   {red_team_html(N)}
   <div class="fig"><div class="ft"><span>그림 1</span>업종 테크노펀더멘탈 지도 — 이익(가로) × 추세(세로)</div>{chart_matrix(P)}
    <div class="src">가로 = 업종 내 시총 2천억↑ 종목의 올해 영업이익 컨센서스 합 ÷ 작년 실제 합 − 1(+200%↑ 오른쪽 끝) · 세로 = 주도 섹터 레이더 점수({md(P.get("radar_as_of") or asof)}) · 원 크기 = 종목 수 · 컨센서스 있는 종목 3개↑ 업종만 · 출처: 네이버 재무·컨센서스(비공식)</div></div></div>
 </div>
</article>
<article class="page">
 <div class="mast"><h2 data-tl="🌐 매크로"><i>STEP 1</i>매크로</h2><span>어느 업종에 유리한가</span></div>
 <section class="sec"><aside class="side">{para(N.get("macro_side"))}</aside><div class="main">
  <div class="fig"><div class="ft"><span>표 1</span>글로벌 지표 — 지금 · 1주 · 1개월</div><div class="tw"><table><thead><tr><th class="l">지표</th><th>최근</th><th>1주</th><th>1개월</th></tr></thead><tbody>{"".join(mrow)}</tbody></table></div><div class="src">출처: Yahoo Finance(비공식, 지연 가능)</div></div>
  {extra_html(P)}
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
  {counter_html(N, [(m["group"], m["group"], f'{m["rank"]}위 · 이익 {gtxt(m.get("opg"))}') for m in sorted(MT, key=lambda m: m["rank"]) if quad(m) == "리더"], "리더 업종 반론")}
 </div></section>
</article>
<article class="page">
 <div class="mast"><h2 data-tl="🎯 종목"><i>STEP 5</i>종목 — 펀더 필터 → 기술 트리거</h2><span>감시 목록 {P["screener"].get("count") or "-"}종목 훑기 · 확정 신호 {P["screener"].get("signals", 0)}건 · {md(P["screener"].get("as_of") or asof)}</span></div>
 <p style="margin:0 0 6px;font-size:13px"><b>펀더 점수</b>(추정 3): ① 다음 분기 영업이익 추정치가 1년 전 같은 분기보다 +20%↑ 또는 흑자전환 ② 올해 EPS 추정치가 작년보다 증가 ③ 올해 영업이익 추정치가 한 달 전보다 상향. 증권사 추정치가 없는 종목은 발표된 실적(분기 영업이익·EPS)으로 본 참고 점수 2점이고 감점하지 않습니다. 핵심 후보에서 빼는 것은 펀더 0점(추정·발표 모두)입니다. <b>기술 점수</b>(3): ① RS 80↑ ② 기준가 10% 안 + 빠진 조건 없음 ③ 업종 동행. 점에 마우스를 올리면 근거가 보입니다.</p>
 <div class="tw"><table><thead><tr><th class="l">종목 <small>업종·순위</small></th><th>분류</th><th>펀더</th><th>기술</th><th>최근 분기</th><th>올해(E)</th><th>PER(E)</th><th>RS</th><th>기준가</th><th>거리</th><th>손절가</th><th>1R 수량</th><th>베이스</th><th>업종</th><th class="l">일정·빠진 조건</th></tr></thead><tbody>{"".join(brow)}</tbody></table></div>
 <div class="src">최근 분기·올해(E) = 영업이익 증가율 · 손절가 = 기준가 −8% · 1R 수량 = 30만 원 ÷ (기준가 − 손절가) · 🎯 관찰 풀 · 출처: 감시 목록(screener.py), 네이버 재무·컨센서스(비공식)</div>
 {counter_html(N, [(b["code"], b["name"], f'펀더 {(b["fs"] or {}).get("pts", 0)} · 기술 {b["tech"]}') for b in core], "핵심 후보 반론")}
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


HOW = [   # 그림·표 제목 머리 → 읽는 법 (2026-11-20 사용자 확정: 표·차트에 설명 보충)
    ("업종 테크노펀더멘탈 지도", "오른쪽일수록 올해 이익이 많이 늘고, 위일수록 주가 추세가 강한 업종입니다. <b>오른쪽 위(리더)</b>는 이익과 추세가 함께 좋은 곳, <b>오른쪽 아래(기다림)</b>는 이익은 느는데 주가가 아직 안 따라온 곳입니다. 스트림은 오른쪽에 있는 업종에서 찾고, 위로 올라오는지를 지켜봅니다."),
    ("글로벌 지표", "해외 시장이 위험을 좋아하는지 피하는지를 봅니다. 주가지수·반도체 지수가 내리고 VIX(공포 지수)와 금리가 오르면 위험 회피입니다. 1주보다 <b>1개월 칸</b>이 큰 흐름입니다."),
    ("매크로 → 업종 연결", "위 지표의 변화가 국내 어느 업종에 유리하고 불리한지를 규칙으로 옮긴 표입니다. 예를 들어 유가가 내리면 항공·화학 비용이 줄어듭니다. 방향을 참고하는 용도이고 종목 선택의 근거는 아닙니다."),
    ("코스피 120거래일", "지수가 점선(20일선) 위에 있어야 돌파 매매가 잘 통합니다. ▼(분산일)는 거래가 늘면서 내린 날로, 25일 안에 5개를 넘으면 큰손이 파는 중이라는 신호입니다."),
    ("시장 폭", "지수가 아니라 <b>종목 수</b>로 본 시장 건강입니다. 50일선 위 종목이 50%를 넘으면 대부분의 종목이 오르는 장, 30% 아래면 소수만 버티는 장입니다."),
    ("ADR", "오른 종목 수 ÷ 내린 종목 수를 20일 평균한 값입니다. 120 위는 과열, 75 아래는 침체로 봅니다. 침체 구간에서 돌아설 때가 반등의 시작인 경우가 많습니다."),
    ("코스피 투자자별 순매수", "막대가 위면 산 것, 아래면 판 것입니다. <b>외국인과 기관이 같은 날 함께 사는지</b>가 중요합니다. 개인만 사는 상승은 오래가지 못하는 편입니다."),
    ("5일 순매수 상위 업종", "최근 5일 동안 외국인·기관 돈이 들어온 업종입니다. 스트림 업종이 여기에 올라오면 '이익이 가격에 반영되기 시작했다'는 확인이 됩니다. 5일 수급만으로 스트림을 바꾸지는 않습니다."),
    ("5일 순매도 상위 업종", "최근 5일 동안 돈이 빠져나간 업종입니다. 스트림 업종이 여기 있으면 '이익은 그대로, 가격은 쉬는 중'인지 이익 전제가 깨진 것인지를 본문에서 따집니다."),
    ("업종 스코어", "업종마다 강도 점수(주가 추세)와 올해 영업이익 증가율(이익)을 나란히 놓은 표입니다. 분류 칸의 <b>리더</b> = 둘 다 좋음, <b>기다림</b> = 이익만 좋음, <b>모멘텀만</b> = 주가만 좋음, <b>회피</b> = 둘 다 약함입니다."),
    ("분기 영업이익", "막대는 분기 영업이익, 선은 영업이익률입니다. 막대가 계단처럼 올라가고 선도 함께 오르면 '많이 팔면서 더 남기는' 구간입니다. 흐린 막대는 증권사 추정치입니다."),
]
_JUL = [("줄기로", "스트림으로"), ("줄기를", "스트림을"), ("줄기가", "스트림이"), ("줄기는", "스트림은"), ("줄기와", "스트림과"), ("줄기", "스트림"), ("띔", "스트림")]   # 용어: 스트림 (2026-11-20 사용자 확정, 옛 말 띔·줄기)


def polish(html):
    """render 마무리 (2026-11-20 사용자 확정): ① 그림·표 제목 아래 '읽는 법' ② 옛 말 '띔'·'줄기' → '스트림'(조사까지)"""
    def add(m):
        title = re.sub(r"<[^>]+>", "", m.group(0))
        for key, txt in HOW:
            if key in title:
                return m.group(0) + f'<div class="how"><b>읽는 법</b> · {txt}</div>'
        return m.group(0)
    html = re.sub(r'<div class="ft">.*?</div>', add, html)
    for a, b in _JUL:
        html = html.replace(a, b)
    return html


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
    b = polish(b)
    for _a, _b in _JUL:   # 제목(호 목록·텔레그램에 쓰임)도 같은 용어로
        N["title"] = str(N.get("title") or "").replace(_a, _b)
    page = ("<!doctype html><html lang=\"ko\"><head><meta charset=\"utf-8\"><meta name=\"viewport\" content=\"width=device-width,initial-scale=1,viewport-fit=cover\">"
            f"<title>테크노펀더멘탈 주간 {P['date']}</title><link rel=\"stylesheet\" href=\"https://fonts.googleapis.com/css2?family=IBM+Plex+Sans+KR:wght@400;600;700&family=Noto+Serif+KR:wght@800&family=IBM+Plex+Mono&display=swap\">"
            f"<style>{TOKENS_PAGE}{CSS}</style></head><body>{b}</body></html>")
    rep = ROOT / "reports" / P["date"]; rep.mkdir(parents=True, exist_ok=True)
    (rep / "strategy_tf.html").write_text(page, encoding="utf-8")
    out = {"date": P["date"], "made_at": P["made_at"], "title": N.get("title"), "narr": bool(user), "css": TOKENS_WEB + CSS, "html": b,
           "page": f"reports/{P['date']}/strategy_tf.html"}
    (TF / "latest.json").write_text(json.dumps(out, ensure_ascii=False), encoding="utf-8")
    (TF / f"issue_{P['date']}.json").write_text(json.dumps(out, ensure_ascii=False), encoding="utf-8")   # 지난 호 보기용 (2026-11-15)
    return {"page": out["page"], "narr": bool(user), "title": out["title"], "core": [x["name"] for x in P["board"] if cat(x)[0] == 0]}


def pool(date=None):
    """관찰 풀 = 큰 스트림의 기업 지도 (2026-11-20 사용자 확정: "보고서의 관찰 풀은 큰 줄기를 잡는 목적, 셋업 보드는 지금의 수급과 위치").
    전략 보고서(data/strategy/latest.json)의 스트림 중 유지되는 줄기(확신 2↑ · 단계가 소멸이 아님)의 기업 지도에서 행동이 '회피'가 아닌 종목.
    차트 조건(기준가·RS·업종 강도)으로는 넣고 빼지 않는다 — 차트 자리는 셋업 보드가 본다. 줄기가 유지되면 풀도 유지된다.
    보고서에 줄기가 없으면 옛 방식(pool_board: 감시 목록 × 펀더·기술)으로 대신 쓴다."""
    rep = _j(DATA / "strategy" / "latest.json") or {}
    keep = [t for t in rep.get("themes") or [] if (t.get("conviction") or 0) >= 2 and t.get("stage") != "소멸" and t.get("companies")]
    if not keep:
        return pool_board(date)
    try:
        from sector_map import custom_map
        cmap = custom_map()
    except Exception:
        cmap = {}
    fund = _fund()
    q = lambda v: str(v or "").replace('"', "").replace("\n", " ")  # noqa: E731
    now = datetime.now(KST).strftime("%Y-%m-%d %H:%M")
    L = ["# 관찰 풀 — 전략 보고서 '큰 스트림'의 기업 지도 (strategy_tf.py pool, 2026-11-20 사용자 확정). 줄기가 유지되는 동안 풀도 유지.",
         "# 차트 조건으로 넣고 빼지 않음(차트 자리는 셋업 보드). 직접 고쳐도 됨. 감시 목록(screener --pool)은 이 풀 + RS 70↑만 본다. 주문 기능 없음.",
         f'updated = "{now}"', f'source = "전략 보고서 {q(rep.get("issue"))} 큰 스트림"', ""]
    seen, out, skip = set(), {}, []
    for t in keep:
        items = []
        for c in t["companies"]:
            code = str(c.get("code") or "")
            if not code or code in seen:
                continue
            if c.get("action") == "회피":
                skip.append(c.get("name")); continue
            seen.add(code)
            f = fscore(fund.get(code), None)
            pts = f["pts"] if f else None
            items.append(f'  {{ name = "{q(c.get("name"))}", code = "{code}", role = "{q(c.get("role"))}", group = "{q(cmap.get(code))}", '
                         f'action = "{q(c.get("action") or "관찰")}", fund = {pts if pts is not None else -1} }},')
        if items:
            nm = q(t.get("name")).split(" — ")[0].split(" (")[0]
            L += ["[[themes]]", f'id = "{q(t.get("id"))}"', f'name = "🌳 {nm}"', 'stage = "큰 스트림"', "stocks = ["] + items + ["]", ""]
            out[t.get("id")] = len(items)
    weak = [q(t.get("name")).split(" — ")[0] for t in rep.get("themes") or [] if t not in keep]
    if weak:
        L.append("# 풀에 넣지 않은 스트림(약화·관찰·이익 미확인): " + ", ".join(weak))
    if skip:
        L.append("# 줄기 안이지만 보고서가 '회피'로 적은 종목: " + ", ".join(x for x in skip if x))
    (ROOT / "config" / "watch_pool.toml").write_text("\n".join(L) + "\n", encoding="utf-8")
    return {"mode": "큰 스트림", "themes": out, "n": len(seen), "left_out_themes": weak, "skip": skip}


def pool_board(date=None):
    """(옛 방식, 2026-11-14~11-20) 관찰 풀을 테크노펀더 지면 기준으로 다시 씀 (2026-11-14 사용자 지적: 풀이 옛 v3 스트림 기준이라 보고서와 달랐음).
    핵심 후보(준비) · 펀더 OK·기술 대기(관찰) · 달리는 주도주 펀더 2↑(첫 눌림 대기) · 리더 업종 주도주 펀더 2↑(업종 리더). 펀더 0~1은 넣지 않음."""
    fs = [TF / f"prep_{date}.json"] if date else sorted(TF.glob("prep_*.json"))
    P = _j(fs[-1])
    BD = sorted(P["board"], key=lambda b: (cat(b)[0], b["dist"] if b["dist"] is not None else 99))
    fp = lambda b: (b["fs"] or {}).get("pts", 0)  # noqa: E731
    seen = set()

    def take(L):
        out = []
        for b in L:
            if b["code"] not in seen:
                seen.add(b["code"]); out.append(b)
        return out
    core = take([b for b in BD if cat(b)[0] == 0])
    wait = take([b for b in BD if cat(b)[0] == 1])
    run = take([b for b in BD if cat(b)[0] == 4 and fp(b) >= 2])
    from universe import load as _uni
    code_of = {x["name"]: x["code"] for x in _uni()["stocks"]}
    fund = _fund()
    lead = []
    MT = sorted([m for m in P["matrix"] if m.get("opg") is not None and (m.get("n_fund") or 0) >= 3 and quad(m) == "리더"], key=lambda m: m["rank"])
    for m in MT:
        k = 0
        for nm in m.get("leaders") or []:
            c = code_of.get(nm)
            if not c or c in seen:
                continue
            f = fscore(fund.get(c), None)
            if f and f["pts"] >= 2:
                seen.add(c); lead.append({"name": nm, "code": c, "group": m["group"], "pts": f["pts"]}); k += 1
            if k >= 2:
                break
    skip = [b["name"] for b in BD if cat(b)[0] in (2, 3) or (cat(b)[0] == 4 and fp(b) < 2)]
    q = lambda v: str(v or "").replace('"', "")  # noqa: E731
    row = lambda nm, c, role, g: f'  {{ name = "{q(nm)}", code = "{c}", role = "{q(role)}", group = "{q(g)}" }},'  # noqa: E731
    now = datetime.now(KST).strftime("%Y-%m-%d %H:%M")
    L = ["# 관찰 풀 — 테크노펀더 주간 지면(strategy_tf.py pool)이 고른 종목. 매주 토요일 보고서 때 다시 씀.",
         "# 직접 고쳐도 됨(빼려면 줄 삭제, 넣으려면 같은 형식으로 추가). 감시 목록(screener --pool)은 이 풀 + RS 70↑만 본다. 주문 기능 없음.",
         f'updated = "{now}"', f'source = "테크노펀더 주간 {P["date"]}"', ""]
    for tid, name, stage, items in [
        ("C1", "🎯 핵심 후보 — 기술 2/3↑ + 펀더 0점 아님 (기준가 돌파 대기)", "준비", [row(b["name"], b["code"], f"준비 · 기준가 {b['breakout']:,}" if b.get("breakout") else "준비", b["group"]) for b in core]),
        ("C2", "펀더 OK · 기술 대기 — 이익은 받쳐 주고 베이스·RS를 기다림", "관찰", [row(b["name"], b["code"], "관찰", b["group"]) for b in wait]),
        ("C3", "달리는 주도주 — 베이스 없음, 추격하지 않고 첫 눌림 대기", "첫 눌림 대기", [row(b["name"], b["code"], "눌림 대기", b["group"]) for b in run]),
        ("C4", "리더 업종 주도주 — 업종 이익 +20%↑ × 강도 65↑, 종목 펀더 2/3↑", "리더 업종", [row(x["name"], x["code"], "업종 리더", x["group"]) for x in lead])]:
        if items:
            L += ["[[themes]]", f'id = "{tid}"', f'name = "{name}"', f'stage = "{stage}"', "stocks = ["] + items + ["]", ""]
    if skip:
        L.append("# 넣지 않음(기술만 좋고 펀더 0~1 또는 미확인): " + ", ".join(skip))
    (ROOT / "config" / "watch_pool.toml").write_text("\n".join(L) + "\n", encoding="utf-8")
    return {"core": len(core), "wait": len(wait), "run": len(run), "lead": len(lead), "skip": skip}


def _v3_issues():
    """v3 보고서: history/*.json(지난 호) + latest.json(이번 호) → {날짜: json}"""
    out = {}
    for f in sorted((DATA / "strategy" / "history").glob("*.json")) + [DATA / "strategy" / "latest.json"]:
        d = _j(f)
        if d and not d.get("sample"):
            out[(d.get("made_at") or f.stem)[:10]] = d
    return out


def issues():
    """발간호 목록 (웹 '전략 › 보고서' 칩, 2026-11-15 사용자 확정 A안): 최신 먼저 [{date, issue, title, tf, v3}]"""
    v3 = _v3_issues()
    tf = {f.stem[6:]: _j(f) for f in TF.glob("issue_*.json")}
    rows = []
    for d in sorted(set(v3) | set(tf), reverse=True):
        a, b = v3.get(d) or {}, tf.get(d) or {}
        rows.append({"date": d, "issue": (a.get("issue") or "").split(" ·")[0], "title": b.get("title") or a.get("title") or "", "tf": bool(b), "v3": bool(a)})
    return rows


def write_issue_files(outdir):
    """지난 호 본문 파일 → site/r/날짜.json ({v3, tf}). 웹이 누를 때만 받음"""
    outdir.mkdir(parents=True, exist_ok=True)
    v3 = _v3_issues()
    tf = {f.stem[6:]: _j(f) for f in TF.glob("issue_*.json")}
    for d in set(v3) | set(tf):
        (outdir / f"{d}.json").write_text(json.dumps({"date": d, "v3": v3.get(d), "tf": tf.get(d)}, ensure_ascii=False), encoding="utf-8")
    return len(set(v3) | set(tf))


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
          f"🎯 핵심 후보 {len(core)}종목 (기술 2/3↑ + 펀더 0점 아님, 기준가까지)"]
    L += [f"- {b['name']} 기준가 {w(b['breakout'])}원 ({b['dist']:.1f}%) · 펀더 {(b['fs'] or {}).get('pts', 0)}/3 · 기술 {b['tech']}/3" for b in core[:5]]
    pm = (N.get("red_team") or {}).get("premortem") or []
    if pm:
        L += ["", "⚖️ 반론가: 4주 뒤 틀렸다면"] + [f"{'①②③'[i]} {re.sub(r'<[^>]+>', '', str(x))}" for i, x in enumerate(pm[:3])]
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
    pl = sp.add_parser("pool", help="관찰 풀을 이 지면 기준으로 다시 씀 → config/watch_pool.toml"); pl.add_argument("--date")
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
    elif a.cmd == "pool":
        print(json.dumps(pool(a.date), ensure_ascii=False))
    elif a.cmd == "tg":
        print(json.dumps(tg(a.date), ensure_ascii=False))
    else:
        print(json.dumps(render(a.date), ensure_ascii=False))


if __name__ == "__main__":
    main()
