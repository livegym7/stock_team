#!/usr/bin/env python3
"""전략 보고서 재료 (토큰 0). Claude 전략가는 이 결과만 읽고 보고서를 쓴다 — 31일 치 채널 글을 다시 읽지 않는다.

python3 tools/strategy_prep.py prep            # 4검증(말·이익·가격·돈) 숫자 + 국면 + 자료실·메모·일정 → data/strategy/prep/날짜.json + 요약 출력
python3 tools/strategy_prep.py score           # 지난 보고서 스트림·관찰 종목의 그 뒤 성적(가설 채점 재료)
python3 tools/strategy_prep.py pool            # latest.json 기업 지도 → config/watch_pool.toml (관찰 풀, 사용자 편집 가능)
python3 tools/strategy_prep.py save --file 초안.json   # 형식 점검 → history 보관 → latest.json → 관찰 풀 갱신

규칙: 주문 기능 없음. 숫자마다 출처·시각. 채널 글은 2차 자료.
"""
import argparse
import glob
import json
import re
import statistics
import sys
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import CONFIG, DATA, ROOT, load_toml, positions  # noqa: E402

KST = timezone(timedelta(hours=9))
STRAT = DATA / "strategy"
PREP = STRAT / "prep"
HIST = STRAT / "history"
POOL = CONFIG / "watch_pool.toml"


def safe(fn, default=None):
    try:
        return fn()
    except Exception as e:  # 재료 하나가 실패해도 나머지는 만든다
        return {"error": f"{type(e).__name__}: {str(e)[:120]}"} if default is None else default


def week_key(iso):
    d = datetime.fromisoformat(iso[:19])
    return (d - timedelta(days=d.weekday())).strftime("%m/%d")


# ---------- 공통 재료 ----------
def universe_maps():
    from universe import load as load_universe
    from sector_map import custom_map
    uni = {s["name"]: s for s in load_universe()["stocks"]}
    cmap = safe(custom_map, {}) or {}
    code_of = {n: s["code"] for n, s in uni.items()}
    group_of = lambda name: cmap.get(code_of.get(name, "")) or uni.get(name, {}).get("industry")
    return uni, code_of, group_of


def load_latest():
    f = STRAT / "latest.json"
    return json.loads(f.read_text(encoding="utf-8")) if f.exists() else None


def split_names(name):
    """'NAVER·삼성에스디에스' 처럼 묶인 이름을 나눔. 괄호 설명은 뗀다."""
    base = re.sub(r"\s*\(.*?\)\s*$", "", name).strip()
    return [x.strip() for x in re.split(r"[·,/]", base) if x.strip()]


def pool_stocks():
    """관찰 풀 (config/watch_pool.toml). 없으면 latest.json 기업 지도에서 임시로."""
    if POOL.exists():
        try:
            import tomllib
            t = tomllib.loads(POOL.read_text(encoding="utf-8"))
            return [dict(s, theme=th.get("id"), theme_name=th.get("name")) for th in t.get("themes", []) for s in th.get("stocks", [])]
        except Exception:
            pass
    L = load_latest()
    if not L:
        return []
    _, code_of, _ = universe_maps()
    out = []
    for th in L.get("themes", []):
        for c in th.get("companies", []):
            for nm in split_names(c["name"]):
                if nm in code_of:
                    out.append({"name": nm, "code": code_of[nm], "role": c.get("role"), "theme": th.get("id"), "theme_name": th.get("name")})
    return out


# ---------- ① 국면 ----------
def regime():
    import sector_etf
    b = sector_etf.stats("KOSPI", "코스피")
    light = "green" if b.get("above20") and b.get("aligned") else "yellow" if b.get("above20") or (b.get("slope20") or 0) > 0 else "red"
    b["light"] = light
    b["source"] = "네이버 코스피 일봉(비공식) · 20일선 · 정배열"
    return b


def market_now():
    import market_pulse
    p = market_pulse.pulse()
    rows = []
    for m in p.get("markets", []):
        rows.append({k: m.get(k) for k in ("market", "price", "change_pct", "status", "at", "deal_date", "individual_eok", "foreign_eok",
                                            "institution_eok", "program_eok", "up", "down", "high52", "low52", "trading_value_eok")})
    return {"markets": rows, "industries_up": p.get("industries", [])[:8], "industries_down": p.get("industries", [])[-8:],
            "themes_up": p.get("themes_up", [])[:8], "source": p.get("source")}


def overseas():
    """해외·매크로: web_build.market() 재사용 (Yahoo 비공식)."""
    import web_build as WB
    m = WB.market(True)
    keep = ("^IXIC", "^GSPC", "^SOX", "KRW=X", "^TNX", "^VIX", "NQ=F", "EWY", "CL=F")
    return [{k: r.get(k) for k in ("name", "symbol", "price", "change_pct", "at")} for r in (m.get("us") or []) if r.get("symbol") in keep]


def econ_recent():
    import market_pulse
    e = market_pulse.econ(back=7, ahead=7)
    rows = e if isinstance(e, list) else (e.get("rows") or e.get("events") or [])
    return rows[:40]


# ---------- ② 말 (채널 언급, 주별) ----------
def talk(allp, group_of, pool, weeks=4):
    """업종(사용자 분류)별·관찰 풀 종목별 주별 글 수. 중복·잡담·시황 제외. 2차 자료."""
    since = (datetime.now(KST) - timedelta(weeks=weeks)).isoformat()
    by_group, by_stock = defaultdict(Counter), defaultdict(Counter)
    direction = defaultdict(lambda: Counter())
    pool_names = {s["name"] for s in pool}
    for x in allp:
        if x["time"] < since or x.get("dup_of") or x.get("digest") or x["type"] in ("other", "market", "macro", "policy", "schedule"):
            continue
        wk = week_key(x["time"])
        names = [st["name"] for st in x.get("stocks", [])][:3]
        for g in {group_of(n) for n in names} - {None}:
            by_group[g][wk] += 1
            if x.get("direction") in ("상향", "하향"):
                direction[g][x["direction"]] += 1
        for n in names:
            if n in pool_names:
                by_stock[n][wk] += 1
    wks = sorted({w for c in by_group.values() for w in c})[-weeks:]
    def row(name, c):
        seq = [c.get(w, 0) for w in wks]
        prev, cur = (seq[-2] if len(seq) > 1 else 0), seq[-1]
        return {"name": name, "weeks": seq, "chg_pct": round((cur / prev - 1) * 100) if prev else None}
    groups = sorted((row(g, c) for g, c in by_group.items()), key=lambda r: -sum(r["weeks"]))[:25]
    for r in groups:
        r["updown"] = dict(direction[r["name"]])
    return {"weeks": wks, "groups": groups, "pool": sorted((row(n, c) for n, c in by_stock.items()), key=lambda r: -sum(r["weeks"])),
            "source": "텔레그램 채널 글(2차 자료), 중복 제외, 종목이 붙은 글만"}


# ---------- ③ 이익 (리포트 방향·컨센서스·실적) ----------
def earnings_axis(allp, uni, companies, pool, by_stock_rep, flow31):
    import web_build as WB
    now = datetime.now(KST)
    wk = (now - timedelta(days=7)).isoformat()
    sec7 = defaultdict(lambda: Counter())
    for x in allp:
        if x["time"] < wk or x.get("dup_of") or x["type"] != "report" or not x.get("stock"):
            continue
        key = uni.get(x["stock"], {}).get("industry", "기타")
        code = uni.get(x["stock"], {}).get("code")
        card = companies.get(code) if code else None
        if card:
            key = card.get("detail") or key
        d = x.get("direction")
        sec7[key]["up" if d == "상향" else "down" if d == "하향" else "new"] += 1
    flow7 = sorted(({"sector": k, "up": v.get("up", 0), "down": v.get("down", 0), "new": v.get("new", 0)} for k, v in sec7.items()),
                   key=lambda s: -(s["up"] + s["down"] + s["new"]))[:20]
    cons = safe(lambda: WB.consensus(allp, uni), {})
    earn = safe(WB.earnings_map, {})
    pool_rows = []
    for s in pool:
        reps = by_stock_rep.get(s["name"], [])
        up = sum(1 for r in reps if r.get("direction") == "상향"); dn = sum(1 for r in reps if r.get("direction") == "하향")
        c = cons.get(s["name"]) if isinstance(cons, dict) else None
        e = earn.get(s.get("code")) if isinstance(earn, dict) else None
        pool_rows.append({"name": s["name"], "reports_31d": len(reps), "up": up, "down": dn,
                          "last": [{"t": r["time"][:10], "broker": r.get("broker"), "dir": r.get("direction"), "before": r.get("before"), "after": r.get("after")} for r in reps[:3]],
                          "consensus": {k: c.get(k) for k in ("now", "n", "chg_pct", "since")} if c else None,
                          "earnings": {k: e.get(k) for k in ("period", "op", "op_est", "op_surprise", "op_yoy", "verdict", "time")} if e else None})
    tot_up = sum(f.get("up", 0) for f in flow31); tot_dn = sum(f.get("down", 0) for f in flow31)
    return {"flow_31d": flow31[:20], "flow_7d": flow7, "totals_31d": {"up": tot_up, "down": tot_dn}, "pool": pool_rows,
            "source": "채널 리포트 요약(2차) 31일 · 컨센서스 = 증권사별 최근 목표가 평균 · 실적 = 채널 잠정실적 공시"}


# ---------- ④ 가격 · ⑤ 돈 ----------
def ensure_daily_cache(min_n=300, workers=4):
    """RS 백분위는 시총 2천억↑ 전 종목 일봉이 있어야 한다. 캐시가 얇으면(새 컨테이너) 받아 둔다 (감시 목록도 같은 캐시를 씀, 2~4분)."""
    from concurrent.futures import ThreadPoolExecutor
    import screener as S
    from universe import load as load_universe
    from common import CACHE
    have = len(list((CACHE / "daily").glob("*.json"))) if (CACHE / "daily").exists() else 0
    if have >= min_n:
        return have
    from backtest import is_etf
    codes = [s["code"] for s in load_universe()["stocks"] if s.get("market_cap_eok", 0) >= 2000 and not is_etf(s["name"])]
    def one(c):
        try:
            S.fetch_daily(c)
        except Exception:
            pass
    with ThreadPoolExecutor(workers) as ex:
        list(ex.map(one, codes))
    return len(list((CACHE / "daily").glob("*.json")))


def price_money(allp, uni, companies, pool, by_stock_rep):
    import web_build as WB
    import market_pulse
    safe(ensure_daily_cache)
    comp = []
    seen = set()
    for s in pool:
        if not s.get("code") or s["code"] in seen:
            continue
        seen.add(s["code"])
        reps = by_stock_rep.get(s["name"], [])
        comp.append({"name": s["name"], "code": s["code"], "n_reports": len(reps), "card": False,
                     "up": sum(1 for r in reps if r.get("direction") == "상향"), "down": sum(1 for r in reps if r.get("direction") == "하향")})
    trends = safe(lambda: WB.company_trends(comp, allp, fetch_limit=60), []) or []
    fl = safe(lambda: market_pulse.flows(), {}) or {}
    st = {x["code"]: x for x in (fl.get("stocks") or [])} if isinstance(fl, dict) else {}
    price_rows = []
    for c in trends if isinstance(trends, list) else []:
        t = c.get("trend") or {}
        f = st.get(c["code"], {})
        price_rows.append({"name": c["name"], "code": c["code"], "price": t.get("price"), "date": t.get("date"), "rs": t.get("rs"), "rs_chg4w": t.get("rs_chg4w"),
                           "r1w": t.get("r1w"), "r1m": t.get("r1m"), "r3m": t.get("r3m"), "off_high": t.get("off_high"),
                           "above20": t.get("above20"), "above50": t.get("above50"),
                           "f5_eok": f.get("f5"), "i5_eok": f.get("i5"), "f_streak": f.get("f_streak"), "i_streak": f.get("i_streak")})
    sectors = []
    for g in (fl.get("sectors") or []) if isinstance(fl, dict) else []:
        sectors.append({k: g.get(k) for k in ("group", "n", "r1", "r5", "r20", "f1", "f5", "i1", "i5", "f20", "i20", "cap_eok")})
    sectors.sort(key=lambda g: -(g.get("r5") or 0))
    return {"pool": price_rows, "sectors": sectors,
            "source": f"가격 네이버 일봉(비공식) · RS = 시총 2천억↑ 종목 중 백분위(12/6/3개월 가중) · 수급 시총 상위 300 외국인·기관 추정 금액(억) {fl.get('at', '') if isinstance(fl, dict) else ''}"}


# ---------- 자료실 · 메모 · 정리 · 일정 ----------
def research_recent(days=14):
    idx = json.loads((DATA / "research" / "index.json").read_text(encoding="utf-8")).get("docs", {}) if (DATA / "research" / "index.json").exists() else {}
    since = (datetime.now(KST) - timedelta(days=days)).strftime("%Y-%m-%d")
    rows = []
    for fid, d in idx.items():
        if (d.get("analyzed_at") or "")[:10] < since:
            continue
        full = DATA / "research" / "docs" / f"{fid}.json"
        extra = {}
        if full.exists():
            j = json.loads(full.read_text(encoding="utf-8"))
            extra = {"stocks": j.get("stocks"), "sectors": [s.get("name") if isinstance(s, dict) else s for s in (j.get("sectors") or [])][:4],
                     "thesis": [t.get("point") if isinstance(t, dict) else t for t in (j.get("thesis") or [])][:3],
                     "risks": (j.get("risks") or [])[:2], "numbers": (j.get("numbers") or [])[:4], "depth": j.get("depth", "full")}
        rows.append({"id": fid, "date": d.get("date"), "broker": d.get("broker"), "kind": d.get("kind"), "title": d.get("title"),
                     "one_line": d.get("one_line"), "url": d.get("url"), **extra})
    rows.sort(key=lambda r: r.get("date") or "", reverse=True)
    return rows


def memos(days=7):
    since = (datetime.now(KST) - timedelta(days=days)).strftime("%Y-%m-%d")
    out = []
    for f in sorted((STRAT / "memos").glob("*.md")):
        if f.stem >= since:
            out.append({"date": f.stem, "text": f.read_text(encoding="utf-8")[:1500]})
    return out


def opinions(days=7):
    """최근 브리핑(마감 리뷰·아침)의 💡 의견 블록만."""
    out = []
    for d in range(days, -1, -1):
        day = (datetime.now(KST) - timedelta(days=d)).strftime("%Y-%m-%d")
        for kind in ("close", "morning"):
            f = ROOT / "reports" / day / f"{kind}.md"
            if f.exists():
                txt = f.read_text(encoding="utf-8")
                m = re.search(r"💡.*?(?=\n#|\n\*\*|\n🔄|\n🌡|\Z)", txt, re.S)
                out.append({"date": day, "kind": kind, "opinion": (m.group(0) if m else txt[:600])[:900]})
    return out


def calendar_ahead(pool, days=14):
    f = DATA / "calendar" / "events.json"
    if not f.exists():
        return []
    ev = json.loads(f.read_text(encoding="utf-8")).get("events", [])
    today = datetime.now(KST).strftime("%Y-%m-%d"); end = (datetime.now(KST) + timedelta(days=days)).strftime("%Y-%m-%d")
    codes = {s.get("code") for s in pool}
    out = [e for e in ev if today <= e.get("date", "") <= end and (e.get("kind") in ("macro", "rate", "earnings_us", "expiry") or e.get("code") in codes)]
    return out[:40]


# ---------- 채널 흐름 (2차 자료): 정리 헤드라인 · 여러 채널 소식 · 리포트 요약 근거 · 말 vs 주가 ----------
DIGEST_KINDS = (("채널 정리", "channels_[0-9]*.md"), ("리포트 정리", "report_live_[0-9]*.md"))   # 리포트 브리핑(14:53)은 리포트 정리와 겹쳐 제외
HEAD_MARKS = ("💡", "🔥", "🔺", "🔽", "🆕", "⚖️", "🌡️", "🧭", "📌", "💼", "🔄")


def digests(days=5, max_chars=900):
    """채널 정리·리포트 정리(Sonnet이 2시간마다 쓴 글)의 머리 부분만: 날마다 마지막 1개씩. 💡 의견·번호 주제·섹터 줄 + 각 다음 2줄. 2차 자료."""
    out = []
    for d in range(days, -1, -1):
        day = (datetime.now(KST) - timedelta(days=d)).strftime("%Y-%m-%d")
        for kind, pat in DIGEST_KINDS:
            fs = sorted(glob.glob(str(ROOT / "reports" / day / pat)))
            if not fs:
                continue
            keep, grab = [], 0
            for l in Path(fs[-1]).read_text(encoding="utf-8").split("\n"):
                t = l.strip()
                if not t:
                    continue
                if t.startswith("#") or re.match(r"^\d\uFE0F?\u20E3", t) or t.startswith(HEAD_MARKS):
                    keep.append(t[:140]); grab = 1; continue
                if grab > 0:
                    keep.append(t[:140]); grab -= 1
            out.append({"date": day, "kind": kind, "file": str(Path(fs[-1]).relative_to(ROOT)), "text": "\n".join(keep)[:max_chars]})
    return out


def hot_topics(allp, days=7, min_channels=3):
    """여러 채널(3곳↑)이 같이 다룬 소식 — 중복 표시(dup_of)로 센다. 원글의 첫 줄만."""
    since = (datetime.now(KST) - timedelta(days=days)).isoformat()
    orig = {f"{x['channel']}/{x['id']}": x for x in allp if not x.get("dup_of") and x["time"] >= since}
    chans = defaultdict(set)
    for x in allp:
        if x.get("dup_of") and x["time"] >= since:
            chans[x["dup_of"]].add(x["channel"])
    rows = []
    for k, cs in chans.items():
        o = orig.get(k)
        if not o:
            continue
        n = len(cs | {o["channel"]})
        if n >= min_channels:
            head = next((l.strip() for l in o["text"].split("\n") if l.strip()), "")[:120]
            rows.append({"time": o["time"][:16], "channels": n, "type": o["type"], "stocks": [st["name"] for st in o.get("stocks", [])][:3], "head": head})
    return sorted(rows, key=lambda r: (-r["channels"], r["time"]))[:25]


def report_points(allp, pool, flow31, days=31, per=2, sectors=6, max_names=20):
    """채널 리포트 요약(2차)의 근거 글머리: 관찰 풀 종목 + 리포트가 많은 섹터 상위의 대표 종목 2개씩(최대 20종목). 종목당 최근 2건."""
    from report_digest import report_row
    since = (datetime.now(KST) - timedelta(days=days)).isoformat()
    by = defaultdict(list)
    for x in sorted(allp, key=lambda x: x["time"], reverse=True):
        if x["type"] == "report" and x.get("stock") and not x.get("dup_of") and x["time"] >= since and not x["text"].startswith("[✨ 리서치]"):
            by[x["stock"]].append(x)
    names = [s["name"] for s in pool]
    for f in flow31[:sectors]:
        names += (f.get("stocks") or [])[:2]
    out, seen = [], set()
    for n in names:
        if n in seen or n not in by or len(out) >= max_names:
            continue
        seen.add(n)
        items = []
        for x in by[n][:per]:
            r = report_row(x)
            items.append({"t": r["time"][:10], "broker": r.get("broker"), "dir": r.get("direction"), "before": r.get("before"), "after": r.get("after"),
                          "title": (r.get("title") or "")[:60], "points": [p[:110] for p in r["points"][:2]]})
        out.append({"name": n, "n_31d": len(by[n]), "up": sum(1 for x in by[n] if x.get("direction") == "상향"), "down": sum(1 for x in by[n] if x.get("direction") == "하향"), "reports": items})
    return out


def channel_themes(allp, uni):
    """업종별 '말 vs 주가' 태그 (web_build.theme_talk 재사용): 🔥주도 후보 / ⚠️말만 / 🤫조용히 오름 / 🧊식는 중."""
    import web_build as WB
    import market_pulse
    fl = safe(lambda: market_pulse.flows(), {}) or {}
    t = WB.theme_talk(allp, fl if isinstance(fl, dict) and "sectors" in fl else None, uni)
    rows = t.get("rows") if isinstance(t, dict) else t
    return [{k: r.get(k) for k in ("group", "talk", "talk_prev", "talk_chg", "up", "down", "stocks", "r5", "r20", "money5", "tag")} for r in (rows or [])[:20]]


def previous_report():
    L = load_latest()
    if not L:
        return None
    return {"made_at": L.get("made_at"), "title": L.get("title"), "conclusion": L.get("conclusion"),
            "themes": [{k: t.get(k) for k in ("id", "name", "stage", "conviction", "invalid", "thesis")} | {"companies": [c["name"] for c in t.get("companies", [])]} for t in L.get("themes", [])],
            "watch": L.get("watch"), "checkpoints": L.get("checkpoints"), "scorecard": L.get("scorecard"),
            "sector_scorecard": L.get("sector_scorecard"), "pool": L.get("pool")}


def trades_state():
    import risk, trades
    r = safe(lambda: risk.evaluate())
    s = safe(trades.summary)
    rv = safe(lambda: trades.review()) if hasattr(trades, "review") else None
    return {"positions": [{k: p.get(k) for k in ("name", "code", "qty", "avg_price", "price", "r_multiple", "stop", "to_stop_pct")} for p in (r or {}).get("positions", [])] if isinstance(r, dict) else None,
            "cr_won": (r or {}).get("cr_won") if isinstance(r, dict) else None, "stats": (s or {}).get("stats") if isinstance(s, dict) else None,
            "closed_recent": ((s or {}).get("closed") or [])[:8] if isinstance(s, dict) else None, "review": rv}


# ---------- prep ----------
def prep(weeks=4):
    import web_build as WB
    now = datetime.now(KST)
    uni, code_of, group_of = universe_maps()
    companies = {k: v for k, v in json.loads((DATA / "companies.json").read_text(encoding="utf-8")).items() if not k.startswith("_")}
    t, allp = WB.tg_data()
    by_stock_rep, flow31 = WB.report_rows(t, allp, companies, uni)
    pool = pool_stocks()
    for s in pool:
        s.setdefault("code", code_of.get(s["name"]))
        s["group"] = group_of(s["name"])
    out = {
        "made_at": now.strftime("%Y-%m-%d %H:%M"), "weeks": weeks,
        "regime": safe(regime), "market": safe(market_now), "overseas": safe(overseas), "econ": safe(econ_recent),
        "talk": safe(lambda: talk(allp, group_of, pool, weeks)),
        "earnings": safe(lambda: earnings_axis(allp, uni, companies, pool, by_stock_rep, flow31)),
        "price_money": safe(lambda: price_money(allp, uni, companies, pool, by_stock_rep)),
        "digests": safe(lambda: digests(5), []),
        "hot_topics": safe(lambda: hot_topics(allp, 7), []),
        "report_points": safe(lambda: report_points(allp, pool, flow31), []),
        "channel_themes": safe(lambda: channel_themes(allp, uni), []),
        "research": safe(lambda: research_recent(14), []),
        "card_digest": safe(lambda: __import__("research_cards").weekly(7), {}),   # 네이버 산업·전략 카드 업종별 집계 (Tier 3)
        "memos": safe(lambda: memos(7), []),
        "opinions": safe(lambda: opinions(7), []),
        "calendar": safe(lambda: calendar_ahead(pool, 14), []),
        "previous": safe(previous_report),
        "pool": pool,
        "trades": safe(trades_state),
        "note": "모든 숫자는 위 source 기준. 채널 글은 2차 자료. 주문 기능 없음. 매매 규칙은 2027-01-31까지 고정(docs/rules.md).",
    }
    PREP.mkdir(parents=True, exist_ok=True)
    f = PREP / f"{now.strftime('%Y-%m-%d')}.json"
    f.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    return out, f


def md_summary(o):
    """에이전트가 읽을 요약(전체 JSON은 파일로). 숫자 4개↑면 줄을 나눈다."""
    L = []
    r = o.get("regime") or {}
    L.append(f"# 전략 재료 {o['made_at']}  (전체: data/strategy/prep/*.json)")
    L.append(f"## ① 국면: 신호등 {r.get('light')} · 코스피 20일선 대비 {r.get('gap20')}% · 1주 {r.get('r1w')}% · 1개월 {r.get('r1m')}% · 고점 대비 {r.get('off_high')}% ({r.get('date')} 종가)")
    for m in (o.get("market") or {}).get("markets", []):
        L.append(f"- {m.get('market')} {m.get('price')} ({m.get('change_pct')}%) 외국인 {m.get('foreign_eok')}억 기관 {m.get('institution_eok')}억 개인 {m.get('individual_eok')}억 · 오른 {m.get('up')} 내린 {m.get('down')} · 신고가 {m.get('high52')} 신저가 {m.get('low52')} ({m.get('at')})")
    tk = o.get("talk") or {}
    L.append(f"## ② 말: 업종별 주별 글 수 (주 시작일 {tk.get('weeks')})")
    for g in tk.get("groups", [])[:15]:
        L.append(f"- {g['name']}: {g['weeks']} ({'+' if (g['chg_pct'] or 0) > 0 else ''}{g['chg_pct']}%) 목표가 {g.get('updown')}")
    L.append("관찰 풀 종목 주별 언급: " + " · ".join(f"{p['name']} {p['weeks']}" for p in tk.get("pool", [])[:20]))
    ea = o.get("earnings") or {}
    L.append(f"## ③ 이익: 31일 리포트 상향 {ea.get('totals_31d', {}).get('up')} / 하향 {ea.get('totals_31d', {}).get('down')}")
    L.append("최근 7일 섹터 흐름: " + " · ".join(f"{f['sector']} 🔺{f.get('up', 0)}🔽{f.get('down', 0)}🆕{f.get('new', 0)}" for f in ea.get("flow_7d", [])[:12]))
    for p in ea.get("pool", []):
        c = p.get("consensus") or {}; e = p.get("earnings") or {}
        L.append(f"- {p['name']}: 리포트 {p['reports_31d']}건 🔺{p['up']} 🔽{p['down']} · 컨센 {c.get('now')} ({c.get('chg_pct')}%, {c.get('n')}곳) · 실적 {e.get('verdict') or '-'} 영업이익 {e.get('op')} vs 예상 {e.get('op_est')}")
    pm = o.get("price_money") or {}
    L.append("## ④⑤ 가격·돈: 관찰 풀")
    for p in pm.get("pool", []):
        L.append(f"- {p['name']} {p.get('price')} ({p.get('date')}) RS {p.get('rs')} (4주 {p.get('rs_chg4w')}) · 1주 {p.get('r1w')}% 1개월 {p.get('r1m')}% 고점 대비 {p.get('off_high')}% · 20일선 {'위' if p.get('above20') else '아래'} · 외국인5일 {p.get('f5_eok')}억 기관5일 {p.get('i5_eok')}억")
    L.append("업종 5일 수익률·수급 상위: " + " · ".join(f"{s['group']} {s.get('r5')}% (외 {s.get('f5')} 기 {s.get('i5')})" for s in pm.get("sectors", [])[:10]))
    L.append("업종 5일 하위: " + " · ".join(f"{s['group']} {s.get('r5')}%" for s in pm.get("sectors", [])[-6:]))
    L.append("## 채널 흐름 (2차 자료) — 업종별 말 vs 주가")
    for r in o.get("channel_themes") or []:
        L.append(f"- {r.get('group')}: 글 {r.get('talk')}(전 {r.get('talk_prev')}, {r.get('talk_chg')}%) 🔺{r.get('up')}🔽{r.get('down')} · 5일 {r.get('r5')}% 20일 {r.get('r20')}% · 수급5일 {r.get('money5')}억 → {r.get('tag')} · {', '.join((r.get('stocks') or [])[:3])}")
    L.append("## 🔥 여러 채널이 같이 다룬 소식 (7일, 3곳↑)")
    for h in o.get("hot_topics") or []:
        L.append(f"- [{h['time'][5:]} · {h['channels']}곳 · {h['type']}] {h['head']} {('(' + ', '.join(h['stocks']) + ')') if h['stocks'] else ''}")
    L.append("## 채널 정리·리포트 정리 헤드라인 (5일, 날마다 마지막 1개, 머리 부분만)")
    for d in o.get("digests") or []:
        L.append(f"### [{d['date']} {d['kind']}] ({d['file']})")
        L.append(d["text"])
    L.append("## 채널 리포트 요약 근거 (2차 · 관찰 풀 + 리포트 많은 섹터 대표 종목, 종목당 최근 2건)")
    for rp in o.get("report_points") or []:
        L.append(f"- {rp['name']}: 31일 {rp['n_31d']}건 🔺{rp['up']} 🔽{rp['down']}")
        for r in rp["reports"]:
            tp = f"{r['before']:,}→{r['after']:,}" if r.get("before") and r.get("after") else (f"{r['after']:,}" if r.get("after") else "")
            L.append(f"  · {r['t'][5:]} {r.get('broker') or ''} {r.get('dir') or ''} {tp} {('— ' + r['title']) if r.get('title') else ''}")
            for pt in r["points"]:
                L.append(f"    - {pt}")
    cd = o.get("card_digest") or {}
    if cd.get("sectors"):
        import research_cards
        L.append(research_cards.weekly_md(cd).replace("## ", "## 네이버 산업·전략 리포트 카드 (7일) — ", 1))
    L.append(f"## 자료실 최근 14일 {len(o.get('research') or [])}건")
    for d in (o.get("research") or [])[:30]:
        L.append(f"- [{d.get('date')} {d.get('broker')} {d.get('kind')}] {d.get('title')} — {d.get('one_line')}")
    L.append("## 스트림 메모")
    for m in o.get("memos") or []:
        L.append(m["text"])
    L.append("## 최근 의견")
    for op in (o.get("opinions") or [])[-6:]:
        L.append(f"[{op['date']} {op['kind']}] {op['opinion']}")
    L.append("## 앞으로 14일 일정")
    for e in o.get("calendar") or []:
        L.append(f"- {e.get('date')} {e.get('time') or ''} {e.get('name')} ({e.get('kind')})")
    pv = o.get("previous")
    if pv:
        L.append(f"## 지난 보고서 {pv.get('made_at')}: {pv.get('title')}")
        for th in pv.get("themes", []):
            L.append(f"- {th['id']} {th['name']} [{th['stage']} · 확신 {th['conviction']}] 무효: {th.get('invalid')}")
        L.append("체크포인트: " + " / ".join(pv.get("checkpoints") or []))
    tr = o.get("trades") or {}
    L.append(f"## 매매: 보유 {len(tr.get('positions') or [])} · 통계 {tr.get('stats')}")
    return "\n".join(L)


# ---------- score ----------
def score():
    """지난 보고서 스트림별: 그 뒤 관찰 종목·업종의 가격·RS·수급 변화 (채점은 에이전트가, 숫자는 여기서)."""
    L = load_latest()
    if not L:
        return {"error": "latest.json 없음"}
    o, _ = prep(weeks=4)
    pm = {p["name"]: p for p in (o.get("price_money") or {}).get("pool", [])}
    tk = {p["name"]: p for p in (o.get("talk") or {}).get("pool", [])}
    ea = {p["name"]: p for p in (o.get("earnings") or {}).get("pool", [])}
    out = {"made_at": o["made_at"], "report_made_at": L.get("made_at"), "themes": []}
    for th in L.get("themes", []):
        rows = []
        for c in th.get("companies", []):
          for nm in split_names(c["name"]):
            p, t, e = pm.get(nm, {}), tk.get(nm, {}), ea.get(nm, {})
            rows.append({"name": nm, "role": c.get("role"), "r1w": p.get("r1w"), "r1m": p.get("r1m"), "rs": p.get("rs"), "rs_chg4w": p.get("rs_chg4w"),
                         "f5": p.get("f5_eok"), "i5": p.get("i5_eok"), "talk_weeks": t.get("weeks"), "up": e.get("up"), "down": e.get("down"), "earnings": e.get("earnings")})
        out["themes"].append({"id": th["id"], "name": th["name"], "stage": th.get("stage"), "conviction": th.get("conviction"),
                              "invalid": th.get("invalid"), "companies": rows})
    out["checkpoints"] = L.get("checkpoints")
    out["previous_scorecard"] = L.get("scorecard")
    return out


# ---------- pool ----------
def write_pool(L=None):
    L = L or load_latest()
    if not L:
        raise SystemExit("data/strategy/latest.json 없음")
    _, code_of, group_of = universe_maps()
    lines = ["# 관찰 풀 — 전략 보고서가 고른 종목 (Claude가 보고서 저장 때 다시 씀. 직접 고쳐도 됨: 빼고 싶은 종목은 줄을 지우고, 넣고 싶은 종목은 같은 형식으로 추가)",
             "# 감시 목록(screener --pool)은 이 풀 + RS 70↑ 종목만 본다. 주문 기능 없음.",
             f'updated = "{datetime.now(KST).strftime("%Y-%m-%d %H:%M")}"', f'source = "전략 보고서 {L.get("made_at", "")}"', ""]
    n = 0
    for th in L.get("themes", []):
        lines += ["[[themes]]", f'id = "{th.get("id", "")}"', f'name = "{th.get("name", "").replace(chr(34), "")}"', f'stage = "{th.get("stage", "")}"', "stocks = ["]
        for c in th.get("companies", []) + [{"name": x, "role": "풀"} for x in th.get("pool_extra", [])]:
            for nm in split_names(c["name"]):
                code = (c.get("code") if len(split_names(c["name"])) == 1 else None) or code_of.get(nm)
                if not code:
                    lines.append(f'  # {{ name = "{nm}" }}  # 종목 코드 못 찾음(비상장·ETF·해외·시총 2천억 미만?) — 확인 필요')
                    continue
                role = (c.get("role") or "").replace('"', "")
                lines.append(f'  {{ name = "{nm}", code = "{code}", role = "{role}", group = "{group_of(nm) or ""}" }},')
                n += 1
        lines += ["]", ""]
    POOL.write_text("\n".join(lines), encoding="utf-8")
    return n


# ---------- save ----------
REQUIRED = ("title", "made_at", "conclusion", "summary", "regime", "themes", "sector_scorecard", "pool", "scenarios", "scorecard", "checkpoints", "risks", "references")


def save(path):
    d = json.loads(Path(path).read_text(encoding="utf-8"))
    missing = [k for k in REQUIRED if k not in d]
    if missing:
        raise SystemExit(f"형식 오류: 빠진 칸 {missing} (docs/strategy-report-format.md 참고)")
    if d.get("sample"):
        raise SystemExit("sample = true 인 초안은 저장하지 않음")
    for th in d["themes"]:
        for k in ("id", "name", "stage", "conviction", "thesis", "logic", "evidence", "companies", "against", "invalid"):
            if k not in th:
                raise SystemExit(f"스트림 {th.get('id')} 에 {k} 없음")
        # 반론 3개 이상 (2026-11-15 사용자 확정: 반론가 규칙 '스트림마다 3~5개'를 저장 때 검사)
        n_against = len([x for x in (th.get("against") or []) if str(x).strip()])
        if n_against < 3:
            raise SystemExit(f"스트림 {th.get('id')} 반론이 {n_against}개 — 3개 이상 필요 (반론가 단계를 다시 하세요)")
    if not d.get("red_team"):
        raise SystemExit("red_team 칸 없음 — 반론가 보조 에이전트 결과(누가·몇 개·확신도 조정)를 적으세요 (SKILL 2단계)")
    HIST.mkdir(parents=True, exist_ok=True)
    old = load_latest()
    if old:
        (HIST / f"{(old.get('made_at') or 'old')[:10]}.json").write_text(json.dumps(old, ensure_ascii=False, indent=1), encoding="utf-8")
    d["version"] = 3
    (STRAT / "latest.json").write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8")
    n = write_pool(d)
    return {"saved": str(STRAT / "latest.json"), "history": sorted(p.name for p in HIST.glob("*.json")), "pool_stocks": n}


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd")
    p = sub.add_parser("prep"); p.add_argument("--weeks", type=int, default=4); p.add_argument("--json", action="store_true", help="요약 대신 JSON 출력")
    sub.add_parser("score")
    sub.add_parser("pool")
    s = sub.add_parser("save"); s.add_argument("--file", required=True)
    a = ap.parse_args()
    if a.cmd in (None, "prep"):
        o, f = prep(getattr(a, "weeks", 4))
        if getattr(a, "json", False):
            print(json.dumps(o, ensure_ascii=False))
        else:
            print(md_summary(o)); print(f"\n(저장: {f})")
    elif a.cmd == "score":
        print(json.dumps(score(), ensure_ascii=False, indent=1))
    elif a.cmd == "pool":
        print(json.dumps({"pool_stocks": write_pool(), "file": str(POOL)}, ensure_ascii=False))
    elif a.cmd == "save":
        print(json.dumps(save(a.file), ensure_ascii=False))


if __name__ == "__main__":
    main()
