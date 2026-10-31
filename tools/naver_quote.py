"""네이버 증권 국내 주식 시세 조회. KIS가 클라우드에서 접속되지 않아 대신 쓰는 도구.

공식 API가 아니다(네이버 증권 웹·모바일 화면이 쓰는 주소). robots.txt가 자동 수집을 막고 있으므로
관심종목만, 필요할 때 최소한으로 호출한다. 응답 형식은 예고 없이 바뀔 수 있다.

사용법:
    python3 tools/naver_quote.py price                       # 관심종목(국내) 전체 현재가
    python3 tools/naver_quote.py price --stock 005930        # 특정 종목 (종목코드)
    python3 tools/naver_quote.py investor --stock 005930     # 최근 일별 개인·외국인·기관 순매수 (수량)
    python3 tools/naver_quote.py daily --stock 005930 --days 120   # 일봉 (수정주가)
    python3 tools/naver_quote.py index                       # 코스피·코스닥 지수

출력 형식은 tools/kis_quote.py와 같다 (source, fetched_at, results).
"""
import argparse
import ast
import json
import re
import sys
import time
import urllib.error
from datetime import datetime, timedelta, timezone

from common import http_get, watchlist

POLLING = "https://polling.finance.naver.com/api/realtime/domestic/stock/"
MOBILE = "https://m.stock.naver.com/api/stock/"
SISE = "https://api.finance.naver.com/siseJson.naver"
KST = timezone(timedelta(hours=9))


def num(v):
    """'1,234' '+1,742,739' '46.17%' '9.89배' 같은 문자열을 숫자로. 비어 있으면 None."""
    if v in (None, "", "N/A", "-"):
        return None
    if isinstance(v, (int, float)):
        return v
    s = re.sub(r"[,+%배원\s]", "", str(v))
    try:
        f = float(s)
    except ValueError:
        return None
    return int(f) if f.is_integer() else f


def eok(v):
    """'1,289조 1,044억' → 12891044 (억원 단위)."""
    if not v:
        return None
    jo = re.search(r"([\d,]+)조", v)
    ek = re.search(r"([\d,]+)억", v)
    if not (jo or ek):
        return None
    return (num(jo.group(1)) * 10000 if jo else 0) + (num(ek.group(1)) if ek else 0)


def get_json(url, params=None):
    try:
        return json.loads(http_get(url, params))
    except urllib.error.HTTPError as e:
        sys.exit(f"네이버 증권 조회 실패 (HTTP {e.code}): {url}")
    except urllib.error.URLError as e:
        sys.exit(f"네이버 증권 접속 실패: {e.reason}\n"
                 "403/connect_rejected라면 클라우드 환경 편집 > 네트워크 액세스 > 허용된 도메인을 확인하세요.")


def targets(stock):
    if stock:
        names = {s["code"]: s["name"] for s in watchlist("KR")}
        return [(stock, names.get(stock, ""))]
    return [(s["code"], s["name"]) for s in watchlist("KR")]


def price_all(codes):
    """현재가는 여러 종목을 한 번에 받고, 52주 고저·PER 등은 종목마다 1번씩 받는다."""
    live = {d["itemCode"]: d for d in get_json(POLLING + ",".join(c for c, _ in codes))["datas"]}
    out = []
    for code, name in codes:
        d = live.get(code)
        if not d:
            out.append({"stock": name, "code": code, "error": "네이버 증권에 없는 종목코드"})
            continue
        time.sleep(0.3)
        info = {t["code"]: t for t in get_json(MOBILE + code + "/integration").get("totalInfos", [])}
        val = lambda k: info.get(k, {}).get("value")
        price = num(d.get("closePriceRaw") or d.get("closePrice"))
        # 네이버의 '전일'·등락은 넥스트레이드(NXT) 애프터마켓까지 포함한 값이라 한국거래소(KRX) 종가와 다를 수 있다
        # (예: 2026-10-30 삼성전자 네이버 전일 232,000원, KRX 전일 종가 230,500원). 등락은 KRX 일봉으로 다시 계산한다
        trade_date = (d.get("localTradedAt") or "")[:10].replace("-", "")
        time.sleep(0.3)
        prev = [r for r in daily(code, name, 5)["rows"] if r["date"] < trade_date]
        prev_close = prev[-1]["close"] if prev else None
        change = price - prev_close if (price is not None and prev_close) else None
        out.append({
            "stock": name or d.get("stockName"), "code": code,
            "traded_at": d.get("localTradedAt"),     # 시세 기준 시각 (장 마감 후·휴일에는 마지막 거래일)
            "market_status": d.get("marketStatus"),  # OPEN(장중) / CLOSE(마감)
            # 아래 가격·거래량은 한국거래소(KRX) 기준. 넥스트레이드(NXT) 거래는 빠져 있다
            "price": price,
            "prev_close": prev_close, "prev_date": prev[-1]["date"] if prev else None,  # KRX 전일 종가
            "change": change,
            "change_pct": round(change / prev_close * 100, 2) if change is not None else None,
            "naver_change_pct": num(d.get("fluctuationsRatioRaw") or d.get("fluctuationsRatio")),  # 참고: 네이버 표시값
            "open": num(d.get("openPriceRaw")), "high": num(d.get("highPriceRaw")), "low": num(d.get("lowPriceRaw")),
            "volume": num(d.get("accumulatedTradingVolumeRaw")),
            "value_mil": round(num(d["accumulatedTradingValueRaw"]) / 1e6) if d.get("accumulatedTradingValueRaw") else None,
            "high_52w": num(val("highPriceOf52Weeks")), "low_52w": num(val("lowPriceOf52Weeks")),
            "per": num(val("per")), "pbr": num(val("pbr")),
            "per_basis": info.get("per", {}).get("valueDesc"),   # PER·PBR 계산에 쓴 실적 기준 (예: 2026.06.)
            "est_per": num(val("cnsPer")),            # 증권사 추정치 기준 PER
            "market_cap_eok": eok(val("marketValue")),  # 시가총액 (억원)
            "foreign_ratio": num(val("foreignRate")),   # 외국인 보유 한도 대비 소진율 (%)
        })
    return out


def index_all():
    out = []
    for code in ("KOSPI", "KOSDAQ"):
        d = get_json(MOBILE.replace("/stock/", "/index/") + code + "/basic")
        out.append({
            "index": d.get("stockName") or code, "code": code, "traded_at": d.get("localTradedAt"),
            "price": num(d.get("closePrice")), "change": num(d.get("compareToPreviousClosePrice")),
            "change_pct": num(d.get("fluctuationsRatio")),
        })
        time.sleep(0.3)
    return out


def investor(code, name, days):
    """날짜별 순매수 수량(주, 음수면 순매도). 한 번에 최대 60일. 금액은 제공되지 않는다.
    개인+외국인+기관의 합이 0이 아닌 것은 기타법인 등 나머지 투자자 몫이다."""
    rows, before = [], None
    while len(rows) < days:
        params = {"pageSize": min(60, days - len(rows))}
        if before:
            params["bizdate"] = before  # 이 날짜 이전 데이터
        batch = get_json(MOBILE + code + "/trend", params)
        if not batch:
            break
        for r in batch:
            rows.append({
                "date": r["bizdate"], "close": num(r.get("closePrice")),
                "individual_qty": num(r.get("individualPureBuyQuant")),
                "foreign_qty": num(r.get("foreignerPureBuyQuant")),
                "institution_qty": num(r.get("organPureBuyQuant")),
                "foreign_hold_ratio": num(r.get("foreignerHoldRatio")),  # 외국인 지분율 (%)
            })
        before = batch[-1]["bizdate"]
        time.sleep(0.3)
    return {"stock": name, "code": code, "rows": rows[:days]}


def daily(code, name, days):
    """일봉. 가격은 수정주가(액면분할 등 반영), 거래량은 수정되지 않은 실제 거래량.
    거래정지일(시가·고가·저가가 0)은 뺀다."""
    end = datetime.now(KST)
    start = end - timedelta(days=int(days * 1.5) + 10)  # 휴장일을 고려해 달력 기준으로 넉넉히
    raw = http_get(SISE, {
        "symbol": code, "requestType": 1, "timeframe": "day",
        "startTime": start.strftime("%Y%m%d"), "endTime": end.strftime("%Y%m%d"),
    }).decode("utf-8", "replace")
    table = ast.literal_eval(raw.strip())  # [['날짜','시가',...], ["20260901", 256500, ...], ...]
    rows = []
    for r in table[1:]:
        date, o, h, l, c, v = r[:6]
        if not o and not v:
            continue
        rows.append({"date": date, "open": o, "high": h, "low": l, "close": c, "volume": v})
    return {"stock": name, "code": code, "adjusted_price": True, "rows": rows[-days:]}


def main():
    p = argparse.ArgumentParser(description="네이버 증권 국내 주식 시세 조회 (비공식, 관심종목만 최소 호출)")
    sub = p.add_subparsers(dest="cmd", required=True)
    sp = sub.add_parser("price", help="현재가·52주 고저·PER/PBR·시총·외국인 소진율")
    sp.add_argument("--stock", help="종목코드 6자리 (없으면 관심종목 전체)")
    si = sub.add_parser("investor", help="투자자별 순매수 수량")
    si.add_argument("--stock", help="종목코드 6자리 (없으면 관심종목 전체)")
    si.add_argument("--days", type=int, default=5)
    sd = sub.add_parser("daily", help="일봉")
    sd.add_argument("--stock", required=True, help="종목코드 6자리")
    sd.add_argument("--days", type=int, default=120, help="거래일 수")
    sub.add_parser("index", help="코스피·코스닥 지수")
    a = p.parse_args()

    codes = targets(getattr(a, "stock", None))
    if a.cmd == "index":
        results = index_all()
    elif a.cmd == "price":
        results = price_all(codes)
    else:
        results = []
        for code, name in codes:
            results.append(investor(code, name, a.days) if a.cmd == "investor" else daily(code, name, a.days))
            time.sleep(0.3)
    print(json.dumps({
        "source": "네이버 증권 (비공식)",
        "fetched_at": datetime.now(KST).isoformat(timespec="seconds"),
        "results": results,
    }, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
