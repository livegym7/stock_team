"""한국투자증권(KIS) Open API 시세 조회. **조회 전용** — 주문 관련 API는 만들지 않는다.

사용법:
    python3 tools/kis_quote.py price                       # 관심종목(국내) 전체 현재가
    python3 tools/kis_quote.py price --stock 005930        # 특정 종목 (종목코드)
    python3 tools/kis_quote.py investor --stock 005930     # 최근 일별 개인·외국인·기관 순매수
    python3 tools/kis_quote.py daily --stock 005930 --days 120   # 일봉 (시가·고가·저가·종가·거래량)

필요한 환경 변수: KIS_APP_KEY, KIS_APP_SECRET
접근 토큰은 하루(24시간) 유효하고 너무 자주 새로 받으면 제한이 걸리므로 data/cache/에 저장해 재사용한다.
"""
import argparse
import json
import os
import sys
import time
import urllib.error
from datetime import datetime, timedelta

from common import CACHE, http_get, http_post_json, require_env, watchlist

BASE = "https://openapi.koreainvestment.com:9443"
TOKEN_FILE = CACHE / "kis_token.json"


def num(v):
    """KIS는 숫자를 문자열로 준다. 정수/실수로 바꾸고, 비어 있으면 None."""
    if v in (None, ""):
        return None
    f = float(v)
    return int(f) if f.is_integer() else f


def get_token():
    if TOKEN_FILE.exists():
        saved = json.loads(TOKEN_FILE.read_text(encoding="utf-8"))
        # 만료 10분 전까지는 저장된 토큰을 쓴다
        if saved.get("expires_at", 0) - 600 > time.time():
            return saved["access_token"]
    key, secret = require_env("KIS_APP_KEY", "KIS_APP_SECRET")
    try:
        res = http_post_json(
            f"{BASE}/oauth2/tokenP",
            {"grant_type": "client_credentials", "appkey": key, "appsecret": secret},
        )
    except urllib.error.HTTPError as e:
        # 응답 본문에는 키가 들어 있지 않다. 상태 코드와 설명만 보여준다
        sys.exit(f"KIS 토큰 발급 실패 (HTTP {e.code}): {e.read().decode('utf-8', 'replace')}")
    if "access_token" not in res:
        sys.exit(f"KIS 토큰 발급 실패: {res.get('error_description') or res}")
    CACHE.mkdir(parents=True, exist_ok=True)
    TOKEN_FILE.write_text(json.dumps({
        "access_token": res["access_token"],
        "expires_at": time.time() + int(res.get("expires_in", 86400)),
    }), encoding="utf-8")
    os.chmod(TOKEN_FILE, 0o600)
    return res["access_token"]


def quote_api(path, tr_id, params):
    key, secret = require_env("KIS_APP_KEY", "KIS_APP_SECRET")
    headers = {
        "authorization": f"Bearer {get_token()}",
        "appkey": key,
        "appsecret": secret,
        "tr_id": tr_id,
        "custtype": "P",
    }
    try:
        res = json.loads(http_get(f"{BASE}{path}", params, headers=headers))
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", "replace")
        if "EGW00123" in body:  # 토큰 만료 → 저장된 토큰을 지우고 다시 실행하게 한다
            TOKEN_FILE.unlink(missing_ok=True)
            sys.exit("KIS 접근 토큰이 만료되었습니다. 다시 실행해 주세요.")
        sys.exit(f"KIS 조회 실패 (HTTP {e.code}): {body}")
    if res.get("rt_cd") != "0":
        sys.exit(f"KIS 오류 {res.get('msg_cd')}: {res.get('msg1')}")
    return res


def targets(stock):
    if stock:
        names = {s["code"]: s["name"] for s in watchlist("KR")}
        return [(stock, names.get(stock, ""))]
    return [(s["code"], s["name"]) for s in watchlist("KR")]


def price(code, name):
    o = quote_api(
        "/uapi/domestic-stock/v1/quotations/inquire-price", "FHKST01010100",
        {"FID_COND_MRKT_DIV_CODE": "J", "FID_INPUT_ISCD": code},
    )["output"]
    return {
        "stock": name, "code": code,
        "price": num(o["stck_prpr"]),           # 현재가 (장 마감 후·휴일에는 마지막 종가)
        "change": num(o["prdy_vrss"]),          # 전일 대비 (원)
        "change_pct": num(o["prdy_ctrt"]),      # 등락률 (%)
        "open": num(o["stck_oprc"]), "high": num(o["stck_hgpr"]), "low": num(o["stck_lwpr"]),
        "volume": num(o["acml_vol"]),           # 거래량 (주)
        "value_mil": round(num(o["acml_tr_pbmn"]) / 1e6) if o.get("acml_tr_pbmn") else None,  # 거래대금 (백만원)
        "high_52w": num(o["w52_hgpr"]), "low_52w": num(o["w52_lwpr"]),
        "per": num(o.get("per")), "pbr": num(o.get("pbr")),
        "market_cap_eok": num(o.get("hts_avls")),   # 시가총액 (억원)
        "foreign_ratio": num(o.get("hts_frgn_ehrt")),  # 외국인 보유 비율 (%)
    }


def investor(code, name, days):
    rows = quote_api(
        "/uapi/domestic-stock/v1/quotations/inquire-investor", "FHKST01010900",
        {"FID_COND_MRKT_DIV_CODE": "J", "FID_INPUT_ISCD": code},
    )["output"]
    out = []
    for r in rows[:days]:
        if not r.get("frgn_ntby_qty"):  # 장중에는 오늘 줄이 비어 있다 (장 마감 후 채워짐)
            continue
        out.append({
            "date": r["stck_bsop_date"], "close": num(r["stck_clpr"]),
            # 순매수 수량 (주, 음수면 순매도)
            "individual_qty": num(r["prsn_ntby_qty"]),
            "foreign_qty": num(r["frgn_ntby_qty"]),
            "institution_qty": num(r["orgn_ntby_qty"]),
            # 순매수 금액 (백만원)
            "individual_mil": num(r.get("prsn_ntby_tr_pbmn")),
            "foreign_mil": num(r.get("frgn_ntby_tr_pbmn")),
            "institution_mil": num(r.get("orgn_ntby_tr_pbmn")),
        })
    return {"stock": name, "code": code, "rows": out}


def daily(code, name, days):
    """일봉. 한 번에 최대 100개라서 기간을 나눠서 여러 번 받는다. 수정주가 기준."""
    end = datetime.now()
    start = end - timedelta(days=int(days * 1.5) + 10)  # 휴장일을 고려해 달력 기준으로 넉넉히
    rows, cur_end = {}, end
    while cur_end >= start:
        res = quote_api(
            "/uapi/domestic-stock/v1/quotations/inquire-daily-itemchartprice", "FHKST03010100",
            {
                "FID_COND_MRKT_DIV_CODE": "J", "FID_INPUT_ISCD": code,
                "FID_INPUT_DATE_1": start.strftime("%Y%m%d"), "FID_INPUT_DATE_2": cur_end.strftime("%Y%m%d"),
                "FID_PERIOD_DIV_CODE": "D", "FID_ORG_ADJ_PRC": "0",
            },
        )
        batch = [r for r in res.get("output2", []) if r.get("stck_bsop_date")]
        if not batch:
            break
        for r in batch:
            rows[r["stck_bsop_date"]] = {
                "date": r["stck_bsop_date"],
                "open": num(r["stck_oprc"]), "high": num(r["stck_hgpr"]),
                "low": num(r["stck_lwpr"]), "close": num(r["stck_clpr"]),
                "volume": num(r["acml_vol"]),
            }
        oldest = min(r["stck_bsop_date"] for r in batch)
        if len(batch) < 100:
            break
        cur_end = datetime.strptime(oldest, "%Y%m%d") - timedelta(days=1)
        time.sleep(0.1)  # 초당 호출 제한 대비
    ordered = sorted(rows.values(), key=lambda r: r["date"])[-days:]
    return {"stock": name, "code": code, "rows": ordered}


def main():
    p = argparse.ArgumentParser(description="KIS 국내 주식 시세 조회 (조회 전용)")
    sub = p.add_subparsers(dest="cmd", required=True)
    sp = sub.add_parser("price", help="현재가")
    sp.add_argument("--stock", help="종목코드 6자리 (없으면 관심종목 전체)")
    si = sub.add_parser("investor", help="투자자별 순매수")
    si.add_argument("--stock", help="종목코드 6자리 (없으면 관심종목 전체)")
    si.add_argument("--days", type=int, default=5)
    sd = sub.add_parser("daily", help="일봉")
    sd.add_argument("--stock", required=True, help="종목코드 6자리")
    sd.add_argument("--days", type=int, default=120, help="거래일 수")
    a = p.parse_args()

    results = []
    for code, name in targets(a.stock):
        if a.cmd == "price":
            results.append(price(code, name))
        elif a.cmd == "investor":
            results.append(investor(code, name, a.days))
        else:
            results.append(daily(code, name, a.days))
        time.sleep(0.1)
    print(json.dumps({
        "source": "한국투자증권 Open API",
        "fetched_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "results": results,
    }, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
