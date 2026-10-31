"""DART(금융감독원 전자공시) 조회.

사용법:
    python3 tools/dart.py list --days 3                 # 관심종목 전체의 최근 3일 공시
    python3 tools/dart.py list --stock 005930 --days 7  # 특정 종목 (종목코드)
    python3 tools/dart.py fin --stock 005930 --year 2026 --quarter 3   # 주요 재무 (분기)

필요한 환경 변수: DART_API_KEY
"""
import argparse
import io
import json
import sys
import xml.etree.ElementTree as ET
import zipfile
from datetime import datetime, timedelta

from common import CACHE, http_get, require_env, watchlist

API = "https://opendart.fss.or.kr/api"
# 제목에 이 단어가 들어가면 중요 공시로 표시
IMPORTANT = [
    "잠정", "실적", "유상증자", "무상증자", "감자", "전환사채", "신주인수권", "교환사채",
    "자기주식", "최대주주", "합병", "분할", "공급계약", "소송", "횡령", "배임", "거래정지", "상장폐지",
]
REPORT_CODES = {1: "11013", 2: "11012", 3: "11014", 4: "11011"}  # 1분기, 반기, 3분기, 사업보고서


def api_json(path, **params):
    (key,) = require_env("DART_API_KEY")
    res = json.loads(http_get(f"{API}/{path}", {"crtfc_key": key, **params}))
    status = res.get("status")
    if status == "013":  # 조회된 데이터 없음
        return {"list": []}
    if status != "000":
        sys.exit(f"DART 오류 {status}: {res.get('message')}")
    return res


def corp_codes():
    """종목코드(6자리) -> DART 고유번호(8자리) 표. 파일이 커서(약 3.6MB, 클라우드에서 수 분) 7일에 한 번만 내려받는다."""
    path = CACHE / "dart_corp_codes.json"
    if path.exists() and datetime.now().timestamp() - path.stat().st_mtime < 7 * 86400:
        return json.loads(path.read_text(encoding="utf-8"))
    (key,) = require_env("DART_API_KEY")
    print("DART 회사 코드표를 내려받는 중입니다 (몇 분 걸릴 수 있음)...", file=sys.stderr)
    try:
        raw = http_get(f"{API}/corpCode.xml", {"crtfc_key": key}, timeout=60)
    except OSError as e:
        if path.exists():  # 새로 못 받으면 예전 표라도 쓴다
            print(f"코드표 갱신 실패({e}), 저장된 표를 사용합니다.", file=sys.stderr)
            return json.loads(path.read_text(encoding="utf-8"))
        raise
    with zipfile.ZipFile(io.BytesIO(raw)) as z:
        root = ET.fromstring(z.read(z.namelist()[0]))
    table = {}
    for c in root.iter("list"):
        stock = (c.findtext("stock_code") or "").strip()
        if stock:
            table[stock] = c.findtext("corp_code").strip()
    CACHE.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(table), encoding="utf-8")
    return table


def disclosures(stock, name, days):
    corp = corp_codes().get(stock)
    if not corp:
        sys.exit(f"DART에서 종목코드 {stock}를 찾지 못했습니다.")
    end = datetime.now()
    res = api_json(
        "list.json", corp_code=corp, page_count=100,
        bgn_de=(end - timedelta(days=days)).strftime("%Y%m%d"), end_de=end.strftime("%Y%m%d"),
    )
    out = []
    for d in res["list"]:
        title = d["report_nm"].strip()
        out.append({
            "stock": name or d["corp_name"],
            "date": d["rcept_dt"],
            "title": title,
            "filer": d["flr_nm"],
            "important": any(k in title for k in IMPORTANT),
            "url": f"https://dart.fss.or.kr/dsaf001/main.do?rcpNo={d['rcept_no']}",
        })
    return out


def financials(stock, year, quarter):
    corp = corp_codes().get(stock)
    res = api_json("fnlttSinglAcnt.json", corp_code=corp, bsns_year=str(year), reprt_code=REPORT_CODES[quarter])
    keep = {"매출액", "영업이익", "당기순이익", "자산총계", "부채총계", "자본총계"}
    rows = [r for r in res["list"] if r.get("fs_div") == "CFS" and r["account_nm"] in keep]  # 연결재무제표 기준
    return [
        {"account": r["account_nm"], "current": r.get("thstrm_amount"), "previous": r.get("frmtrm_amount"),
         "period": r.get("thstrm_nm")}
        for r in rows
    ]


def main():
    p = argparse.ArgumentParser(description="DART 공시 조회")
    sub = p.add_subparsers(dest="cmd", required=True)
    l = sub.add_parser("list")
    l.add_argument("--stock", help="종목코드 (없으면 관심종목 전체)")
    l.add_argument("--days", type=int, default=3)
    f = sub.add_parser("fin")
    f.add_argument("--stock", required=True)
    f.add_argument("--year", type=int, required=True)
    f.add_argument("--quarter", type=int, choices=[1, 2, 3, 4], required=True)
    a = p.parse_args()

    if a.cmd == "list":
        targets = [(a.stock, None)] if a.stock else [(s["code"], s["name"]) for s in watchlist("KR")]
        out = [d for code, name in targets for d in disclosures(code, name, a.days)]
    else:
        out = financials(a.stock, a.year, a.quarter)
    print(json.dumps(out, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
