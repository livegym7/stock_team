"""대시보드용 데이터 파일 만들기 → data/dashboard/<이름>.json (각 파일은 {"rows": [...]} 형식).

대시보드(Claude 아티팩트)는 이 파일들을 그대로 올려서 보여 준다. 숫자는 여기서만 만든다.

    kospi_daily   코스피 일봉 종가 160일 (신호등·차트용)
    market        지수·해외·매크로 지표 타일
    flows         시장 투자자별 순매수 (억원)
    sectors       섹터 ETF 강도 (tools/sector_etf.py)
    industries    네이버 업종 79개 실시간 등락·상승 종목 수
    watch         감시 목록 (data/bus/최근/screener.json)
    running       1stage 진행 중 종목
    channel_mix   최근 24시간 채널 글 분류별 개수 (중복 제외)
    report_dirs   최근 리포트 목표가 상향/하향 건수
    top_news      여러 채널이 다룬 소식 위주 주요 글
    schedule      채널에 올라온 일정 글 (7일)
    disclosures   관심종목 공시 (DART 3일)

사용법:
    python3 tools/dashboard_data.py             # 전부
    python3 tools/dashboard_data.py --collect   # 채널 새 글부터 모으고 전부
    python3 tools/dashboard_data.py --only market flows
"""
import argparse
import json
import re
import sys
import time
from datetime import datetime, timedelta

from common import DATA, ROOT, http_get, watchlist
from naver_quote import KST, num

OUT = DATA / "dashboard"
MOBILE = "https://m.stock.naver.com/api"


def iso(d):
    return f"{d[:4]}-{d[4:6]}-{d[6:8]}" if re.fullmatch(r"\d{8}", d or "") else d


def kospi_daily():
    raw = http_get("https://api.finance.naver.com/siseJson.naver", {
        "symbol": "KOSPI", "requestType": 1, "timeframe": "day",
        "startTime": (datetime.now(KST) - timedelta(days=260)).strftime("%Y%m%d"),
        "endTime": datetime.now(KST).strftime("%Y%m%d")}).decode("utf-8", "replace")
    rows = [{"date": iso(d), "close": float(v.split(",")[3])} for d, v in re.findall(r"\[\"(\d{8})\",\s*([^\]]+)\]", raw)]
    return rows[-160:]


def market():
    rows = []
    for code, name in (("KOSPI", "코스피"), ("KOSDAQ", "코스닥")):
        d = json.loads(http_get(f"{MOBILE}/index/{code}/basic"))
        rows.append({"key": code, "name": name, "group": "국내", "value": num(d["closePrice"]),
                     "change": num(d["compareToPreviousClosePrice"]), "change_pct": num(d["fluctuationsRatio"]),
                     "unit": "pt", "as_of": d.get("localTradedAt", "")[:16], "source": "네이버 증권"})
    from us_quote import quote
    for sym, key, name, group, unit in (
            ("NQ=F", "NQ", "나스닥100 선물", "해외", "pt"), ("^GSPC", "SPX", "S&P 500", "해외", "pt"),
            ("^SOX", "SOX", "美 반도체지수", "해외", "pt"), ("KRW=X", "USDKRW", "원/달러", "매크로", "원"),
            ("CL=F", "WTI", "WTI 유가", "매크로", "$"), ("^TNX", "UST10", "미 10년물 금리", "매크로", "%"),
            ("^VIX", "VIX", "VIX 공포지수", "매크로", "pt")):
        q = quote(sym, name, "rate" if key == "UST10" else "index")
        rows.append({"key": key, "name": name, "group": group, "value": q["price"], "change": q["change"],
                     "change_pct": q["change_pct"], "unit": unit, "as_of": q["traded_at_kst"][:16],
                     "source": "Yahoo Finance (지연 가능)"})
        time.sleep(0.2)
    return rows


def flows():
    rows = []
    for code, name in (("KOSPI", "코스피"), ("KOSDAQ", "코스닥")):
        d = json.loads(http_get(f"{MOBILE}/index/{code}/trend"))
        for k, inv in (("personalValue", "개인"), ("foreignValue", "외국인"), ("institutionalValue", "기관")):
            rows.append({"market": name, "investor": inv, "value_eok": num(d[k]), "date": iso(d["bizdate"])})
    return rows


def sectors():
    from sector_etf import run
    r = run()
    b = r["benchmark"]
    rows = [{"sector": "시장 (기준)", "etf": b["etf"], "rs_score": 0, **{k: b[k] for k in b if k != "etf"}}]
    rows += r["results"]
    for x in rows:
        x["date"] = iso(x["date"])
    return rows


def industries():
    g = json.loads(http_get(f"{MOBILE}/stocks/industry", {"page": 1, "pageSize": 100}))["groups"]
    t = datetime.now(KST).strftime("%Y-%m-%d %H:%M")
    return [{"name": x["name"], "change_pct": num(x["changeRate"]), "rise": x["riseCount"], "fall": x["fallCount"],
             "total": x["totalCount"], "rise_ratio": round(x["riseCount"] / x["totalCount"], 3), "time": t} for x in g]


def _screener():
    files = sorted((ROOT / "data" / "bus").glob("*/screener.json"))
    if not files:
        return None
    return json.loads(files[-1].read_text(encoding="utf-8"))


def watch():
    s = _screener()
    if not s:
        return []
    rows = []
    for r in s["watch"]:
        lv = r.get("levels") or {}
        if not lv:
            continue
        status = "신호" if r["gate_pass"] and ("G" in r["today"] or ("돌파" in r["today"] and set(r["setups"]) & set("ABCDE"))) \
            else "임박" if r["close"] >= lv["alert"] else "대기"
        rows.append({"code": r["code"], "stock": r["stock"], "sector": r["sector"], "status": status,
                     "close": r["close"], "alert": lv["alert"], "breakout": lv["breakout"],
                     "distance_pct": lv["distance_pct"], "stop_1r": lv["stop_1r"],
                     "setups": ",".join(r["setups"]), "today": ",".join(r["today"]), "rs": r["rs"],
                     "date": iso(r["date"])})
    return sorted(rows, key=lambda x: x["distance_pct"])


def running():
    s = _screener()
    if not s:
        return []
    return [{"code": r["code"], "stock": r["stock"], "sector": r["sector"], "close": r["close"],
             "run_pct": r.get("run_pct"), "off_high_pct": r["off_high_pct"], "value20_eok": r["value20_eok"],
             "rs": r["rs"], "date": iso(r["date"])} for r in s.get("running", [])[:15]]


def _posts(hours):
    from tg_channel import recent_posts
    return recent_posts(hours)


def channel_mix():
    from tg_channel import CATEGORIES
    posts = _posts(24)
    out = []
    for k, label in CATEGORIES.items():
        if k == "other":
            continue
        out.append({"category": k, "label": label, "count": sum(1 for p in posts if p["type"] == k)})
    return out


def report_dirs():
    posts = [p for p in _posts(36) if p["type"] == "report" and p.get("direction") in ("상향", "하향")]
    return [{"direction": d, "count": sum(1 for p in posts if p["direction"] == d)} for d in ("상향", "하향")]


def top_news():
    from tg_channel import CATEGORIES
    posts = [p for p in _posts(24) if p["type"] in ("macro", "policy", "earnings", "company", "market")]
    posts.sort(key=lambda p: (len(p.get("also_in", [])), p["time"]), reverse=True)
    out = []
    for p in posts[:12]:
        lines = [x.strip() for x in re.sub(r"https?://\S+", "", p["text"]).split("\n") if x.strip()]
        while lines and re.fullmatch(r"[\d.:\-\s]+", lines[0]):  # 첫 줄이 시각뿐이면 건너뜀
            lines.pop(0)
        first = " · ".join(lines[:2]) if lines and len(lines[0]) < 25 else (lines[0] if lines else "")
        first = re.sub(r"^\s*(✅|속보\s*:|\[속보\])\s*", "", first)[:90]
        out.append({"id": f"{p['channel']}/{p['id']}", "time": p["time"][:16].replace("T", " "),
                    "category": CATEGORIES[p["type"]], "channels": 1 + len(p.get("also_in", [])),
                    "title": first, "url": p["url"]})
    return out


def schedule():
    posts = [p for p in _posts(24 * 7) if p["type"] == "schedule"]
    return [{"id": f"{p['channel']}/{p['id']}", "time": p["time"][:16].replace("T", " "),
             "title": re.sub(r"https?://\S+", "", p["text"]).strip().split("\n")[0][:80],
             "text": re.sub(r"https?://\S+", "", p["text"]).strip()[:400], "url": p["url"]} for p in reversed(posts)][:8]


def disclosures():
    from dart import disclosures as dl
    rows = []
    for s in watchlist("KR"):
        for d in dl(s["code"], s["name"], 3):
            rows.append({"id": d["url"].rsplit("=", 1)[-1], "stock": d["stock"], "date": iso(d["date"]),
                         "title": d["title"], "important": d["important"], "url": d["url"]})
    return rows


BUILDERS = {f.__name__: f for f in (kospi_daily, market, flows, sectors, industries, watch, running,
                                     channel_mix, report_dirs, top_news, schedule, disclosures)}


def main():
    p = argparse.ArgumentParser(description="대시보드용 데이터 파일 만들기")
    p.add_argument("--collect", action="store_true", help="텔레그램 채널 새 글부터 모으기")
    p.add_argument("--only", nargs="*", choices=list(BUILDERS))
    a = p.parse_args()
    if a.collect:
        from tg_channel import collect_all
        collect_all()
    OUT.mkdir(parents=True, exist_ok=True)
    made_at = datetime.now(KST).isoformat(timespec="seconds")
    summary = {}
    for name in a.only or BUILDERS:
        try:
            rows = BUILDERS[name]()
        except SystemExit as e:  # 환경 변수 없음 등
            summary[name] = f"건너뜀: {e}"
            continue
        except Exception as e:
            summary[name] = f"실패: {type(e).__name__}: {e}"
            continue
        (OUT / f"{name}.json").write_text(json.dumps({"made_at": made_at, "rows": rows}, ensure_ascii=False, indent=1),
                                          encoding="utf-8")
        summary[name] = len(rows)
    print(json.dumps({"made_at": made_at, "out": str(OUT.relative_to(ROOT)), "rows": summary}, ensure_ascii=False, indent=1))
    if any(isinstance(v, str) for v in summary.values()):
        sys.exit(1)


if __name__ == "__main__":
    main()
