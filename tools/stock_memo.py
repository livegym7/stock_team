#!/usr/bin/env python3
"""종목 메모 (깊이 모드, 2026-11-20 사용자 확정): 보유·관찰 풀 종목만, Opus가 공시·실적·리포트 전문·경쟁사를 읽고 쓰는 한 장.
  깊은 카드(stock_cards.py, 한 줄 소개)보다 깊다: 이익이 왜 느는가 · 근거 · 반대 근거 · 가설이 깨지는 조건 · 다음 확인 날짜.
  매수 기록 때 묻는 세 질문(띔·가설·깨지는 조건)의 재료가 된다. 매수·매도는 단정하지 않는다(절대 규칙 4).

  python3 tools/stock_memo.py queue [--top 4]        # 오늘 쓸 종목 (보유 먼저, 메모 없는 것 → 오래된 것 순) + 재료 모으는 명령
  python3 tools/stock_memo.py save --file x.json     # 형식 검사 → data/stock_memos/코드.json (+ history는 git)
  python3 tools/stock_memo.py show --code 035900     # 저장된 메모
  python3 tools/stock_memo.py list                   # 메모 있는 종목·날짜

JSON 칸: code, name, updated(자동), thesis(가설 한 문장, 80자 이내), business(무엇으로 돈을 버나 2~3줄),
  drivers[{point, evidence}] 2~4개(이익이 느는 이유 + 숫자·출처), numbers[{label, value, source}] 3~8개,
  peers[{name, note}] 0~4개(경쟁사 대비), bull[] 2~3줄, bear[] 2~3줄(반드시), invalid[] 1~3줄(가설이 깨지는 조건: 숫자·날짜로),
  next[{when, what}] 1~4개(다음 확인할 일정), read[] 읽은 자료(증권사 날짜 제목 / DART 공시명 날짜), sources 한 줄.
"""
import argparse, json, sys, tomllib
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import ROOT  # noqa: E402
from strategy_prep import KST  # noqa: E402

DIR = ROOT / "data" / "stock_memos"
BAD = ("매수하세요", "매도하세요", "사야 합니다", "팔아야 합니다", "무조건", "반드시 오릅니다", "적극 매수", "강력 매수")


def targets():
    out, seen = [], set()

    def add(code, name, why):
        if code and code not in seen:
            seen.add(code); out.append({"code": code, "name": name, "why": why})
    try:
        pos = tomllib.loads((ROOT / "config" / "positions.toml").read_text(encoding="utf-8")).get("positions", [])
    except Exception:
        pos = []
    for p in pos:
        if p.get("book") != "addon":      # 부록(지수 ETF)은 메모 대상 아님
            add(str(p.get("code", "")), p.get("name", ""), "보유")
    try:
        pool = tomllib.loads((ROOT / "config" / "watch_pool.toml").read_text(encoding="utf-8")).get("themes", [])
    except Exception:
        pool = []
    for th in pool:
        for s in th.get("stocks", []):
            add(str(s.get("code", "")), s.get("name", ""), f"관찰 풀 {th.get('id', '')}")
    return out


def load(code):
    f = DIR / f"{code}.json"
    return json.loads(f.read_text(encoding="utf-8")) if f.exists() else None


def queue(top):
    T = targets()
    for i, t in enumerate(T):
        m = load(t["code"])
        t["memo_updated"] = (m or {}).get("updated", "")
        t["_k"] = (0 if t["why"] == "보유" else 1 if t["why"].endswith("C1") else 2, t["memo_updated"], i)
    # 메모 없는 것 먼저(보유 → 핵심 후보 → 나머지), 그다음 오래된 메모 순
    T.sort(key=lambda t: (bool(t["memo_updated"]), t["memo_updated"], t["_k"][0], t["_k"][2]))
    pick = T[:top]
    for t in pick:
        t.pop("_k", None); c, n = t["code"], t["name"]
        t["materials"] = [f"python3 tools/fundamentals.py show --stock {c}",
                          f"python3 tools/tg_channel.py company --stock {n} --days 30",
                          f"python3 tools/dart.py list --days 90   # 관심종목에 없으면 건너뜀",
                          f"python3 tools/naver_research.py candidates   # '{n}' 리포트 nid를 찾아 pdf --cat company --nid … --max 60000 (최근 2~3건, 원문 저장 금지)",
                          f"python3 tools/naver_quote.py daily --stock {c} --days 120",
                          f"python3 tools/news.py search --query \"{n}\" --hours 240"]
    return {"at": datetime.now(KST).strftime("%Y-%m-%d %H:%M"), "n_targets": len(T), "pick": pick,
            "note": "한 종목에 15~25분. 재료에 없는 숫자는 쓰지 않는다. 채널 글은 2차 자료로 표시."}


def save(path):
    d = json.loads(Path(path).read_text(encoding="utf-8"))
    need = ("code", "name", "thesis", "business", "drivers", "numbers", "bull", "bear", "invalid", "next", "read", "sources")
    miss = [k for k in need if not d.get(k)]
    if miss:
        raise SystemExit(f"빠진 칸: {miss}")
    if len(d["thesis"]) > 80:
        raise SystemExit(f"thesis는 80자 이내: 지금 {len(d['thesis'])}자")
    lim = {"drivers": (2, 4), "numbers": (3, 8), "bull": (2, 3), "bear": (2, 3), "invalid": (1, 3), "next": (1, 4), "read": (2, 12)}
    for k, (lo, hi) in lim.items():
        if not isinstance(d[k], list) or not lo <= len(d[k]) <= hi:
            raise SystemExit(f"{k}는 {lo}~{hi}개: 지금 {len(d[k]) if isinstance(d[k], list) else '목록 아님'}")
    if any(not x.get("evidence") for x in d["drivers"]) or any(not x.get("source") for x in d["numbers"]):
        raise SystemExit("drivers에는 evidence, numbers에는 source가 있어야 합니다")
    js = json.dumps(d, ensure_ascii=False)
    hit = [b for b in BAD if b in js]
    if hit:
        raise SystemExit(f"매수·매도 단정 표현: {hit}")
    flat = [d["thesis"]] + [x for k in ("bull", "bear", "invalid") for x in d[k]]
    bad_end = [s for s in flat if s.rstrip(" .").endswith(("한다", "이다", "된다", "있다", "없다", "했다", "였다"))]
    if bad_end:
        raise SystemExit(f"어투는 '~입니다': {bad_end[:2]}")
    d["updated"] = datetime.now(KST).strftime("%Y-%m-%d")
    d["by"] = d.get("by", "opus")
    DIR.mkdir(parents=True, exist_ok=True)
    (DIR / f"{d['code']}.json").write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8")
    return {"saved": d["code"], "name": d["name"], "updated": d["updated"]}


def main():
    ap = argparse.ArgumentParser(); sp = ap.add_subparsers(dest="cmd", required=True)
    p = sp.add_parser("queue"); p.add_argument("--top", type=int)
    p = sp.add_parser("save"); p.add_argument("--file", required=True)
    p = sp.add_parser("show"); p.add_argument("--code", required=True)
    sp.add_parser("list")
    a = ap.parse_args()
    if a.cmd == "queue":
        import depth
        o = queue(a.top or depth.get("stock_memo_n", 4) or 4)
    elif a.cmd == "save":
        o = save(a.file)
    elif a.cmd == "show":
        o = load(a.code) or {"error": "메모 없음"}
    else:
        o = sorted(({"code": f.stem, **{k: json.loads(f.read_text(encoding="utf-8")).get(k) for k in ("name", "updated", "thesis")}}
                    for f in DIR.glob("*.json")), key=lambda x: x.get("updated") or "") if DIR.exists() else []
    print(json.dumps(o, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
