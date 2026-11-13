#!/usr/bin/env python3
"""거래대금 상위 100 (2026-11-13 사용자 요청): 코스피·코스닥 합쳐 거래대금 순, ETF·ETN·스팩·우선주 제외.

  python3 tools/value_top.py          # JSON 출력 (web_build가 D.vtop으로 넣음)

출처: 네이버 증권(비공식) '거래대금 상위'(priceTop) 순위. 장중에는 웹이 /api/quote?top=1 로 1분마다 다시 받는다.
토큰 0. 주문 기능 없음.
"""
import json, sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import http_get  # noqa: E402
from strategy_prep import KST  # noqa: E402

API = "https://m.stock.naver.com/api/stocks/priceTop/"


def num(s):
    try:
        return float(str(s).replace(",", ""))
    except Exception:
        return None


def is_plain(s):
    """보통주만: ETF·ETN·스팩·우선주·리츠 제외."""
    n = s.get("stockName") or ""
    if s.get("stockEndType") != "stock" or "스팩" in n or "리츠" in n:
        return False
    return not (n.endswith(("우", "우B", "우C")) and len(n) > 2) and "(전환)" not in n


def fetch(n=100):
    rows = []
    for m in ("KOSPI", "KOSDAQ"):
        for page in (1, 2, 3):
            try:
                d = json.loads(http_get(API + m, {"page": page, "pageSize": 100}, timeout=15, retries=2))
            except Exception:
                break
            for s in d.get("stocks") or []:
                if is_plain(s):
                    rows.append({"code": s["itemCode"], "name": s["stockName"], "market": m, "price": num(s.get("closePrice")),
                                 "chg": num(s.get("fluctuationsRatio")),
                                 "value_eok": round((num(s.get("accumulatedTradingValue")) or 0) / 100),   # 백만원 → 억원
                                 "cap_eok": num(s.get("marketValue")), "at": (s.get("localTradedAt") or "")[:16].replace("T", " ")})
            if len([r for r in rows if r["market"] == m]) >= n:
                break
    rows.sort(key=lambda r: -r["value_eok"])
    return {"made_at": datetime.now(KST).strftime("%Y-%m-%d %H:%M"), "items": rows[:n],
            "rule": "코스피·코스닥 합산 거래대금 순 · ETF·ETN·스팩·우선주·리츠 제외 · 네이버(비공식)"}


if __name__ == "__main__":
    o = fetch()
    print(json.dumps({"made_at": o["made_at"], "n": len(o["items"]), "top5": [(r["name"], r["value_eok"]) for r in o["items"][:5]]}, ensure_ascii=False))
