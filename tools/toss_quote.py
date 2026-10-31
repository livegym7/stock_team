"""토스증권 Open API 국내 주식 시세 조회. **조회 전용** — 계좌·주문·조건주문 API는 만들지 않는다.

사용법:
    python3 tools/toss_quote.py price                       # 관심종목(국내) 전체 현재가 + 오늘 일봉
    python3 tools/toss_quote.py price --stock 005930        # 특정 종목 (종목코드)
    python3 tools/toss_quote.py investor --stock 005930 --days 5   # 일별 개인·외국인·기관·기타법인 순매수 (수량)
    python3 tools/toss_quote.py daily --stock 005930 --days 120    # 일봉 (기본 수정주가, --raw면 미수정)

필요한 환경 변수: TOSS_CLIENT_ID, TOSS_CLIENT_SECRET
허용 IP: 토스증권 WTS 설정 > Open API > 허용 IP 관리에 등록된 IP에서만 호출된다 (아니면 403).
접근 토큰은 24시간 유효하고 클라이언트당 1개만 살아 있다(새로 받으면 이전 토큰 무효).
그래서 data/cache/에 저장해 재사용한다.

토스가 주지 않는 것: 52주 고저, PER/PBR, 시가총액, 등락률(공식 기준가 대비), 순매수 금액.
→ 이런 값은 tools/naver_quote.py를 쓴다.
문서: https://openapi.tossinvest.com/openapi-docs/latest/openapi.json (v1.2.28 기준으로 작성)
"""
import argparse
import gzip
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone

from common import CACHE, USER_AGENT, require_env, watchlist

BASE = "https://openapi.tossinvest.com"
TOKEN_FILE = CACHE / "toss_token.json"
KST = timezone(timedelta(hours=9))
NAVER_HINT = "토스 Open API에 없는 값입니다. tools/naver_quote.py price를 쓰세요."


def num(v):
    """토스는 숫자를 문자열('71600', '0.5089')로 준다. 정수/실수로 바꾸고, 비어 있으면 None."""
    if v in (None, ""):
        return None
    f = float(v)
    return int(f) if f.is_integer() else f


def read_body(resp):
    """토스는 Accept-Encoding을 안 보내도 gzip으로 압축해 줄 때가 있다."""
    raw = resp.read()
    return gzip.decompress(raw) if raw[:2] == b"\x1f\x8b" else raw


def explain(e):
    """접속 실패 원인을 사용자가 알아볼 수 있게 설명한다. 요청 내용(키·토큰)은 출력하지 않는다."""
    if isinstance(e, urllib.error.HTTPError):
        body = read_body(e).decode("utf-8", "replace")
        try:
            j = json.loads(body)
            err = j.get("error")
            # 토큰 발급은 OAuth2 형식 {"error": "...", "error_description": "..."}, 나머지는 {"error": {"code", "message"}}
            code, msg = (err.get("code"), err.get("message")) if isinstance(err, dict) else (err, j.get("error_description"))
        except ValueError:
            code, msg = None, body[:200]
        hint = ""
        if code in ("ip-not-allowed", "access_denied") or "IP" in str(msg):
            hint = ("\n→ 허용 IP 목록에 없는 곳에서 호출했습니다. 토스증권 WTS 설정 > Open API > 허용 IP 관리에 "
                    "이 컴퓨터의 공인 IP를 등록해야 합니다. 클라우드 세션은 IP가 바뀔 수 있어 맞지 않을 수 있습니다.")
        elif code == "invalid_client":
            hint = "\n→ 앱키(client_id)나 시크릿(client_secret) 값이 틀렸습니다. WTS의 복사 버튼으로 다시 복사해 등록하세요."
        elif code in ("invalid-token", "expired-token", "token-revoked"):
            TOKEN_FILE.unlink(missing_ok=True)
            hint = "\n→ 저장된 토큰이 무효가 되어 지웠습니다. 다시 실행하면 새로 받습니다."
        return f"토스 응답 HTTP {e.code} [{code}]: {msg}{hint}"
    reason = getattr(e, "reason", e)
    if "403" in str(reason) or "connect_rejected" in str(reason):
        return (f"토스 접속 실패: {reason}\n→ 클라우드 환경 편집 > 네트워크 액세스 > 허용된 도메인에 "
                "openapi.tossinvest.com 을 추가하세요.")
    if isinstance(reason, ConnectionResetError) or "reset" in str(reason).lower():
        return f"토스 접속 실패: {reason}\n→ 연결 중 서버가 끊었습니다(해외 IP 차단 가능성)."
    return f"토스 접속 실패: {reason}"


def request(method, path, params=None, data=None, headers=None):
    url = BASE + path + ("?" + urllib.parse.urlencode(params) if params else "")
    req = urllib.request.Request(url, data=data, method=method,
                                 headers={"User-Agent": USER_AGENT, "Accept": "application/json", **(headers or {})})
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            return json.loads(read_body(resp))
    except (urllib.error.URLError, OSError) as e:
        sys.exit(explain(e))


def get_token():
    if TOKEN_FILE.exists():
        saved = json.loads(TOKEN_FILE.read_text(encoding="utf-8"))
        # 만료 10분 전까지는 저장된 토큰을 쓴다 (새로 받으면 이전 토큰이 바로 무효가 되므로 아껴 쓴다)
        if saved.get("expires_at", 0) - 600 > time.time():
            return saved["access_token"]
    cid, secret = require_env("TOSS_CLIENT_ID", "TOSS_CLIENT_SECRET")
    body = urllib.parse.urlencode({"grant_type": "client_credentials", "client_id": cid, "client_secret": secret})
    res = request("POST", "/oauth2/token", data=body.encode(),
                  headers={"Content-Type": "application/x-www-form-urlencoded"})
    if "access_token" not in res:
        sys.exit("토스 토큰 발급 실패: 응답에 access_token이 없습니다.")
    CACHE.mkdir(parents=True, exist_ok=True)
    TOKEN_FILE.touch(mode=0o600)
    os.chmod(TOKEN_FILE, 0o600)
    TOKEN_FILE.write_text(json.dumps({
        "access_token": res["access_token"],
        "expires_at": time.time() + int(res.get("expires_in", 86400)),
    }), encoding="utf-8")
    return res["access_token"]


def api(path, params):
    """시세·종목 정보 조회 (토큰만 필요, 계좌 헤더는 보내지 않는다)."""
    return request("GET", path, params, headers={"Authorization": f"Bearer {get_token()}"})["result"]


def targets(stock):
    if stock:
        names = {s["code"]: s["name"] for s in watchlist("KR")}
        return [(stock, names.get(stock, ""))]
    return [(s["code"], s["name"]) for s in watchlist("KR")]


def candle_row(c):
    return {
        "date": c["timestamp"][:10].replace("-", ""),
        "open": num(c["openPrice"]), "high": num(c["highPrice"]),
        "low": num(c["lowPrice"]), "close": num(c["closePrice"]),
        "volume": num(c["volume"]),
    }


def price_all(codes):
    """현재가는 여러 종목을 한 번에 받는다. 시가·고가·저가·거래량은 종목마다 일봉 2개를 받아 채운다."""
    live = {p["symbol"]: p for p in api("/api/v1/prices", {"symbols": ",".join(c for c, _ in codes)})}
    out = []
    for code, name in codes:
        p = live.get(code)
        if not p:
            out.append({"stock": name, "code": code, "error": "토스에 없는 종목코드"})
            continue
        bars = api("/api/v1/candles", {"symbol": code, "interval": "1d", "count": 2})["candles"]
        today = candle_row(bars[0]) if bars else {}
        prev_close = num(bars[1]["closePrice"]) if len(bars) > 1 else None
        last = num(p["lastPrice"])
        out.append({
            "stock": name, "code": code,
            "traded_at": p.get("timestamp"),   # 마지막 체결 시각 (장 마감 후·휴일에는 마지막 거래일)
            "candle_date": today.get("date"),  # 아래 시가·고가·저가·거래량의 거래일
            # 토스 국내 시세는 KRX+NXT(넥스트레이드) 통합값이다 (네이버 price는 KRX만)
            "price": last,
            # 전일 대비: 전날 일봉 종가 기준. 공식 기준가와 다를 수 있다(토스 FAQ)
            "change": last - prev_close if prev_close is not None else None,
            "change_pct": round((last / prev_close - 1) * 100, 2) if prev_close else None,
            "prev_close": prev_close,
            "open": today.get("open"), "high": today.get("high"), "low": today.get("low"),
            "volume": today.get("volume"),
            "currency": p.get("currency"),
            "not_provided": ["high_52w", "low_52w", "per", "pbr", "market_cap_eok", "foreign_ratio", "value_mil"],
            "not_provided_hint": NAVER_HINT,
        })
        time.sleep(0.1)
    return out


def flow(v):
    return num(v["netBuyVolume"]) if v else None


def investor(code, name, days):
    """날짜별 순매수 수량(주, 음수면 순매도). KRX+NXT 통합, 외국인은 등록외국인 기준. 금액은 제공되지 않는다.
    당일 기록은 장중 잠정치라 개인·기타법인이 비어 있다(당일 저녁 확정)."""
    rows, until = [], None
    while len(rows) < days:
        params = {"count": min(100, days - len(rows))}
        if until:
            params["until"] = until
        res = api(f"/api/v1/stocks/{code}/investor-trading", params)
        for r in res["records"]:
            fh = r.get("foreignerHolding")
            rows.append({
                "date": r["date"].replace("-", ""),
                "individual_qty": flow(r.get("individual")),
                "foreign_qty": flow(r.get("foreigner")),
                "institution_qty": flow(r.get("institution")),
                "other_corp_qty": flow(r.get("otherCorporation")),
                "foreign_hold_ratio": round(num(fh["holdingRate"]) * 100, 2) if fh else None,  # 외국인 지분율 (%)
                "updated_at": r.get("updatedAt"),
            })
        until = res.get("nextUntil")
        if not until or not res["records"]:
            break
        time.sleep(0.15)
    return {"stock": name, "code": code, "rows": rows[:days]}


def daily(code, name, days, adjusted=True):
    """일봉. 한 번에 최대 200개, 그 이상은 이어 받는다. 기본은 수정주가(가격·거래량 모두 조정)."""
    rows, before = [], None
    while len(rows) < days:
        params = {"symbol": code, "interval": "1d", "count": min(200, days - len(rows)),
                  "adjusted": "true" if adjusted else "false"}
        if before:
            params["before"] = before
        res = api("/api/v1/candles", params)
        rows += [candle_row(c) for c in res["candles"]]
        before = res.get("nextBefore")
        if not before or not res["candles"]:
            break
        time.sleep(0.1)
    rows = sorted(rows[:days], key=lambda r: r["date"])  # 토스는 최신순 → 오래된 순으로 바꾼다
    return {"stock": name, "code": code, "adjusted_price": adjusted, "rows": rows}


def main():
    p = argparse.ArgumentParser(description="토스증권 Open API 국내 주식 시세 조회 (조회 전용)")
    sub = p.add_subparsers(dest="cmd", required=True)
    sp = sub.add_parser("price", help="현재가 + 오늘 시가·고가·저가·거래량")
    sp.add_argument("--stock", help="종목코드 6자리 (없으면 관심종목 전체)")
    si = sub.add_parser("investor", help="투자자별 순매수 수량")
    si.add_argument("--stock", help="종목코드 6자리 (없으면 관심종목 전체)")
    si.add_argument("--days", type=int, default=5)
    sd = sub.add_parser("daily", help="일봉")
    sd.add_argument("--stock", required=True, help="종목코드 6자리")
    sd.add_argument("--days", type=int, default=120, help="거래일 수")
    sd.add_argument("--raw", action="store_true", help="수정주가 미적용 (당시 실제 가격·거래량)")
    a = p.parse_args()

    codes = targets(a.stock)
    if a.cmd == "price":
        results = price_all(codes)
    else:
        results = []
        for code, name in codes:
            results.append(investor(code, name, a.days) if a.cmd == "investor"
                           else daily(code, name, a.days, adjusted=not a.raw))
            time.sleep(0.1)
    print(json.dumps({
        "source": "토스증권 Open API (KRX+NXT 통합 시세)",
        "fetched_at": datetime.now(KST).isoformat(timespec="seconds"),
        "results": results,
    }, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
