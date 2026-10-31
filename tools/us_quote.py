"""해외(미국) 시세 조회: 주요 지수, 관심종목(US), 원/달러 환율, 미 10년물 금리, VIX.

Yahoo Finance 차트 API(query1.finance.yahoo.com/v8/finance/chart)를 표준 라이브러리로 직접 부른다.
yfinance 패키지가 내부에서 쓰는 것과 같은 주소다. 공식 공개 API가 아니므로 응답 형식이 바뀔 수 있고,
지수·주가는 거래소 기준으로 약 15분 늦을 수 있다.

사용법:
    python3 tools/us_quote.py price                    # 지수·환율·금리·VIX + 관심종목(US) 전체
    python3 tools/us_quote.py price --symbol NVDA      # 특정 종목 (야후 티커)
    python3 tools/us_quote.py daily --symbol ^GSPC --days 60   # 일봉

출력 형식은 다른 시세 도구와 같다 (source, fetched_at, results).
"""
import argparse
import json
import sys
import time
import urllib.error
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from common import http_get, watchlist

CHART = "https://query1.finance.yahoo.com/v8/finance/chart/"
KST = timezone(timedelta(hours=9))

# 기본으로 보는 시장 지표 (야후 티커, 한글 이름, 분류)
MARKET = [
    ("^GSPC", "S&P 500", "index"),
    ("^IXIC", "나스닥 종합", "index"),
    ("^DJI", "다우존스", "index"),
    ("^SOX", "필라델피아 반도체", "index"),
    ("KRW=X", "원/달러 환율", "fx"),
    ("^TNX", "미 10년물 국채 금리(%)", "rate"),
    ("^VIX", "VIX 변동성 지수", "volatility"),
]


def get_chart(symbol, params):
    try:
        d = json.loads(http_get(CHART + symbol, params))
    except urllib.error.HTTPError as e:
        sys.exit(f"야후 파이낸스 조회 실패 (HTTP {e.code}): {symbol}")
    except urllib.error.URLError as e:
        sys.exit(f"야후 파이낸스 접속 실패: {e.reason}")
    res = (d.get("chart") or {}).get("result")
    if not res:
        return None
    return res[0]


def bars(r):
    """[(날짜(거래소 현지), 시가, 고가, 저가, 종가, 거래량), ...] — 종가가 없는 줄은 뺀다."""
    tz = ZoneInfo(r["meta"].get("exchangeTimezoneName") or "America/New_York")
    q = r["indicators"]["quote"][0]
    out = []
    for i, ts in enumerate(r.get("timestamp") or []):
        if q["close"][i] is None:
            continue
        out.append((datetime.fromtimestamp(ts, tz).date().isoformat(),
                    q["open"][i], q["high"][i], q["low"][i], q["close"][i], q["volume"][i]))
    return out


def rnd(v, n=2):
    return None if v is None else round(v, n)


def quote(symbol, name, kind):
    r = get_chart(symbol, {"range": "1mo", "interval": "1d"})
    if not r:
        return {"symbol": symbol, "name": name, "error": "야후 파이낸스에 없는 티커"}
    m = r["meta"]
    tz = ZoneInfo(m.get("exchangeTimezoneName") or "America/New_York")
    t = datetime.fromtimestamp(m["regularMarketTime"], tz)
    price = m.get("regularMarketPrice")
    # 전일 종가 = 기준 시각 날짜보다 앞선 마지막 일봉 종가 (meta의 chartPreviousClose는 기간 시작 전 값이라 쓰지 않음)
    prev = [b for b in bars(r) if b[0] < t.date().isoformat()]
    prev_close = prev[-1][4] if prev else None
    change = price - prev_close if (price is not None and prev_close) else None
    return {
        "symbol": symbol, "name": name or m.get("shortName"), "kind": kind,
        "currency": m.get("currency"),
        "traded_at": t.isoformat(timespec="minutes"),                      # 시세 기준 시각 (거래소 현지)
        "traded_at_kst": t.astimezone(KST).isoformat(timespec="minutes"),  # 같은 시각, 한국시간
        "price": rnd(price, 4 if kind == "rate" else 2),
        "prev_close": rnd(prev_close, 4 if kind == "rate" else 2),
        "prev_date": prev[-1][0] if prev else None,
        # 금리는 %포인트 차이(change)가 더 의미 있다. 4.93 → 4.99 면 +0.06%p
        "change": rnd(change, 4 if kind == "rate" else 2),
        "change_pct": rnd(change / prev_close * 100) if change is not None else None,
        "day_high": rnd(m.get("regularMarketDayHigh")), "day_low": rnd(m.get("regularMarketDayLow")),
        "volume": m.get("regularMarketVolume") or None,
        "high_52w": rnd(m.get("fiftyTwoWeekHigh")), "low_52w": rnd(m.get("fiftyTwoWeekLow")),
    }


def daily(symbol, days):
    r = get_chart(symbol, {"range": "2y" if days > 250 else "1y", "interval": "1d"})
    if not r:
        return {"symbol": symbol, "error": "야후 파이낸스에 없는 티커"}
    rows = [{"date": d, "open": rnd(o), "high": rnd(h), "low": rnd(l), "close": rnd(c), "volume": v}
            for d, o, h, l, c, v in bars(r)]
    # 마지막 줄은 장중이면 아직 확정되지 않은 값이다
    return {"symbol": symbol, "name": r["meta"].get("shortName"), "adjusted_price": False,
            "rows": rows[-days:]}


def main():
    p = argparse.ArgumentParser(description="해외 시세 조회 (Yahoo Finance 차트 API, 비공식)")
    sub = p.add_subparsers(dest="cmd", required=True)
    sp = sub.add_parser("price", help="지수·환율·금리·VIX·관심종목(US) 현재가")
    sp.add_argument("--symbol", help="야후 티커 (없으면 시장 지표 + 관심종목(US) 전체)")
    sd = sub.add_parser("daily", help="일봉")
    sd.add_argument("--symbol", required=True)
    sd.add_argument("--days", type=int, default=60, help="거래일 수 (최대 약 500)")
    a = p.parse_args()

    if a.cmd == "daily":
        results = [daily(a.symbol, a.days)]
    else:
        if a.symbol:
            items = [(a.symbol, None, "stock")]
        else:
            items = MARKET + [(s["code"], s["name"], "stock") for s in watchlist("US")]
        results = []
        for sym, name, kind in items:
            results.append(quote(sym, name, kind))
            time.sleep(0.2)
    print(json.dumps({
        "source": "Yahoo Finance (비공식, 지연 시세일 수 있음)",
        "fetched_at": datetime.now(KST).isoformat(timespec="seconds"),
        "results": results,
    }, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
