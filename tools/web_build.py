"""웹 화면(트레이딩룸) 만들기: 여러 도구의 결과를 data 하나로 모아 web/index.html에 넣는다.

설계: docs/web-design.md. 보기 전용 (주문 기능 없음). 계좌 정보가 들어가므로 비공개 Artifact로만 올린다.

사용법:
    python3 tools/web_build.py            # 데이터 모으기 → web/index.html (Claude가 Artifact로 다시 올림)
    python3 tools/web_build.py --no-live  # 시세 조회 없이 (빠른 확인용)
"""
import argparse
import glob
import json
import re
import statistics
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

from common import DATA, ROOT, channels, http_get, load_toml, positions
from naver_quote import KST

WEB = ROOT / "web"
SCHEDULE = [("06:55", "아침 브리핑", "morning"), ("09:53", "오전 리포트 브리핑", "report_brief_am"),
            ("14:53", "오후 리포트 브리핑", "report_brief_pm"), ("16:07", "감시 목록", "watchlist")]
KIND = {"morning": "아침 브리핑", "report_brief_am": "리포트 브리핑 · 오전", "report_brief_pm": "리포트 브리핑 · 오후",
        "channels": "채널 정리"}


def safe(fn, default=None):
    try:
        return fn()
    except Exception as e:  # 한 칸이 실패해도 나머지는 만든다
        return default if default is not None else {"error": str(e)[:200]}


def market(live):
    if not live:
        return {}
    import subprocess
    def run(*args):
        out = subprocess.run(["python3", *args], cwd=ROOT, capture_output=True, text=True, timeout=120).stdout
        return json.loads(out)
    kr = safe(lambda: run("tools/naver_quote.py", "index"))
    us = safe(lambda: run("tools/us_quote.py", "price"))
    import us_quote
    extra = {"NQ=F": ("나스닥100 선물", "future"), "EWY": ("EWY 한국 ETF", "etf")}
    want = ["EWY", "^GSPC", "^IXIC", "NQ=F", "^DJI", "^SOX", "KRW=X", "^TNX", "^VIX", "CL=F"]  # 화면 순서
    got = {r["symbol"]: r for r in (us.get("results", []) if isinstance(us, dict) else []) if r.get("price") is not None}
    for sym, (name, kind) in extra.items():
        q = safe(lambda: us_quote.quote(sym, name, kind), {})
        if q.get("price") is not None:
            got[sym] = q
    usr = [got[s] for s in want if s in got]
    syms = ["^KS11", "^KQ11"] + want
    return {"kr": kr.get("results", []) if isinstance(kr, dict) else [], "us": usr,
            "spark": {s: v for s in syms if (v := safe(lambda s=s: spark(s), {})) and v.get("c")},
            "source": "코스피·코스닥 네이버, 해외 Yahoo Finance (비공식) · 미니 차트 Yahoo 5분봉(전일+당일)"}


def spark(symbol, keep=80):
    """미니 차트용: 전일+당일 5분봉 종가. 전일 구간 끝 = 당일 기준선(전일 종가)."""
    d = json.loads(http_get("https://query1.finance.yahoo.com/v8/finance/chart/" + symbol, {"range": "2d", "interval": "5m"}))
    r = d["chart"]["result"][0]
    off = r["meta"].get("gmtoffset", 0)
    pts = [(t, c) for t, c in zip(r.get("timestamp", []), r["indicators"]["quote"][0]["close"]) if c is not None]
    if not pts:
        return {}
    day = lambda t: datetime.fromtimestamp(t + off, timezone.utc).strftime("%Y-%m-%d")
    days = sorted({day(t) for t, _ in pts})
    prev = [p for p in pts if day(p[0]) == days[0]] if len(days) > 1 else []
    cur = [p for p in pts if day(p[0]) == days[-1]]
    step = max(1, (len(prev) + len(cur)) // keep)
    thin = lambda xs: xs[::step] + ([xs[-1]] if xs and (len(xs) - 1) % step else [])
    prev, cur = thin(prev), thin(cur)
    base = prev[-1][1] if prev else r["meta"].get("chartPreviousClose")
    return {"c": [round(c, 2) for _, c in prev + cur], "split": len(prev), "base": round(base, 2) if base else None,
            "day": days[-1], "last_kst": datetime.fromtimestamp(cur[-1][0] + 9 * 3600, timezone.utc).strftime("%m/%d %H:%M") if cur else None}


def section(text, marker):
    """브리핑 본문에서 marker(예: 💡)로 시작하는 줄부터 빈 줄 두 번 전까지."""
    lines = text.splitlines()
    for i, ln in enumerate(lines):
        if ln.strip().startswith(marker):
            out = []
            for x in lines[i:]:
                if len(out) > 1 and not x.strip():  # 제목 줄 다음 첫 빈 줄에서 끝
                    break
                if x.strip():
                    out.append(x)
            return "\n".join(out[:8]).strip()
    return None


def briefs(days=21):
    rows = []
    since = (datetime.now(KST) - timedelta(days=days)).strftime("%Y-%m-%d")
    for f in sorted(glob.glob(str(ROOT / "reports" / "*" / "*.md")), reverse=True):
        p = Path(f)
        day = p.parent.name
        if day < since or p.stem.endswith("_test"):
            continue
        kind = next((k for k in KIND if p.stem.startswith(k)), "etc")
        text = p.read_text(encoding="utf-8")
        rows.append({"date": day, "kind": kind, "kind_name": KIND.get(kind, p.stem), "file": f"reports/{day}/{p.name}",
                     "title": text.splitlines()[0].strip() if text else p.stem, "text": text,
                     "opinion": section(text, "💡") or section(text, "🧭")})
    return rows


def schedule(now, brief_rows):
    today = now.strftime("%Y-%m-%d")
    have = {b["kind"] for b in brief_rows if b["date"] == today}
    if (ROOT / "reports" / today / "watchlist.png").exists() or (DATA / "bus" / today / "screener.json").exists():
        have.add("watchlist")
    out = []
    for t, name, kind in SCHEDULE:
        due = now.weekday() < 5 and now.strftime("%H:%M") >= t
        out.append({"time": t, "name": name, "kind": kind, "done": kind in have,
                    "state": "완료" if kind in have else ("늦음·확인 필요" if due else ("예정" if now.weekday() < 5 else "휴장"))})
    return out


def watch():
    files = sorted(glob.glob(str(DATA / "bus" / "*" / "screener.json")))
    if not files:
        return None
    d = json.loads(Path(files[-1]).read_text(encoding="utf-8"))
    keep = ["stock", "code", "market", "sector", "close", "date", "rs", "value20_eok", "off_high_pct", "checks",
            "gate_score", "setups", "run_pct", "today", "vol_ratio", "stage", "levels", "overhead_zone",
            "tier", "missing", "group", "ia", "ia_up_share", "gate_miss"]
    def slim(x):
        y = {k: x.get(k) for k in keep}
        b = x.get("base") or {}
        y["base"] = {k: b.get(k) for k in ("pivot", "pivot_date", "days", "depth_pct", "stage1_pct", "giveback_pct", "vol_dryup")} if b else None
        return y
    return {"as_of": d.get("as_of"), "made_at": d.get("made_at"), "count": d.get("count"), "rules": d.get("rules"),
            "source": d.get("source"), "watch": [slim(x) for x in d.get("watch", [])],
            "running": [slim(x) for x in d.get("running", [])], "near_miss": [slim(x) for x in d.get("near_miss", [])[:15]],
            "signals": [slim(x) for x in d.get("signals", [])], "candidates": [slim(x) for x in d.get("candidates", [])]}


def polling(codes):
    """네이버 실시간: 현재가·등락·고가·누적 거래량."""
    out = {}
    codes = list(dict.fromkeys(c for c in codes if c))
    for i in range(0, len(codes), 40):
        d = safe(lambda: json.loads(http_get("https://polling.finance.naver.com/api/realtime/domestic/stock/" + ",".join(codes[i:i + 40]))), {})
        for x in d.get("datas", []):
            def num(k):
                try:
                    return float(str(x.get(k + "Raw") or x.get(k) or 0).replace(",", ""))
                except ValueError:
                    return 0.0
            out[x["itemCode"]] = {"price": num("closePrice"), "change_pct": num("fluctuationsRatio"),
                                  "high": num("highPrice"), "volume": num("accumulatedTradingVolume"),
                                  "at": (x.get("localTradedAt") or "")[:16], "status": x.get("marketStatus")}
    return out


def session_frac(now):
    """정규장(09:00~15:30) 중 지난 비율. 장 전·후는 1 (하루치로 봄)."""
    m = now.hour * 60 + now.minute
    return 1.0 if m < 540 or m >= 930 or now.weekday() >= 5 else max(0.05, (m - 540) / 390)


def clean_head(text):
    """글 첫 줄에서 [말머리]·✅ 같은 장식을 뗀 제목."""
    first = re.sub(r"https?://\S+", "", text).strip().split("\n")[0]
    first = re.sub(r"^(\s*(✅|📌|\[[^\]]*\]|【[^】]*】)\s*)+", "", first)
    return first.strip()[:90]


def insights(W, etf, allp, by_stock, now):
    """홈 인사이트: 시장 신호등 · 셋업 점검(감시 목록 × 지금 가격) · 주도주 · 채널 특징주 · 강한/약한 섹터.
    조건 충족 여부를 보여 줄 뿐 매수 추천이 아니다 (절대 규칙 4)."""
    import screener
    S = screener
    out = {"at": now.strftime("%Y-%m-%d %H:%M")}
    # 1) 시장 신호등 (KODEX 200: 20일선 위/아래, 이평 정배열)
    b = (etf or {}).get("benchmark") or {}
    if b:
        light = "green" if b.get("above20") and b.get("aligned") else "yellow" if b.get("above20") or (b.get("slope20") or 0) > 0 else "red"
        out["regime"] = {"light": light, "etf": b.get("etf"), "gap20": b.get("gap20"), "slope20": b.get("slope20"),
                         "r1w": b.get("r1w"), "r1m": b.get("r1m"), "off_high": b.get("off_high"), "date": b.get("date"),
                         "text": {"green": "지수가 20일선 위 · 이평 정배열 → 돌파 매매에 우호적",
                                  "yellow": "지수가 20일선 근처 · 방향 탐색 → 돌파는 거래량 확인을 더 엄격히",
                                  "red": "지수가 20일선 아래 · 하락 추세 → 돌파 실패가 잦은 구간, 신규 진입은 작게"}[light]}
    W = W or {}
    cands = W.get("watch", []) + [x for x in W.get("near_miss", []) if x.get("gate_score", 0) >= 6 and x.get("levels")]
    leaders = W.get("running", [])
    # 인더스트리 액션(지금 기준): 후보 종목의 업종(사용자 분류 → 네이버 업종) 다른 종목들 실시간 등락
    from sector_map import custom_map
    from universe import load as load_universe
    from backtest import is_etf
    cmap = custom_map()
    uni = [u for u in load_universe()["stocks"] if (u.get("market_cap_eok") or 0) >= 2000 and not is_etf(u["name"])
           and u.get("market") not in ("KONEX", "2")]
    grp_of = {u["code"]: cmap.get(u["code"]) or "네이버:" + u["industry"] for u in uni}
    members = defaultdict(list)
    for c, g in grp_of.items():
        members[g].append(c)
    need = {grp_of.get(x["code"]) for x in cands if grp_of.get(x["code"])}
    peer_codes = [c for g in need for c in members[g][:80]]
    q = polling([x["code"] for x in cands + leaders] + peer_codes)
    frac = session_frac(now)
    rows = []
    for x in cands:
        lv = x.get("levels") or {}
        live = q.get(x["code"], {})
        price = live.get("price") or x.get("close")
        pivot, alert = lv.get("breakout"), lv.get("alert")
        if not pivot or not price or not x.get("value20_eok") or (live and not live.get("volume")):
            continue  # 거래 없는 종목(신규 상장·거래정지)은 뺀다
        vols = [d["volume"] for d in safe(lambda: screener.fetch_daily(x["code"]), [])[-21:-1]]
        avgv = sum(vols) / len(vols) if vols else None
        pace = round(live.get("volume", 0) / (avgv * frac), 2) if avgv and live.get("volume") else None
        dist = round((pivot / price - 1) * 100, 1)
        if price >= pivot:
            status, rank = "기준가 돌파 중", 0  # 인더스트리 액션 없으면 아래에서 '업종 무반응'으로 바꿈
        elif price >= alert:
            status, rank = "알림가 도달", 1
        elif dist <= 5:
            status, rank = "기준가 근접", 2
        else:
            status, rank = "대기", 3
        pros, cons = [], []
        if x.get("gate_score") == 7:
            pros.append("관문 7/7")
        else:
            cons.append("관문 " + ", ".join(k for k, v in (x.get("checks") or {}).items() if not v) + " 미달")
        if x.get("rs", 0) >= 90:
            pros.append(f"RS {x['rs']}")
        bs = x.get("base") or {}
        if bs.get("vol_dryup") and bs["vol_dryup"] < 0.8:
            pros.append(f"조정 중 거래량 마름({bs['vol_dryup']})")
        if bs.get("giveback_pct") is not None and bs["giveback_pct"] > 40:
            cons.append(f"상승분 {bs['giveback_pct']}% 반납")
        if x.get("today"):
            pros.append("어제 " + ", ".join(x["today"]))
        if rank <= 1:
            if pace is not None and pace >= 1.5:
                pros.append(f"거래량 페이스 {pace}배")
            elif pace is not None:
                cons.append(f"거래량 페이스 {pace}배 (돌파 기준 1.5배 미만)")
        if x.get("overhead_zone"):
            cons.append("위쪽 매물대")
        g = grp_of.get(x["code"])
        xs = [q[c]["change_pct"] / 100 for c in members.get(g, [])[:80] if c != x["code"] and c in q]
        ia, ia_share, ia_med = S.industry_action(xs) if g else ("확인 불가", None, None)
        gname = (g or "").replace("네이버:", "")
        if ia == "동반 상승":
            pros.append(f"업종 동반 상승({gname} {ia_share}%가 +2%↑)")
        else:
            cons.append(f"인더스트리 액션 없음({gname}{'' if ia_share is None else f' {ia_share}%만 +2%↑'}) → 돌파해도 신호 아님")
        if out.get("regime", {}).get("light") == "red":
            cons.append("시장 신호등 빨강")
        if rank == 0 and ia != "동반 상승":
            status = "돌파 중 · 업종 무반응"
        rows.append({"ia": ia, "ia_group": gname, "stock": x["stock"], "code": x["code"], "sector": x["sector"], "setups": x.get("setups", []),
                     "price": price, "change_pct": live.get("change_pct"), "pivot": pivot, "alert": alert, "stop": lv.get("stop_1r"),
                     "dist_pct": dist, "pace": pace, "status": status, "rank": rank, "pros": pros, "cons": cons, "rs": x.get("rs")})
    out["setups"] = sorted(rows, key=lambda r: (r["rank"], r["dist_pct"]))[:8]
    out["setups_note"] = f"감시 목록 {W.get('as_of', '')} 기준가 × 네이버 현재가({now.strftime('%H:%M')}). 거래량 페이스 = 오늘 누적 ÷ (20일 평균 × 장 경과 비율)"
    # 2) 주도주: 1stage 진행 중 · RS 상위 (조정 없이 신고가 근처를 달리는 종목)
    out["leaders"] = [{"stock": x["stock"], "code": x["code"], "sector": x["sector"], "rs": x["rs"], "run_pct": x.get("run_pct"),
                       "off_high_pct": x.get("off_high_pct"), "price": q.get(x["code"], {}).get("price") or x["close"],
                       "change_pct": q.get(x["code"], {}).get("change_pct")}
                      for x in sorted(leaders, key=lambda x: (-x["rs"], -(x.get("run_pct") or 0)))[:6]]
    # 3) 채널 특징주: 24시간 안에 여러 채널·여러 글이 다룬 종목
    since = now - timedelta(hours=24)
    cnt, chans, heads, kinds = Counter(), defaultdict(set), {}, defaultdict(Counter)
    for x in allp:
        if datetime.fromisoformat(x["time"]) < since or x["type"] in ("other", "market"):
            continue
        names = {x["stock"]} if x["type"] == "report" and x.get("stock") else {st["name"] for st in x.get("stocks", [])}
        names = {n for n in names if n != x.get("broker") and not n.endswith("증권")} if x["type"] == "report" else names
        if not names or len(names) > 3:  # 여러 종목 나열 글은 제외
            continue
        for n in names:
            cnt[n] += 1
            chans[n].add(x["channel"])
            kinds[n][x["type"]] += 1
            if n not in heads or x["type"] in ("earnings", "company"):
                heads[n] = clean_head(x["text"])
    today = now.strftime("%Y-%m-%d")
    hot = []
    for n, c in cnt.most_common(30):
        rs = [r for r in by_stock.get(n, []) if r["time"].startswith(today)]
        score = c + 2 * len(chans[n]) + len(rs)
        hot.append({"stock": n, "posts": c, "channels": len(chans[n]), "headline": heads.get(n), "kinds": dict(kinds[n]),
                    "reports_today": len(rs), "up": sum(r.get("direction") == "상향" for r in rs),
                    "down": sum(r.get("direction") == "하향" for r in rs), "score": score})
    out["hot"] = sorted(hot, key=lambda h: -h["score"])[:6]
    # 4) 섹터: ETF 1주 수익률 상·하위
    res = (etf or {}).get("results") or []
    srt = sorted(res, key=lambda r: -(r.get("r1w") or -99))
    out["sectors_up"] = [{k: r.get(k) for k in ("sector", "etf", "r1w", "r1m", "above20", "rs_score")} for r in srt[:3]]
    out["sectors_down"] = [{k: r.get(k) for k in ("sector", "etf", "r1w", "r1m", "above20", "rs_score")} for r in srt[-3:][::-1]]
    return out


def lab(data, now):
    """검증실: 백테스트 결과(tools/backtest.py) · 감시 목록 성적표 · 매매 일지 · 주간 리뷰."""
    out = {}
    for k, f in (("backtest", "latest.json"), ("scorecard", "scorecard.json")):
        path = DATA / "backtest" / f
        out[k] = safe(lambda: json.loads(path.read_text(encoding="utf-8"))) if path.exists() else None
    jpath = DATA / "journal.jsonl"
    out["journal"] = [json.loads(x) for x in jpath.read_text(encoding="utf-8").splitlines() if x.strip()][-50:][::-1] if jpath.exists() else []
    # 주간 리뷰 (이번 주 월요일부터)
    monday = (now - timedelta(days=now.weekday())).strftime("%Y-%m-%d")
    etf = data.get("sectors_etf") or {}
    res = sorted(etf.get("results") or [], key=lambda r: -(r.get("r1w") or -99))
    rk = data.get("risk") or {}
    out["weekly"] = {
        "from": monday, "to": now.strftime("%Y-%m-%d"),
        "kospi_1w": (etf.get("benchmark") or {}).get("r1w"), "bench": (etf.get("benchmark") or {}).get("etf"),
        "top": [(r["sector"], r.get("r1w")) for r in res[:3]], "bottom": [(r["sector"], r.get("r1w")) for r in res[-3:][::-1]],
        "briefs": sum(1 for b in data.get("briefs", []) if b["date"] >= monday),
        "watch_n": len((data.get("watch") or {}).get("watch", [])),
        "pnl_won": sum(p.get("pnl_won") or 0 for p in rk.get("positions", [])), "cr_pct": rk.get("CR_pct"), "e_pct": rk.get("E_pct"),
        "journal_n": sum(1 for j in out["journal"] if j.get("date", "") >= monday),
    }
    return out


def tg_data():
    import tg_channel as t
    allp = [x for c in t.channels() for x in t.load_store(c["id"]).values()]
    return t, allp


def report_rows(t, allp, companies, uni):
    from report_digest import report_row
    month_ago = datetime.now(KST) - timedelta(days=31)
    reps = [x for x in allp if not x.get("dup_of") and x["type"] == "report" and x.get("stock")
            and not x["text"].startswith("[✨ 리서치]") and datetime.fromisoformat(x["time"]) >= month_ago]
    by_stock = defaultdict(list)
    for x in reps:
        r = report_row(x)
        r["points"] = r["points"][:3]
        by_stock[x["stock"]].append(r)
    # 섹터 흐름 (1개월)
    sec = defaultdict(lambda: {"up": 0, "down": 0, "new": 0, "changes": [], "stocks": Counter()})
    for name, rs in by_stock.items():
        code = uni.get(name, {}).get("code")
        card = companies.get(code) if code else None
        key = card["detail"] if card else uni.get(name, {}).get("industry", "기타")
        big = card["sector"] if card else None
        for r in rs:
            d = r.get("direction")
            sec[key]["up" if d == "상향" else "down" if d == "하향" else "new"] += 1
            if r.get("before") and r.get("after"):
                sec[key]["changes"].append(r["after"] / r["before"] - 1)
            sec[key]["stocks"][name] += 1
            sec[key]["big"] = big
    flow = sorted(({"sector": k, "big": v.get("big"), "up": v["up"], "down": v["down"], "new": v["new"],
                    "avg_change_pct": round(statistics.mean(v["changes"]) * 100, 1) if v["changes"] else None,
                    "stocks": [n for n, _ in v["stocks"].most_common(6)]} for k, v in sec.items()),
                  key=lambda s: -(s["up"] + s["down"] + s["new"]))[:30]
    return by_stock, flow


def company_trends(comp_list, allp):
    """기업 메뉴용: 강도(RS 백분위)와 그 추이, 가격 흐름, 중요도 점수. 일봉은 감시 목록 캐시 재사용."""
    import screener as S
    from common import CACHE, positions, watchlist
    # 1) 전체 종목 RS 분포 (감시 목록이 받아 둔 일봉 캐시, 시총 2천억↑)
    closes = {}
    for f in (CACHE / "daily").glob("*.json"):
        try:
            rows = json.loads(f.read_text())["rows"]
        except Exception:
            continue
        if len(rows) >= 130:
            closes[f.stem] = [r["close"] for r in rows]
    lags = list(range(0, 65, 5))  # 오늘, 1주 전 … 12주 전
    dist = {}
    for lag in lags:
        vals = []
        for c in closes.values():
            x = S.rs_raw(c[:len(c) - lag] if lag else c)
            if x is not None:
                vals.append(x)
        dist[lag] = sorted(vals)
    rich = len(closes) >= 300  # 감시 목록 캐시가 충분할 때만 RS 계산. 아니면(깃허브 액션 등) 저장해 둔 값 사용
    snap_path = DATA / "radar" / "company_rs.json"
    snap = {}
    if not rich and snap_path.exists():
        snap = json.loads(snap_path.read_text(encoding="utf-8"))
    pct = lambda lag, x: None if x is None or not rich or not dist[lag] else round(sum(1 for y in dist[lag] if y <= x) / len(dist[lag]) * 99)
    held = {p["code"] for p in positions()}
    watch = {w["code"] for w in watchlist() if w.get("code")}
    since7 = datetime.now(KST) - timedelta(days=7)
    mention = Counter()
    for x in allp:
        if x.get("dup_of") or datetime.fromisoformat(x["time"]) < since7:
            continue
        for st in x.get("stocks", [])[:3]:
            mention[st["code"]] += 1
    for c in comp_list:
        code = c["code"]
        rows = None
        if code in closes:
            rows = json.loads((CACHE / "daily" / f"{code}.json").read_text())["rows"]
        else:
            rows = safe(lambda: S.fetch_daily(code)) or []
        cl = [r["close"] for r in rows]
        tr = {"held": code in held, "watch": code in watch, "mentions_7d": mention[code]}
        if len(cl) >= 30:
            ret = lambda n: round((cl[-1] / cl[-1 - n] - 1) * 100, 1) if len(cl) > n else None
            ma = lambda n: sum(cl[-n:]) / n if len(cl) >= n else None
            hi = max(r["high"] for r in rows[-250:])
            m20, m50 = ma(20), ma(50)
            rs_hist = [{"lag": lag, "rs": pct(lag, S.rs_raw(cl[:len(cl) - lag] if lag else cl))} for lag in lags]
            rs_now = rs_hist[0]["rs"]
            rs_4w = next((h["rs"] for h in rs_hist if h["lag"] == 20), None)
            last = rows[-125:]
            tr.update({"price": cl[-1], "date": rows[-1]["date"], "r1w": ret(5), "r1m": ret(21), "r3m": ret(62),
                       "off_high": round((cl[-1] / hi - 1) * 100, 1),
                       "above20": m20 and cl[-1] > m20, "above50": m50 and cl[-1] > m50,
                       "rs": rs_now, "rs_chg4w": (rs_now - rs_4w) if rs_now is not None and rs_4w is not None else None,
                       "rs_hist": [h["rs"] for h in rs_hist][::-1],
                       "chart": {"d": [r["date"] for r in last], "c": [r["close"] for r in last],
                                 "ma20": [round(sum(cl[i - 19:i + 1]) / 20) if i >= 19 else None for i in range(len(cl) - len(last), len(cl))],
                                 "ma50": [round(sum(cl[i - 49:i + 1]) / 50) if i >= 49 else None for i in range(len(cl) - len(last), len(cl))]},
                       "spark": [round(x) for x in cl[-60:]]})
        # 중요도: 보유 40 · 관심 20 · 1개월 리포트(최대 30) · 7일 채널 언급(최대 20) · 목표가 변경 쏠림(최대 10)
        net = c["up"] - c["down"]
        tr["importance"] = (40 if tr["held"] else 20 if tr["watch"] else 0) + min(c["n_reports"], 10) * 3 \
            + min(tr["mentions_7d"], 10) * 2 + min(abs(net), 5) * 2
        if not rich and code in snap:
            tr.update(snap[code])
        c["trend"] = tr
        c["target_hist"] = [{"t": r["time"][:10], "after": r["after"], "dir": r.get("direction"), "broker": r.get("broker")}
                            for r in c.pop("_all_reports", []) if r.get("after")]
    if rich:
        snap_path.parent.mkdir(parents=True, exist_ok=True)
        snap_path.write_text(json.dumps({c["code"]: {k: c["trend"].get(k) for k in ("rs", "rs_chg4w", "rs_hist")}
                                         for c in comp_list if c["trend"].get("rs") is not None}, ensure_ascii=False), encoding="utf-8")
    return comp_list



def channel_feed(t, allp, hours=72):
    since = datetime.now(KST) - timedelta(hours=hours)
    rows = []
    for x in sorted(allp, key=lambda p: p["time"], reverse=True):
        if datetime.fromisoformat(x["time"]) < since or x.get("dup_of") or x["type"] == "other":
            continue
        rows.append({"time": x["time"][:16].replace("T", " "), "channel": x["channel"], "type": x["type"],
                     "type_name": t.CATEGORIES[x["type"]], "text": re.sub(r"https?://\S+", "", x["text"]).strip()[:700],
                     "url": x["url"], "also_in": x.get("also_in", []), "photo": bool(x.get("photos")),
                     "stocks": [s["name"] for s in x.get("stocks", [])][:4]})
    return rows


def channel_stats(t, allp):
    since = datetime.now(KST) - timedelta(days=30)
    out = []
    for c in t.channels():
        ps = [x for x in allp if x["channel"] == c["id"] and datetime.fromisoformat(x["time"]) >= since]
        cnt = Counter(t.CATEGORIES[x["type"]] for x in ps if not x.get("dup_of"))
        out.append({"id": c["id"], "description": c.get("description", ""), "posts_30d": len(ps),
                    "per_day": round(len(ps) / 30, 1), "dups": sum(1 for x in ps if x.get("dup_of")),
                    "top": cnt.most_common(3)})
    return out


def main():
    p = argparse.ArgumentParser(description="웹 화면 데이터 만들기")
    p.add_argument("--no-live", action="store_true", help="시세 조회 생략")
    p.add_argument("--data-out", help="화면 대신 데이터 JSON만 이 경로에 쓰기 (깃허브 Actions 새로고침용)")
    p.add_argument("--only", choices=["channels"], help="한 부분만 새로 (나머지는 지난 데이터 그대로). channels = 채널 새 글 수집 후 채널 피드·특징주만")
    a = p.parse_args()
    now = datetime.now(KST)
    if a.only:
        return partial(a.only, now)
    from universe import load as load_universe
    uni = {s["name"]: s for s in load_universe()["stocks"]}
    companies = {k: v for k, v in json.loads((DATA / "companies.json").read_text(encoding="utf-8")).items() if not k.startswith("_")}
    t, allp = tg_data()
    by_stock, flow = report_rows(t, allp, companies, uni)
    brief_rows = briefs()

    import risk
    risk_now = safe(lambda: risk.evaluate()) if not a.no_live else safe(lambda: risk.evaluate(prices={}))
    comp_list = []
    for code, c in companies.items():
        rs = by_stock.get(c["name"], [])
        afters = [r["after"] for r in rs if r.get("after")]
        comp_list.append({**c, "code": code, "market_cap_eok": uni.get(c["name"], {}).get("market_cap_eok"),
                          "reports": rs[-8:][::-1], "n_reports": len(rs), "_all_reports": rs,
                          "up": sum(r.get("direction") == "상향" for r in rs), "down": sum(r.get("direction") == "하향" for r in rs),
                          "median_target": statistics.median(afters) if afters else None})
    comp_list.sort(key=lambda c: -c["n_reports"])
    comp_list = safe(lambda: company_trends(comp_list, allp)) or [{k: v for k, v in c.items() if k != "_all_reports"} for c in comp_list]

    data = {
        "built_at": now.strftime("%Y-%m-%d %H:%M"),
        "market": market(not a.no_live),
        "risk": risk_now,
        "account": load_toml("account.toml"),
        "schedule": schedule(now, brief_rows),
        "briefs": brief_rows,
        "watch": watch(),
        "sectors_etf": None,
        "report_flow": flow,
        "companies": comp_list,
        "channels": channel_feed(t, allp),
        "channel_stats": channel_stats(t, allp),
        "categories": t.CATEGORIES,
        "note": "보기 전용 · 주문 기능 없음 · 채널 글은 2차 자료",
    }
    if not a.no_live:
        import subprocess
        out = subprocess.run(["python3", "tools/sector_etf.py"], cwd=ROOT, capture_output=True, text=True, timeout=300).stdout
        data["sectors_etf"] = safe(lambda: json.loads(out))
    data["insights"] = safe(lambda: insights(data["watch"], data["sectors_etf"], allp, by_stock, now))
    data["lab"] = lab(data, now)
    rp = DATA / "radar" / "latest.json"
    data["radar"] = safe(lambda: json.loads(rp.read_text(encoding="utf-8"))) if rp.exists() else None
    data["refresh"] = {"owner": "livegym7", "repo": "stock_team", "workflow": "web-data.yml", "branch": "web-data", "path": "data.json"}
    data["parts"] = {k: data["built_at"] for k in ("market", "risk", "channels", "insights")}
    if a.data_out:
        Path(a.data_out).parent.mkdir(parents=True, exist_ok=True)
        Path(a.data_out).write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        print(json.dumps({"built_at": data["built_at"], "out": a.data_out}, ensure_ascii=False))
        return
    blob = write_html(data)
    print(json.dumps({"built_at": data["built_at"], "out": "web/index.html", "kb": round(len(blob) / 1024),
                      "briefs": len(brief_rows), "companies": len(comp_list), "channels": len(data["channels"]),
                      "watch": len((data["watch"] or {}).get("watch", []))}, ensure_ascii=False))


LAST = WEB / "last_data.json"   # 마지막 전체 데이터 (부분 새로고침용, 커밋 안 함)


def write_html(data):
    WEB.mkdir(exist_ok=True)
    LAST.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    tpl = (WEB / "app.html").read_text(encoding="utf-8")
    blob = json.dumps(data, ensure_ascii=False).replace("</", "<\\/")
    (WEB / "index.html").write_text(tpl.replace("/*__DATA__*/null", blob), encoding="utf-8")
    return blob


def partial(part, now):
    """부분 새로고침: 지난 전체 데이터에서 한 부분만 바꿔 다시 쓴다 (시세·백테스트 등은 그대로)."""
    if not LAST.exists():
        raise SystemExit("지난 전체 데이터(web/last_data.json)가 없습니다. 먼저 python3 tools/web_build.py 로 전체를 만드세요")
    data = json.loads(LAST.read_text(encoding="utf-8"))
    stamp = now.strftime("%Y-%m-%d %H:%M")
    if part == "channels":
        import tg_channel
        new = tg_channel.collect_all()
        t, allp = tg_data()
        data["channels"] = channel_feed(t, allp)
        data["channel_stats"] = channel_stats(t, allp)
        from universe import load as load_universe
        uni = {s["name"]: s for s in load_universe()["stocks"]}
        companies = {k: v for k, v in json.loads((DATA / "companies.json").read_text(encoding="utf-8")).items() if not k.startswith("_")}
        by_stock, flow = report_rows(t, allp, companies, uni)
        data["report_flow"] = flow
        ins = data.get("insights") or {}
        fresh = safe(lambda: insights({}, None, allp, by_stock, now))   # 특징주만 새로 (셋업·섹터는 그대로)
        if isinstance(fresh, dict) and "hot" in fresh:
            ins["hot"] = fresh["hot"]
        data["insights"] = ins
        data.setdefault("parts", {})["channels"] = stamp
        info = {"new_posts": new}
    data["built_at"] = max(data.get("built_at", ""), stamp)
    write_html(data)
    print(json.dumps({"part": part, "at": stamp, **info, "channels": len(data["channels"])}, ensure_ascii=False))


if __name__ == "__main__":
    main()
