#!/usr/bin/env python3
"""Claude 인사이트 — 채널 흐름을 며칠 단위로 묶어 'Claude만의 해석'을 쓰는 재료와 저장 (2026-11-11 사용자 요청).

웹 '오늘' 맨 위 💡 CLAUDE 인사이트 칸이 이 파일(data/insight/latest.json)을 그린다.
리포트 상향·하향 나열이 아니라: 며칠째 이어지는 큰 흐름 / 오늘 바뀐 것 / 말과 주가가 엇갈리는 곳 /
내 전략(돌파·관찰 풀)에 주는 뜻 / 반대 근거 / 볼 것(숫자 조건)을 쓴다.

  python3 tools/insight.py prep [--days 3]     # 재료 요약(토큰 0, 약 1.2만 자): 정리 헤드라인·🔥여러 채널·말 vs 주가·스트림 메모·카드 새 주장·시세
  python3 tools/insight.py save --file x.json   # 형식 검사 → data/insight/latest.json + history/
  python3 tools/insight.py show                 # 지금 저장된 인사이트

쓰는 곳: /live-brief(2시간마다, Sonnet)가 채널·리포트 정리 뒤 마지막 단계로 쓴다. 숫자마다 출처·시각, 채널은 2차 자료.
"""
import argparse, json, sys
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import ROOT  # noqa: E402
from strategy_prep import KST  # noqa: E402

DATA = ROOT / "data" / "insight"
REQUIRED = ("made_at", "headline", "story", "shifts", "gaps", "meaning", "against", "watch")
LISTS = ("story", "shifts", "gaps", "meaning", "against", "watch")


def prep(days=3):
    import strategy_prep as SP
    import web_build as WB
    now = datetime.now(KST)
    uni, code_of, group_of = SP.universe_maps()
    t, allp = WB.tg_data()
    since = (now - timedelta(days=days)).isoformat()
    recent = [x for x in allp if x["time"] >= since and not x.get("dup_of")]
    by_type = {}
    for x in recent:
        by_type[x["type"]] = by_type.get(x["type"], 0) + 1
    cd = SP.safe(lambda: __import__("research_cards").weekly(days + 2), {}) or {}
    new_claims = []
    for s in (cd.get("sectors") or [])[:8]:
        for c in (s.get("new_claims") or [])[:2]:
            new_claims.append(f"[{s['sector']}] {c}")
    prev = None
    f = DATA / "latest.json"
    if f.exists():
        p = json.loads(f.read_text(encoding="utf-8"))
        prev = {k: p.get(k) for k in ("made_at", "headline", "story", "watch")}
    return {
        "made_at": now.strftime("%Y-%m-%d %H:%M"), "days": days,
        "regime": SP.safe(SP.regime), "market": SP.safe(SP.market_now), "overseas": SP.safe(SP.overseas),
        "posts": {"n": len(recent), "by_type": by_type, "channels": len({x["channel"] for x in recent})},
        "digests": SP.safe(lambda: SP.digests(days, 700), []),
        "hot_topics": SP.safe(lambda: SP.hot_topics(allp, days, 3), [])[:12],
        "channel_themes": SP.safe(lambda: SP.channel_themes(allp, uni), [])[:14],
        "memos": SP.safe(lambda: SP.memos(days + 1), []),
        "card_new_claims": new_claims[:12],
        "trades": SP.safe(SP.trades_state),
        "previous": prev,
    }


def md(o):
    L = [f"# 인사이트 재료 {o['made_at']} (최근 {o['days']}일, 채널 글 {o['posts']['n']}건·{o['posts']['channels']}곳 {o['posts']['by_type']})"]
    r = o.get("regime") or {}
    if r:
        L.append(f"## 국면: {r.get('light')} · 20일선 {r.get('gap20')}% · 1주 {r.get('r1w')}% · 고점 대비 {r.get('off_high')}% ({r.get('date')} 종가)")
    M = o.get("market") or {}
    for m in M.get("markets") or []:
        L.append(f"- {m['market']} {m['price']} ({m['change_pct']}%) {m.get('status')} {m.get('at')} · 외국인 {m.get('foreign_eok')}억 기관 {m.get('institution_eok')}억 개인 {m.get('individual_eok')}억 · 오른 {m.get('up')} 내린 {m.get('down')} · 신고가 {m.get('high52')} 신저가 {m.get('low52')}")
    for k, nm in (("industries_up", "업종 상위"), ("industries_down", "업종 하위"), ("themes_up", "테마 상위")):
        if M.get(k):
            L.append(f"- {nm}: " + " · ".join(f"{x['name']} {x['change_pct']}%" for x in M[k][:8]))
    if o.get("overseas"):
        L.append("- 해외: " + " · ".join(f"{x['name']} {x['price']} ({x['change_pct']}%)" for x in o["overseas"]))
    if o.get("previous"):
        p = o["previous"]
        L.append(f"## 지난 인사이트 {p.get('made_at')}: {p.get('headline')}")
        for s in (p.get("story") or [])[:3]:
            L.append(f"- 흐름: {s}")
        for s in (p.get("watch") or [])[:3]:
            L.append(f"- 볼 것: {s}")
    L.append("## 말 vs 주가 (업종별 7일 글 수·5/20일 수익률·5일 수급)")
    for c in o.get("channel_themes") or []:
        L.append(f"- {c['group']}: 글 {c['talk']}(전 {c['talk_prev']}, {c['talk_chg']}%) 🔴{c['up']}🔵{c['down']} · 5일 {c['r5']}% 20일 {c['r20']}% · 수급 {c['money5']}억 → {c.get('tag') or ''} · {', '.join((c.get('stocks') or [])[:3])}")
    L.append("## 🔥 여러 채널(3곳↑)이 같이 다룬 소식")
    for h in o.get("hot_topics") or []:
        L.append(f"- [{h['time'][5:]} · {h['channels']}곳 · {h['type']}] {h['head']}")
    L.append("## 채널 정리·리포트 정리 헤드라인 (날마다 마지막)")
    for d in o.get("digests") or []:
        L.append(f"### [{d['date']} {d['kind']}]\n{d['text']}")
    if o.get("card_new_claims"):
        L.append("## 리포트 카드의 새 주장")
        L += [f"- {c}" for c in o["card_new_claims"]]
    if o.get("memos"):
        L.append("## 스트림 메모")
        for m in o["memos"]:
            L.append(m if isinstance(m, str) else json.dumps(m, ensure_ascii=False)[:1500])
    if o.get("trades"):
        L.append(f"## 계좌: {json.dumps(o['trades'], ensure_ascii=False)[:400]}")
    return "\n".join(L)


def save(path):
    d = json.loads(Path(path).read_text(encoding="utf-8"))
    miss = [k for k in REQUIRED if not d.get(k)]
    if miss:
        raise SystemExit(f"빠진 칸: {miss}")
    for k in LISTS:
        if not isinstance(d[k], list):
            raise SystemExit(f"{k}는 문장 목록이어야 함")
    if len(d["headline"]) > 32:
        raise SystemExit(f"headline은 한 줄(32자 이내)로: 지금 {len(d['headline'])}자")
    n = sum(len(d[k]) for k in LISTS)
    if n > 12:
        raise SystemExit(f"항목이 너무 많음({n}개) — 칸마다 1~2개, 전체 12개 이내")
    long = [x[:20] for k in LISTS for x in d[k] if len(x) > 110]
    if long:
        raise SystemExit(f"항목은 두 문장·110자 이내로: {long}")
    bad = [w for w in ("매수 추천", "매도 추천", "사세요", "파세요", "비중 확대 추천") if w in json.dumps(d, ensure_ascii=False)]
    if bad:
        raise SystemExit(f"매수·매도 단정 표현: {bad} — 관찰/준비/회피로 바꿀 것")
    d.setdefault("by", "Claude")
    DATA.mkdir(parents=True, exist_ok=True)
    (DATA / "history").mkdir(exist_ok=True)
    txt = json.dumps(d, ensure_ascii=False, indent=1)
    (DATA / "latest.json").write_text(txt, encoding="utf-8")
    (DATA / "history" / (d["made_at"].replace(":", "").replace(" ", "_") + ".json")).write_text(txt, encoding="utf-8")
    return {"saved": "data/insight/latest.json", "made_at": d["made_at"], "headline": d["headline"]}


def main():
    ap = argparse.ArgumentParser()
    sp = ap.add_subparsers(dest="cmd", required=True)
    p = sp.add_parser("prep"); p.add_argument("--days", type=int, default=3); p.add_argument("--json", action="store_true")
    s = sp.add_parser("save"); s.add_argument("--file", required=True)
    sp.add_parser("show")
    a = ap.parse_args()
    if a.cmd == "prep":
        o = prep(a.days)
        print(json.dumps(o, ensure_ascii=False, indent=1) if a.json else md(o))
    elif a.cmd == "save":
        print(json.dumps(save(a.file), ensure_ascii=False))
    else:
        f = DATA / "latest.json"
        print(f.read_text(encoding="utf-8") if f.exists() else "{}")


if __name__ == "__main__":
    main()
