#!/usr/bin/env python3
"""체크포인트 (Balance Lab 2.0 T-02, 2026-11-12 사용자 확정): 하루 다섯 번 07 · 10 · 12 · 15 · 18시에 쓰는 한 장 (2026-11-19 사용자 확정: 3회 → 5회, 채널·리포트 정리는 같은 회차가 이어서 쓰고 웹에서 체크포인트 아래 '근거' 칸으로 붙음).
  텔레그램은 07 · 12 · 18시 회차만 보낸다 (10 · 15시는 웹에만).

  "직전 체크포인트 이후 바뀐 것 → 지금 상태 → 다음까지 볼 것" 세 칸, 칸마다 1~3줄.
  지난 체크포인트의 '볼 것'을 맞음/틀림/진행으로 채점한다.
  이것이 아침 브리핑·인사이트·리포트 브리핑·마감 리뷰의 텔레그램 역할을 대신한다 (텔레그램은 체크포인트 3회 + 즉시 알림).

  python3 tools/checkpoint.py prep [--slot 07|10|12|15|18]   # 재료(토큰 0): 국면·시세·수급·해외·채널 3일 흐름·보유 위험·관찰 풀 근접·일정·지난 체크포인트
  python3 tools/checkpoint.py save --file x.json      # 형식 검사 → data/checkpoint/latest.json + history + reports/날짜/checkpoint_HHMM.md
  python3 tools/checkpoint.py send                    # 방금 저장한 체크포인트를 텔레그램으로 (features.toml이 허용하는 유일한 정기 브리핑)

JSON 칸: made_at, slot("07"|"10"|"12"|"15"|"18"), title(32자 이내), changed, now, watch, graded[{watch, result: 맞음|틀림|진행, note}],
         mine(보유·관찰 풀에 주는 뜻), sources(한 줄). 항목은 110자 이내, 문장은 "~입니다."로 맺는다. 매수·매도 단정 금지.
         18시 회차는 마감 리뷰를 겸한다 (2026-11-13 사용자 확정): market(지수 한 줄)·today(오늘 중요했던 것)를 더 쓰고 칸마다 최대 4개.
"""
import argparse, json, sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import ROOT  # noqa: E402
from strategy_prep import KST  # noqa: E402

DATA = ROOT / "data" / "checkpoint"
SLOTS = {"07": "07:00 장 시작 전", "10": "10:00 장 초반", "12": "12:00 오전 마감", "15": "15:00 마감 직전", "18": "18:00 마감 리뷰"}
TG_SLOTS = ("07", "12", "18")   # 텔레그램은 하루 3회 유지 (2026-11-19), 10·15시는 웹에만
LISTS = ("changed", "now", "watch")
# 18:30 회차는 마감 리뷰를 겸한다 (2026-11-13 사용자 확정): market 한 줄 + today(오늘 시장에서 중요했던 것)


def slot_now(now=None):
    h = (now or datetime.now(KST)).hour
    return "07" if h < 9 else "10" if h < 11 else "12" if h < 14 else "15" if h < 17 else "18"


def prep(slot):
    import insight
    o = insight.prep(3)
    o["slot"] = slot
    prev = DATA / "latest.json"
    o["previous_checkpoint"] = json.loads(prev.read_text(encoding="utf-8")) if prev.exists() else None
    try:
        import risk
        from common import positions
        ev = risk.evaluate(positions())
        o["holdings"] = [{k: p.get(k) for k in ("name", "price", "avg_price", "stop", "to_stop_pct", "r_multiple", "phase", "alert")} for p in ev["positions"]]
        o["account"] = {k: ev.get(k) for k in ("CR_pct", "CR_limit_pct", "E_pct", "room_for_new_risk_won")}
    except Exception as e:
        o["holdings_error"] = type(e).__name__
    try:   # 오늘 급등 테마 (2026-11-25: 보안주 집단 상한가가 체크포인트·소식 정리에 빠졌음) — 장중·마감 회차만
        from datetime import datetime as _dt
        from naver_quote import KST as _K
        _n = _dt.now(_K)
        if _n.weekday() < 5 and _n.strftime("%H:%M") >= "09:20":
            import hot_now
            o["themes_today"] = hot_now.themes()
    except Exception as e:
        o["themes_today_error"] = type(e).__name__
    try:   # 관찰 풀 기준가 근접 (마지막 확정 감시 목록 기준)
        import glob
        fs = sorted(glob.glob(str(ROOT / "data" / "bus" / "*" / "screener.json")))
        w = json.loads(Path(fs[-1]).read_text(encoding="utf-8")) if fs else {}
        near = []
        for k in ("signals", "candidates", "watch"):
            for x in w.get(k, []) or []:
                d = (x.get("levels") or {}).get("distance_pct")
                if d is not None and abs(d) <= 3:
                    near.append({"name": x.get("stock"), "tier": k, "close": x.get("close"), "breakout": (x.get("levels") or {}).get("breakout"), "distance_pct": d, "today": x.get("today")})
        o["pool_near"] = sorted(near, key=lambda z: abs(z["distance_pct"]))[:8]
        o["screener_as_of"] = w.get("as_of")
    except Exception as e:
        o["pool_near_error"] = type(e).__name__
    try:   # 탑다운 요약 (2026-11-14 1차): 국면·분산일 · 업종 분류(주간 지면) · 핵심 후보(펀더+기술) 기준가 거리
        import strategy_tf
        o["topdown"] = strategy_tf.topdown_brief()
    except Exception as e:
        o["topdown_error"] = type(e).__name__
    try:
        import strategy_prep as SP
        o["calendar"] = SP.safe(lambda: SP.calendar_ahead(SP.pool_stocks(), 2), [])
    except Exception:
        pass
    if slot == "18":   # 마감 리뷰를 겸한다 (2026-11-13 사용자 확정): 오늘 잠정실적 · 리포트 흐름 · 매매 복기
        today = datetime.now(KST).strftime("%Y-%m-%d")
        try:
            E = json.loads((ROOT / "data" / "earnings" / "latest.json").read_text(encoding="utf-8"))
            o["earnings_today"] = [e for e in (E.get("rows") or []) if str(e.get("time", "")).startswith(today)]
        except Exception as e:
            o["earnings_error"] = type(e).__name__
        try:
            w = json.loads((ROOT / "web" / "last_data.json").read_text(encoding="utf-8"))
            o["report_flow"] = (w.get("report_flow") or [])[:8]
            o["reports_today"] = [{"name": c["name"], "broker": r.get("broker"), "after": r.get("after"), "before": r.get("before"), "dir": r.get("direction"),
                                   "point": (r.get("points") or [""])[0][:120]}
                                  for c in w.get("companies") or [] for r in (c.get("reports") or []) if str(r.get("time", "")).startswith(today)][:25]
            o["highs_today"] = {"as_of": (w.get("highs") or {}).get("as_of"), "groups": (w.get("highs") or {}).get("groups", [])[:5]}
        except Exception as e:
            o["reports_error"] = type(e).__name__
        try:
            import trades
            o["trade_review"] = trades.review()
        except Exception as e:
            o["trade_review_error"] = type(e).__name__
    return o


def md_prep(o):
    import insight
    L = [f"# 체크포인트 재료 · {SLOTS[o['slot']]} ({o['made_at']})"]
    p = o.get("previous_checkpoint")
    if p:
        L.append(f"## 지난 체크포인트 {p.get('made_at')} ({SLOTS.get(p.get('slot'), '')}): {p.get('title')}")
        L += [f"- 볼 것(채점 대상): {x}" for x in p.get("watch", [])]
    L.append("## 보유·계좌")
    for h in o.get("holdings") or []:
        L.append(f"- {h['name']} {h['price']} (평단 {h['avg_price']}, 손절 {h['stop']}, 손절까지 {h['to_stop_pct']}%, {h['r_multiple']}R, {h['phase']}) {h.get('alert') or ''}")
    if o.get("account"):
        L.append(f"- 계좌: CR {o['account']['CR_pct']}% / 한도 {o['account']['CR_limit_pct']}% · 투자 비중 {o['account']['E_pct']}%")
    T = o.get("topdown") or {}
    if T:   # 탑다운 요약 (2026-11-14): now 칸은 매크로 → 국면 → 수급 → 업종 순서, mine 칸에 핵심 후보 거리
        L.append("## 탑다운 요약 (now 칸 순서: 매크로 → 국면 → 수급 → 업종)")
        r = T.get("regime") or {}
        if r:
            L.append(f"- 국면: 코스피 {r.get('close')} · 20일선 대비 {r.get('gap20')}% · 20일선 기울기 {r.get('slope20')}% · 분산일(25거래일) {r.get('dist_days_n')}개 ({r.get('date')} 종가)")
        sw = T.get("sectors_week") or {}
        if sw:
            L.append(f"- 업종 분류(주간 지면 {sw.get('as_of')}): 리더 {', '.join(sw.get('리더') or []) or '-'} / 모멘텀만 {', '.join(sw.get('모멘텀만') or []) or '-'} / 기다림 {', '.join(sw.get('기다림') or []) or '-'}")
        bw = T.get("breadth_week") or {}
        if bw:
            L.append(f"- 시장 폭: 50일선 위 {bw.get('a50')}% · 20일선 위 {bw.get('a20')}% ({bw.get('date')})")
        L.append(f"## 핵심 후보 (펀더 2/3↑ + 기술 2/3↑) — mine 칸에 기준가까지 %")
        L += [f"- {x['name']} ({x['group']}) 기준가 {x['breakout']} · {x['dist']}% 남음 · 펀더 {'발표' if x.get('ftype') == 'A' else '추정'} {x['fp']}/{x.get('fmax', 3)} · 기술 {x['tech']}/3 {x.get('note') or ''}" for x in T.get("core") or []] or ["- 없음"]
    TT = o.get("themes_today") or {}
    if TT.get("themes"):
        L.append(f"## 오늘 급등 테마 (자동 집계 · {TT.get('source')} {TT.get('at')}) — '바뀐 것'에 한 줄로 꼭 넣는다(원인은 채널 글에서, 못 찾으면 '원인 확인 안 됨')")
        L += [f"- {x['theme']}: +10%↑ {x['up_n']}종목(상한가 {x['limit_up']}) — " + ", ".join(f"{s['name']} {s['chg']:+.1f}%{' [내 목록]' if s['mine'] else ''}" for s in x["stocks"]) for x in TT["themes"]]
    L.append(f"## 관찰 풀 기준가 ±3% (감시 목록 {o.get('screener_as_of')})")
    L += [f"- {x['name']} ({x['tier']}) {x['close']} → 기준가 {x['breakout']} ({x['distance_pct']:+}%) 오늘 {x.get('today') or ''}" for x in o.get("pool_near") or []]
    if o.get("calendar"):
        L.append("## 오늘·내일 일정")
        L += [f"- {c}" if isinstance(c, str) else f"- {c.get('date', '')} {c.get('time', '')} {c.get('name', c.get('title', ''))}" for c in o["calendar"][:10]]
    if o.get("earnings_today"):
        L.append("## 오늘 잠정실적")
        L += [f"- {e.get('name')} {e.get('period')} 영업이익 {e.get('op')} (예상 {e.get('op_est')}, {e.get('op_surprise')}%) {e.get('verdict') or ''} · {e.get('time')} {e.get('channel')}" for e in o["earnings_today"][:12]]
    if o.get("reports_today"):
        L.append("## 오늘 리포트 (채널 요약 2차)")
        L += [f"- {r['name']} {r.get('broker') or ''} {r.get('before') or ''}→{r.get('after')} {r.get('dir') or ''} · {r['point']}" for r in o["reports_today"]]
    if o.get("report_flow"):
        L.append("- 31일 업종 흐름: " + " · ".join(f"{s.get('sector')} 🔴{s.get('up')}/🔵{s.get('down')}" for s in o["report_flow"]))
    if (o.get("highs_today") or {}).get("groups"):
        L.append("- 신고가 많은 업종: " + " · ".join(f"{g['group']} {g['n60']}" for g in o["highs_today"]["groups"]))
    tr = o.get("trade_review") or {}
    if tr:
        L.append(f"## 매매 복기: 끝난 거래 {tr.get('n')}건 · 승률 {tr.get('win_rate')}% · 기대값 {tr.get('expectancy_r')}R · 연속 손절 {tr.get('current_loss_streak')} · 규칙 지킴 {tr.get('rule_ok_pct')}%")
        L += [f"- {x}" for x in (tr.get("lessons") or [])[:4]]
    L.append(insight.md(o))
    return "\n".join(L)


def save(path):
    d = json.loads(Path(path).read_text(encoding="utf-8"))
    for k in ("made_at", "slot", "title", "changed", "now", "watch"):
        if not d.get(k):
            raise SystemExit(f"빠진 칸: {k}")
    if d["slot"] not in SLOTS:
        raise SystemExit("slot은 07 / 10 / 12 / 15 / 18")
    if len(d["title"]) > 32:
        raise SystemExit(f"title은 32자 이내: 지금 {len(d['title'])}자")
    cap = 4 if d["slot"] == "18" else 3   # 18:30은 마감 리뷰를 겸해 한 칸 더 (2026-11-13)
    for k in LISTS + ("mine", "today"):
        v = d.get(k) or []
        if not isinstance(v, list) or len(v) > cap:
            raise SystemExit(f"{k}는 1~{cap}개 문장 목록")
        long = [x[:20] for x in v if len(x) > 110]
        if long:
            raise SystemExit(f"{k} 항목은 110자 이내: {long}")
    for g in d.get("graded") or []:
        if g.get("result") not in ("맞음", "틀림", "진행"):
            raise SystemExit("graded.result는 맞음/틀림/진행")
    import re   # 어투: 문장은 "~입니다"로 맺는다 (사용자 확정 2026-11-13). 명사로 끝나는 줄은 그대로 둔다
    plain = [x[:24] for k in LISTS + ("mine", "today") for x in (d.get(k) or []) if re.search(r"(?<!니)다\.?$", x.strip())]
    if plain:
        raise SystemExit(f'어투: 문장은 "~입니다"로 맺습니다. 고칠 줄: {plain}')
    bad = [w for w in ("매수 추천", "매도 추천", "사세요", "파세요", "비중 확대 추천") if w in json.dumps(d, ensure_ascii=False)]
    if bad:
        raise SystemExit(f"매수·매도 단정 표현: {bad}")
    DATA.mkdir(parents=True, exist_ok=True)
    (DATA / "history").mkdir(exist_ok=True)
    txt = json.dumps(d, ensure_ascii=False, indent=1)
    (DATA / "latest.json").write_text(txt, encoding="utf-8")
    stamp = d["made_at"].replace(":", "").replace(" ", "_").replace("-", "")
    (DATA / "history" / f"{stamp}.json").write_text(txt, encoding="utf-8")
    day, hm = d["made_at"][:10], d["made_at"][11:16].replace(":", "")
    rep = ROOT / "reports" / day / f"checkpoint_{hm}.md"
    rep.parent.mkdir(parents=True, exist_ok=True)
    rep.write_text(to_md(d), encoding="utf-8")
    return {"saved": "data/checkpoint/latest.json", "report": str(rep.relative_to(ROOT)), "title": d["title"]}


def to_md(d):
    mark = {"맞음": "✅", "틀림": "❌", "진행": "⏳"}
    L = [f"# 🧭 [체크포인트] {SLOTS[d['slot']]} — {d['made_at'][5:10].replace('-', '/')}", ""]
    if d.get("market"):
        L += [d["market"], ""]
    L += [f"💡 {d['title']}", ""]
    if d.get("graded"):
        L.append("📋 지난 '볼 것' 채점")
        L += [f"- {mark[g['result']]} {g['watch']}" + (f" → {g['note']}" if g.get("note") else "") for g in d["graded"]]
        L.append("")
    for k, n in (("changed", "🔄 바뀐 것"), ("today", "📊 오늘 중요했던 것"), ("now", "📍 지금 상태"), ("mine", "⭐ 내 종목·관찰 풀"), ("watch", "👀 다음 체크포인트까지 볼 것")):
        if d.get(k):
            L.append(n)
            L += [f"- {x}" for x in d[k]]
            L.append("")
    L.append(f"출처: {d.get('sources', '')} · 채널 글은 2차 자료 · 판단은 본인")
    L.append("웹: https://balance-lab.pages.dev")
    return "\n".join(L) + "\n"


def main():
    ap = argparse.ArgumentParser()
    sp = ap.add_subparsers(dest="cmd", required=True)
    p = sp.add_parser("prep"); p.add_argument("--slot", choices=list(SLOTS)); p.add_argument("--json", action="store_true")
    s = sp.add_parser("save"); s.add_argument("--file", required=True)
    sp.add_parser("send")
    a = ap.parse_args()
    if a.cmd == "prep":
        o = prep(a.slot or slot_now())
        print(json.dumps(o, ensure_ascii=False, indent=1, default=str) if a.json else md_prep(o))
    elif a.cmd == "save":
        print(json.dumps(save(a.file), ensure_ascii=False))
    else:
        d = json.loads((DATA / "latest.json").read_text(encoding="utf-8"))
        rep = ROOT / "reports" / d["made_at"][:10] / f"checkpoint_{d['made_at'][11:16].replace(':', '')}.md"
        if d.get("slot") not in TG_SLOTS:
            print(json.dumps({"sent": False, "why": f"{d.get('slot')}시 회차는 웹에만 올립니다 (텔레그램은 07·12·18시)"}, ensure_ascii=False)); return
        import subprocess
        subprocess.run([sys.executable, str(ROOT / "tools" / "telegram_send.py"), "--file", str(rep)], check=True)


if __name__ == "__main__":
    main()
