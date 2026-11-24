#!/usr/bin/env python3
"""지금 보는 것 두 가지 (2026-11-24 사용자 요청, 표시만 — 매매 규칙 아님, Claude 토큰 0).

1) night: 나스닥 100 선물(네이버 해외선물, 10분 지연) + EWY(미국 상장 한국 ETF, 야후 — 정규장 밖이면 시간외 가격)
   코스피 야간선물은 무료로 받을 곳을 찾지 못해 EWY로 대신한다.
2) hot: 네이버 검색 상위 30종목 — 지금 주목받는 종목. 화면이 내 업종 분류로 묶어 보여 준다(종목 › 주목).

화면이 열려 있는 동안에는 Cloudflare 함수(functions/api/quote.js ?night=1&hot=1)가 같은 값을 1분마다 준다.
이 도구는 웹을 만들 때 넣는 첫 값이다.

사용법:
    python3 tools/hot_now.py night
    python3 tools/hot_now.py hot
"""
import json
import sys
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
KST = timezone(timedelta(hours=9))
UA = {"User-Agent": "Mozilla/5.0", "Referer": "https://m.stock.naver.com/"}
NQ = "https://polling.finance.naver.com/api/realtime/worldstock/futures/NQcv1"
EWY = "https://query1.finance.yahoo.com/v8/finance/chart/EWY?interval=5m&range=1d&includePrePost=true"
TOP = "https://m.stock.naver.com/api/stocks/searchTop/all?page=1&pageSize=30"


def _get(url):
    return json.load(urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=15))


def _num(s):
    try:
        return float(str(s).replace(",", ""))
    except (TypeError, ValueError):
        return None


def _kst(iso):
    try:
        return datetime.fromisoformat(iso).astimezone(KST).strftime("%Y-%m-%d %H:%M")
    except (TypeError, ValueError):
        return ""


def ewy_from_chart(j):
    """야후 차트 응답 → {price, change_pct, at, session}. 정규장이면 전일 종가 대비, 정규장 밖이면 마지막 정규장 종가 대비."""
    r = j["chart"]["result"][0]
    m, ts, cl = r["meta"], r.get("timestamp") or [], (r["indicators"]["quote"][0].get("close") or [])
    last = next(((t, c) for t, c in zip(reversed(ts), reversed(cl)) if c), None)
    if not last:
        return None
    t, px = last
    reg = (m.get("currentTradingPeriod") or {}).get("regular") or {}
    inreg = reg.get("start", 0) <= t < reg.get("end", 0)
    base = m.get("chartPreviousClose") if inreg else m.get("regularMarketPrice")
    return {"price": round(px, 2), "change_pct": round((px / base - 1) * 100, 2) if base else None,
            "at": datetime.fromtimestamp(t, KST).strftime("%Y-%m-%d %H:%M"), "session": "정규장" if inreg else "시간외"}


def night():
    out = {"at": datetime.now(KST).strftime("%Y-%m-%d %H:%M"), "source": "네이버 해외선물(10분 지연) · Yahoo Finance(비공식)"}
    try:
        x = _get(NQ)["datas"][0]
        out["nq"] = {"price": _num(x.get("closePrice")), "change_pct": _num(x.get("fluctuationsRatio")), "status": x.get("marketStatus"),
                     "at": _kst(x.get("localTradedAt")), "delay": (x.get("stockExchangeType") or {}).get("delayTime")}
    except Exception as e:
        out["nq_error"] = str(e)[:80]
    try:
        out["ewy"] = ewy_from_chart(_get(EWY))
    except Exception as e:
        out["ewy_error"] = str(e)[:80]
    return out


def hot():
    """검색 상위 30. 업종(g) = 내 분류(sector_map) 먼저, 없으면 네이버 업종. rs = 레이더의 RS(있을 때)."""
    from sector_map import custom_map
    from universe import load
    cm, uni = custom_map(), {u["code"]: u for u in load()["stocks"]}
    try:
        rs = json.loads((Path(__file__).resolve().parent.parent / "data" / "radar" / "company_rs.json").read_text())
    except Exception:
        rs = {}
    items = []
    for i, s in enumerate(_get(TOP).get("stocks") or []):
        c = s.get("itemCode")
        if s.get("stockEndType") != "stock" or not c:
            continue
        items.append({"rank": i + 1, "code": c, "name": s.get("stockName"), "price": _num(s.get("closePrice")), "chg": _num(s.get("fluctuationsRatio")),
                      "value_eok": round((_num(s.get("accumulatedTradingValue")) or 0) / 100), "g": cm.get(c) or (uni.get(c) or {}).get("industry") or "",
                      "rs": (rs.get(c) or {}).get("rs")})
    return {"made_at": datetime.now(KST).strftime("%Y-%m-%d %H:%M"), "source": "네이버 금융 검색 상위(비공식)", "items": items}


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "night"
    print(json.dumps(night() if cmd == "night" else hot(), ensure_ascii=False, indent=1))
