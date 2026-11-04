"""다가오는 일정 모으기 (Claude 없이). 하루 한 번 받아 data/calendar/events.json 에 쌓는다.

출처
  - 경제지표: ForexFactory 주간 캘린더(공개 JSON, 이번 주) — 미국·중국·한국·일본·유로 '중요(High)' 지표, 한국시간으로 변환
  - 국내 실적·IR: DART 공시 '기업설명회(IR)개최' (최근 30일 공시 → 문서에서 개최 일시 읽음), 시총 2천억↑·기업 메뉴 종목만
  - 미국 실적: Nasdaq 실적 캘린더(공개 API) — 빅테크·반도체 + 관심종목(US)
  - 직접 확인한 일정: config/calendar.toml (FOMC·금통위·만기 등, 출처 기재)
사용법:
    python3 tools/calendar_fetch.py            # 오늘 이미 받았으면 건너뜀
    python3 tools/calendar_fetch.py --force
"""
import argparse
import io
import json
import os
import re
import time
import zipfile
from datetime import datetime, timedelta, timezone

from common import DATA, http_get, load_toml
from naver_quote import KST

OUT = DATA / "calendar"
EV = OUT / "events.json"
IR_CACHE = OUT / "ir_cache.json"
US_MAJOR = ["NVDA", "MSFT", "AAPL", "AMZN", "GOOGL", "META", "AVGO", "TSM", "MU", "AMD", "ORCL", "TSLA", "ASML", "QCOM", "INTC", "SNOW", "PLTR", "CRM", "ADBE", "MRVL"]
FF_COUNTRY = {"USD": "미국", "CNY": "중국", "KRW": "한국", "JPY": "일본", "EUR": "유로존"}
UA = {"User-Agent": "Mozilla/5.0", "Accept": "application/json"}


def get_json(url, params=None):
    return json.loads(http_get(url, params, headers=UA))


def macro(now):
    out = []
    try:
        d = get_json("https://nfs.faireconomy.media/ff_calendar_thisweek.json")
    except Exception as e:
        return out, f"경제지표 실패: {type(e).__name__}"
    for x in d:
        if x.get("impact") != "High" or x.get("country") not in FF_COUNTRY:
            continue
        t = datetime.fromisoformat(x["date"]).astimezone(KST)
        kind = "policy" if re.search(r"Rate|FOMC|Monetary|Fed Chair|Powell|BOJ|ECB|Press Conference", x["title"], re.I) else "macro"
        out.append({"date": t.strftime("%Y-%m-%d"), "time": t.strftime("%H:%M"), "kind": kind,
                    "name": f"{FF_COUNTRY[x['country']]} {x['title']}",
                    "detail": " · ".join(f"{k} {x[k]}" for k in ("forecast", "previous") if x.get(k)).replace("forecast", "예상").replace("previous", "이전"),
                    "source": "ForexFactory 경제 캘린더", "id": f"ff:{x['country']}:{x['title']}:{t:%Y%m%d}"})
    return out, None


def us_earnings(now, days=21):
    want = set(US_MAJOR)
    try:
        from common import watchlist
        want |= {w.get("code") or w.get("symbol") for w in watchlist() if w.get("market") == "US"}
    except Exception:
        pass
    want.discard(None)
    out, err = [], None
    for i in range(days):
        d = now.date() + timedelta(days=i)
        if d.weekday() >= 5:
            continue
        try:
            rows = (get_json("https://api.nasdaq.com/api/calendar/earnings", {"date": d.isoformat()}).get("data") or {}).get("rows") or []
        except Exception as e:
            err = f"미국 실적 일부 실패: {type(e).__name__}"; continue
        for r in rows:
            if r.get("symbol") in want:
                tm = {"time-pre-market": "장전", "time-after-hours": "장마감 후"}.get(r.get("time"), "")
                kst = d + timedelta(days=1) if tm == "장마감 후" else d
                out.append({"date": kst.isoformat(), "time": "", "kind": "earnings_us",
                            "name": f"{r['symbol']} 실적 ({r.get('name', '')[:30]})",
                            "detail": f"미국 {d.isoformat()} {tm} 발표 → 한국시간 {'다음 날 아침' if tm == '장마감 후' else '당일 밤'} · 분기 {r.get('fiscalQuarterEnding', '')} · EPS 예상 {r.get('epsForecast', '-')}",
                            "source": "Nasdaq 실적 캘린더", "symbol": r["symbol"], "id": f"us:{r['symbol']}:{d.isoformat()}"})
        time.sleep(0.3)
    return out, err


def kr_ir(now, days=30):
    key = os.environ.get("DART_API_KEY")
    if not key:
        return [], "DART_API_KEY 없음 → 국내 IR 건너뜀"
    import dart
    from universe import load
    uni = {s["code"]: s for s in load()["stocks"]}
    comp = json.loads((DATA / "companies.json").read_text(encoding="utf-8"))
    cache = json.loads(IR_CACHE.read_text(encoding="utf-8")) if IR_CACHE.exists() else {}
    hits, page = [], 1
    bgn = (now - timedelta(days=days)).strftime("%Y%m%d")
    while True:
        r = dart.api_json("list.json", bgn_de=bgn, end_de=now.strftime("%Y%m%d"), pblntf_ty="I", page_count=100, page_no=page)
        for x in r.get("list", []):
            code = x.get("stock_code") or ""
            if "기업설명회" in x["report_nm"] and code and ((uni.get(code) or {}).get("market_cap_eok", 0) >= 2000 or code in comp):
                hits.append(x)
        if page >= int(r.get("total_page", 1)):
            break
        page += 1
        time.sleep(0.2)
    out = []
    for x in hits:
        no = x["rcept_no"]
        if no not in cache:
            try:
                raw = http_get("https://opendart.fss.or.kr/api/document.xml", {"crtfc_key": key, "rcept_no": no}, timeout=30)
                z = zipfile.ZipFile(io.BytesIO(raw))
                t = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", z.read(z.namelist()[0]).decode("utf-8", "replace")))
                m = re.search(r"일시\s*(20\d\d)[-.년\s]+(\d{1,2})[-.월\s]+(\d{1,2})[일\s]*(\d{1,2}:\d{2})?", t)
                what = re.search(r"주요\s*설명회\s*내용\(?요약\)?\s*(.{0,120}?)\s*\d\.\s", t)
                cache[no] = {"date": f"{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}" if m else None,
                             "time": (m.group(4) or "") if m else "", "what": what.group(1).strip() if what else ""}
            except Exception:
                cache[no] = {"date": None}
            time.sleep(0.2)
        c = cache[no]
        if c.get("date"):
            out.append({"date": c["date"], "time": c.get("time", ""), "kind": "earnings_kr",
                        "name": f"{x['corp_name']} 기업설명회(IR)", "detail": (c.get("what") or "")[:120],
                        "source": "DART 공시", "code": x["stock_code"],
                        "url": f"https://dart.fss.or.kr/dsaf001/main.do?rcpNo={no}", "id": f"ir:{x['stock_code']}:{c['date']}"})
    IR_CACHE.write_text(json.dumps(cache, ensure_ascii=False), encoding="utf-8")
    return out, None


def manual():
    out = []
    for e in (load_toml("calendar.toml") or {}).get("events", []):
        out.append({**e, "id": "m:" + e["date"] + ":" + e["name"]})
    return out


def build(force=False):
    now = datetime.now(KST)
    OUT.mkdir(parents=True, exist_ok=True)
    old = json.loads(EV.read_text(encoding="utf-8")) if EV.exists() else {"events": []}
    if not force and old.get("fetched_at", "")[:10] == now.strftime("%Y-%m-%d"):
        return old
    errs = []
    keep_from = (now - timedelta(days=40)).strftime("%Y-%m-%d")
    # 지난 경제지표·실적도 한 달은 남긴다 (달력에서 지난 날짜도 보도록). 이번에 다시 받은 것이 우선
    ev = {e["id"]: e for e in old.get("events", []) if e.get("date", "") >= keep_from and not e["id"].startswith("m:")}
    for fn in (macro, us_earnings, kr_ir):
        rows, err = fn(now)
        if err:
            errs.append(err)
        for r in rows:
            ev[r["id"]] = r
    for r in manual():
        ev[r["id"]] = r
    data = {"fetched_at": now.strftime("%Y-%m-%d %H:%M"), "errors": errs,
            "events": sorted(ev.values(), key=lambda e: (e["date"], e.get("time", "")))}
    EV.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    return data


def main():
    p = argparse.ArgumentParser(description="다가오는 일정 모으기")
    p.add_argument("--force", action="store_true")
    a = p.parse_args()
    d = build(a.force)
    from collections import Counter
    print(json.dumps({"fetched_at": d["fetched_at"], "errors": d["errors"], "n": len(d["events"]),
                      "by_kind": Counter(e["kind"] for e in d["events"])}, ensure_ascii=False))


if __name__ == "__main__":
    main()
