"""네이버(Npay 증권) 리서치 리포트 수집 · 중요도 점수 · PDF 전문 읽기. 국내종목·산업분석·투자전략만.

1차 자료: 증권사·작성일·제목·요약, 종목 리포트는 종목코드·목표주가·투자의견까지 (채널 요약보다 정확).
네이버가 화면에 쓰는 비공개 주소라 바뀌면 멈출 수 있다. PDF 원문은 임시로 받아 글자만 뽑고 바로 지운다 (절대 규칙 3).

사용법:
    python3 tools/naver_research.py collect [--days 45]     # 새 리포트 받기 (처음엔 45일 거슬러), data/naver_research/
    python3 tools/naver_research.py candidates [--date 2026-11-04] [--top 20]   # 규칙 점수로 후보 (토큰 0)
    python3 tools/naver_research.py pdf --cat company --nid 97620             # PDF 전문 글자 출력 (원문은 저장 안 함)
    python3 tools/naver_research.py pick --date 2026-11-04 --nid company:97620 --why "이유"   # Claude가 고른 것 기록
"""
import argparse
import html
import json
import re
import subprocess
import tempfile
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from pathlib import Path

from common import DATA, http_get, positions, watchlist
from naver_quote import KST

API = "https://stock.naver.com/api/stockSecurity/researches/v2"
CATS = {"company": "국내종목", "industry": "산업분석", "invest": "투자전략"}
DIR = DATA / "naver_research"
H = {"User-Agent": "Mozilla/5.0", "Accept": "application/json", "Referer": "https://stock.naver.com/research"}


def clean(t, n=600):
    t = html.unescape(re.sub(r"<[^>]+>", " ", t or ""))
    return re.sub(r"\s+", " ", t).strip()[:n]


def store_path(cat):
    return DIR / f"{cat}.jsonl"


def load(cat):
    p = store_path(cat)
    if not p.exists():
        return {}
    return {d["nid"]: d for d in (json.loads(l) for l in p.read_text(encoding="utf-8").splitlines() if l.strip())}


def save(cat, store):
    DIR.mkdir(parents=True, exist_ok=True)
    rows = sorted(store.values(), key=lambda d: int(d["nid"]))
    store_path(cat).write_text("\n".join(json.dumps(d, ensure_ascii=False) for d in rows) + "\n", encoding="utf-8")


def collect(days=45):
    out = {}
    for cat in CATS:
        st = load(cat)
        since = (datetime.now(KST) - timedelta(days=days)).strftime("%Y-%m-%d")
        new, page = 0, 0
        while page < 800:
            d = json.loads(http_get(f"{API}/{cat}", {"index": page, "size": 50}, headers=H))
            items = d.get("items") or []
            stop = False
            for it in items:
                if it["writeDate"] < since:
                    stop = True; break
                if it["nid"] in st:
                    stop = True; continue
                row = {"nid": it["nid"], "cat": cat, "date": it["writeDate"], "broker": it.get("brokerName"),
                       "title": clean(it.get("title"), 200), "summary": clean(it.get("content"), 600),
                       "reads": int(it.get("readCount") or 0)}
                if cat == "company":
                    row.update({"code": it.get("itemCode"), "name": it.get("itemName"),
                                "target": int(it["goalPrice"]) if str(it.get("goalPrice") or "").isdigit() and int(it["goalPrice"]) > 0 else None,
                                "opinion": it.get("opinionText"), "op_type": it.get("opinionType")})
                if cat == "industry":
                    row.update({"industry": it.get("industryKoreanName"), "analyst": it.get("analystName")})
                st[it["nid"]] = row; new += 1
            if stop or not d.get("hasNext"):
                break
            page += 1
        # 조회수는 날마다 늘어나므로 최근 3일치는 첫 페이지 값으로 갱신
        save(cat, st)
        out[cat] = {"new": new, "total": len(st)}
    return out


def _ctx():
    """점수에 쓰는 맥락: 보유·관심, 강도(RS), 섹터 레이더 상위, 딥리서치 테마 종목·섹터, 최근 실적 서프라이즈."""
    ctx = {"held": {p["code"] for p in positions()}, "watch": {w.get("code") for w in watchlist() if w.get("code")}}
    try:
        ctx["rs"] = {k: v.get("rs") for k, v in json.loads((DATA / "radar" / "company_rs.json").read_text(encoding="utf-8")).items()}
    except Exception:
        ctx["rs"] = {}
    try:
        g = json.loads((DATA / "radar" / "latest.json").read_text(encoding="utf-8"))["groups"]
        ctx["hot_groups"] = [x["group"] for x in g[:10]]
    except Exception:
        ctx["hot_groups"] = []
    try:
        syn = json.loads((DATA / "research" / "synthesis.json").read_text(encoding="utf-8"))
        ctx["theme_names"] = {n for c in syn.get("chains", []) for nd in c["nodes"] for n in nd["stocks"]} | \
            {n for i in syn.get("ideas", []) for n in i.get("stocks", [])}
        ctx["theme_words"] = {w for s in syn.get("leading_sectors", []) for w in re.findall(r"[가-힣A-Za-z]{2,}", s["name"])}
    except Exception:
        ctx["theme_names"], ctx["theme_words"] = set(), set()
    try:
        cut = (datetime.now(KST) - timedelta(days=4)).strftime("%Y-%m-%d")
        ctx["earn"] = {r["code"]: r for r in json.loads((DATA / "earnings" / "latest.json").read_text(encoding="utf-8"))["rows"]
                       if r["time"][:10] >= cut and r.get("verdict") in ("서프라이즈", "쇼크")}
    except Exception:
        ctx["earn"] = {}
    from sector_map import custom_map
    ctx["group"] = custom_map()
    return ctx


def score_company(r, prev, same_day, ctx):
    s, why = 0, []
    c = r.get("code")
    if c in ctx["held"]:
        s += 100; why.append("⭐보유")
    elif c in ctx["watch"]:
        s += 60; why.append("☆관심")
    if prev and prev.get("target") and r.get("target"):
        chg = (r["target"] / prev["target"] - 1) * 100
        r["prev_target"], r["target_chg"] = prev["target"], round(chg, 1)
        if abs(chg) >= 15:
            s += 30; why.append(f"목표가 {chg:+.0f}%")
        elif abs(chg) >= 8:
            s += 15; why.append(f"목표가 {chg:+.0f}%")
    if prev and prev.get("op_type") and r.get("op_type") and prev["op_type"] != r["op_type"]:
        s += 30; why.append(f"의견 변경 {prev.get('opinion')}→{r.get('opinion')}")
    if same_day >= 2:
        s += 8 * (same_day - 1); why.append(f"같은 날 {same_day}개 증권사")
    if c in ctx["earn"]:
        s += 15; why.append(f"실적 {ctx['earn'][c]['verdict']}")
    rs = ctx["rs"].get(c)
    if rs is not None and rs >= 80:
        s += 10; why.append(f"RS {rs}")
    if r.get("name") in ctx["theme_names"]:
        s += 20; why.append("딥리서치 테마 종목")
    if ctx["group"].get(c) in ctx["hot_groups"]:
        s += 10; why.append(f"강한 업종({ctx['group'][c]})")
    s += min(20, r.get("reads", 0) // 50)
    if re.search(r"Preview|Review|실적|가이던스|턴어라운드|쇼티지|수주|신규|커버리지", r["title"] + r.get("summary", "")[:200]):
        s += 5
    return s, why


def score_text(r, ctx):
    s, why = 0, []
    text = r["title"] + " " + r.get("summary", "")[:400]
    names = [n for n in ctx.get("my_names", []) if n and n in text]
    if names:
        s += 40; why.append("내 종목 언급: " + ",".join(names[:3]))
    if r.get("industry") and any(r["industry"] in g or g in r["industry"] for g in ctx["hot_groups"]):
        s += 15; why.append(f"강한 업종({r['industry']})")
    tw = [w for w in ctx["theme_words"] if w in text]
    if tw:
        s += 15; why.append("딥리서치 테마: " + ",".join(tw[:2]))
    if re.search(r"전망|Outlook|연간|2027|Top ?[Pp]ick|쇼티지|가격 인상|업황|사이클|턴어라운드|전략", r["title"]):
        s += 12; why.append("전망·전략성 제목")
    if re.search(r"Daily|데일리|모닝|Morning|Weekly|위클리|주간|Short Comment|코멘트|채권", r["title"], re.I):
        s -= 15
    s += min(20, r.get("reads", 0) // 40)
    return s, why


def candidates(day=None, top=20):
    day = day or datetime.now(KST).strftime("%Y-%m-%d")
    ctx = _ctx()
    try:
        names = json.loads((DATA / "companies.json").read_text(encoding="utf-8"))
        my = ctx["held"] | ctx["watch"]
        ctx["my_names"] = [v["name"] for k, v in names.items() if k in my]
    except Exception:
        ctx["my_names"] = []
    comp = load("company")
    hist = defaultdict(list)
    for r in sorted(comp.values(), key=lambda x: (x["date"], int(x["nid"]))):
        hist[(r.get("broker"), r.get("code"))].append(r)
    today = [r for r in comp.values() if r["date"] == day]
    per_item = Counter(r.get("code") for r in today)
    out = []
    for r in today:
        h = [x for x in hist[(r.get("broker"), r.get("code"))] if (x["date"], int(x["nid"])) < (r["date"], int(r["nid"]))]
        r = dict(r)
        s, why = score_company(r, h[-1] if h else None, per_item[r.get("code")], ctx)
        out.append({**r, "score": s, "why": why})
    for cat in ("industry", "invest"):
        for r in load(cat).values():
            if r["date"] == day:
                s, why = score_text(r, ctx)
                out.append({**r, "score": s, "why": why})
    out.sort(key=lambda x: -x["score"])
    # 다양하게: 국내종목 12(한 종목 최대 2건) · 산업분석 5 · 투자전략 3 칸을 나눠 고른다
    slots = {"company": round(top * 0.6), "industry": round(top * 0.25), "invest": top - round(top * 0.6) - round(top * 0.25)}
    per_stock, chosen = Counter(), []
    for x in out:
        if slots.get(x["cat"], 0) <= 0:
            continue
        if x["cat"] == "company":
            if per_stock[x.get("code")] >= 2:
                continue
            per_stock[x.get("code")] += 1
        slots[x["cat"]] -= 1
        chosen.append(x)
    chosen.sort(key=lambda x: -x["score"])
    path = DIR / f"candidates_{day}.json"
    old = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    res = {"date": day, "made_at": datetime.now(KST).strftime("%Y-%m-%d %H:%M"), "n_total": len(out),
           "by_cat": dict(Counter(x["cat"] for x in out)), "candidates": chosen, "picked": old.get("picked", [])}
    DIR.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    (DIR / "candidates_latest.json").write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    return res


def pdf_text(cat, nid):
    d = json.loads(http_get(f"{API}/{cat}/{nid}", headers=H))
    url = d.get("attachUrl")
    if not url:
        return {"error": "PDF 링크 없음", "summary": clean(d.get("content"), 3000)}
    with tempfile.TemporaryDirectory() as tmp:   # 원문은 임시 폴더에서만, 끝나면 자동 삭제
        pdf = Path(tmp) / "r.pdf"
        pdf.write_bytes(http_get(url, headers={"User-Agent": "Mozilla/5.0", "Referer": "https://stock.naver.com/"}, timeout=60))
        txt = subprocess.run(["pdftotext", "-layout", str(pdf), "-"], capture_output=True, text=True, timeout=120).stdout
    return {"nid": nid, "cat": cat, "title": d.get("title"), "broker": d.get("brokerName"), "date": d.get("writeDate"),
            "page_url": f"https://stock.naver.com/research/{cat}/{nid}", "pdf_url": url, "chars": len(txt), "text": txt}


def pick(day, ids, why):
    path = DIR / f"candidates_{day}.json"
    res = json.loads(path.read_text(encoding="utf-8")) if path.exists() else candidates(day)
    have = {p["id"] for p in res.get("picked", [])}
    for i in ids:
        if i not in have:
            res.setdefault("picked", []).append({"id": i, "why": why, "at": datetime.now(KST).strftime("%H:%M")})
    path.write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    if (DIR / "candidates_latest.json").exists() and json.loads((DIR / "candidates_latest.json").read_text(encoding="utf-8")).get("date") == day:
        (DIR / "candidates_latest.json").write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    return res["picked"]


def main():
    p = argparse.ArgumentParser(description="네이버 리서치 (국내종목·산업분석·투자전략)")
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("collect"); s.add_argument("--days", type=int, default=45)
    s = sub.add_parser("candidates"); s.add_argument("--date"); s.add_argument("--top", type=int, default=20)
    s = sub.add_parser("pdf"); s.add_argument("--cat", required=True, choices=list(CATS)); s.add_argument("--nid", required=True)
    s.add_argument("--max", type=int, default=40000, help="출력 글자 수 상한 (토큰 절약)")
    s = sub.add_parser("pick"); s.add_argument("--date", required=True); s.add_argument("--nid", action="append", required=True); s.add_argument("--why", default="")
    a = p.parse_args()
    if a.cmd == "collect":
        print(json.dumps(collect(a.days), ensure_ascii=False))
    elif a.cmd == "candidates":
        r = candidates(a.date, a.top)
        print(json.dumps({**r, "candidates": [{k: x.get(k) for k in ("cat", "nid", "broker", "title", "name", "target", "target_chg", "opinion", "industry", "reads", "score", "why", "summary")}
                                              for x in r["candidates"]]}, ensure_ascii=False, indent=1))
    elif a.cmd == "pdf":
        r = pdf_text(a.cat, a.nid)
        if "text" in r:
            r["text"] = re.sub(r"[ \t]{3,}", "  ", r["text"])[:a.max]
        print(json.dumps(r, ensure_ascii=False, indent=1))
    else:
        print(json.dumps(pick(a.date, a.nid, a.why), ensure_ascii=False))


if __name__ == "__main__":
    main()
