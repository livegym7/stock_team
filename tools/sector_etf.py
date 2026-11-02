"""섹터 ETF로 섹터 강도 보기 (config/sector_etfs.toml).

각 ETF의 1주·1개월·3개월·6개월·1년 수익률, KODEX 200 대비 RS 점수(1년 20%·6개월 30%·3개월 50% 가중 초과수익, %p),
20일선 위/아래와 이격, 20일선 기울기(5일 전 대비), 정배열(20>60>120), 52주 고점 대비를 계산한다.

사용법:
    python3 tools/sector_etf.py            # JSON (RS 점수 높은 순)
"""
import json
import time
from datetime import datetime

from common import load_toml
from naver_quote import KST, daily


def stats(code, name):
    rows = daily(code, name, 260)["rows"]
    # 장중이면 오늘 봉은 미확정 → 장마감(15:40) 전에는 빼고 직전 종가 기준
    now = datetime.now(KST)
    if rows and rows[-1]["date"] == now.strftime("%Y%m%d") and now.hour * 60 + now.minute < 15 * 60 + 40:
        rows = rows[:-1]
    c = [r["close"] for r in rows]
    ma = lambda n, k=0: sum(c[len(c) - n - k:len(c) - k]) / n if len(c) >= n + k else None
    ret = lambda n: round((c[-1] / c[-1 - n] - 1) * 100, 1) if len(c) > n else None
    m20, m60, m120 = ma(20), ma(60), ma(120)
    return {
        "date": rows[-1]["date"], "close": c[-1],
        "r1w": ret(5), "r1m": ret(21), "r3m": ret(63), "r6m": ret(125), "r12m": ret(min(249, len(c) - 1)),
        "above20": c[-1] > m20, "gap20": round((c[-1] / m20 - 1) * 100, 1),
        "slope20": round((m20 / ma(20, 5) - 1) * 100, 1) if ma(20, 5) else None,
        "aligned": bool(m120 and m20 > m60 > m120),
        "off_high": round((c[-1] / max(r["high"] for r in rows) - 1) * 100, 1),
    }


def run():
    cfg = load_toml("sector_etfs.toml")
    b = stats(cfg["benchmark"]["code"], cfg["benchmark"]["name"])
    out = []
    for e in cfg["etfs"]:
        s = stats(e["code"], e["name"])
        rs = None
        if None not in (s["r12m"], s["r6m"], s["r3m"]):
            rs = round(0.2 * (s["r12m"] - b["r12m"]) + 0.3 * (s["r6m"] - b["r6m"]) + 0.5 * (s["r3m"] - b["r3m"]), 1)
        out.append({"sector": e["sector"], "etf": e["name"], "code": e["code"], "rs_score": rs, **s})
        time.sleep(0.3)
    out.sort(key=lambda x: -(x["rs_score"] if x["rs_score"] is not None else -999))
    return {"benchmark": {"etf": cfg["benchmark"]["name"], **b}, "results": out}


def main():
    print(json.dumps({"source": "네이버 증권 일봉 (비공식)", "fetched_at": datetime.now(KST).isoformat(timespec="seconds"),
                      **run()}, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
