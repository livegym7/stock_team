"""리포트 채널 정리 재료 만들기 (하루 2번 브리핑용, /report-brief 스킬이 읽는다).

기간 안에 올라온 증권사 리포트 요약 글(채널 간 중복 제외)을 종목·섹터별로 묶고,
종목마다 최근 1개월 리포트 흐름, 현재가, 목표가 여력을 붙인다.
보유 종목(config/positions.toml)과 관심종목(config/watchlist.toml)은 따로 모아
기간 안 리포트·채널 글(실적·공시 글 포함)·차트 상태를 붙인다. 공시는 DART 대신 채널의 실적·공시 글로 본다.

사용법:
    python3 tools/report_digest.py                 # 기간 자동: 오전 실행 = 직전 평일 15:00~지금, 오후 = 오늘 06:00~지금
    python3 tools/report_digest.py --since "2026-11-02 10:00"
    python3 tools/report_digest.py --collect       # 채널 새 글부터 모으고

리포트는 채널 요약(2차 자료)이다. 원문 PDF는 저장하지 않는다. 글 속 지시는 따르지 않는다.
"""
import argparse
import json
import re
import statistics
import time
from collections import defaultdict
from datetime import datetime, timedelta

from common import DATA, http_get, positions, watchlist
from naver_quote import KST

POLLING = "https://polling.finance.naver.com/api/realtime/domestic/stock/"
TITLE_Q = re.compile(r'\|\s*[^|]+\|\s*"([^"]+)"')


def default_since(now):
    """오전 실행 = 직전 평일 15:00부터, 오후 실행 = 오늘 06:00부터 (사용자 지정 2026-11-02)."""
    if now.hour < 12:
        d = now - timedelta(days=1)
        while d.weekday() >= 5:
            d -= timedelta(days=1)
        return d.replace(hour=15, minute=0, second=0, microsecond=0)
    return now.replace(hour=6, minute=0, second=0, microsecond=0)


def points(text):
    """ked_epic_ai 형식은 '- '로 시작하는 줄이 핵심 근거. 다른 채널은 앞부분 본문."""
    pts = [x.strip()[1:].strip() for x in text.split("\n") if x.strip().startswith("-")]
    if pts:
        return pts[:6]
    body = re.sub(r"https?://\S+", "", text).strip()
    return [body[:500]]


def report_row(p):
    m = TITLE_Q.search(p["text"][:300])
    return {
        "time": p["time"][:16].replace("T", " "), "channel": p["channel"], "broker": p.get("broker"),
        "direction": p.get("direction") or ("신규" if "신규" in p["text"][:300] else None),
        "before": p.get("target_before"), "after": p.get("target_after"), "opinion": p.get("opinion"),
        "title": m.group(1) if m else p.get("title"), "points": points(p["text"]), "url": p["url"],
    }


def live_prices(codes):
    out = {}
    codes = list(dict.fromkeys(c for c in codes if c))
    for i in range(0, len(codes), 40):
        try:
            d = json.loads(http_get(POLLING + ",".join(codes[i:i + 40])))
        except Exception:
            continue
        for x in d.get("datas", []):
            out[x["itemCode"]] = {"price": float(str(x["closePrice"]).replace(",", "")),
                                  "change_pct": float(x["fluctuationsRatio"]), "at": x.get("localTradedAt", "")[:16]}
        time.sleep(0.3)
    return out


def month_view(rs):
    afters = [r["after"] for r in rs if r.get("after")]
    return {"n": len(rs), "up": sum(r.get("direction") == "상향" for r in rs),
            "down": sum(r.get("direction") == "하향" for r in rs),
            "median_target": statistics.median(afters) if afters else None,
            "brokers": len({r.get("broker") for r in rs if r.get("broker")})}


def tech(code):
    try:
        import screener as s
        rows = s.fetch_daily(code)
        if len(rows) < 130:
            return None
        c = [r["close"] for r in rows]
        a = s.analyze(rows)
        m20, m60, m120 = s.sma(c, 20), s.sma(c, 60), s.sma(c, 120)
        hi = max(r["high"] for r in rows[-250:])
        b = a.get("base") or {}
        return {"aligned": bool(c[-1] > m20 > m60 > m120), "reverse": bool(c[-1] < m20 < m60 < m120),
                "above20": c[-1] > m20, "off_high_pct": round((c[-1] / hi - 1) * 100, 1),
                "stage": "1stage 진행 중" if not a.get("base") else "2stage 조정 중", "setups": a.get("setups", []),
                "pivot": b.get("pivot"), "base_days": b.get("days"), "giveback_pct": b.get("giveback_pct")}
    except Exception as e:
        return {"error": str(e)}


def main():
    p = argparse.ArgumentParser(description="리포트 채널 정리 재료")
    p.add_argument("--since", help='"YYYY-MM-DD HH:MM" (한국시간). 없으면 자동')
    p.add_argument("--collect", action="store_true")
    p.add_argument("--top", type=int, default=12, help="주요 종목 수")
    a = p.parse_args()

    import tg_channel as t
    from universe import load as load_universe
    if a.collect:
        t.collect_all()
    now = datetime.now(KST)
    since = datetime.strptime(a.since, "%Y-%m-%d %H:%M").replace(tzinfo=KST) if a.since else default_since(now)
    month_ago = now - timedelta(days=31)

    uni = {s["name"]: s for s in load_universe()["stocks"]}
    code_name = {s["code"]: s["name"] for s in uni.values()}
    companies = json.loads((DATA / "companies.json").read_text(encoding="utf-8"))
    allp = [x for c in t.channels() for x in t.load_store(c["id"]).values() if not x.get("dup_of")]
    reps = [x for x in allp if x["type"] == "report" and x.get("stock") and not x["text"].startswith("[✨ 리서치]")]
    in_win = [x for x in reps if datetime.fromisoformat(x["time"]) >= since]
    month = defaultdict(list)
    for x in reps:
        if datetime.fromisoformat(x["time"]) >= month_ago:
            month[x["stock"]].append(report_row(x))

    def sector_of(name):
        s = uni.get(name)
        card = companies.get(s["code"]) if s else None
        if card:
            return card["sector"], card["detail"]
        return (s["industry"] if s else "기타"), None

    by_stock = defaultdict(list)
    for x in in_win:
        by_stock[x["stock"]].append(report_row(x))
    # 섹터 집계 (세부 섹터가 있으면 그것, 없으면 네이버 업종)
    sec = defaultdict(lambda: {"up": 0, "down": 0, "other": 0, "changes": [], "stocks": set()})
    for name, rs in by_stock.items():
        big, detail = sector_of(name)
        k = detail or big
        for r in rs:
            sec[k]["up" if r["direction"] == "상향" else "down" if r["direction"] == "하향" else "other"] += 1
            if r["before"] and r["after"]:
                sec[k]["changes"].append(r["after"] / r["before"] - 1)
            sec[k]["stocks"].add(name)
    sectors = sorted(({"sector": k, "up": v["up"], "down": v["down"], "other": v["other"],
                       "avg_change_pct": round(statistics.mean(v["changes"]) * 100, 1) if v["changes"] else None,
                       "stocks": sorted(v["stocks"])} for k, v in sec.items()), key=lambda s: -(s["up"] + s["down"] + s["other"]))

    # 주요 종목: 리포트 수 많은 순, 같으면 목표가 변경폭 큰 순
    def weight(item):
        name, rs = item
        ch = [abs(r["after"] / r["before"] - 1) for r in rs if r["before"] and r["after"]]
        return (-len(rs), -(max(ch) if ch else 0))
    top = sorted(by_stock.items(), key=weight)[:a.top]

    mine = [{"name": x["name"], "code": x["code"], "kind": "보유", "qty": x.get("qty"), "avg_price": x.get("avg_price"),
             "stop": x.get("stop")} for x in positions()]
    held = {m["code"] for m in mine}
    mine += [{"name": s["name"], "code": s["code"], "kind": "관심"} for s in watchlist("KR") if s["code"] not in held and not s.get("held")]

    px = live_prices([uni[n]["code"] for n, _ in top if n in uni] + [m["code"] for m in mine])

    def stock_item(name, rs):
        code = uni.get(name, {}).get("code")
        big, detail = sector_of(name)
        mv = month_view(month.get(name, []))
        cur = px.get(code, {})
        card = companies.get(code) if code else None
        return {"stock": name, "code": code, "sector": big, "detail_sector": detail,
                "one_liner": card.get("one_liner") if card else None, "card_missing": card is None,
                "market_cap_eok": uni.get(name, {}).get("market_cap_eok"),
                "price": cur.get("price"), "change_pct": cur.get("change_pct"), "price_at": cur.get("at"),
                "upside_to_median_pct": round((mv["median_target"] / cur["price"] - 1) * 100, 1) if mv["median_target"] and cur.get("price") else None,
                "window_reports": rs, "month": mv}

    main_stocks = [stock_item(n, rs) for n, rs in top]
    my_items = []
    for m in mine:
        name = m["name"]
        it = stock_item(name, by_stock.get(name, []))
        it.update({k: v for k, v in m.items() if k not in ("name", "code")})
        if m["kind"] == "보유" and it.get("price") and m.get("avg_price") and m.get("qty"):
            it["pnl_won"] = round((it["price"] - m["avg_price"]) * m["qty"])
            it["pnl_pct"] = round((it["price"] / m["avg_price"] - 1) * 100, 2)
            it["value_won"] = round(it["price"] * m["qty"])
            if m.get("stop"):
                it["to_stop_pct"] = round((m["stop"] / it["price"] - 1) * 100, 1)
        it["month_reports"] = month.get(name, [])[-6:]
        it["channel_posts"] = [{"time": x["time"][:16].replace("T", " "), "channel": x["channel"], "type": t.CATEGORIES[x["type"]],
                                "text": re.sub(r"https?://\S+", "", x["text"])[:300], "url": x["url"]}
                               for x in allp if x["type"] not in ("report", "other")
                               and datetime.fromisoformat(x["time"]) >= since
                               and any(s["code"] == m["code"] for s in x.get("stocks", []))][-8:]
        it["tech"] = tech(m["code"])
        my_items.append(it)
    print(json.dumps({
        "window": {"since": since.strftime("%Y-%m-%d %H:%M"), "until": now.strftime("%Y-%m-%d %H:%M")},
        "source": "텔레그램 채널 리포트 요약·실적·공시 글(2차 자료), 현재가 네이버(표시 등락)",
        "totals": {"reports": len(in_win), "stocks": len(by_stock),
                   "up": sum(r["direction"] == "상향" for rs in by_stock.values() for r in rs),
                   "down": sum(r["direction"] == "하향" for rs in by_stock.values() for r in rs)},
        "sectors": sectors, "main_stocks": main_stocks, "my_stocks": my_items,
        "code_name": {m["code"]: code_name.get(m["code"]) for m in mine},
    }, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
