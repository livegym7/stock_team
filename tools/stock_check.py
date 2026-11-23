#!/usr/bin/env python3
"""종목 점검표 (토큰 0, 2026-11-23 사용자 확정): 종목 메모가 놓치기 쉬운 세 가지를 공시·재무 숫자로 자동 계산한다.
  ① 희석 위험 — 최근 3년 전환사채·신주인수권부사채·교환사채·유상증자 결정(DART 주요사항보고서): 금액·전환가·주식 수 대비 비율·전환 가능 시작일
  ② 이익의 질 — 최근 분기·반기·사업보고서(DART 전체 재무제표, 연결 우선): 매출 증가율과 재고·매출채권 증가율, 영업현금흐름 ÷ 순이익, 재고·매출채권 일수
  ③ 주가에 이미 반영된 기대 — 올해 추정 EPS 기준 PER(E)에서 "3년 뒤 PER이 보통 수준(12배)으로 내려와도 주가가 제자리이려면 필요한 EPS 성장률"
  모두 '점검용 숫자'이고 매수·매도 판단이 아니다(절대 규칙 4). 매매 규칙에는 들어가지 않는다.

  python3 tools/stock_check.py show --stock 092870          # 한 종목 (화면 출력)
  python3 tools/stock_check.py update [--top 40]            # 보유 + 관찰 풀 → data/stock_checks.json (하루 한 번이면 충분)
필요한 환경 변수: DART_API_KEY (없으면 ③만 계산)
"""
import argparse, json, os, sys, time
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import DATA  # noqa: E402
from naver_quote import KST  # noqa: E402

OUT = DATA / "stock_checks.json"
NORMAL_PER, YEARS = 12, 3          # ③의 가정: 3년 뒤 PER 12배 (코스피 장기 평균 근처, 표시용 가정)
REPORTS = [("11014", "3분기", 273), ("11012", "반기", 181), ("11013", "1분기", 90), ("11011", "연간", 365)]   # 보고서 코드 · 이름 · 누적 일수
DIL = [("cvbdIsDecsn", "전환사채", "cv_prc", "cvisstk_cnt", "cvisstk_tisstk_vs", "cvrqpd_bgd", "bd_fta"),
       ("bdwtIsDecsn", "신주인수권부사채", "ex_prc", "nstk_isstk_cnt", "nstk_isstk_tisstk_vs", "expd_bgd", "bd_fta"),
       ("exbdIsDecsn", "교환사채", "ex_prc", "extg_stkcnt", "extg_tisstk_vs", "exrqpd_bgd", "bd_fta")]


def _n(v):
    try:
        return float(str(v).replace(",", "").strip())
    except Exception:
        return None


def _d(v):
    """'2025년 07월 09일' / '2025.07.09' / '20250709' → '2025-07-09'"""
    s = "".join(c for c in str(v or "") if c.isdigit())
    return f"{s[:4]}-{s[4:6]}-{s[6:8]}" if len(s) >= 8 else ""


def dilution(corp, price=None):
    import dart
    now = datetime.now(KST)
    bgn, end = (now - timedelta(days=365 * 3)).strftime("%Y%m%d"), now.strftime("%Y%m%d")
    ev = []
    for ep, kind, kp, kc, kr, kb, ka in DIL:
        for x in dart.api_json(ep + ".json", corp_code=corp, bgn_de=bgn, end_de=end).get("list", []):
            p, frm = _n(x.get(kp)), _d(x.get(kb))
            e = {"date": _d(x.get("rcept_no")), "kind": kind, "amount_eok": round((_n(x.get(ka)) or 0) / 1e8), "price": p,
                 "shares": _n(x.get(kc)), "pct": _n(x.get(kr)), "from": frm,
                 "url": f"https://dart.fss.or.kr/dsaf001/main.do?rcpNo={x.get('rcept_no')}"}
            e["open"] = bool(frm and frm <= now.strftime("%Y-%m-%d"))                 # 전환(행사) 청구가 이미 가능한가
            e["in_money"] = bool(price and p and price > p)                            # 지금 주가가 전환가보다 높은가
            ev.append(e)
        time.sleep(0.1)
    for x in dart.api_json("piicDecsn.json", corp_code=corp, bgn_de=bgn, end_de=end).get("list", []):
        sh, base = _n(x.get("nstk_ostk_cnt")) or 0, _n(x.get("bfic_tisstk_ostk")) or 0
        amt = sum(_n(x.get(k)) or 0 for k in ("fdpp_fclt", "fdpp_bsninh", "fdpp_op", "fdpp_dtrp", "fdpp_ocsa", "fdpp_etc"))
        ev.append({"date": _d(x.get("rcept_no")), "kind": "유상증자", "amount_eok": round(amt / 1e8), "shares": sh,
                   "pct": round(sh / base * 100, 1) if base else None, "how": x.get("ic_mthn"),
                   "url": f"https://dart.fss.or.kr/dsaf001/main.do?rcpNo={x.get('rcept_no')}"})
    ev.sort(key=lambda e: e["date"], reverse=True)
    live = [e for e in ev if e["kind"] != "유상증자" and e.get("open") and e.get("in_money")]
    soon = [e for e in ev if e["kind"] != "유상증자" and not e.get("open")]
    recent = [e for e in ev if e["kind"] == "유상증자" and e["date"] >= (now - timedelta(days=365)).strftime("%Y-%m-%d")]
    level = "주의" if live or recent else "확인" if soon or ev else "없음"
    if live:
        line = f"전환 가능한 {live[0]['kind']}가 있고 주가가 전환가({live[0]['price']:,.0f}원)보다 높습니다 — 주식 수의 {sum(e.get('pct') or 0 for e in live):.1f}%가 매물로 나올 수 있습니다."
    elif recent:
        line = f"최근 1년 안에 유상증자 결정({recent[0]['date']}, {recent[0]['amount_eok']:,}억)이 있었습니다."
    elif soon:
        line = f"{soon[0]['kind']}가 {soon[0]['from']}부터 전환 가능합니다(전환가 {soon[0]['price']:,.0f}원, 주식 수의 {soon[0].get('pct') or 0:.1f}%)."
    elif ev:
        line = f"최근 3년 {len(ev)}건이 있었지만 지금 매물로 나올 조건은 아닙니다."
    else:
        line = "최근 3년 전환사채·유상증자 결정 공시가 없습니다."
    return {"level": level, "line": line, "events": ev[:6], "source": "DART 주요사항보고서(최근 3년)", "caveat": "발행 결정 공시 기준입니다. 이미 주식으로 바뀌었거나 갚은 물량은 빼지 못했으니 남은 잔액은 공시 원문에서 확인합니다."}


def _acct(rows, sj, *ids):
    for i in ids:
        for r in rows:
            if r.get("sj_div") in sj and (r.get("account_id") == i or r.get("account_nm", "").replace(" ", "") == i):
                return r
    return None


def quality(corp):
    import dart
    y = datetime.now(KST).year
    for year in (y, y - 1):
        for code, name, days in REPORTS:
            rows = []
            for fs in ("CFS", "OFS"):                                    # 연결 먼저, 없으면 별도
                rows = dart.api_json("fnlttSinglAcntAll.json", corp_code=corp, bsns_year=str(year), reprt_code=code, fs_div=fs).get("list", [])
                if rows:
                    break
            time.sleep(0.1)
            if not rows:
                continue
            IS, annual = ("CIS", "IS"), code == "11011"
            cum = lambda r: _n(r.get("thstrm_amount") if annual else (r.get("thstrm_add_amount") or r.get("thstrm_amount"))) if r else None  # noqa: E731
            prv = lambda r: _n(r.get("frmtrm_amount") if annual else (r.get("frmtrm_add_amount") or r.get("frmtrm_q_amount"))) if r else None  # noqa: E731
            rev = _acct(rows, IS, "ifrs-full_Revenue", "매출액", "수익(매출액)", "영업수익")
            cogs = _acct(rows, IS, "ifrs-full_CostOfSales", "매출원가")
            ni = _acct(rows, IS, "ifrs-full_ProfitLoss", "당기순이익", "분기순이익", "반기순이익")
            inv = _acct(rows, ("BS",), "ifrs-full_Inventories", "재고자산")
            rec = _acct(rows, ("BS",), "ifrs-full_TradeAndOtherCurrentReceivables", "dart_ShortTermTradeReceivable", "매출채권", "매출채권및기타채권")
            ocf = _acct(rows, ("CF",), "ifrs-full_CashFlowsFromUsedInOperatingActivities", "영업활동현금흐름", "영업활동으로인한현금흐름")
            R, R0, C, N = cum(rev), prv(rev), cum(cogs), cum(ni)
            I, I0 = (_n(inv.get("thstrm_amount")), _n(inv.get("frmtrm_amount"))) if inv else (None, None)
            A, A0 = (_n(rec.get("thstrm_amount")), _n(rec.get("frmtrm_amount"))) if rec else (None, None)
            O = _n(ocf.get("thstrm_amount")) if ocf else None
            g = lambda a, b: round((a / b - 1) * 100) if a is not None and b and b > 0 else None  # noqa: E731
            eok = lambda v: round(v / 1e8) if v is not None else None  # noqa: E731
            q = {"period": f"{year}년 {name}", "sales_eok": eok(R), "sales_yoy": g(R, R0), "net_eok": eok(N), "ocf_eok": eok(O),
                 "ocf_to_net": round(O / N, 2) if O is not None and N and N > 0 else None,
                 "inventory_eok": eok(I), "inventory_chg": g(I, I0), "receivable_eok": eok(A), "receivable_chg": g(A, A0),
                 "inventory_days": round(I / C * days) if I and C and C > 0 else None, "receivable_days": round(A / R * days) if A and R and R > 0 else None,
                 "note": "매출·순이익·현금흐름은 그 해 누적(전년 같은 기간 대비), 재고·매출채권은 작년 말 대비", "source": f"DART {year}년 {name}보고서"}
            flags = []
            if q["net_eok"] and q["net_eok"] > 0 and q["ocf_eok"] is not None and q["ocf_eok"] < 0:
                flags.append(f"순이익은 {q['net_eok']:,}억인데 영업으로 들어온 현금은 {q['ocf_eok']:,}억입니다(이익이 아직 현금이 되지 않음).")
            elif q["ocf_to_net"] is not None and q["ocf_to_net"] < 0.5:
                flags.append(f"영업현금흐름이 순이익의 {q['ocf_to_net']:.0%}뿐입니다.")
            for lab, chg in (("재고", q["inventory_chg"]), ("매출채권", q["receivable_chg"])):
                if chg is not None and q["sales_yoy"] is not None and chg - q["sales_yoy"] >= 30 and chg >= 30:
                    flags.append(f"{lab}가 작년 말보다 {chg:+}% 늘어 매출 증가율({q['sales_yoy']:+}%)보다 빠릅니다.")
            q["flags"] = flags
            q["level"] = "주의" if len(flags) >= 2 or (flags and "현금은" in flags[0]) else "확인" if flags else "양호"
            q["line"] = flags[0] if flags else "매출·재고·매출채권·현금흐름 사이에 눈에 띄는 어긋남이 없습니다."
            return q
    return None


def priced(code):
    import fundamentals, naver_quote
    f = fundamentals.fetch(code) or {}
    est = [a for a in f.get("annual") or [] if a.get("e") and a.get("eps")]
    act = [a for a in f.get("annual") or [] if not a.get("e") and a.get("eps") is not None]
    try:
        px = naver_quote.price_all([(code, "")])[0].get("price")
    except Exception:
        px = None
    if not est or not px or est[0]["eps"] <= 0:
        return {"price": px, "line": "추정 EPS가 없어 계산하지 못했습니다(적자이거나 증권사 추정 없음)."}
    e = est[0]
    per = px / e["eps"]
    need = round(((per / NORMAL_PER) ** (1 / YEARS) - 1) * 100)
    grow = round((e["eps"] / act[-1]["eps"] - 1) * 100) if act and act[-1]["eps"] and act[-1]["eps"] > 0 else None
    line = (f"올해 추정 EPS 기준 PER {per:.1f}배입니다. {YEARS}년 뒤 PER이 {NORMAL_PER}배로 내려와도 주가가 제자리이려면 EPS가 해마다 {need:+}%씩 늘어야 합니다."
            if need > 0 else f"올해 추정 EPS 기준 PER {per:.1f}배로, 보통 수준({NORMAL_PER}배)보다 낮아 주가에 큰 성장 기대가 들어 있지 않습니다.")
    return {"price": px, "eps_est": e["eps"], "year": e["p"][:4], "per_est": round(per, 1), "need_growth": need, "eps_growth_this_year": grow,
            "level": "높음" if need >= 25 else "보통" if need >= 10 else "낮음", "line": line,
            "assume": f"가정: {YEARS}년 뒤 PER {NORMAL_PER}배(표시용). 가정을 바꾸면 숫자가 달라집니다.", "source": "네이버 재무·컨센서스 · 현재가 네이버"}


def check(code, name=""):
    out = {"code": code, "name": name, "at": datetime.now(KST).strftime("%Y-%m-%d %H:%M")}
    try:
        out["priced"] = priced(code)
    except Exception as e:
        out["priced"] = {"line": f"계산 실패: {type(e).__name__}"}
    if not os.environ.get("DART_API_KEY"):
        out["note"] = "DART_API_KEY가 없어 희석·이익의 질은 건너뜀"
        return out
    import dart
    corp = dart.corp_codes().get(code)
    if not corp:
        out["note"] = "DART 고유번호 없음"
        return out
    for k, fn in (("dilution", lambda: dilution(corp, (out["priced"] or {}).get("price"))), ("quality", lambda: quality(corp))):
        try:
            out[k] = fn()
        except SystemExit as e:
            out[k] = {"line": f"조회 실패: {e}"}
        except Exception as e:
            out[k] = {"line": f"계산 실패: {type(e).__name__}"}
    return out


def update(top):
    import stock_memo
    T = stock_memo.targets()[:top]
    old = json.loads(OUT.read_text(encoding="utf-8")) if OUT.exists() else {}
    res = dict(old.get("stocks") or {})
    for t in T:
        res[t["code"]] = check(t["code"], t["name"])
    res = {c: v for c, v in res.items() if c in {t["code"] for t in T}}
    OUT.write_text(json.dumps({"at": datetime.now(KST).strftime("%Y-%m-%d %H:%M"), "stocks": res}, ensure_ascii=False, indent=1), encoding="utf-8")
    lv = lambda k: sum(1 for v in res.values() if (v.get(k) or {}).get("level") == "주의")  # noqa: E731
    return {"saved": len(res), "dilution_warn": lv("dilution"), "quality_warn": lv("quality"), "file": str(OUT.relative_to(DATA.parent))}


def main():
    ap = argparse.ArgumentParser(description="종목 점검표: 희석 위험 · 이익의 질 · 주가에 반영된 기대 (토큰 0)")
    sp = ap.add_subparsers(dest="cmd", required=True)
    s = sp.add_parser("show"); s.add_argument("--stock", required=True)
    u = sp.add_parser("update"); u.add_argument("--top", type=int, default=40)
    a = ap.parse_args()
    print(json.dumps(check(a.stock) if a.cmd == "show" else update(a.top), ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
