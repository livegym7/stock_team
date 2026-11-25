#!/usr/bin/env python3
"""지금 보는 것 두 가지 (2026-11-24 사용자 요청, 표시만 — 매매 규칙 아님, Claude 토큰 0).

1) night: 나스닥 100 선물(네이버 해외선물, 10분 지연) + EWY(미국 상장 한국 ETF, 야후 — 정규장 밖이면 시간외 가격)
   코스피 야간선물은 무료로 받을 곳을 찾지 못해 EWY로 대신한다.
2) hot: 네이버 검색 상위 30종목 — 지금 주목받는 종목. 화면이 내 업종 분류로 묶어 보여 준다(종목 › 주목).

화면이 열려 있는 동안에는 Cloudflare 함수(functions/api/quote.js ?night=1&hot=1)가 같은 값을 1분마다 준다.
이 도구는 웹을 만들 때 넣는 첫 값이다.

사용법:
    python3 tools/hot_now.py night
    python3 tools/hot_now.py hot
    python3 tools/hot_now.py themes      # 오늘 급등 테마(업종 안 +10%↑ 3종목 이상) — 소식 정리·체크포인트 재료
"""
import json
import sys
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
KST = timezone(timedelta(hours=9))
UA = {"User-Agent": "Mozilla/5.0", "Referer": "https://m.stock.naver.com/"}
NQ = "https://polling.finance.naver.com/api/realtime/worldstock/futures/NQcv1"
EWY = "https://query1.finance.yahoo.com/v8/finance/chart/EWY?interval=5m&range=1d&includePrePost=true"
TOP = "https://m.stock.naver.com/api/stocks/searchTop/all?page=1&pageSize=30"


def _get(url):
    return json.load(urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=15))


def _num(s):
    try:
        return float(str(s).replace(",", ""))
    except (TypeError, ValueError):
        return None


def _kst(iso):
    try:
        return datetime.fromisoformat(iso).astimezone(KST).strftime("%Y-%m-%d %H:%M")
    except (TypeError, ValueError):
        return ""


def ewy_from_chart(j):
    """야후 차트 응답 → {price, change_pct, at, session}. 정규장이면 전일 종가 대비, 정규장 밖이면 마지막 정규장 종가 대비."""
    r = j["chart"]["result"][0]
    m, ts, cl = r["meta"], r.get("timestamp") or [], (r["indicators"]["quote"][0].get("close") or [])
    last = next(((t, c) for t, c in zip(reversed(ts), reversed(cl)) if c), None)
    if not last:
        return None
    t, px = last
    reg = (m.get("currentTradingPeriod") or {}).get("regular") or {}
    inreg = reg.get("start", 0) <= t < reg.get("end", 0)
    base = m.get("chartPreviousClose") if inreg else m.get("regularMarketPrice")
    return {"price": round(px, 2), "change_pct": round((px / base - 1) * 100, 2) if base else None,
            "at": datetime.fromtimestamp(t, KST).strftime("%Y-%m-%d %H:%M"), "session": "정규장" if inreg else "시간외"}


def night():
    out = {"at": datetime.now(KST).strftime("%Y-%m-%d %H:%M"), "source": "네이버 해외선물(10분 지연) · Yahoo Finance(비공식)"}
    try:
        x = _get(NQ)["datas"][0]
        out["nq"] = {"price": _num(x.get("closePrice")), "change_pct": _num(x.get("fluctuationsRatio")), "status": x.get("marketStatus"),
                     "at": _kst(x.get("localTradedAt")), "delay": (x.get("stockExchangeType") or {}).get("delayTime")}
    except Exception as e:
        out["nq_error"] = str(e)[:80]
    try:
        out["ewy"] = ewy_from_chart(_get(EWY))
    except Exception as e:
        out["ewy_error"] = str(e)[:80]
    return out


def hot():
    """검색 상위 30. 업종(g) = 내 분류(sector_map) 먼저, 없으면 네이버 업종. rs = 레이더의 RS(있을 때)."""
    from sector_map import custom_map
    from universe import load
    cm, uni = custom_map(), {u["code"]: u for u in load()["stocks"]}
    try:
        rs = json.loads((Path(__file__).resolve().parent.parent / "data" / "radar" / "company_rs.json").read_text())
    except Exception:
        rs = {}
    items = []
    for i, s in enumerate(_get(TOP).get("stocks") or []):
        c = s.get("itemCode")
        if s.get("stockEndType") != "stock" or not c:
            continue
        items.append({"rank": i + 1, "code": c, "name": s.get("stockName"), "price": _num(s.get("closePrice")), "chg": _num(s.get("fluctuationsRatio")),
                      "value_eok": round((_num(s.get("accumulatedTradingValue")) or 0) / 100), "g": cm.get(c) or (uni.get(c) or {}).get("industry") or "",
                      "rs": (rs.get(c) or {}).get("rs")})
    return {"made_at": datetime.now(KST).strftime("%Y-%m-%d %H:%M"), "source": "네이버 금융 검색 상위(비공식)", "items": items}


def themes(min_up=10.0, min_n=3, top=25):
    """오늘 급등 테마 (2026-11-25 사용자 지적: 보안주가 집단 상한가인데 소식 정리에 카드가 없었음 — 토큰 0, 10초쯤).
    네이버 테마(시장에서 부르는 이름: '보안주(정보)' 등) 가운데 평균 등락 상위 25개를 보고, 그 안에서 +10%↑ 종목이 3개 이상인 테마만 고른다.
    시총이 작은 종목도 포함한다(감시 대상 2천억↑만 보면 소형주 테마가 안 잡힌다). 내 목록(보유·관찰 풀) 종목은 표시한다.
    글을 쓰는 쪽(소식 정리·체크포인트)이 '오늘 시장에서 실제로 움직인 것'을 놓치지 않게 하는 재료다. 글감용이며 매매 규칙이 아니다."""
    import tomllib
    root = Path(__file__).resolve().parent.parent
    mine = set()
    try:
        mine |= {s["code"] for th in tomllib.loads((root / "config" / "watch_pool.toml").read_text(encoding="utf-8")).get("themes") or [] for s in th.get("stocks") or []}
        from common import positions
        mine |= {p["code"] for p in positions()}
    except Exception:
        pass
    out, at = [], ""
    for g in (_get(f"https://m.stock.naver.com/api/stocks/theme?page=1&pageSize={top}").get("groups") or []):
        try:
            d = _get(f"https://m.stock.naver.com/api/stocks/theme/{g['no']}?page=1&pageSize=12")
        except Exception:
            continue
        st = [(_num(x.get("fluctuationsRatio")) or 0, x.get("stockName"), x.get("itemCode"), _num(x.get("marketValue")),
               ((x.get("compareToPreviousPrice") or {}).get("name") == "UPPER_LIMIT")) for x in d.get("stocks") or []]
        at = max([at] + [(x.get("localTradedAt") or "")[:16].replace("T", " ") for x in d.get("stocks") or []])
        up = [x for x in st if x[0] >= min_up]
        if len(up) >= min_n:
            out.append({"theme": g.get("name"), "avg": _num(g.get("changeRate")), "n": g.get("totalCount"), "rise": g.get("riseCount"), "up_n": len(up),
                        "limit_up": sum(1 for x in up if x[4]),
                        "stocks": [{"name": n, "code": c, "chg": chg, "cap_eok": cap, "mine": c in mine} for chg, n, c, cap, _ in up[:6]]})
    out.sort(key=lambda x: (-x["limit_up"], -x["up_n"], -(x["avg"] or 0)))
    seen, uniq = set(), []          # 같은 종목들로 이뤄진 테마가 여러 이름으로 겹치면 앞의 것만
    for x in out:
        k = {s["code"] for s in x["stocks"]}
        if len(k & seen) * 3 < len(k) * 2:      # 종목의 3분의 2 이상이 앞 테마와 겹치면 같은 움직임으로 본다
            uniq.append(x)
        seen |= k
    return {"at": at, "source": "네이버 테마(비공식)", "rule": f"테마 안에서 +{min_up:g}%↑ 종목이 {min_n}개 이상", "themes": uniq[:5]}


def themes_line():
    """글쓰기 재료용 요약 (없으면 '없음')."""
    try:
        t = themes()
    except Exception as e:
        return f"집계 실패({type(e).__name__})"
    if not t["themes"]:
        return f"없음 ({t['rule']} 기준 · {t['at']})"
    return " / ".join(f"{x['theme']}(평균 {x['avg']:+.1f}%, {x['n']}종목 중 오른 종목 {x['rise']}): +10%↑ {x['up_n']}종목·상한가 {x['limit_up']} — "
                      + ", ".join(f"{s['name']} {s['chg']:+.1f}%{' [내 목록]' if s['mine'] else ''}" for s in x["stocks"])
                      for x in t["themes"]) + f" (출처: {t['source']} {t['at']})"


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "night"
    print(json.dumps(night() if cmd == "night" else themes() if cmd == "themes" else hot(), ensure_ascii=False, indent=1))
