"""웹 화면(트레이딩룸) 만들기: 여러 도구의 결과를 data 하나로 모아 web/index.html에 넣는다.

보기 전용 (주문 기능 없음). 화면은 main에 푸시하면 깃허브가 Balance Lab(Cloudflare Pages, 접근 잠금)에 배포한다.

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
SCHEDULE = [("06:55", "아침 브리핑", "morning"),
            ("14:53", "리포트 브리핑", "report_brief_pm"), ("15:47", "마감 리뷰", "close"), ("16:07", "감시 목록", "watchlist")]
KIND = {"morning": "아침 브리핑", "report_brief_am": "리포트 브리핑 · 오전", "report_brief_pm": "리포트 브리핑 · 오후",
        "channels": "채널 정리", "report_live": "리포트 정리", "close": "마감 리뷰", "weekly": "주간 리뷰",
        "strategy": "전략 보고서", "deep_research": "딥리서치", "checkpoint": "체크포인트"}


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
    extra = {"NQ=F": ("나스닥100 선물", "future"), "EWY": ("EWY 한국 ETF", "etf"), "CL=F": ("WTI 원유", "future"),
             "DX-Y.NYB": ("달러인덱스", "fx"), "^N225": ("닛케이225", "index"), "000001.SS": ("상해종합", "index"), "^TWII": ("대만 가권", "index")}   # 2026-11-15 추가
    want = ["EWY", "^GSPC", "^IXIC", "NQ=F", "^DJI", "^SOX", "KRW=X", "DX-Y.NYB", "^TNX", "^VIX", "CL=F", "^N225", "000001.SS", "^TWII"]  # 화면 순서
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


def file_time(p):
    """파일이 마지막으로 바뀐 한국 시각 "YYYY-MM-DD HH:MM". 커밋된 그대로면 git 커밋 시각(깃허브 배포에서도 정확), 아직 안 올린 변경이면 파일 수정 시각."""
    import subprocess
    p = Path(p)
    if not p.exists():
        return None
    try:
        rel = str(p.resolve().relative_to(ROOT))
        dirty = subprocess.run(["git", "status", "--porcelain", "--", rel], cwd=ROOT, capture_output=True, text=True, timeout=15).stdout.strip()
        if not dirty:
            iso = subprocess.run(["git", "log", "-1", "--format=%cI", "--", rel], cwd=ROOT, capture_output=True, text=True, timeout=15).stdout.strip()
            if iso:
                return datetime.fromisoformat(iso).astimezone(KST).strftime("%Y-%m-%d %H:%M")
    except Exception:
        pass
    return datetime.fromtimestamp(p.stat().st_mtime, KST).strftime("%Y-%m-%d %H:%M")


def brief_times():
    """보고서 파일이 처음 저장(커밋)된 한국 시각 {경로: "HH:MM"}. 예약 브리핑은 파일 이름에 시각이 없어서 커밋 시각을 쓴다."""
    import subprocess
    out = {}
    try:
        log = subprocess.run(["git", "log", "--diff-filter=A", "--name-only", "--format=@%cI", "--since=30 days ago", "--", "reports"],
                             cwd=ROOT, capture_output=True, text=True, timeout=30).stdout
    except Exception:
        return out
    cur = None
    for line in log.splitlines():
        if line.startswith("@"):
            cur = datetime.fromisoformat(line[1:]).astimezone(KST).strftime("%H:%M")
        elif line.strip() and cur:
            out.setdefault(line.strip(), cur)
    return out


def research_digest_rows(since, skip_days=()):
    """소식 › 정리 '자료' 칸 (2026-11-15 사용자 요청): 자료실 깊이 읽기(data/research/docs)를 날짜별 한 장으로 모음. 토큰 0.
    11/05부터 깊이 읽기는 문서만 저장하고 정리 글을 쓰지 않아 자료 칸이 11/04에서 멈춰 있었음."""
    by = {}
    for f in (DATA / "research" / "docs").glob("*.json"):
        try:
            d = json.loads(f.read_text(encoding="utf-8"))
        except Exception:
            continue
        at = (d.get("analyzed_at") or "")[:16]
        if at[:10] >= since and at[:10] not in skip_days:
            by.setdefault(at[:10], []).append(d)
    out = []
    for day, L in by.items():
        L.sort(key=lambda d: d.get("analyzed_at") or "")
        heads = [re.sub(r"\s*\(.*?\d{4}-\d{2}-\d{2}\)\s*$", "", re.sub(r"^\[([^]]*)\]\s*", r"\1 · ", d.get("title") or ""))[:40] for d in L]
        lines = [f"📚 자료실 깊이 읽기 · {day[5:].replace('-', '/')} · {len(L)}건", "", "💡 " + " / ".join(heads[:3]) + (f" 외 {len(L) - 3}건" if len(L) > 3 else "")]
        lines += [f"- {d.get('broker') or ''} · {re.sub(r'^\[[^]]*\]\s*', '', d.get('title') or '')[:60]}" for d in L]
        lines.append("")
        for i, d in enumerate(L, 1):
            C = d.get("claude") if isinstance(d.get("claude"), dict) else {}
            contra = any("반대" in str(t) for t in (d.get("tags") or [])) or "반대" in str(d.get("depth") or "")
            lines.append(f"{i}. {'⚖️ ' if contra else ''}{d.get('title') or ''} ({d.get('kind') or ''})")
            if d.get("one_line"):
                lines.append(f"- {d['one_line']}")
            for c in (C.get("counter") or [])[:1]:
                lines.append(f"- 반대 근거: {c}")
            qa = [q for q in (d.get("questions") or []) if q.get("answer") and not str(q["answer"]).startswith("없음")][:2]
            for q in qa:
                lines.append(f"- 질문 답: {str(q.get('q'))[:50]} → {str(q['answer'])[:120]}")
            if d.get("url"):
                lines.append(f"- 원문: {d['url']}")
            lines.append("")
        lines.append("자세한 요약은 전략 › 자료실 · 출처: 증권사 리포트(1차) 요약 · 판단은 본인이 합니다.")
        text = "\n".join(lines)
        out.append({"date": day, "time": (L[-1].get("analyzed_at") or "")[11:16], "kind": "deep_research", "kind_name": KIND.get("deep_research", "딥리서치"),
                    "file": f"data/research/docs ({day})", "title": lines[0], "text": text, "opinion": "\n".join(lines[3:3 + len(L)])})
    return out


def briefs(days=21):
    rows = []
    times = brief_times()
    since = (datetime.now(KST) - timedelta(days=days)).strftime("%Y-%m-%d")
    for f in sorted(glob.glob(str(ROOT / "reports" / "*" / "*.md")), reverse=True):
        p = Path(f)
        day = p.parent.name
        if day < since or p.stem.endswith(("_test", "_tg")):   # _tg = 텔레그램으로 보낸 요약본(본문과 중복)
            continue
        kind = next((k for k in KIND if p.stem.startswith(k)), "etc")
        text = p.read_text(encoding="utf-8")
        rel = f"reports/{day}/{p.name}"
        m = re.search(r"_(\d{2})(\d{2})$", p.stem)  # channels_1130 처럼 이름에 시각이 있으면 그걸 쓴다
        tm = f"{m.group(1)}:{m.group(2)}" if m else times.get(rel) or (file_time(p) or "")[11:]
        rows.append({"date": day, "time": tm, "kind": kind, "kind_name": KIND.get(kind, p.stem), "file": rel,
                     "title": text.splitlines()[0].strip() if text else p.stem, "text": text,
                     "opinion": section(text, "💡") or section(text, "🧭")})
    rows += research_digest_rows(since, {r["date"] for r in rows if r["kind"] == "deep_research"})
    rows.sort(key=lambda r: (r["date"], r["time"]), reverse=True)
    # 2시간마다 쌓이는 채널·리포트 정리는 누적 정리라 날마다 마지막 1개만 카드로 (오늘 포함, 2026-11-12 사용자 요청).
    # 앞선 회차 시각은 versions에 남겨 카드에 "n회째 · 첫 정리 08:12"로 보여 준다
    keep, out = {}, []
    for r in rows:
        if r["kind"] in ("channels", "report_live"):
            k = (r["date"], r["kind"])
            if k in keep:
                keep[k]["versions"].append(r["time"])
                continue
            r["versions"] = [r["time"]]
            keep[k] = r
        out.append(r)
    return out


def schedule(now, brief_rows):
    today = now.strftime("%Y-%m-%d")
    have = {b["kind"] for b in brief_rows if b["date"] == today}
    # 감시 목록은 장 마감 뒤(16시 이후) 만든 것만 '완료'로 본다 (장중 "모니터링 새로고침" 결과는 제외)
    for f in (ROOT / "reports" / today / "watchlist.png", DATA / "bus" / today / "screener.json"):
        ft = file_time(f)
        if ft and ft[:10] == today and ft[11:] >= "16:00":
            have.add("watchlist")
    out = []
    mon = (load_toml("features.toml") or {}).get("monitoring", True)
    for t, name, kind in SCHEDULE:
        if kind == "watchlist" and not mon:
            continue
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
    # 1) 시장 신호등 (코스피 지수: 20일선 위/아래, 이평 정배열 — 2026-11-05 KODEX 200 → 코스피로 변경, 사용자 요청)
    try:
        import sector_etf
        b = {"etf": "코스피", **sector_etf.stats("KOSPI", "코스피")}
    except Exception:
        b = (etf or {}).get("benchmark") or {}
    if b:
        from common import regime_light
        light = regime_light(b.get("above20"), b.get("aligned"), b.get("slope20"))
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


def company_trends(comp_list, allp, fetch_limit=10):
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
        elif fetch_limit > 0:   # 캐시에 없는 종목(주로 시총 2천억 미만)은 몇 개만 새로 받는다
            fetch_limit -= 1
            rows = safe(lambda: S.fetch_daily(code)) or []
        else:
            rows = []
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
                       # 차트는 카드·보유·관심·리포트 2건↑ 종목만 (데이터 크기). 이동평균은 화면에서 계산하도록 50일 더 보냄
                       "chart": {"d0": last[0]["date"][:4], "d": [r["date"][4:] for r in last], "c": [round(x) for x in cl[-(len(last) + 49):]]}
                       if (c.get("card", True) or tr["held"] or tr["watch"] or c["n_reports"] >= 2) else None,
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
        out = {c["code"]: {k: c["trend"].get(k) for k in ("rs", "rs_chg4w", "rs_hist")} for c in comp_list if c["trend"].get("rs") is not None}
        if "KOSPI" in closes:   # 코스피 지수도 같은 식으로 RS (종목 RS 추이와 비교용, 2026-11-13)
            k = closes["KOSPI"]
            out["_KOSPI"] = {"rs_hist": [pct(lag, S.rs_raw(k[:len(k) - lag] if lag else k)) for lag in lags][::-1]}
        snap_path.write_text(json.dumps(out, ensure_ascii=False), encoding="utf-8")
    return comp_list



def build_companies(allp, uni, companies, by_stock, fetch_limit=10):
    """기업 메뉴: 기업 카드가 있는 종목 + 최근 31일 채널 리포트가 있는 모든 종목.
    카드가 없는 종목은 업종(사용자 분류 → 네이버)만 붙이고 사업 한 줄은 비워 둔다 (리포트 브리핑 때 Claude가 카드를 채움)."""
    from sector_map import custom_map
    cmap = custom_map()
    out = {}
    names = {c["name"]: code for code, c in companies.items()}
    for name in set(names) | set(by_stock):
        code = names.get(name) or uni.get(name, {}).get("code")
        if not code or code in out:
            continue
        rs = by_stock.get(name, [])
        card = companies.get(code)
        u = uni.get(name, {})
        grp = cmap.get(code) or u.get("industry") or "기타"
        base = {**card, "card": True} if card else {"name": name, "sector": grp, "detail": grp, "sub_sectors": [],
                                                      "one_liner": "", "card": False, "sources": []}
        afters = [r["after"] for r in rs if r.get("after")]
        chg = [r["after"] / r["before"] - 1 for r in rs if r.get("after") and r.get("before")]
        latest = {}
        for r in rs:   # 증권사별 가장 최근 목표가
            if r.get("broker") and r.get("after"):
                latest[r["broker"]] = {"broker": r["broker"], "before": r.get("before"), "after": r["after"], "dir": r.get("direction"), "time": r["time"][:10]}
        rev = {"net": sum(r.get("direction") == "상향" for r in rs) - sum(r.get("direction") == "하향" for r in rs),
               "avg_chg": round(statistics.mean(chg) * 100, 1) if chg else None,
               "brokers": sorted(latest.values(), key=lambda x: x["time"], reverse=True)[:10]}
        out[code] = {**base, "rev": rev, "group": grp, "code": code, "market_cap_eok": u.get("market_cap_eok"),
                     "reports": [{**r, "points": [x[:180] for x in r.get("points", [])][:3 if card else 2]} for r in rs[-(8 if card else 4):][::-1]],
                     "n_reports": len(rs), "_all_reports": rs,
                     "last_report": rs[-1]["time"] if rs else None,
                     "up": sum(r.get("direction") == "상향" for r in rs), "down": sum(r.get("direction") == "하향" for r in rs),
                     "median_target": statistics.median(afters) if afters else None}
    comp_list = sorted(out.values(), key=lambda c: -c["n_reports"])
    return safe(lambda: company_trends(comp_list, allp, fetch_limit)) or [{k: v for k, v in c.items() if k != "_all_reports"} for c in comp_list]


def earnings_map():
    """채널 실적 공시(잠정실적) → {코드: 가장 최근 분기 1건} (tools/earnings.py)."""
    import earnings
    out = {}
    for r in earnings.build():
        out.setdefault(r["code"], r)
    return out


def research(comp_list, allp):
    """딥리서치: Claude가 드라이브 리포트를 읽고 쓴 분석(data/research) + 언급 종목의 시장 확인(RS·수익률)."""
    rd = DATA / "research"
    docs = [json.loads(f.read_text(encoding="utf-8")) for f in sorted((rd / "docs").glob("*.json"))] if (rd / "docs").exists() else []
    docs.sort(key=lambda d: (d.get("analyzed_at") or d.get("date") or ""), reverse=True)   # 읽은 날 순 (2026-11-11)
    syn = json.loads((rd / "synthesis.json").read_text(encoding="utf-8")) if (rd / "synthesis.json").exists() else None
    folders = [f.get("name") for f in (safe(lambda: load_toml("research.toml"), {}) or {}).get("folders", [])]
    from universe import load as load_universe
    uni = {s["name"]: s for s in load_universe()["stocks"]}
    codes = {}
    for d in docs:
        for st in d.get("stocks", []):
            if st.get("code"):
                codes[st["code"]] = st["name"]
    for x in (syn or {}).get("leading_stocks", []) + [{"name": n} for i in (syn or {}).get("ideas", []) for n in i.get("stocks", [])]:
        c = uni.get(x.get("name"), {}).get("code")
        if c:
            codes[c] = x["name"]
    have = {c["code"]: c.get("trend") or {} for c in comp_list}
    stubs = [{"name": n, "code": c, "n_reports": 0, "up": 0, "down": 0, "card": False} for c, n in codes.items() if c not in have]
    if stubs:
        for c in safe(lambda: company_trends(stubs, allp, fetch_limit=8), []) or []:
            have[c["code"]] = c.get("trend") or {}
    keep = ("rs", "rs_chg4w", "r1m", "r3m", "off_high", "price", "spark", "held", "watch")
    import screener as S

    def closes(code):
        return safe(lambda: S.fetch_daily(code), []) or []

    def before(rows, day):
        d = day.replace("-", "")
        past = [r for r in rows if r["date"] < d]
        return past[-1]["close"] if past else None

    def after_n(rows, day, n):
        d = day.replace("-", "")
        fut = [r for r in rows if r["date"] >= d]
        return fut[n - 1]["close"] if len(fut) >= n else None

    bench = closes("KOSPI")   # 코스피 지수 (시장 기준, 2026-11-05)
    bench_now = bench[-1]["close"] if bench else None

    def perf(code, base, day):
        rows = closes(code) if code else []
        if not rows or not base:
            return {}
        now = rows[-1]["close"]
        out = {"now": now, "ret": round((now / base - 1) * 100, 1)}
        for label, n in (("w1", 5), ("m1", 21), ("m3", 63)):
            v = after_n(rows, day, n)
            if v:
                out[label] = round((v / base - 1) * 100, 1)
        return out

    ideas_book = json.loads((rd / "ideas.json").read_text(encoding="utf-8")) if (rd / "ideas.json").exists() else {"ideas": {}}
    ideas = []
    for it in ideas_book["ideas"].values():
        st = [{**x, **perf(x.get("code"), x.get("base"), it["first_seen"])} for x in it["stocks"]]
        rets = [x["ret"] for x in st if x.get("ret") is not None]
        bb0 = before(bench, it["first_seen"])   # 2026-11-16: 저장된 bench_base는 옛 기준(KODEX 200 가격)이라 −94% 오류 → 등록일 전 거래일 코스피 종가로 다시 계산
        b = round((bench_now / bb0 - 1) * 100, 1) if bench_now and bb0 else None
        avg = round(sum(rets) / len(rets), 1) if rets else None
        ideas.append({**it, "stocks": st, "avg_ret": avg, "bench_ret": b, "excess": round(avg - b, 1) if avg is not None and b is not None else None})
    ideas.sort(key=lambda x: x["first_seen"], reverse=True)
    picks = []   # 문서별 Top pick·수혜 종목: 리포트 날 전 종가 대비
    for d in docs:
        if not d.get("date"):
            continue
        bb = before(bench, d["date"])
        for st in d.get("stocks", []):
            if st.get("code") and st.get("role") in ("Top pick", "수혜"):
                rows = closes(st["code"])
                base = before(rows, d["date"])
                pf = perf(st["code"], base, d["date"])
                if pf:
                    picks.append({"doc": d["file_id"], "broker": d.get("broker"), "date": d["date"], "name": st["name"], "code": st["code"],
                                  "role": st["role"], "target": st.get("target"), "base": base, **pf,
                                  "bench_ret": round((bench_now / bb - 1) * 100, 1) if bb and bench_now else None})
    by_broker = {}
    for x in picks:
        b = by_broker.setdefault(x["broker"] or "-", {"broker": x["broker"], "n": 0, "sum": 0.0, "win": 0, "excess": 0.0})
        b["n"] += 1; b["sum"] += x["ret"]; b["win"] += x["ret"] > 0
        b["excess"] += x["ret"] - (x.get("bench_ret") or 0)
    brokers = sorted(({"broker": v["broker"], "n": v["n"], "avg": round(v["sum"] / v["n"], 1), "win": v["win"],
                       "excess": round(v["excess"] / v["n"], 1)} for v in by_broker.values()), key=lambda x: -x["excess"])
    import naver_research as NR
    cand = None
    if safe(lambda: NR.collect(45)) is not None:   # 새 리포트만 받음 (보통 몇 초)
        cand = safe(lambda: NR.candidates())
    if not cand or isinstance(cand, dict) and cand.get("error"):
        p = NR.DIR / "candidates_latest.json"
        cand = json.loads(p.read_text(encoding="utf-8")) if p.exists() else None
    # 네이버 산업·전략 리포트 카드 (research_cards.py, 최근 7일) — 전체 목록을 웹에 (2026-11-11)
    cards = []
    for f in sorted((rd / "cards").glob("2*.json"))[-7:] if (rd / "cards").exists() else []:
        for c in json.loads(f.read_text(encoding="utf-8")).values():
            cards.append({k: c.get(k) for k in ("nid", "cat", "date", "broker", "title", "industry", "sector", "url", "summary", "status", "stance", "stance_hint", "thesis", "numbers3", "reasons", "risks",
                                                 "new_claim", "depth_value", "stocks_key", "stocks", "novelty", "new_ratio", "contrarian", "series_key", "body", "deep_file")})
    cards.sort(key=lambda c: (c["date"], c.get("novelty") or 0), reverse=True)
    wk = rd / "cards" / "weekly_latest.json"
    card_weekly = json.loads(wk.read_text(encoding="utf-8")) if wk.exists() else None
    return {"docs": docs, "synthesis": syn, "folders": folders, "ideas": ideas, "picks": picks, "brokers": brokers, "naver": cand, "cards": cards, "card_weekly": card_weekly,
            "bench": {"name": "코스피", "now": bench_now},
            "trend": {c: {k: (have.get(c) or {}).get(k) for k in keep} for c in codes}}


THUMBS = DATA / "cache" / "thumbs"


def thumb(url, key, width):
    """텔레그램 사진을 작게 줄여 페이지 안에 넣을 data 주소로 (웹 화면은 외부 사진 주소를 못 불러오므로).
    한 번 받은 것은 data/cache/thumbs에 남겨 다시 받지 않는다. 사진 처리 도구(PIL)가 없거나 실패하면 None."""
    import base64
    import hashlib
    f = THUMBS / (hashlib.sha1(key.encode()).hexdigest()[:16] + f"_{width}.jpg")
    if not f.exists():
        try:
            from io import BytesIO
            from PIL import Image
            im = Image.open(BytesIO(http_get(url, timeout=15, retries=1))).convert("RGB")
            im.thumbnail((width, width * 2))
            THUMBS.mkdir(parents=True, exist_ok=True)
            im.save(f, "JPEG", quality=55, optimize=True)
        except Exception:
            return None
    return "data:image/jpeg;base64," + base64.b64encode(f.read_bytes()).decode()


def channel_feed(t, allp, hours=72, img_hours=24, img_budget=180):
    """채널 메뉴 글 목록. 최근 img_hours 시간 글은 사진·링크 썸네일을 작게 넣는다 (최대 img_budget장, 페이지 무게 때문)."""
    now = datetime.now(KST)
    since, img_since = now - timedelta(hours=hours), now - timedelta(hours=img_hours)
    rows, used = [], 0
    for x in sorted(allp, key=lambda p: p["time"], reverse=True):
        tm = datetime.fromisoformat(x["time"])
        if tm < since or x.get("dup_of") or x["type"] == "other":
            continue
        photos, imgs = x.get("photos") or [], []
        lk = dict(x.get("link") or {}) or None
        if tm >= img_since:
            for i, u in enumerate(photos[:2]):
                if used < img_budget and (d := thumb(u, f"{x['url']}#{i}", 480)):
                    imgs.append(d)
                    used += 1
            if lk and lk.get("image") and used < img_budget:
                lk["thumb"] = thumb(lk["image"], x["url"] + "#link", 200)
                used += bool(lk["thumb"])
        if lk:
            lk.pop("image", None)
        text = x["text"] if x["text"] != "[사진]" else ""
        rows.append({"time": x["time"][:16].replace("T", " "), "channel": x["channel"], "type": x["type"],
                     "type_name": t.CATEGORIES[x["type"]], "text": re.sub(r"https?://\S+", "", text).strip()[:900],
                     "url": x["url"], "also_in": x.get("also_in", []), "photo": len(photos), "imgs": imgs, "link": lk,
                     "views": x.get("views"), "stocks": [s["name"] for s in x.get("stocks", [])][:4],
                     "seen": (x.get("seen") or "")[:16].replace("T", " "), "digest": x.get("digest")})
    # 오래된 썸네일 정리 (3일)
    for f in THUMBS.glob("*.jpg") if THUMBS.exists() else []:
        if f.stat().st_mtime < now.timestamp() - 3 * 86400:
            f.unlink(missing_ok=True)
    return rows


# ---------------- 시황 분석 (2026-11-04 사용자 요청: 분석·시황 중심) ----------------
def slim_flows(f):
    """화면용 수급: 종목 전체 목록은 빼고 순위·업종만"""
    return {k: v for k, v in f.items() if k != "stocks"} if isinstance(f, dict) else f


def why_moved(pulse, allp, by_stock, flows, hours=36, n=12):
    """많이 오르고 내린 종목에 그 종목을 다룬 채널 글·리포트·수급을 붙인다 ("왜 올랐나")."""
    if not pulse:
        return None
    since = (datetime.now(KST) - timedelta(hours=hours)).isoformat()
    posts = defaultdict(list)
    for x in allp:
        if x["time"] < since or x.get("dup_of") or x["type"] == "other" or x.get("digest"):
            continue
        for st in x.get("stocks", [])[:3]:
            posts[st["name"]].append(x)
    fl = {s["code"]: s for s in (flows or {}).get("stocks", [])}
    def snip(text, name):
        """여러 종목을 나열한 글이면 그 종목이 나오는 부분만"""
        t = re.sub(r"https?://\S+", "", text).strip()
        i = t.find(name)
        if i > 60:
            t = "… " + t[max(0, i - 10):]
        return t[:180]

    def one(m):
        nm = m["name"]
        # 그 종목이 주인공인 글만: 종목이 1~2개뿐이거나, 글 앞부분(80자)에 이름이 나오는 글
        ps = [x for x in posts.get(nm, []) if len(x.get("stocks", [])) <= 2 or nm in x["text"][:80]]
        ps.sort(key=lambda x: x["time"], reverse=True)
        reps = [r for r in by_stock.get(m["name"], []) if r["time"] >= since[:16].replace("T", " ")]
        f = fl.get(m["code"])
        return {**m, "posts": [{"time": x["time"][5:16].replace("T", " "), "channel": x["channel"], "type": t_name(x["type"]),
                                "text": snip(x["text"], nm), "url": x["url"]} for x in ps[:3]],
                "n_posts": len(ps), "reports": [{"broker": r.get("broker"), "direction": r.get("direction"), "after": r.get("after")} for r in reps[:3]],
                "flow": {"f1": f["f1"], "i1": f["i1"], "f_streak": f["f_streak"], "date": f["date"]} if f else None}
    return {"at": pulse.get("at"), "up": [one(m) for m in pulse.get("movers_up", [])[:n]], "down": [one(m) for m in pulse.get("movers_down", [])[:n]]}


def t_name(k):
    import tg_channel
    return tg_channel.CATEGORIES.get(k, k)


def theme_talk(allp, flows, uni, days=5):
    """업종별 '말 vs 주가': 채널·리포트 언급(최근 5일 vs 그 전 5일)과 실제 주가·수급을 나란히."""
    from sector_map import custom_map
    cmap = custom_map()
    now = datetime.now(KST)
    cur_s, prev_s = (now - timedelta(days=days)).isoformat(), (now - timedelta(days=days * 2)).isoformat()
    code_of = {n: s["code"] for n, s in uni.items()}
    talk = defaultdict(lambda: {"cur": 0, "prev": 0, "up": 0, "down": 0, "stocks": Counter()})
    for x in allp:
        if x["time"] < prev_s or x.get("dup_of") or x["type"] in ("other", "market", "macro", "policy", "schedule") or x.get("digest"):
            continue
        names = [st["name"] for st in x.get("stocks", [])][:3]
        grps = {cmap.get(code_of.get(nm, "")) or uni.get(nm, {}).get("industry") for nm in names} - {None}
        for g in grps:
            t = talk[g]
            if x["time"] >= cur_s:
                t["cur"] += 1
                t["up"] += x.get("direction") == "상향"
                t["down"] += x.get("direction") == "하향"
                for nm in names:
                    if (cmap.get(code_of.get(nm, "")) or uni.get(nm, {}).get("industry")) == g:
                        t["stocks"][nm] += 1
            else:
                t["prev"] += 1
    sec = {g["group"]: g for g in (flows or {}).get("sectors", [])}
    rows = []
    for g, t in talk.items():
        if t["cur"] + t["prev"] < 4:
            continue
        f = sec.get(g) or {}
        r5, money = f.get("r5"), (f.get("f5", 0) + f.get("i5", 0)) if f else None
        chg = (t["cur"] - t["prev"]) / max(t["prev"], 1)
        loud = t["cur"] >= 6 and t["cur"] >= t["prev"] * 1.3
        if r5 is None:
            tag = ""
        elif loud and r5 > 2 and (money or 0) > 0:
            tag = "🔥 말·주가·수급 모두 ↑ (주도 후보)"
        elif loud and r5 > 0:
            tag = "📈 말과 주가 함께 ↑"
        elif loud and r5 < -1:
            tag = "⚠️ 말은 많은데 주가 ↓"
        elif not loud and r5 > 4:
            tag = "🤫 조용히 오름 (말 적음)"
        elif t["cur"] < t["prev"] * 0.6 and r5 < 0:
            tag = "🧊 관심 식는 중"
        else:
            tag = ""
        rows.append({"group": g, "talk": t["cur"], "talk_prev": t["prev"], "talk_chg": round(chg * 100), "up": t["up"], "down": t["down"],
                     "stocks": [n for n, _ in t["stocks"].most_common(4)], "r1": f.get("r1"), "r5": r5, "r20": f.get("r20"),
                     "money5": money, "n": f.get("n"), "tag": tag})
    rows.sort(key=lambda r: (not r["tag"].startswith(("🔥", "⚠️", "📈", "🤫")), -r["talk"]))
    return {"at": now.strftime("%Y-%m-%d %H:%M"), "days": days, "rows": rows[:30],
            "note": f"말 = 최근 {days}일 채널 글·리포트 중 그 업종 종목이 나온 글 수 (시황·매크로 글 제외, 중복 제외) · 주가·수급 = 시총 상위 300종목 기준 업종 시총가중 수익률·외국인+기관 5일 순매수(억)"}


def consensus(allp, uni, days=30, window=90):
    """종목별 목표가 컨센서스 추이: 날마다 '증권사별 가장 최근 목표가(90일 안)'의 평균. 증권사 2곳 이상인 종목만."""
    from tg_channel import broker_key
    now = datetime.now(KST)
    since = (now - timedelta(days=days + window)).isoformat()
    hist = defaultdict(list)   # 종목 → [(날짜, 증권사, 목표가)]
    for x in allp:
        if x["time"] < since or x["type"] != "report" or not x.get("stock") or not x.get("target_after") or not x.get("broker"):
            continue
        hist[x["stock"]].append((x["time"][:10], broker_key(x["broker"]), x["target_after"]))
    out = {}
    dates = [(now - timedelta(days=d)).strftime("%Y-%m-%d") for d in range(days, -1, -1)]
    for name, rows in hist.items():
        rows.sort()
        series = []
        for d in dates:
            lo = (datetime.fromisoformat(d) - timedelta(days=window)).strftime("%Y-%m-%d")
            latest = {}
            for dt, b, tp in rows:
                if lo <= dt <= d:
                    latest[b] = tp
            if len(latest) >= 2:
                series.append([d, round(statistics.mean(latest.values())), len(latest)])
        if len(series) < 2:
            continue
        first, last = series[0][1], series[-1][1]
        out[name] = {"now": last, "n": series[-1][2], "chg_pct": round((last / first - 1) * 100, 1) if first else None,
                     "series": series, "since": series[0][0]}
    return out


def equity(risk_now):
    """계좌 수익률 곡선: 매매 일지(data/trades) + 네이버 일봉 종가. 날마다 (실현 + 평가 손익) ÷ 계좌 원금, 코스피 지수와 비교."""
    import screener as S
    import trades as TR
    log = sorted(TR.read_log("main"), key=lambda e: (e["date"], e.get("at", "")))
    if not log:
        return None
    acc = load_toml("account.toml") or {}
    cap, since, rate = acc.get("capital") or 1, acc.get("capital_start_at") or "9999", acc.get("cost_rate", 0.0)
    start = log[0]["date"].replace("-", "")
    bench = [r for r in S.fetch_daily("KOSPI") if r["date"] >= start]   # 시장 비교 = 코스피 지수 (2026-11-05)
    if not bench:
        return None
    closes = {c: {r["date"]: r["close"] for r in S.fetch_daily(c)} for c in {e["code"] for e in log}}
    live = {p["code"]: p.get("price") for p in (risk_now or {}).get("positions", []) if p.get("price")}
    today = datetime.now(KST).strftime("%Y%m%d")
    pts, b0 = [], None
    for br in bench:
        d = br["date"]
        qty, cost, realized, ra = defaultdict(int), defaultdict(float), 0.0, 0.0   # ra = 계좌 새 시작(since) 이후 실현 − 비용
        for e in log:
            if e["date"].replace("-", "") > d:
                break
            c = e["code"]
            after = e["type"] in ("buy", "sell") and (e.get("at") or "") >= since
            if after:   # 2026-11-18부터 거래 비용 0.23% 반영
                ra -= e.get("fee_won") if e.get("fee_won") is not None else (e["qty"] * e["price"] * rate if e["type"] == "sell" else 0)   # 왕복 0.23%는 매도 때
            if e["type"] == "buy":
                qty[c] += e["qty"]; cost[c] += e["qty"] * e["price"]
            elif e["type"] == "sell" and qty[c]:
                avg = cost[c] / qty[c]
                realized += (e["price"] - avg) * e["qty"]
                if after:
                    ra += (e["price"] - avg) * e["qty"]
                cost[c] -= avg * e["qty"]; qty[c] -= e["qty"]
        unreal = 0.0
        for c, q in qty.items():
            if q:
                px = live.get(c) if d == today and live.get(c) else closes[c].get(d)
                if px is None:   # 거래 없는 날은 직전 종가
                    prev = [v for k, v in closes[c].items() if k <= d]
                    px = prev[-1] if prev else cost[c] / q
                unreal += px * q - cost[c]
        b0 = b0 or br["close"]
        pts.append({"date": f"{d[:4]}-{d[4:6]}-{d[6:]}", "ret": round((realized + unreal) / cap * 100, 3),
                    "bench": round((br["close"] / b0 - 1) * 100, 3), "realized": round(realized), "unreal": round(unreal), "ra": round(ra)})
    # 2026-11-18 사용자 확정: 계좌는 capital_start_at 시점에 1,500만 원으로 새로 시작 → 그 뒤 날짜만, 수익률 = (새 시작 뒤 실현 − 비용 + 지금 평가 손익) ÷ 1,500만
    #   시작 전날을 0으로 두고 코스피도 그 전날 종가 기준. 평가 손익은 시작 전부터 들고 있던 종목(예: JYP)의 매수가 기준 손익도 포함
    sd = since[:10]
    if sd < "9999":
        base = [p for p in pts if p["date"] < sd]
        if base:
            b = base[-1]; bb = 1 + b["bench"] / 100
            pts = [dict(b, ret=0.0, bench=0.0, realized=0)] + [
                {**p, "ret": round((p["ra"] + p["unreal"]) / cap * 100, 3), "bench": round(((1 + p["bench"] / 100) / bb - 1) * 100, 3), "realized": p["ra"]}
                for p in pts if p["date"] >= sd]
    return {"capital": cap, "since": sd, "points": pts}


def automation(now, data, allp):
    """자동 작업 현황: config/automation.toml 목록마다 오늘 실행됐는지 결과 파일로 확인 (토큰 0)."""
    import subprocess
    tasks = (safe(lambda: load_toml("automation.toml"), {}) or {}).get("tasks", [])
    today, hm, wd = now.strftime("%Y-%m-%d"), now.strftime("%H:%M"), now.weekday()
    times = brief_times()

    def mtime(p):   # 깃허브 배포에서도 맞도록 커밋 시각 우선 (2026-11-12)
        return file_time(p)

    alert_state = {}
    try:
        subprocess.run(["git", "fetch", "-q", "origin", "alert-state"], cwd=ROOT, capture_output=True, timeout=30)
        alert_state = json.loads(subprocess.run(["git", "show", "origin/alert-state:state.json"], cwd=ROOT, capture_output=True, text=True, timeout=15).stdout or "{}")
    except Exception:
        pass
    out = []
    for t in tasks:
        chk, last, detail = t.get("check", ""), None, ""
        if chk.startswith("report:"):
            name = chk.split(":", 1)[1]
            f = ROOT / "reports" / today / f"{name}.md"
            if f.exists():
                last = today + " " + (times.get(f"reports/{today}/{name}.md") or mtime(f)[11:])
            else:
                fs = sorted(glob.glob(str(ROOT / "reports" / "*" / f"{name}.md")))
                last = (Path(fs[-1]).parent.name + " " + (times.get(str(Path(fs[-1]).relative_to(ROOT))) or "")) if fs else None
        elif chk == "checkpoint":
            fc = DATA / "checkpoint" / "latest.json"
            cp = json.loads(fc.read_text(encoding="utf-8")) if fc.exists() else {}
            last, detail = cp.get("made_at"), f"슬롯 {cp.get('slot', '-')} · {cp.get('title', '')[:30]}"
        elif chk == "weekly":
            fs = sorted(glob.glob(str(ROOT / "reports" / "*" / "weekly.md")))
            last = Path(fs[-1]).parent.name if fs else None
        elif chk == "bus":
            fs = sorted(glob.glob(str(DATA / "bus" / "*" / "screener.json")))
            last = mtime(Path(fs[-1])) if fs else None
        elif chk == "naver_pick":
            fs = sorted(glob.glob(str(DATA / "naver_research" / "candidates_2*.json")))
            picked = [f for f in fs if json.loads(Path(f).read_text(encoding="utf-8")).get("picked")]
            last = Path(picked[-1]).stem.split("_")[1] if picked else None
            detail = "Claude가 고른 리포트 기록 기준"
        elif chk == "live":
            fs = sorted(glob.glob(str(ROOT / "reports" / today / "channels_[0-9]*.md")) + glob.glob(str(ROOT / "reports" / today / "report_live_[0-9]*.md")),
                        key=lambda f: Path(f).stem[-4:])
            last = (today + " " + Path(fs[-1]).stem[-4:-2] + ":" + Path(fs[-1]).stem[-2:]) if fs else None
            detail = f"오늘 정리 {len(fs)}개 (채널·리포트)"
        elif chk == "web":
            last, detail = data.get("built_at"), "이 화면 데이터 시각"
        elif chk == "alerts":
            last = (alert_state.get("last_check") or "")[:16].replace("T", " ") or None
            n = len((alert_state.get("sent") or {}).get(today, []))
            detail = f"오늘 보낸 알림 {n}건" if alert_state else "기록 없음(아직 자동 실행 전)"
        elif chk == "calendar":
            c = data.get("calendar") or {}
            last, detail = c.get("fetched_at"), ("일부 실패: " + ", ".join(c.get("errors") or [])) if c.get("errors") else ""
        elif chk == "naver":
            n = ((data.get("research") or {}).get("naver") or {})
            last, detail = n.get("made_at"), f"오늘 {n.get('n_total', 0)}건"
        elif chk == "channels":
            ts = [x["time"] for x in allp]
            last, detail = (max(ts)[:16].replace("T", " ") if ts else None), "가장 최근 수집된 글 시각"
        elif chk == "cards":
            fs = sorted(glob.glob(str(DATA / "research" / "cards" / "2*.json")))
            if fs:
                cs = json.loads(Path(fs[-1]).read_text(encoding="utf-8"))
                filled = [c for c in cs.values() if c.get("filled_at")]
                last = max((c["filled_at"] for c in filled), default=None)
                detail = f"{Path(fs[-1]).stem} 초안 {len(cs)} · 카드 {len(filled)}"
        elif chk == "strategy":
            f = DATA / "strategy" / "latest.json"
            st = json.loads(f.read_text(encoding="utf-8")) if f.exists() else {}
            last, detail = st.get("made_at"), (st.get("issue") or "")
        run_today = bool(last and last[:10] == today)
        is_day = (wd == 4) if t.get("days") == "fri" else (wd == 5) if t.get("days") == "sat" else wd < 5
        if t.get("days") in ("fri", "sat") and last and not run_today:   # 주 1회 작업은 이번 주에 했으면 ok
            run_today = (now - datetime.fromisoformat(last[:10]).replace(tzinfo=KST)).days < 7
        late = is_day and hm > _plus(t.get("due", "23:59"), 40) and not run_today
        state = "off" if t.get("paused") else "ok" if run_today else ("late" if late else ("wait" if is_day else "off"))
        out.append({**t, "last": last, "detail": detail, "state": state})
    # 데이터 출처 상태
    src = []
    m = data.get("market") or {}
    src.append({"name": "국내 지수 (네이버)", "ok": bool(m.get("kr")), "note": ""})
    src.append({"name": "해외 시세 (Yahoo)", "ok": bool(m.get("us")), "note": f"{len(m.get('us') or [])}개"})
    src.append({"name": "보유 종목 현재가 (네이버)", "ok": bool((data.get("risk") or {}).get("positions")), "note": (data.get("risk") or {}).get("at", "")})
    c = data.get("calendar") or {}
    src.append({"name": "일정 (ForexFactory·DART·Nasdaq)", "ok": bool(c.get("events")) and not c.get("errors"), "note": ", ".join(c.get("errors") or [])})
    n = (data.get("research") or {}).get("naver") or {}
    src.append({"name": "네이버 리서치", "ok": bool(n.get("n_total")), "note": n.get("made_at", "")})
    src.append({"name": "텔레그램 채널", "ok": bool(allp), "note": f"{len(data.get('channel_stats') or [])}개 채널"})
    return {"tasks": out, "sources": src, "checked_at": now.strftime("%Y-%m-%d %H:%M")}


def _alerts_backup(now):
    import alerts
    if not alerts.market_open(now):
        return
    import subprocess
    subprocess.run(["python3", "tools/alerts.py"], cwd=ROOT, capture_output=True, timeout=180)


def _plus(hm, minutes):
    h, m = map(int, hm.split(":"))
    t = h * 60 + m + minutes
    return f"{min(t // 60, 23):02d}:{t % 60:02d}"


def channel_raw(allp, hours=72):
    """브리핑 머리줄용 원래 글 수: [시각, 채널, 0=정리 대상 / 1=중복 / 2=잡담·짧은 글]."""
    since = datetime.now(KST) - timedelta(hours=hours)
    return [[x["time"][:16].replace("T", " "), x["channel"], 1 if x.get("dup_of") else 2 if x["type"] == "other" else 0]
            for x in sorted(allp, key=lambda p: p["time"]) if datetime.fromisoformat(x["time"]) >= since]


def channel_stats(t, allp):
    """채널 성향 30일: 글 수·분류, 여러 채널이 다룬 소식에서 '먼저 올린' 횟수와 따라 올릴 때 늦은 시간(분 중앙값), 많이 올리는 시간대."""
    since = datetime.now(KST) - timedelta(days=30)
    ps30 = [x for x in allp if datetime.fromisoformat(x["time"]) >= since]
    by_key = {f"{x['channel']}/{x['id']}": x for x in allp}
    first, follow, delays = Counter(), Counter(), defaultdict(list)
    for x in ps30:
        if x.get("also_in") and not x.get("dup_of"):
            first[x["channel"]] += 1
        if x.get("dup_of"):
            root = by_key.get(x["dup_of"])
            if root and root["channel"] != x["channel"]:
                follow[x["channel"]] += 1
                delays[x["channel"]].append((datetime.fromisoformat(x["time"]) - datetime.fromisoformat(root["time"])).total_seconds() / 60)
    out = []
    for c in t.channels():
        ps = [x for x in ps30 if x["channel"] == c["id"]]
        own = [x for x in ps if not x.get("dup_of")]
        cnt = Counter(t.CATEGORIES[x["type"]] for x in own)
        hours = Counter(datetime.fromisoformat(x["time"]).hour for x in ps)
        f, fo = first[c["id"]], follow[c["id"]]
        out.append({"id": c["id"], "description": c.get("description", ""), "posts_30d": len(ps),
                    "per_day": round(len(ps) / 30, 1), "dups": sum(1 for x in ps if x.get("dup_of")),
                    "original_pct": round(len(own) / len(ps) * 100) if ps else None,
                    "first": f, "follow": fo, "first_pct": round(f / (f + fo) * 100) if f + fo else None,
                    "lag_min": round(statistics.median(delays[c["id"]])) if delays[c["id"]] else None,
                    "peak_hours": [h for h, _ in hours.most_common(2)],
                    "useful_pct": round(sum(1 for x in own if x["type"] in ("report", "earnings", "company")) / len(own) * 100) if own else None,
                    "top": cnt.most_common(3)})
    return out


def calendar(allp, now):
    """일정: tools/calendar_fetch.py가 모은 data/calendar/events.json(경제지표·국내 IR·미국 실적·직접 확인 일정, 하루 한 번)
    + 최근 3일 채널 '일정' 글. 보유·관심·기업 메뉴 종목이면 표시."""
    import calendar_fetch
    d = safe(lambda: calendar_fetch.build(), {}) or {}
    if not d.get("events"):
        d = {"events": [{**e, "id": "m:" + e["date"]} for e in (safe(lambda: load_toml("calendar.toml"), {}) or {}).get("events", [])]}
    from common import positions, watchlist
    held = {p["code"] for p in positions()}
    watch = {w.get("code") for w in watchlist()}
    from universe import load as load_universe
    mcap = {x["code"]: x.get("market_cap_eok") or 0 for x in load_universe()["stocks"]}
    comp = set(json.loads((DATA / "companies.json").read_text(encoding="utf-8")))
    rank = {"policy": 1, "macro": 2, "earnings_us": 3, "market": 4, "earnings_kr": 5, "earnings": 5}
    ev = []
    for e in d.get("events", []):
        e = dict(e)
        e["mcap"] = mcap.get(e.get("code"), 0)
        if e.get("source", "").startswith("ForexFactory") and " " in e["name"] and not e.get("name_en"):
            ctry, en = e["name"].split(" ", 1)
            e["name"], e["name_en"] = f"{ctry} {calendar_fetch.ko_title(en)}", en
        e["rel"] = bool(e.get("code") and (e["code"] in held or e["code"] in watch or e["code"] in comp)) or e["kind"] in ("policy", "macro", "market", "earnings_us")
        e["days"] = (datetime.strptime(e["date"], "%Y-%m-%d").date() - now.date()).days
        e["mine"] = "held" if e.get("code") in held else "watch" if e.get("code") in watch else None
        # 중요도 순: 보유·관심 > 금리·정책 > 경제지표 > 미국 실적 > 만기 > 국내 IR(시총 큰 순)
        e["prio"] = (0 if e["mine"] else rank.get(e["kind"], 6)) * 1e7 - min(e["mcap"], 9_999_999) / 1
        ev.append(e)
    ev.sort(key=lambda e: (e["date"], e["prio"]))
    since = now - timedelta(days=3)
    posts = [{"time": x["time"][:16].replace("T", " "), "channel": x["channel"], "text": re.sub(r"https?://\S+", "", x["text"]).strip()[:300], "url": x.get("url")}
             for x in sorted(allp, key=lambda p: p["time"], reverse=True)
             if x["type"] == "schedule" and not x.get("dup_of") and datetime.fromisoformat(x["time"]) >= since][:8]
    return {"events": ev, "channel_posts": posts, "fetched_at": d.get("fetched_at"), "errors": d.get("errors", [])}


def main():
    p = argparse.ArgumentParser(description="웹 화면 데이터 만들기")
    p.add_argument("--no-live", action="store_true", help="시세 조회 생략")
    p.add_argument("--data-out", help="화면 대신 데이터 JSON만 이 경로에 쓰기 (깃허브 Actions 새로고침용)")
    p.add_argument("--only", choices=["channels", "analysis", "monitoring"],
                   help="한 부분만 새로 (나머지는 지난 데이터 그대로). channels = 채널 글·기업만(몇 초) / analysis = 분석 메뉴(시세·계좌·브리핑·기업·채널) / monitoring = 감시 목록 다시 계산(screener) + 섹터·검증실")
    a = p.parse_args()
    now = datetime.now(KST)
    if a.only == "channels":
        return partial(a.only, now)
    last = json.loads(LAST.read_text(encoding="utf-8")) if LAST.exists() else {}
    if a.only and not last:
        raise SystemExit("지난 전체 데이터(web/last_data.json)가 없습니다. 먼저 python3 tools/web_build.py 로 전체를 만드세요")
    if a.only == "monitoring" and not (load_toml("features.toml") or {}).get("monitoring", True):
        raise SystemExit("모니터링이 중단 상태입니다 (config/features.toml monitoring = false)")
    if a.only == "monitoring":
        import subprocess
        # 감시 목록 다시 계산(섹터 레이더 포함). 텔레그램은 보내지 않음. 몇 분 걸림
        scope = ((load_toml("features.toml") or {}).get("scope") or (load_toml("features.toml") or {}).get("monitoring_scope") or "")
        subprocess.run(["python3", "tools/screener.py"] + (["--pool"] if scope == "pool" else []), cwd=ROOT, capture_output=True, text=True, timeout=1800)   # 예약(16:07)과 같은 범위로 (2026-11-20)
    from universe import load as load_universe
    uni = {s["name"]: s for s in load_universe()["stocks"]}
    companies = {k: v for k, v in json.loads((DATA / "companies.json").read_text(encoding="utf-8")).items() if not k.startswith("_")}
    import tg_channel
    collected = safe(lambda: tg_channel.collect_all())   # 브리핑 이후 올라온 리포트도 기업 메뉴에 바로 반영
    t, allp = tg_data()
    by_stock, flow = report_rows(t, allp, companies, uni)
    brief_rows = briefs()

    import risk
    risk_now = safe(lambda: risk.evaluate()) if not a.no_live else safe(lambda: risk.evaluate(prices={}))
    # 보유 종목 업종(사용자 분류표) → 웹 '내 계좌' 업종 분포 (2026-11-05)
    if risk_now and risk_now.get("positions"):
        from sector_map import custom_map
        cmap = safe(custom_map, {}) or {}
        for p in risk_now["positions"]:
            p["sector"] = cmap.get(p.get("code"), "기타")
    comp_list = build_companies(allp, uni, companies, by_stock)

    data = {
        "built_at": now.strftime("%Y-%m-%d %H:%M"),
        "market": market(not a.no_live),
        "risk": risk_now,
        "trades": safe(lambda: __import__("trades").summary()),
        "trade_review": safe(lambda: __import__("trades").review()),   # 매매 복기 (2026-11-10)
        "addon_trades": safe(lambda: __import__("trades").addon_summary()),   # 부록 · 지수 되돌림 성적 (2026-11-18)
        "watch_pool": load_toml("watch_pool.toml"),                    # 관찰 풀 (전략 보고서가 고른 종목)
        "equity": safe(lambda: equity(risk_now)),
        "account": {**load_toml("account.toml"), **__import__("common").account_state()},   # capital = 지금 계좌(시작 + 실현 손익 − 비용, 2026-11-18)
        "schedule": schedule(now, brief_rows),
        "briefs": brief_rows,
        "watch": watch(),   # 감시 목록 파일만 읽음 (계산은 모니터링 새로고침·16:07 예약)
        "sectors_etf": None,
        "report_flow": flow,
        "companies": comp_list,
        "research": safe(lambda: research(comp_list, allp)),
        "earnings": safe(lambda: earnings_map()),
        "channels": channel_feed(t, allp),
        "channel_stats": channel_stats(t, allp),
        "channel_raw": channel_raw(allp),
        "stock_names": safe(lambda: __import__("universe").bold_names(), []),
        "pulse": safe(lambda: __import__("market_pulse").pulse()) if not a.no_live else last.get("pulse"),
        "flows": safe(lambda: slim_flows(__import__("market_pulse").flows())) if not a.no_live else last.get("flows"),
        "econ": safe(lambda: __import__("market_pulse").econ()) if not a.no_live else last.get("econ"),
        "calendar": safe(lambda: calendar(allp, now)),
        "categories": t.CATEGORIES,
        "note": "보기 전용 · 주문 기능 없음 · 채널 글은 2차 자료",
    }
    full_flows = safe(lambda: __import__("market_pulse").flows())   # 캐시(3시간)라 위와 같은 값
    data["why"] = safe(lambda: why_moved(data.get("pulse"), allp, by_stock, full_flows if isinstance(full_flows, dict) and "stocks" in full_flows else None))
    data["themes"] = safe(lambda: theme_talk(allp, full_flows if isinstance(full_flows, dict) and "sectors" in full_flows else None, uni))
    cons = safe(lambda: consensus(allp, uni), {})
    if isinstance(cons, dict) and "error" not in cons:
        for c in comp_list:
            if c["name"] in cons:
                c["cons"] = cons[c["name"]]
    mon = (load_toml("features.toml") or {}).get("monitoring", True)   # 모니터링 중단 중이면 감시 목록·섹터 ETF·검증실 계산을 건너뜀
    data["features"] = {"monitoring": mon}
    if not mon:
        data["watch"], data["sectors_etf"] = (last or {}).get("watch") or data["watch"], (last or {}).get("sectors_etf")
    elif a.only == "analysis":
        data["sectors_etf"] = last.get("sectors_etf")
    elif not a.no_live:
        import subprocess
        out = subprocess.run(["python3", "tools/sector_etf.py"], cwd=ROOT, capture_output=True, text=True, timeout=300).stdout
        data["sectors_etf"] = safe(lambda: json.loads(out))
    data["insights"] = safe(lambda: insights(data["watch"], data["sectors_etf"], allp, by_stock, now))
    rp = DATA / "radar" / "latest.json"
    if a.only == "analysis" or not mon:
        data["lab"], data["radar"] = (last or {}).get("lab"), (last or {}).get("radar")
    else:
        data["lab"] = lab(data, now)
        data["radar"] = safe(lambda: json.loads(rp.read_text(encoding="utf-8"))) if rp.exists() else None
    data["parts"] = {**(last.get("parts") or {}), **{k: data["built_at"] for k in ("market", "risk", "channels", "insights")}}
    data["automation"] = safe(lambda: automation(now, data, allp))
    if a.only == "monitoring":   # 모니터링만: 분석 쪽은 지난 데이터 그대로
        keep = {k: last.get(k) for k in ("market", "risk", "trades", "equity", "briefs", "companies", "research", "earnings", "channels", "channel_stats", "report_flow", "schedule", "pulse", "flows", "econ", "why", "themes")}
        hot = (last.get("insights") or {}).get("hot")
        data.update(keep)
        if isinstance(data.get("insights"), dict) and hot is not None:
            data["insights"]["hot"] = hot
        data["parts"] = {**(last.get("parts") or {}), "monitoring": data["built_at"]}
    else:
        data["parts"]["analysis"] = data["built_at"]
        if not a.only:
            data["parts"]["monitoring"] = data["built_at"]
    if a.data_out:
        Path(a.data_out).parent.mkdir(parents=True, exist_ok=True)
        Path(a.data_out).write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        print(json.dumps({"built_at": data["built_at"], "out": a.data_out}, ensure_ascii=False))
        return
    # 장중이면 보유 종목·감시 목록 알림도 확인 (깃허브 자동 실행이 늦을 때 대비, 토큰 0)
    safe(lambda: _alerts_backup(now))
    blob = write_html(data)
    print(json.dumps({"built_at": data["built_at"], "out": "web/index.html", "kb": round(len(blob) / 1024),
                      "briefs": len(brief_rows), "companies": len(comp_list), "channels": len(data["channels"]),
                      "watch": len((data["watch"] or {}).get("watch", []))}, ensure_ascii=False))


LAST = WEB / "last_data.json"   # 마지막 전체 데이터 (부분 새로고침용, 커밋 안 함)


def index_daily():
    """코스피·코스닥 일봉 (네이버 siseJson, 비공식) → {KOSPI: [[날짜, 시가, 고가, 저가, 종가, 거래량], ...]} 최근 260개."""
    import ast
    from common import http_get
    end = datetime.now(KST); start = end - timedelta(days=600)
    out = {}
    for m in ("KOSPI", "KOSDAQ"):
        raw = http_get("https://api.finance.naver.com/siseJson.naver", {"symbol": m, "requestType": 1, "timeframe": "day",
                       "startTime": start.strftime("%Y%m%d"), "endTime": end.strftime("%Y%m%d")}).decode("utf-8", "replace")
        rows = [r for r in ast.literal_eval(raw.strip()) if r and str(r[0]).isdigit()]
        out[m] = [[r[0], r[1], r[2], r[3], r[4], r[5]] for r in rows][-380:]   # 1년 표시 + 120일선 계산용
    return out


def vtop_enrich(o):
    """거래대금 상위: 일봉 캐시로 20·60일선·52주 범위·RS를 붙임 (차트 위치를 한눈에)."""
    from common import CACHE
    try:
        base = json.loads((WEB / "highs_base.json").read_text(encoding="utf-8"))["stocks"]
    except Exception:
        base = {}
    for x in o.get("items") or []:
        f = CACHE / "daily" / f"{x['code']}.json"
        b = base.get(x["code"]) or {}
        x["rs"] = b.get("rs")
        if not f.exists():
            continue
        try:
            rows = json.loads(f.read_text())["rows"][-250:]
        except Exception:
            continue
        c = [r["close"] for r in rows]
        if len(c) >= 60:
            x["ma20"], x["ma60"] = round(sum(c[-20:]) / 20), round(sum(c[-60:]) / 60)
        x["hi"], x["lo"] = max(r["high"] for r in rows), min(r["low"] for r in rows)
    return o


def write_ohlc(data):
    """종목별 일봉 파일 web/c/코드.json (최근 250개 [날짜,시가,고가,저가,종가,거래량]) — 감시 목록 일봉 캐시에서. 보유·관찰 풀은 화면 안에도 넣음(Artifact용)."""
    from common import CACHE
    out_dir = WEB / "c"
    out_dir.mkdir(exist_ok=True)
    keep = {p.get("code") for p in ((data.get("risk") or {}).get("positions") or [])}
    for th in (data.get("watch_pool") or {}).get("themes", []):
        keep |= {s.get("code") for s in th.get("stocks", [])}
    embed, n = {}, 0
    # 2026-11-13: 기업 카드 종목 + 시총 2천억↑ 전 종목(일봉 캐시 있는 것) → 모든 종목명에 팝업
    comp = {c.get("code") for c in data.get("companies") or []}
    uni = {}
    try:   # 기본 카드(기업 개요, tools/stock_profile.py) — 기업 메뉴 종목에도 붙임
        prof = json.loads((DATA / "stock_profiles.json").read_text(encoding="utf-8"))
    except Exception:
        prof = {}
    for c in data.get("companies") or []:
        if prof.get(c.get("code"), {}).get("summary"):
            c["profile"] = prof[c["code"]]["summary"]
    try:
        import new_highs
        b = json.loads((WEB / "highs_base.json").read_text(encoding="utf-8"))["stocks"] if (WEB / "highs_base.json").exists() else {}
        for code, s in new_highs.universe_info().items():
            if code not in comp and (CACHE / "daily" / f"{code}.json").exists():
                uni[code] = [s["name"], s["group"], (b.get(code) or {}).get("rs"), (prof.get(code) or {}).get("summary") or "", s["cap"]]
    except Exception:
        pass
    data["uni"] = uni
    for c in list(data.get("companies") or []) + [{"code": k} for k in uni]:
        f = CACHE / "daily" / f"{c.get('code')}.json"
        if not f.exists():
            continue
        try:
            rows = json.loads(f.read_text())["rows"][-400:]   # 1년 표시 + 120일선 계산용 (2026-11-13)
        except Exception:
            continue
        arr = [[r["date"], r["open"], r["high"], r["low"], r["close"], r["volume"]] for r in rows]
        (out_dir / f"{c['code']}.json").write_text(json.dumps(arr, separators=(",", ":")), encoding="utf-8")
        n += 1
        if c["code"] in keep:
            embed[c["code"]] = arr[-380:]
        if isinstance(c.get("trend"), dict) and c["trend"].get("live_chg") is None and len(arr) > 1:   # 목록 '오늘' 칸: 마지막 종가 기준 등락
            c["trend"]["live_chg"] = round((arr[-1][4] / arr[-2][4] - 1) * 100, 2)
        if c["code"] in uni and len(arr) > 22:   # 목록용 숫자 (2026-11-13): 종가 · 오늘 등락 · 1개월 · 52주 고점 대비
            cl, hi = arr[-1][4], max(r[2] for r in arr[-250:])
            uni[c["code"]] += [cl, round((cl / arr[-2][4] - 1) * 100, 2), round((cl / arr[-22][4] - 1) * 100, 1), round((cl / hi - 1) * 100, 1), arr[-1][0]]
    return embed


def write_html(data):
    # Claude 인사이트 (2026-11-11): 채널 며칠 치를 종합한 해석 — tools/insight.py save 가 씀. 어떤 갱신이든 최신 파일을 실음
    # 알림 센터 (2026-11-12): 깃허브 알림 작업이 보낸 메시지 기록 (alert-state 브랜치)
    try:
        import subprocess
        subprocess.run(["git", "fetch", "-q", "origin", "alert-state"], cwd=ROOT, capture_output=True, timeout=30)
        st = json.loads(subprocess.run(["git", "show", "origin/alert-state:state.json"], cwd=ROOT, capture_output=True, text=True, timeout=15).stdout or "{}")
        data["alerts"] = {"last_check": (st.get("last_check") or "")[:16].replace("T", " "), "log": st.get("log") or {}}
    except Exception:
        pass
    # 차트 데이터 (2026-11-13): 코스피·코스닥 일봉 260개 + 종목별 일봉 파일(web/c/코드.json, 마우스오버 팝업·종목 페이지용, 웹에서만 필요할 때 받음)
    data["index_daily"] = safe(index_daily, {})
    import strategy_tf   # 핵심 후보 매일 갱신(2026-11-14 1차): 감시 목록 × 실적 → D.tf_core + web/core.json(장중 알림이 읽음)
    data["tf_core"] = safe(strategy_tf.core_list)
    import backtest_ibs   # 부록 · 지수 되돌림 현황판 재료 (2026-11-18, 토큰 0)
    data["ibs_board"] = safe(backtest_ibs.board)
    import macro_board   # 시장 › 매크로 재료: 해외 지수·피어·금리·미국 산업 대표 종목 일봉 + 유동성·레버리지 (2026-11-19, 토큰 0)
    data["macro_board"] = safe(macro_board.build)
    import sector_track   # 업종 지도 발자취: 지난 60거래일 업종 강도 다시 계산 (2026-11-19, 토큰 0, 약 10초)
    data["sector_track"] = safe(sector_track.build)
    data["tf_market"] = safe(lambda: strategy_tf.market_fragments(strategy_tf.daily_market()))   # 시장(탑다운) 탭·오늘 국면 추적판 (2026-11-14 2차, 약 10초)
    if data.get("tf_core"):
        safe(lambda: (WEB / "core.json").write_text(json.dumps(data["tf_core"], ensure_ascii=False), encoding="utf-8"))
    import fundamentals   # 실적·밸류에이션 (2026-11-13): 네이버 재무·컨센서스 캐시 → D.fund, 네이버 기준 서프라이즈 → D.fund_sur
    data["fund"], data["fund_sur"] = safe(fundamentals.build_web, ({}, []))
    data["index_rs"] = safe(lambda: json.loads((DATA / "radar" / "company_rs.json").read_text(encoding="utf-8")).get("_KOSPI", {}).get("rs_hist"))   # 코스피 RS 12주
    # 신고가 모아보기 (2026-11-13): 마감 확정 목록 + 장중 비교용 기준선 web/highs_base.json (깃허브 알림 작업이 20분마다 site/highs_live.json)
    import new_highs
    data["highs"] = safe(new_highs.eod)
    data["vtop"] = safe(lambda: vtop_enrich(__import__("value_top").fetch()))   # 거래대금 상위 100 (2026-11-13)
    data["etfb"] = safe(lambda: __import__("etf_board").fetch())   # ETF 시세판 (2026-11-13)
    safe(lambda: (WEB / "highs_base.json").write_text(json.dumps(new_highs.base(), ensure_ascii=False, separators=(",", ":")), encoding="utf-8"))
    data["ohlc"] = safe(lambda: write_ohlc(data), {})
    # 수급 오실레이터 (2026-11-13, 후보 B): 캐시로 계산 → web/f/코드.json(종목 페이지 그림) + 요약 P
    import flow_osc
    data["flowosc"] = safe(lambda: flow_osc.build_web(WEB / "f"), {})
    fc = DATA / "checkpoint" / "latest.json"   # 체크포인트 (Balance Lab 2.0, 하루 3회)
    if fc.exists():
        data["checkpoint"] = safe(lambda: json.loads(fc.read_text(encoding="utf-8")))
    fi = DATA / "insight" / "latest.json"
    if fi.exists():
        data["insight"] = safe(lambda: json.loads(fi.read_text(encoding="utf-8")))
    # 전략 보고서: 실제 보고서(latest.json)가 있으면 그것, 없으면 형식 보기용 예시(sample.json)
    for f in (DATA / "strategy" / "latest.json", DATA / "strategy" / "sample.json"):
        if f.exists():
            data["strategy"] = json.loads(f.read_text(encoding="utf-8"))
            break
    ftf = DATA / "strategy" / "tf" / "latest.json"   # 테크노펀더멘탈 주간 보고서(2026-11-14 확정): strategy_tf.py render 결과 조각
    if ftf.exists():
        data["strategy_tf"] = safe(lambda: json.loads(ftf.read_text(encoding="utf-8")))
    data["strategy_issues"] = safe(lambda: __import__("strategy_tf").issues())   # 발간호 칩 (2026-11-15)
    def _secpop():   # 업종 마우스오버 팝업 재료 (2026-11-15): 레이더 주요 종목 펀더 점수 + 업종 올해 이익(지난 주간 지면)
        import strategy_tf as T
        fund, fp = T._fund(), {}
        for g in ((data.get("radar") or {}).get("groups") or []):
            for l in g.get("leaders") or []:
                f = T.fscore(fund.get(l.get("code")), None)
                if f:
                    fp[l["code"]] = f["pts"]
        fs = sorted((DATA / "strategy" / "tf").glob("prep_*.json"))
        opg = {m["group"]: m.get("opg") for m in (json.loads(fs[-1].read_text(encoding="utf-8")).get("matrix") or [])} if fs else {}
        return {"fp": fp, "opg": opg}
    data["secpop"] = safe(_secpop)
    # 깊이 모드 자료 (2026-11-20): 종목 메모(코드 → 메모)
    data["stock_memos"] = safe(lambda: {f.stem: json.loads(f.read_text(encoding="utf-8")) for f in (DATA / "stock_memos").glob("*.json")}, {})
    data["brief_missed"] = safe(lambda: __import__("live_brief").missed(data), [])   # 놓친 것 점검 (2026-11-15, 토큰 0)
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
        data["channel_raw"] = channel_raw(allp)
        data["calendar"] = safe(lambda: calendar(allp, now))
        from universe import load as load_universe
        uni = {s["name"]: s for s in load_universe()["stocks"]}
        companies = {k: v for k, v in json.loads((DATA / "companies.json").read_text(encoding="utf-8")).items() if not k.startswith("_")}
        by_stock, flow = report_rows(t, allp, companies, uni)
        data["report_flow"] = flow
        data["companies"] = build_companies(allp, uni, companies, by_stock, fetch_limit=0)
        cons = safe(lambda: consensus(allp, uni), {})
        for c in data["companies"]:
            if isinstance(cons, dict) and c["name"] in cons:
                c["cons"] = cons[c["name"]]
        data["earnings"] = safe(lambda: earnings_map())
        ins = data.get("insights") or {}
        fresh = safe(lambda: insights({}, None, allp, by_stock, now))   # 특징주만 새로 (셋업·섹터는 그대로)
        if isinstance(fresh, dict) and "hot" in fresh:
            ins["hot"] = fresh["hot"]
        data["insights"] = ins
        data["research"] = safe(lambda: research(data["companies"], allp))   # 자료실 새 요약도 바로 보이게
        rows = briefs()   # 매시간 채널·리포트 정리가 막 저장됐을 수 있어 목록도 새로
        data["briefs"] = rows
        data["schedule"] = schedule(now, rows)
        data["trade_review"] = safe(lambda: __import__("trades").review())
        data["watch_pool"] = load_toml("watch_pool.toml")
        data.setdefault("parts", {})["channels"] = stamp
        info = {"new_posts": new}
    data["built_at"] = max(data.get("built_at", ""), stamp)
    write_html(data)
    print(json.dumps({"part": part, "at": stamp, **info, "channels": len(data["channels"])}, ensure_ascii=False))


if __name__ == "__main__":
    main()
