"""보유 종목 장중 알림 — Claude 없이 규칙으로만 판단해 텔레그램으로 보낸다 (토큰 0).

알림 조건 (보유 종목마다, 같은 알림은 하루 한 번만):
  - 손절가 도달 / 손절가까지 3% 이내
  - 3R 도달 (50% 익절 + 남은 물량 손절가 본전 규칙)
  - 3R 이후 20일선 아래 (종가로 확인 필요)
  - 하루 등락 -5% 이하 / +7% 이상
  - 감시 목록(전날 확정) 종목이 장중에 기준가나 최대 매물대를 넘으면 모두(2026-11-24 단순화: 조건은 딱지로만 — 기준가·매물대·거래량·동행·펀더, 웹 신호 줄과 같음) · 기준가 근접(−2% 이내)은 관찰 풀·핵심 후보만
  - 보유 종목이 주인공인 채널 새 글 (기업·실적·리포트·정책 글, 중복·잡담·시황 나열 제외, 지난 확인 이후) — 웹 알림 센터에만 남기고 텔레그램으로는 보내지 않음(2026-11-24)
판단만 알린다. 매수·매도를 대신하지 않는다 (절대 규칙 1·4).

사용법:
    python3 tools/alerts.py            # 확인 후 새 알림이 있으면 텔레그램 전송
    python3 tools/alerts.py --dry      # 보내지 않고 무엇을 보낼지만 출력
    python3 tools/alerts.py --force    # 장 시간이 아니어도 확인 (시험용)
상태 파일(보낸 알림·마지막 확인 시각): --state 경로 (기본 data/cache/alerts_state.json)
"""
import argparse
import json
import os
from datetime import datetime, timedelta
from pathlib import Path

from common import CACHE, DATA, positions
from naver_quote import KST

NEAR_STOP = 3.0      # 손절가까지 % 이내면 근접
DROP, JUMP = -5.0, 7.0


def market_open(now):
    return now.weekday() < 5 and "08:55" <= now.strftime("%H:%M") <= "15:40"


def load_state(path):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except Exception:
        return {}


def breakout_watch(now, sent, limit=40):
    """전날 감시 목록(신호·후보·대기)의 기준가를 장중 현재가와 비교.
    근접: 알림가(기준가 −2%) 이상 / 돌파 중: 기준가 이상 → 예상 거래량(지금까지 거래량 ÷ 장 경과 비율)이 50일 평균의 몇 배인지 함께."""
    import glob
    from common import http_get
    from screener import RULES
    files = sorted(glob.glob(str(DATA / "bus" / "*" / "screener.json")))
    if not files:
        return []
    d = json.loads(Path(files[-1]).read_text(encoding="utf-8"))
    items = []
    for tier, key in (("✅신호", "signals"), ("👀후보", "candidates"), ("대기", "watch")):
        for x in d.get(key) or []:
            lv = x.get("levels") or {}
            if lv.get("breakout") or (x.get("max_zone") or {}).get("top") or x.get("rebreak"):   # 기준가가 없어도 최대 매물대가 있으면 본다 — 웹 '오늘 넘음'과 같은 대상 (2026-11-25)
                items.append((tier, x))
    core = {}
    for cp in (os.environ.get("CORE_JSON") or "", str(Path(__file__).resolve().parent.parent / "web" / "core.json")):   # 핵심 후보(펀더 2/3↑+기술 2/3↑, 2026-11-14)
        try:
            core = {x["code"]: x for x in json.loads(Path(cp).read_text(encoding="utf-8"))["items"]}; break
        except Exception:
            pass
    items.sort(key=lambda t: (not (core.get(t[1]["code"]) or {}).get("core"), -((core.get(t[1]["code"]) or {}).get("fp") or 0)))   # 핵심 후보 먼저
    items = items[:limit]
    if not items:
        return []
    codes = [x["code"] for _, x in items]
    # 장중 업종 동행용 같은 업종 종목 (core.json의 peers, 2026-11-18)
    codes += sorted({pc for _, x in items for pc in ((core.get(x["code"]) or {}).get("peers") or [])} - set(codes))
    q = {}
    for i in range(0, len(codes), 40):
        raw = json.loads(http_get("https://polling.finance.naver.com/api/realtime/domestic/stock/" + ",".join(codes[i:i + 40])))
        for r in raw.get("datas", []):
            num = lambda k: float(str(r.get(k) or "0").replace(",", "")) if str(r.get(k) or "").replace(",", "").replace(".", "").lstrip("-").isdigit() else None
            q[r["itemCode"]] = {"price": num("closePrice"), "chg": num("fluctuationsRatio"), "vol": num("accumulatedTradingVolume"),
                                "open": num("openPrice"), "high": num("highPrice"), "low": num("lowPrice")}
    try:      # 주도 섹터 레이더 순위(어제 마감 기준 data/radar/latest.json) — 알림에 '업종 n위'로 표시만
        sec_rank = {g["group"]: g["rank"] for g in json.loads((DATA / "radar" / "latest.json").read_text(encoding="utf-8")).get("groups", [])}
    except Exception:
        sec_rank = {}
    opened = now.replace(hour=9, minute=0, second=0, microsecond=0)
    frac = min(1.0, max(0.05, (now - opened).total_seconds() / (390 * 60)))   # 장 경과 비율 (9:00~15:30)
    out = []
    for tier, x in items:
        c, lv, r = x["code"], x.get("levels") or {}, q.get(x["code"]) or {}
        px = r.get("price")
        if not px:
            continue
        piv = lv.get("breakout")
        alert_px = (lv.get("alert") or piv * 0.98) if piv else None
        vr = (r["vol"] / frac / x["vol50"]) if r.get("vol") and x.get("vol50") else None
        vtxt = f" · 예상 거래량 {vr:.1f}배" if vr else ""
        grade = "🔥" if x.get("pool") else ("참고" if x.get("pool") is False else "")   # 관찰 풀 안 🔥 / 밖 참고 (2026-11-10)
        cx = core.get(c) or {}
        if cx.get("core"):
            grade = f"🎯핵심(펀더 {'추정' if cx.get('ftype') == 'E' else '발표'} {cx['fp']}/{cx.get('fmax', 3)}) " + grade
        elif cx and cx.get("fbad", cx.get("fp", 0) <= 1):
            grade = grade + "(펀더 0점) "
        note = f"{grade}{tier} {x['stock']} {px:,.0f}원 ({r.get('chg') or 0:+.2f}%)" + (f" · 기준가 {piv:,}" if piv else "")
        miss = f" · 부족: {', '.join(x.get('missing') or [])}" if x.get("missing") else ""
        # 장중 업종 동행 (screener.industry_action과 같은 규칙: 같은 업종 40%↑가 +2%↑ 또는 중앙값 +1.5%↑, 2026-11-18)
        ch = [q[pc]["chg"] for pc in (cx.get("peers") or []) if (q.get(pc) or {}).get("chg") is not None]
        ia = None
        if len(ch) >= 3:   # screener.IA_RULE["min_peers"]와 같은 값
            import statistics
            from screener import IA_RULE   # 숫자는 screener 한 곳에서만 (2026-11-20, 여기 따로 적혀 있던 40·1.5를 없앰)
            share, med = round(sum(1 for v in ch if v >= IA_RULE["up"] * 100) / len(ch) * 100), statistics.median(ch)
            ia = (share >= IA_RULE["min_up_share"] or med >= IA_RULE["min_median"], share)
        rk = sec_rank.get(x.get("group") or cx.get("group"))     # 주도 섹터 레이더 순위 (2026-11-23: 표시만) — 1~5위면 '주도'
        # 매물대 돌파: 어제 종가 ≤ 최대 매물대(차트 빨간 막대 상단) < 현재가 (2026-11-18 사용자 요청)
        zt = cx.get("zone_top") or (x.get("max_zone") or {}).get("top")
        yc = x.get("close")
        zb = bool(zt and yc and yc <= zt < px)
        bo = bool(piv and px > piv)
        rbp = (x.get("rebreak") or {}).get("pivot")     # 재돌파 선 (2026-11-27, 참고): 최근 신호 뒤 밀렸던 선을 다시 넘음
        rbo = bool(rbp and yc and yc <= rbp < px)
        vok = vr is not None and vr >= RULES["breakout_vol"]
        rule = bo and vok and bool(ia and ia[0])
        # 2026-11-24 사용자 확정(단순화): 웹 신호 줄과 같게 — 오늘 기준가나 최대 매물대를 넘은 감시 목록 종목은 모두 알리고, 조건은 딱지(켜짐 ✓ / 꺼짐 ✗)로만 적는다. 살지 말지는 본인이 판단.
        # 기준가 근접(👀)은 전처럼 관찰 풀·핵심 후보만. 정식 신호(기준가 + 거래량 1.5배 + 업종 동행)를 세는 기준은 그대로다.
        mine = bool(x.get("pool")) or bool(cx.get("core"))
        if bo or zb or rbo:
            ftxt = f"펀더 {'추정' if cx.get('ftype') == 'E' else '발표'} {cx['fp']}/{cx.get('fmax', 3)}{' ✓' if cx.get('fp') else ' ✗'}" if cx.get("ftype") else "펀더 확인 불가"
            tags = [f"기준가 {piv:,} ✓"] if bo else []
            tags += [f"매물대 {zt:,} ✓"] if zb else []
            tags += [f"재돌파 {rbp:,} ✓(참고)"] if rbo and not bo else []
            tags += [f"거래량 {vr:.1f}배 {'✓' if vok else '✗'}" if vr else "거래량 확인 불가", ("동행 ✓" if ia[0] else "나 홀로 ✗") if ia else "업종 확인 불가", ftxt]
            if rk:
                tags.append(f"업종 {rk}위" + ("(주도)" if rk <= 5 else ""))
            # 트리거 n/7 (2026-11-27, 깡토 5강 — 표시만): screener.triggers와 같은 정의를 장중 시세로. 시장은 목록 기준일 값
            tg = x.get("tg_next") or {}
            rng = (r.get("high") or 0) - (r.get("low") or 0)
            tv = [vok if vr else None, ia[0] if ia else None, ((px - r["low"]) / rng * 100 if rng > 0 else 100) >= 70 if r.get("low") else None,
                  (px - r["open"] >= tg["atr20"]) if r.get("open") and tg.get("atr20") else None, bool(tg.get("vcp")),
                  (px > tg["hi250"]) if tg.get("hi250") else None, tg.get("mkt")]
            tags.append(f"트리거 {sum(1 for v in tv if v)}/7")
            head = f"🔔 {'🎯' if cx.get('core') else ''}{x['stock']} {px:,.0f}원 ({r.get('chg') or 0:+.2f}%) · " + " · ".join(tags)
            tail = " — 다섯 조건 중 기준가·거래량·동행 충족(장중), 종가로 확정" if rule else " — 종가로 확정, 판단은 본인"
            out.append((f"sig:{c}", head + tail))
            if rule:   # 처음엔 조건이 덜 켜졌다가 나중에 기준가·거래량·동행이 모두 켜지면 한 번 더
                out.append((f"rule:{c}", head + tail))
        elif not mine:
            continue
        elif alert_px and px >= alert_px:
            out.append((f"near:{c}", f"👀 {note}까지 {(piv / px - 1) * 100:.1f}% 남음{vtxt}{miss}"))
    return out


def addon_signals():
    """부록 · 지수 되돌림: 코스피 20일선 아래 + ETF IBS < 0.2 + 흔들림(ATR 14일) 지난 250일 중 상위 30% → 15:00~15:20 매수 후보.
    웹 '전략 › 부록' 현황판(ibsNow·kospiNow)과 같은 계산. 매수 권유가 아니라 조건 알림."""
    import backtest_ibs as B
    from common import http_get
    bd = B.board(n_recent=0)
    P, K = bd["params"], bd["kospi"]
    num = lambda v: float(str(v).replace(",", "")) if str(v or "").replace(",", "").replace(".", "").isdigit() else None
    ix = json.loads(http_get("https://polling.finance.naver.com/api/realtime/domestic/index/KOSPI"))
    kp = num(ix["datas"][0]["closePrice"])
    ma20 = (K["sum19"] + kp) / 20
    if not kp or kp >= ma20:
        return []
    raw = json.loads(http_get("https://polling.finance.naver.com/api/realtime/domestic/stock/" + ",".join(e["code"] for e in bd["etfs"])))
    q = {r["itemCode"]: r for r in raw.get("datas", [])}
    try:
        import trades as _tr
        pot = _tr.addon_summary(prices={})["capital"]   # 부록 계좌 전액 (2026-11-18: 300만 원에서 시작, 본 계좌와 따로)
    except Exception:
        pot = None
    hits = []
    for e in bd["etfs"]:
        r = q.get(e["code"]) or {}
        H, L, C = num(r.get("highPrice")), num(r.get("lowPrice")), num(r.get("closePrice"))
        if not (H and L and C) or H <= L:
            continue
        ibs = (C - L) / (H - L)
        tr = max(H, e["prev_close"]) - min(L, e["prev_close"])
        atr = (sum(e["tr13"]) + tr) / 14 / C
        rank = sum(1 for x in e["atr_hist"] if x <= atr) / (len(e["atr_hist"]) + 1) * 100
        if ibs < P["ibs"] and rank >= P["atr"]:
            hits.append((e, C, ibs, rank))
    out = []
    for e, C, ibs, rank in hits:
        each = pot / len(hits) if pot else None
        qty = f" · 부록 몫 {each:,.0f}원이면 {int(each // C):,}주" if each else ""
        out.append((f"ibs:{e['code']}", f"🧩 부록 신호 · {e['name']} {C:,.0f}원 · IBS {ibs:.2f}(범위 하위 {ibs * 100:.0f}%) · 흔들림 상위 {100 - rank:.0f}% · 코스피 20일선 {(kp / ma20 - 1) * 100:+.1f}%"
                    f" — 15:00~15:20 매수 후보, 다음 날 종가 매도{qty} (본 규칙과 별개, 판단은 본인)"))
    return out


def check(state, now):
    import risk
    from report_digest import live_prices
    pos = positions()
    ev = risk.evaluate(pos)
    quotes = live_prices([p["code"] for p in pos])
    today = now.strftime("%Y-%m-%d")
    sent = set(state.get("sent", {}).get(today, []))
    out = []

    def add(key, text):
        if key not in sent:
            out.append(text); sent.add(key)

    for p in ev["positions"]:
        if p.get("price") is None:
            continue
        name, q = p["name"], quotes.get(p["code"], {})
        chg = q.get("change_pct")
        head = f"{name} {p['price']:,.0f}원" + (f" ({chg:+.2f}%)" if chg is not None else "")
        if p["price"] <= p["stop"]:
            add(f"{p['code']}:stop_hit", f"🚨 {head} — 손절가 {p['stop']:,}원 도달. 규칙: 손절 (판단은 본인)")
        elif p.get("to_stop_pct") is not None and abs(p["to_stop_pct"]) <= NEAR_STOP:
            add(f"{p['code']}:stop_near", f"⚠️ {head} — 손절가 {p['stop']:,}원까지 {p['to_stop_pct']:+.1f}%")
        if p.get("alert"):
            add(f"{p['code']}:rule:{p['phase'][:2]}", f"⚠️ {head} — {p['alert']}")
        if chg is not None and chg <= DROP:
            add(f"{p['code']}:drop", f"🔵 {head} — 오늘 {chg:+.2f}% 급락")
        if chg is not None and chg >= JUMP:
            add(f"{p['code']}:jump", f"🔴 {head} — 오늘 {chg:+.2f}% 급등 (3R까지 {p.get('to_3r_pct', 0):+.1f}%)")

    # 감시 목록 장중 돌파·근접 (전날 확정 감시 목록의 기준가 기준, 규칙만으로 판단)
    try:
        from common import load_toml
        out_b = breakout_watch(now, sent) if (load_toml("features.toml") or {}).get("monitoring", True) else []   # 모니터링 중단 중엔 돌파 알림 끔
        for key, text in out_b:
            if key not in sent and text in out:   # 같은 줄(기준가·매물대·규칙 충족 동시)은 한 번만
                sent.add(key)
            else:
                add(key, text)
    except Exception as e:
        out.append(f"(감시 목록 확인 실패: {type(e).__name__})")

    for p in pos:   # 부록 · 지수 되돌림 보유 (본 계좌 계산엔 안 들어감): 다음 날 '오늘 종가 매도 차례' (2026-11-18)
        if p.get("book") != "addon":
            continue
        px = (quotes.get(p["code"]) or {}).get("price")
        if px and (p.get("bought") or today) < today and now.strftime("%H:%M") >= "14:50":
            add(f"{p['code']}:addon_exit", f"🧩 부록 {p['name']} {px:,.0f}원 ({(px / p['avg_price'] - 1) * 100:+.2f}%) — 오늘 종가 매도 차례 (최대 하루 보유 규칙)")

    # 부록 · 지수 되돌림 신호 (2026-11-18 사용자 요청): 14:50~15:25에 조건 3개가 모두 맞으면 (웹 현황판과 같은 계산)
    if "14:50" <= now.strftime("%H:%M") <= "15:25":
        try:
            for key, text in addon_signals():
                add(key, text)
        except Exception as e:
            out.append(f"(부록 신호 확인 실패: {type(e).__name__})")

    # 채널 새 글 (보유 종목 언급)
    last = state.get("last_post_time") or (now - timedelta(hours=2)).isoformat(timespec="seconds")
    newest = last
    try:
        import tg_channel as t
        codes = {p["code"]: p["name"] for p in pos}
        posts = []
        for c in t.channels():
            for x in t.load_store(c["id"]).values():
                if x["time"] <= last or x.get("dup_of") or x["type"] == "other":
                    continue
                newest = max(newest, x["time"])
                if x["type"] not in ("company", "earnings", "report", "policy"):
                    continue   # 시황·매크로 나열 글은 제외
                st = x.get("stocks", [])
                main = (x.get("stock") if x["type"] == "report" else None) or (st[0]["name"] if st else None)
                hit = [n for c, n in codes.items() if n == main]   # 보유 종목이 글의 주인공일 때만
                if hit:
                    posts.append((x, hit))
        seen = set()
        for x, hit in sorted(posts, key=lambda z: z[0]["time"])[:8]:
            first = " ".join(t.URL_RE.sub("", x["text"]).split())[:110]
            if first[:50] in seen:
                continue
            seen.add(first[:50])
            add(f"post:{x['channel']}/{x['id']}", f"📡 {'·'.join(hit)} 관련 채널 글 {x['time'][11:16]} ({x['channel']}, {t.CATEGORIES.get(x['type'], x['type'])})\n   {first}\n   {x.get('url', '')}")
    except Exception as e:
        out.append(f"(채널 글 확인 실패: {type(e).__name__})")
    if out:   # 알림 센터(웹 '더보기 › 알림 센터', 2026-11-12): 보낸 메시지를 시각과 함께 남김
        state.setdefault("log", {}).setdefault(today, []).extend({"t": now.strftime("%H:%M"), "msg": m} for m in out if not m.startswith("("))
    state["log"] = {d: v for d, v in (state.get("log") or {}).items() if d >= (now - timedelta(days=3)).strftime("%Y-%m-%d")}
    state.setdefault("sent", {})[today] = sorted(sent)
    state["sent"] = {d: v for d, v in state["sent"].items() if d >= (now - timedelta(days=3)).strftime("%Y-%m-%d")}
    state["last_post_time"] = newest
    state["last_check"] = now.isoformat(timespec="seconds")
    return out, ev


KINDS = [("hold", "🚨 [보유 종목 알림]", ("🚨", "⚠️", "🔵", "🔴")), ("brk", "🔔 [돌파 알림]", ("🔔",)), ("near", "👀 [기준가 근접]", ("👀",)),
         ("addon", "🧩 [부록 알림]", ("🧩",)), ("post", "📡 [보유 종목 소식]", ("📡",)), ("sys", "🛠 [점검 알림]", ("(",))]


def group_msgs(msgs):
    """알림 줄을 종류별로 묶는다 → [(제목, [줄…], 종류)]. 종류는 줄 맨 앞 기호로 가른다(알림을 만드는 곳에서 붙이는 기호)."""
    out = []
    for kind, title, marks in KINDS:
        L = [m for m in msgs if m.startswith(marks)]
        if L:
            out.append((title, L, kind))
    rest = [m for m in msgs if not any(m.startswith(k[2]) for k in KINDS)]
    if rest:
        out.append(("🛠 [점검 알림]", rest, "sys"))
    return out


def live_snapshot(state, ev, now):
    """웹 화면용 장중 스냅샷 (2026-11-12, Balance Lab 2.0 X-03): 지수·수급·보유 손익·관찰 풀 가격·오늘 알림. 20분마다 site/live.json."""
    from report_digest import live_prices
    from common import load_toml
    out = {"at": now.strftime("%Y-%m-%d %H:%M"), "source": "네이버(비공식) 현재가 · 20분 스냅샷"}
    try:
        import market_pulse
        out["markets"] = [{k: m.get(k) for k in ("market", "name", "price", "change_pct", "status", "at", "foreign_eok", "institution_eok", "individual_eok", "up", "down", "flat", "upper", "lower", "high52", "low52")}
                          for m in (market_pulse.market_one("KOSPI"), market_pulse.market_one("KOSDAQ"))]
    except Exception as e:
        out["markets_error"] = type(e).__name__
    out["risk"] = {k: ev.get(k) for k in ("at", "E_pct", "invested_won", "CR_won", "CR_pct", "CR_limit_pct", "room_for_new_risk_won")}
    out["positions"] = [{k: p.get(k) for k in ("code", "name", "price", "price_at", "pnl_won", "r_multiple", "to_stop_pct", "to_3r_pct", "value_won", "phase")} for p in ev["positions"]]
    pool = []
    for th in (load_toml("watch_pool.toml") or {}).get("themes", []):
        pool += [s.get("code") for s in th.get("stocks", []) if s.get("code")]
    out["quotes"] = live_prices(pool + [p["code"] for p in ev["positions"]])
    out["alerts"] = (state.get("log") or {}).get(now.strftime("%Y-%m-%d"), [])
    try:                                   # 주목 탭 '오늘 급등 테마' 줄 (2026-11-26, 토큰 0 · 10초쯤)
        import hot_now
        out["hot_themes"] = hot_now.themes()
    except Exception as e:
        out["hot_themes_error"] = type(e).__name__
    return out


def main():
    p = argparse.ArgumentParser(description="보유 종목 장중 알림")
    p.add_argument("--dry", action="store_true")
    p.add_argument("--force", action="store_true")
    p.add_argument("--collect", action="store_true", help="먼저 채널 새 글 수집")
    p.add_argument("--state", default=str(CACHE / "alerts_state.json"))
    p.add_argument("--live", help="웹 화면용 스냅샷 JSON 경로 (예: site/live.json)")
    a = p.parse_args()
    now = datetime.now(KST)
    if not (a.force or market_open(now)):
        print(json.dumps({"skipped": "장 시간 아님", "at": now.strftime("%Y-%m-%d %H:%M")}, ensure_ascii=False)); return
    if a.collect:
        import tg_channel
        try:
            tg_channel.collect_all()
        except Exception:
            pass
    state = load_state(a.state)
    if a.state == str(CACHE / "alerts_state.json"):   # 로컬 실행: 깃허브 자동 실행이 보낸 기록도 합쳐서 같은 알림을 두 번 안 보냄
        try:
            import subprocess
            subprocess.run(["git", "fetch", "-q", "origin", "alert-state"], capture_output=True, timeout=30)
            gh = json.loads(subprocess.run(["git", "show", "origin/alert-state:state.json"], capture_output=True, text=True, timeout=15).stdout or "{}")
            for d, keys in (gh.get("sent") or {}).items():
                state.setdefault("sent", {})[d] = sorted(set(state.get("sent", {}).get(d, [])) | set(keys))
            state["last_post_time"] = max(state.get("last_post_time") or "", gh.get("last_post_time") or "") or None
        except Exception:
            pass
    import copy
    log_before = copy.deepcopy(state.get("log") or {})
    msgs, ev = check(state, now)
    if a.dry:   # 연습 실행은 보낸 알림이 아니므로 알림 센터 기록에 남기지 않음
        state["log"] = log_before
    sent = False
    # 2026-11-24 사용자 확정: 하루 상한을 없애고, 종류별로 제목을 단 메시지를 따로 보낸다 (제목만 보고 무슨 알림인지 알 수 있게)
    groups = [g for g in group_msgs(msgs) if g[2] != "post"]   # 보유 종목 소식(채널 글)은 텔레그램으로 보내지 않고 웹 알림 센터에만 남긴다 (2026-11-24 사용자 확정)
    if groups and not a.dry:
        from telegram_send import send
        for title, lines, kind in groups:
            foot = f"\n\n리스크: E {ev['E_pct']}% · CR {ev['CR_pct']}% (한도 {ev['CR_limit_pct']}%)" if kind == "hold" else ""
            send(f"{title} · {now.strftime('%m/%d %H:%M')} · {len(lines)}건\n" + "\n".join(lines) + foot + "\n출처: 네이버 현재가(비공식) · 판단은 본인이 합니다")
        sent = True
    if not a.dry:
        Path(a.state).parent.mkdir(parents=True, exist_ok=True)
        Path(a.state).write_text(json.dumps(state, ensure_ascii=False, indent=1), encoding="utf-8")
    if a.live:
        try:
            Path(a.live).parent.mkdir(parents=True, exist_ok=True)
            Path(a.live).write_text(json.dumps(live_snapshot(state, ev, now), ensure_ascii=False), encoding="utf-8")
        except Exception as e:
            print(json.dumps({"live_error": type(e).__name__}))
    print(json.dumps({"at": now.strftime("%Y-%m-%d %H:%M"), "alerts": msgs, "sent": sent}, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
