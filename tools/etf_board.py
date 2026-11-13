#!/usr/bin/env python3
"""ETF 시세판 (2026-11-13 사용자 요청): config/etf_board.toml 목록의 현재가·등락률·거래대금 + 코스피·코스닥 등락률.

  python3 tools/etf_board.py      # JSON (web_build가 D.etfb로 넣음, 장중엔 웹이 /api/quote로 1분마다 가격만 갱신)

목적: 시장(코스피·코스닥) 대비 강한 섹터를 한눈에. 출처 네이버(비공식). 토큰 0. 주문 기능 없음.
"""
import json, re, sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import http_get, load_toml  # noqa: E402
from strategy_prep import KST  # noqa: E402

POLL = "https://polling.finance.naver.com/api/realtime/domestic/"


def num(s):
    try:
        return float(str(s).replace(",", ""))
    except Exception:
        return None


def eok(t):
    """'1.2조' '34.7억' '1,773억' → 억 원"""
    t = str(t or "").replace(",", "")
    m = re.match(r"([\d.]+)\s*(조|억|백만)?", t)
    if not m:
        return None
    v = float(m.group(1))
    return round(v * 10000 if m.group(2) == "조" else v / 100 if m.group(2) == "백만" else v, 1)


def fetch():
    E = (load_toml("etf_board.toml") or {}).get("etfs", [])
    out = []
    codes = [e["code"] for e in E]
    for i in range(0, len(codes), 40):
        try:
            d = json.loads(http_get(POLL + "stock/" + ",".join(codes[i:i + 40])))
        except Exception:
            continue
        for x in d.get("datas", []):
            out.append({"code": x["itemCode"], "name": x.get("stockName"), "price": num(x.get("closePrice")), "chg": num(x.get("fluctuationsRatio")),
                        "value_eok": eok(x.get("accumulatedTradingValue")), "at": (x.get("localTradedAt") or "")[:16].replace("T", " ")})
    idx = []
    try:
        d = json.loads(http_get(POLL + "index/KOSPI,KOSDAQ"))
        idx = [{"code": x["itemCode"], "name": "코스피" if x["itemCode"] == "KOSPI" else "코스닥", "price": num(x.get("closePrice")),
                "chg": num(x.get("fluctuationsRatio"))} for x in d.get("datas", [])]
    except Exception:
        pass
    return {"made_at": datetime.now(KST).strftime("%Y-%m-%d %H:%M"), "items": out, "index": idx,
            "rule": "config/etf_board.toml 목록 · 네이버(비공식) 현재가 · 등락률 순"}


if __name__ == "__main__":
    o = fetch()
    print(json.dumps({"made_at": o["made_at"], "n": len(o["items"]), "index": o["index"],
                      "top3": [(x["name"], x["chg"]) for x in sorted(o["items"], key=lambda x: -(x["chg"] or 0))[:3]]}, ensure_ascii=False))
