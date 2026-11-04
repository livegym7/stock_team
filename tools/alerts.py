"""보유 종목 장중 알림 — Claude 없이 규칙으로만 판단해 텔레그램으로 보낸다 (토큰 0).

알림 조건 (보유 종목마다, 같은 알림은 하루 한 번만):
  - 손절가 도달 / 손절가까지 3% 이내
  - 3R 도달 (50% 익절 + 남은 물량 손절가 본전 규칙)
  - 3R 이후 20일선 아래 (종가로 확인 필요)
  - 하루 등락 -5% 이하 / +7% 이상
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
from datetime import datetime, timedelta
from pathlib import Path

from common import CACHE, positions
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
    state.setdefault("sent", {})[today] = sorted(sent)
    state["sent"] = {d: v for d, v in state["sent"].items() if d >= (now - timedelta(days=3)).strftime("%Y-%m-%d")}
    state["last_post_time"] = newest
    state["last_check"] = now.isoformat(timespec="seconds")
    return out, ev


def main():
    p = argparse.ArgumentParser(description="보유 종목 장중 알림")
    p.add_argument("--dry", action="store_true")
    p.add_argument("--force", action="store_true")
    p.add_argument("--collect", action="store_true", help="먼저 채널 새 글 수집")
    p.add_argument("--state", default=str(CACHE / "alerts_state.json"))
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
    msgs, ev = check(state, now)
    sent = False
    if msgs and not a.dry:
        from telegram_send import send
        text = f"🔔 보유 종목 알림 · {now.strftime('%m/%d %H:%M')}\n" + "\n".join(msgs) + \
               f"\n\n리스크: E {ev['E_pct']}% · CR {ev['CR_pct']}% (한도 {ev['CR_limit_pct']}%)\n출처: 네이버 현재가(비공식)·채널 요약(2차 자료) · 판단은 본인이 합니다"
        send(text); sent = True
    if not a.dry:
        Path(a.state).parent.mkdir(parents=True, exist_ok=True)
        Path(a.state).write_text(json.dumps(state, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps({"at": now.strftime("%Y-%m-%d %H:%M"), "alerts": msgs, "sent": sent}, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
