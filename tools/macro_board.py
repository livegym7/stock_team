"""시장 › 매크로 재료 (2026-11-19 사용자 요청, 토큰 0): 한국·미국·금리·유동성 탭이 쓰는 일봉과 유동성 지표.

  지수·피어·금리·환율·원자재·미국 산업 대표 종목(config/us_sectors.toml) 일봉 = Yahoo Finance 차트 API(비공식, 전일 마감 기준)
  유동성·레버리지 = 금융투자협회 종합통계(freesis): 고객 예탁금·미수금·반대매매 / 신용융자(코스피·코스닥), 하루 늦게 나옴

python3 tools/macro_board.py          # → data/market/macro_board.json (+ 요약 출력)
"""
import json
import sys
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from common import DATA, load_toml
from naver_quote import KST
import us_quote

INDEX = [["^GSPC", "S&P 500"], ["^IXIC", "나스닥"], ["^SOX", "필라델피아 반도체"], ["^DJI", "다우"]]
PEERS = [["^TWII", "대만 가권"], ["^N225", "닛케이 225"], ["000001.SS", "상해종합"], ["EWY", "EWY (미국 상장 한국 ETF)"]]
RATES = [["KRW=X", "원/달러"], ["DX-Y.NYB", "달러인덱스"], ["^TNX", "미국 10년물 금리(%)"], ["^VIX", "VIX 변동성"], ["CL=F", "WTI 유가"]]
N = 200


def rows(sym):
    try:
        r = us_quote.get_chart(sym, {"range": "1y", "interval": "1d"})
        return [[d.replace("-", ""), us_quote.rnd(o), us_quote.rnd(h), us_quote.rnd(l), us_quote.rnd(c), v or 0]
                for d, o, h, l, c, v in us_quote.bars(r) if o and h and l and c][-N:] if r else []
    except Exception:
        return []


def stat(rs):
    if len(rs) < 30:
        return {}
    c = [x[4] for x in rs]
    ret = lambda n: round((c[-1] / c[-1 - n] - 1) * 100, 2) if len(c) > n else None
    ma = lambda n: sum(c[-n:]) / n if len(c) >= n else None
    return {"date": rs[-1][0], "close": c[-1], "d1": ret(1), "w1": ret(5), "m1": ret(21), "m3": ret(63),
            "above20": c[-1] > ma(20), "above60": (c[-1] > ma(60)) if ma(60) else None, "off_high": round((c[-1] / max(x[2] for x in rs) - 1) * 100, 1)}


def kofia(obj, days=420):
    end = datetime.now(KST); start = end - timedelta(days=days)
    body = {"dmSearch": {"tmpV40": "1000000", "tmpV41": "1", "tmpV1": "D", "tmpV45": start.strftime("%Y%m%d"), "tmpV46": end.strftime("%Y%m%d"), "OBJ_NM": obj}}
    req = urllib.request.Request("https://freesis.kofia.or.kr/meta/getMetaDataList.do", data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json", "User-Agent": "Mozilla/5.0", "Referer": "https://freesis.kofia.or.kr/"})
    err = None
    for _ in range(4):   # 응답이 중간에 잘려 오는 일이 있어 다시 시도
        try:
            return sorted(json.loads(urllib.request.urlopen(req, timeout=25).read().decode("utf-8")).get("ds1") or [], key=lambda x: x["TMPV1"])
        except Exception as e:
            err = e
            import time; time.sleep(1.5)
    raise err


def liquidity():
    """단위 억 원. 예탁금·미수금·반대매매(금액·비중%) / 신용융자 전체·코스피·코스닥. 1년 범위 안 위치(0~100)."""
    a, b = kofia("STATSCU0100000060BO"), {x["TMPV1"]: x for x in kofia("STATSCU0100000070BO")}
    eok = lambda v: round(v / 100) if v is not None else None
    ser = [{"date": x["TMPV1"], "deposit": eok(x.get("TMPV2")), "misu": eok(x.get("TMPV5")), "forced": eok(x.get("TMPV6")), "forced_pct": x.get("TMPV7"),
            "credit": eok((b.get(x["TMPV1"]) or {}).get("TMPV2")), "credit_kospi": eok((b.get(x["TMPV1"]) or {}).get("TMPV3")),
            "credit_kosdaq": eok((b.get(x["TMPV1"]) or {}).get("TMPV4"))} for x in a]
    ser = [s for s in ser if s["deposit"] and s["credit"]][-250:]
    if not ser:
        return None
    def pos(k):
        v = [s[k] for s in ser if s[k] is not None]
        return round((v[-1] - min(v)) / ((max(v) - min(v)) or 1) * 100) if v else None
    last, prev, m1 = ser[-1], ser[-2], ser[-21] if len(ser) > 21 else ser[0]
    for s in ser:
        s["ratio"] = round(s["credit"] / s["deposit"] * 100, 1)
    return {"as_of": last["date"], "last": last, "d1": {k: last[k] - prev[k] for k in ("deposit", "credit", "credit_kospi", "credit_kosdaq")},
            "m1_pct": {k: round((last[k] / m1[k] - 1) * 100, 1) for k in ("deposit", "credit")},
            "pos": {k: pos(k) for k in ("deposit", "credit", "credit_kospi", "credit_kosdaq", "ratio", "forced")}, "series": ser,
            "source": "금융투자협회 종합통계(freesis) · 하루 늦게 나옴"}


def build():
    S = (load_toml("us_sectors.toml") or {}).get("sectors", [])
    syms = [s for s, _ in INDEX + PEERS + RATES] + [t for sec in S for t, _ in sec["stocks"]]
    with ThreadPoolExecutor(6) as ex:
        R = dict(zip(syms, ex.map(rows, syms)))
    item = lambda s, n: {"symbol": s, "name": n, **stat(R.get(s) or []), "rows": R.get(s) or []}
    sectors = []
    for sec in S:
        st = [item(t, n) for t, n in sec["stocks"]]
        ok = [x for x in st if x.get("d1") is not None]
        avg = lambda k: round(sum(x[k] for x in ok if x.get(k) is not None) / max(1, len([x for x in ok if x.get(k) is not None])), 2) if ok else None
        sectors.append({"name": sec["name"], "kr": sec.get("kr", ""), "d1": avg("d1"), "w1": avg("w1"), "m1": avg("m1"),
                        "above20": sum(1 for x in ok if x.get("above20")), "n": len(ok), "stocks": st})
    try:
        liq = liquidity()
    except Exception as e:   # 못 받으면 지난번에 받아 둔 값을 그대로 씀
        try:
            liq = json.loads((DATA / "market" / "macro_board.json").read_text(encoding="utf-8")).get("liquidity")
        except Exception:
            liq = None
        liq = liq if (liq or {}).get("series") else {"error": type(e).__name__}
    out = {"made_at": datetime.now(KST).strftime("%Y-%m-%d %H:%M"), "source": "Yahoo Finance 일봉(비공식, 전일 마감 기준) · 금융투자협회",
           "index": [item(s, n) for s, n in INDEX], "peers": [item(s, n) for s, n in PEERS], "rates": [item(s, n) for s, n in RATES],
           "sectors": sectors, "liquidity": liq}
    p = DATA / "market" / "macro_board.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(out, ensure_ascii=False), encoding="utf-8")
    out["_missing"] = [s for s in syms if not R.get(s)]
    return out


def main():
    out = build(); liq = out.get("liquidity") or {}
    print(json.dumps({"made_at": out["made_at"], "missing": out["_missing"],
                      "sectors": [[s["name"], s["d1"], s["w1"], f"{s['above20']}/{s['n']}"] for s in out["sectors"]],
                      "liquidity": {k: liq.get(k) for k in ("as_of", "last", "pos", "error")}}, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
