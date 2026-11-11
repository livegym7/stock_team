"""딥리서치: 구글 드라이브에 올린 리포트 원문을 Claude가 읽고 쓴 심층 분석을 저장·관리한다.

드라이브 읽기와 분석은 Claude가 한다(구글 드라이브 연결). 이 도구는 저장·목록·종합용 재료만 맡는다.
원문(PDF)은 저장하지 않는다. 요약·분석·핵심 숫자와 드라이브 링크만 data/research/에 둔다.

사용법:
    python3 tools/research.py status                    # 분석한 문서 목록(파일 ID) → 새 파일 고를 때
    python3 tools/research.py save --file 분석.json      # 문서 하나 분석 결과 저장 (형식은 .claude/skills/deep-research/SKILL.md)
    python3 tools/research.py skip --id 파일ID --title 이름 --reason "리포트 아님"
    python3 tools/research.py context                   # 종합 분석 재료: 전체 문서 요약 + 언급 종목의 시장 확인(RS·수익률·레이더)
    python3 tools/research.py save-synthesis --file 종합.json   # 아이디어는 성적표(ideas.json)에도 기록 (처음 나온 날 종가 = 기준가)
    python3 tools/research.py record-ideas                       # 지금 종합으로 성적표만 다시 기록
    python3 tools/research.py touch --id 파일ID --modified 시각   # 파일 이름만 바뀐 문서: 수정 시각만 갱신(다시 읽지 않게)

분석 JSON에 "depth": "light"를 넣으면 '요약만(첫 쪽)'으로 표시된다(첫 1~2쪽만 읽은 가벼운 요약).
"""
import argparse
import json
from datetime import datetime

from common import DATA, load_toml
from naver_quote import KST

DIR = DATA / "research"
DOCS = DIR / "docs"
INDEX = DIR / "index.json"
SYN = DIR / "synthesis.json"
IDEAS = DIR / "ideas.json"   # 아이디어 성적표: 처음 나온 날·그날 종가를 기록해 두고 이후 성과를 잰다

REQUIRED = ["file_id", "title", "url", "kind", "subject", "one_line", "summary", "thesis", "stocks", "sectors",
            "outlook", "risks", "claude"]
KINDS = ["기업", "산업", "전략", "매크로"]


def load_index():
    if INDEX.exists():
        return json.loads(INDEX.read_text(encoding="utf-8"))
    return {"docs": {}, "skipped": {}}


def save_index(ix):
    DIR.mkdir(parents=True, exist_ok=True)
    INDEX.write_text(json.dumps(ix, ensure_ascii=False, indent=1), encoding="utf-8")


def now():
    return datetime.now(KST).strftime("%Y-%m-%d %H:%M")


def cmd_status():
    ix = load_index()
    cfg = load_toml("research.toml")
    print(json.dumps({"folders": cfg.get("folders", []),
                      "analyzed": {k: {"title": v["title"], "date": v.get("date"), "drive_modified": v.get("drive_modified")}
                                   for k, v in ix["docs"].items()},
                      "skipped": ix["skipped"], "synthesis_at": json.loads(SYN.read_text(encoding="utf-8")).get("updated_at")
                      if SYN.exists() else None}, ensure_ascii=False, indent=1))


def cmd_save(path):
    d = json.loads(open(path, encoding="utf-8").read())
    miss = [k for k in REQUIRED if k not in d]
    if miss:
        raise SystemExit(f"빠진 항목: {miss}")
    if d["kind"] not in KINDS:
        raise SystemExit(f"kind는 {KINDS} 중 하나")
    if not str(d["url"]).startswith(("https://drive.google.com/", "https://stock.naver.com/research/")):
        raise SystemExit("url은 구글 드라이브 또는 네이버 리서치 페이지 링크여야 합니다 (원문은 저장소에 두지 않음)")
    for k in ("text", "raw", "content"):   # 원문 통째 저장 방지
        d.pop(k, None)
    from universe import load
    uni = {s["name"]: s["code"] for s in load()["stocks"]}
    for s in d.get("stocks", []):
        s["code"] = s.get("code") or uni.get(s.get("name"))
    if d.get("depth") not in (None, "full", "light", "excerpt"):
        raise SystemExit('depth는 "full" / "light"(요약만, 첫 쪽) / "excerpt"(질문 주도 발췌 읽기, 2026-11-11)')
    d["depth"] = d.get("depth") or "full"
    d["analyzed_at"] = now()
    DOCS.mkdir(parents=True, exist_ok=True)
    (DOCS / f"{d['file_id']}.json").write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8")
    ix = load_index()
    ix["docs"][d["file_id"]] = {k: d.get(k) for k in ("title", "broker", "date", "kind", "subject", "one_line", "url", "drive_modified", "analyzed_at", "depth")}
    ix["skipped"].pop(d["file_id"], None)
    save_index(ix)
    print(json.dumps({"saved": d["file_id"], "title": d["title"], "stocks": [s.get("name") for s in d["stocks"]],
                      "no_code": [s.get("name") for s in d["stocks"] if not s.get("code")]}, ensure_ascii=False))


def cmd_touch(fid, modified):
    ix = load_index()
    if fid not in ix["docs"]:
        raise SystemExit(f"분석 목록에 없는 파일: {fid}")
    ix["docs"][fid]["drive_modified"] = modified
    f = DOCS / f"{fid}.json"
    if f.exists():
        d = json.loads(f.read_text(encoding="utf-8"))
        d["drive_modified"] = modified
        f.write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8")
    save_index(ix)
    print(json.dumps({"touched": fid, "drive_modified": modified}, ensure_ascii=False))


def cmd_skip(fid, title, reason):
    ix = load_index()
    ix["skipped"][fid] = {"title": title, "reason": reason, "at": now()}
    save_index(ix)
    print(json.dumps({"skipped": fid}, ensure_ascii=False))


def market_check(names_codes):
    """언급 종목의 시장 확인: 웹 데이터(기업 메뉴 계산값)에서 RS·수익률, 섹터 레이더 순위."""
    out = {}
    last = DATA.parent / "web" / "last_data.json"
    comp = {}
    if last.exists():
        d = json.loads(last.read_text(encoding="utf-8"))
        comp = {c["code"]: c for c in d.get("companies", [])}
        for code, t in ((d.get("research") or {}).get("trend") or {}).items():   # 기업 목록에 없는 종목은 딥리서치 계산값
            comp.setdefault(code, {"trend": t})
    snap = DATA / "radar" / "company_rs.json"
    rs = json.loads(snap.read_text(encoding="utf-8")) if snap.exists() else {}
    for name, code in names_codes:
        t = (comp.get(code) or {}).get("trend") or {}
        out[name] = {"code": code, "rs": t.get("rs", (rs.get(code) or {}).get("rs")), "r1m": t.get("r1m"),
                     "r3m": t.get("r3m"), "off_high": t.get("off_high"), "reports_1m": (comp.get(code) or {}).get("n_reports")}
    return out


def cmd_context():
    docs = [json.loads(f.read_text(encoding="utf-8")) for f in sorted(DOCS.glob("*.json"))]
    names = {(s["name"], s.get("code")) for d in docs for s in d.get("stocks", []) if s.get("name")}
    radar = DATA / "radar" / "latest.json"
    groups = json.loads(radar.read_text(encoding="utf-8")).get("groups", []) if radar.exists() else []
    print(json.dumps({
        "docs": [{"file_id": d["file_id"], "title": d["title"], "broker": d.get("broker"), "date": d.get("date"), "kind": d["kind"],
                  "subject": d["subject"], "one_line": d["one_line"], "thesis": d["thesis"], "stocks": d["stocks"],
                  "sectors": d["sectors"], "outlook": d["outlook"], "catalysts": d.get("catalysts", []), "risks": d["risks"]} for d in docs],
        "market_check": market_check(sorted(names, key=lambda x: x[0])),
        "radar_top": [{"group": g["group"], "rank": g["rank"], "score": g["score"], "rel1m_pct": g["rel1m_pct"]} for g in groups[:15]],
        "note": "market_check: RS 0~99(70↑ 강함)·수익률 %, 출처 네이버 일봉(비공식)·Claude 계산. 레이더 = 업종 강도 순위",
    }, ensure_ascii=False, indent=1))


def close_on(code, day):
    """그 날짜(YYYY-MM-DD) 전날까지의 마지막 종가 (네이버 일봉). 장중에 기록해도 기준가가 흔들리지 않게 '전 거래일 종가'를 쓴다."""
    import screener as S
    rows = S.fetch_daily(code)
    d = day.replace("-", "")
    past = [r for r in rows if r["date"] < d]
    return (past[-1]["close"], past[-1]["date"]) if past else (None, None)


def record_ideas(syn):
    """종합의 아이디어를 성적표에 올린다. 처음 나온 아이디어만 기준가를 새로 잡고, 이미 있으면 상태만 갱신."""
    from universe import load
    uni = {s["name"]: s["code"] for s in load()["stocks"]}
    book = json.loads(IDEAS.read_text(encoding="utf-8")) if IDEAS.exists() else {"ideas": {}}
    day = syn["updated_at"][:10]
    live = set()
    for i in syn.get("ideas", []):
        key = i["title"].strip()
        live.add(key)
        it = book["ideas"].get(key)
        if not it:
            stocks = []
            for n in i.get("stocks", []):
                code = uni.get(n)
                px, pd = close_on(code, day) if code else (None, None)
                stocks.append({"name": n, "code": code, "base": px, "base_date": pd})
            bench, bd = close_on("069500", day)   # KODEX 200 = 코스피200 대신
            it = book["ideas"][key] = {"title": key, "first_seen": day, "stocks": stocks, "bench_base": bench,
                                       "confidence": i.get("confidence"), "horizon": i.get("horizon"),
                                       "evidence_docs": i.get("evidence_docs", []), "thesis": i.get("thesis")}
        it["active"] = True
        it["last_seen"] = day
        it["confidence_now"] = i.get("confidence")
    for k, it in book["ideas"].items():
        if k not in live:
            it["active"] = False
    IDEAS.write_text(json.dumps(book, ensure_ascii=False, indent=1), encoding="utf-8")
    return len(book["ideas"])


def cmd_save_syn(path):
    d = json.loads(open(path, encoding="utf-8").read())
    for k in ("headline", "ideas", "leading_sectors", "leading_stocks", "outlook"):
        if k not in d:
            raise SystemExit(f"빠진 항목: {k}")
    d["updated_at"] = now()
    d["docs_n"] = len(list(DOCS.glob("*.json")))
    SYN.write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8")
    n = record_ideas(d)
    print(json.dumps({"synthesis": d["updated_at"], "ideas": len(d["ideas"]), "scorecard_ideas": n}, ensure_ascii=False))


def main():
    p = argparse.ArgumentParser(description="딥리서치 저장·관리")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("status")
    s = sub.add_parser("save"); s.add_argument("--file", required=True)
    s = sub.add_parser("skip"); s.add_argument("--id", required=True); s.add_argument("--title", default=""); s.add_argument("--reason", default="")
    sub.add_parser("context")
    s = sub.add_parser("save-synthesis"); s.add_argument("--file", required=True)
    sub.add_parser("record-ideas")
    s = sub.add_parser("touch"); s.add_argument("--id", required=True); s.add_argument("--modified", required=True)
    a = p.parse_args()
    if a.cmd == "status":
        cmd_status()
    elif a.cmd == "save":
        cmd_save(a.file)
    elif a.cmd == "skip":
        cmd_skip(a.id, a.title, a.reason)
    elif a.cmd == "touch":
        cmd_touch(a.id, a.modified)
    elif a.cmd == "context":
        cmd_context()
    elif a.cmd == "record-ideas":
        print(json.dumps({"ideas": record_ideas(json.loads(SYN.read_text(encoding="utf-8")))}, ensure_ascii=False))
    else:
        cmd_save_syn(a.file)


if __name__ == "__main__":
    main()
