"""국내 상장 종목 목록 (이름·코드·네이버 업종). 채널 글에서 종목 이름을 찾거나 업종을 붙일 때 쓴다.

네이버 업종 79개의 소속 종목을 모아 data/cache/universe.json에 저장한다 (7일간 재사용).
공식 API가 아니므로 일주일에 한 번 정도만 받는다.

사용법:
    python3 tools/universe.py            # 캐시가 없거나 7일 지났으면 새로 받기
    python3 tools/universe.py --refresh  # 강제로 새로 받기
"""
import argparse
import json
import time
from datetime import datetime, timedelta

from common import CACHE, http_get

API = "https://m.stock.naver.com/api/stocks/industry"
PATH = CACHE / "universe.json"


def fetch():
    groups = json.loads(http_get(API, {"page": 1, "pageSize": 100}))["groups"]
    stocks = {}
    for g in groups:
        page = 1
        while True:
            d = json.loads(http_get(f"{API}/{g['no']}", {"page": page, "pageSize": 100}))
            for s in d["stocks"]:
                stocks[s["itemCode"]] = {
                    "code": s["itemCode"], "name": s["stockName"],
                    "market": {"0": "KOSPI", "1": "KOSDAQ", "2": "KONEX"}.get(str(s.get("sosok")), s.get("sosok")),
                    "industry": g["name"], "industry_no": g["no"],
                    "market_cap_eok": int(str(s.get("marketValue") or "0").replace(",", "") or 0),
                }
            if page * 100 >= d["totalCount"]:
                break
            page += 1
            time.sleep(0.3)
        time.sleep(0.3)
    return {"fetched_at": datetime.now().isoformat(timespec="seconds"), "stocks": list(stocks.values())}


def load(max_age_days=7, refresh=False):
    if not refresh and PATH.exists():
        d = json.loads(PATH.read_text(encoding="utf-8"))
        if datetime.now() - datetime.fromisoformat(d["fetched_at"]) < timedelta(days=max_age_days):
            return d
    d = fetch()
    CACHE.mkdir(parents=True, exist_ok=True)
    PATH.write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")
    return d


# 굵게 표시할 때 일반 단어와 겹치기 쉬운 짧은 종목명
NAME_EXCLUDE = {"대상", "동서", "전방", "신원", "우성", "진도", "선광", "대교", "국전", "조흥", "백산", "방림", "대현", "덕성",
                "금비", "승일", "원림", "도부", "무학", "배럴", "미쥬", "보락", "서흥", "신풍", "경방", "TP", "NC", "레이", "세원",
                "테스", "미코", "피노", "삼현", "태성", "보령"}


def bold_names(extra=()):
    """브리핑·채널 글에서 굵게 표시할 종목명 (긴 이름 먼저). 우선주 제외, 두 글자는 시총 5천억↑만."""
    out = set(extra)
    for x in load()["stocks"]:
        n, cap = x["name"], x.get("market_cap_eok") or 0
        if n in NAME_EXCLUDE or n.endswith(("우", "증권")) or "우B" in n or "(전환)" in n or (len(n) <= 2 and n.isascii()):
            continue
        if (len(n) >= 3 and cap >= 300) or (len(n) == 2 and cap >= 5000):
            out.add(n)
    return sorted(out, key=lambda n: (-len(n), n))


def main():
    p = argparse.ArgumentParser(description="국내 상장 종목 목록 (네이버 업종 기준)")
    p.add_argument("--refresh", action="store_true")
    a = p.parse_args()
    d = load(refresh=a.refresh)
    by_ind = {}
    for s in d["stocks"]:
        by_ind[s["industry"]] = by_ind.get(s["industry"], 0) + 1
    print(json.dumps({"fetched_at": d["fetched_at"], "count": len(d["stocks"]), "industries": len(by_ind)},
                     ensure_ascii=False))


if __name__ == "__main__":
    main()
