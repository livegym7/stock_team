"""보유 종목 장중 알림 — Claude 없이 규칙으로만 판단해 텔레그램으로 보낸다 (토큰 0).

알림 조건 (보유 종목마다, 같은 알림은 하루 한 번만):
  - 손절가 도달 / 손절가까지 3% 이내
  - 3R 도달 (50% 익절 + 남은 물량 손절가 본전 규칙)
  - 3R 이후 20일선 아래 (종가로 확인 필요)
  - 하루 등락 -5% 이하 / +7% 이상
  - 감시 목록(전날 16:07) 종목의 기준가 근접(−2% 이내)·장중 돌파 (예상 거래량 배수 포함) · 핵심 후보(펀더+기술, core.json)는 🎯로 먼저 (2026-11-14)
  - 보유 종목이 주인공인 채널 새 글 (기업·실적·리포트·정책 글, 중복·잡담·시황 나열 제외, 지난 확인 이후)
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
    files = sorted(glob.glob(str(DATA / "bus" / "*" / "screener.json")))
    if not files:
        return []
    d = json.loads(Path(files[-1]).read_text(encoding="utf-8"))
    items = []
    for tier, key in (("✅신호", "signals"), ("👀후보", "candidates"), ("대기", "watch")):
        for x in d.get(key) or []:
            lv = x.get("levels") or {}
            if lv.get("breakout"):
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
    q = {}
    for i in range(0, len(codes), 40):
        raw = json.loads(http_get("https://polling.finance.naver.com/api/realtime/domestic/stock/" + ",".join(codes[i:i + 40])))
        for r in raw.get("datas", []):
            num = lambda k: float(str(r.get(k) or "0").replace(",", "")) if str(r.get(k) or "").replace(",", "").replace(".", "").lstrip("-").isdigit() else None
            q[r["itemCode"]] = {"price": num("closePrice"), "chg": num("fluctuationsRatio"), "vol": num("accumulatedTradingVolume")}
    opened = now.replace(hour=9, minute=0, second=0, microsecond=0)
    frac = min(1.0, max(0.05, (now - opened).total_seconds() / (390 * 60)))   # 장 경과 비율 (9:00~15:30)
    out = []
    for tier, x in items:
        c, lv, r = x["code"], x["levels"], q.get(x["code"]) or {}
        px = r.get("price")
        if not px:
            continue
        piv, alert_px = lv["breakout"], lv.get("alert") or lv["breakout"] * 0.98
        vr = (r["vol"] / frac / x["vol50"]) if r.get("vol") and x.get("vol50") else None
        vtxt = f" · 예상 거래량 {vr:.1f}배" if vr else ""
        grade = "🔥" if x.get("pool") else ("참고" if x.get("pool") is False else "")   # 관찰 풀 안 🔥 / 밖 참고 (2026-11-10)
        cx = core.get(c) or {}
        if cx.get("core"):
            grade = f"🎯핵심(펀더 {cx['fp']}/3) " + grade
        elif cx and cx.get("fp", 0) <= 1:
            grade = grade + "(펀더 미확인) "
        note = f"{grade}{tier} {x['stock']} {px:,.0f}원 ({r.get('chg') or 0:+.2f}%) · 기준가 {piv:,}"
        miss = f" · 부족: {', '.join(x.get('missing') or [])}" if x.get("missing") else ""
        if px > piv:
            ok = vr is not None and vr >= 1.5
            out.append((f"brk:{c}", f"🔔 {note} 돌파 중{vtxt}{' ✓' if ok else ''} — 종가 유지·거래량 1.5배·업종 동반 확인 필요{miss}"))
        elif px >= alert_px:
            out.append((f"near:{c}", f"👀 {note}까지 {(piv / px - 1) * 100:.1f}% 남음{vtxt}{miss}"))
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

    # 감시 목록 장중 돌파·근접 (전날 16:07 감시 목록의 기준가 기준, 규칙만으로 판단)
    try:
        from common import load_toml
        out_b = breakout_watch(now, sent) if (load_toml("features.toml") or {}).get("monitoring", True) else []   # 모니터링 중단 중엔 돌파 알림 끔
        for key, text in out_b:
            add(key, text)
    except Exception as e:
        out.append(f"(감시 목록 확인 실패: {type(e).__name__})")

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
    cap = ((__import__("common").load_toml("features.toml") or {}).get("telegram") or {}).get("alert_daily_cap")
    today = now.strftime("%Y-%m-%d")
    over_cap = bool(cap) and (state.get("tg_count") or {}).get(today, 0) >= cap
    if msgs and not a.dry and over_cap:
        print(json.dumps({"capped": f"오늘 텔레그램 알림 {cap}회 상한 — 웹 알림 센터에만 기록"}, ensure_ascii=False))
    if msgs and not a.dry and not over_cap:
        state["tg_count"] = {today: (state.get("tg_count") or {}).get(today, 0) + 1}
        from telegram_send import send
        text = f"🔔 보유 종목 알림 · {now.strftime('%m/%d %H:%M')}\n" + "\n".join(msgs) + \
               f"\n\n리스크: E {ev['E_pct']}% · CR {ev['CR_pct']}% (한도 {ev['CR_limit_pct']}%)\n출처: 네이버 현재가(비공식)·채널 요약(2차 자료) · 판단은 본인이 합니다"
        send(text); sent = True
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
