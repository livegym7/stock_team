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
from datetime import datetime, timedelta
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
    want = ["^GSPC", "^IXIC", "^DJI", "^SOX", "KRW=X", "^TNX", "^VIX", "CL=F"]
    usr = [r for r in us.get("results", []) if r.get("symbol") in want] if isinstance(us, dict) else []
    return {"kr": kr.get("results", []) if isinstance(kr, dict) else [], "us": usr,
            "source": "코스피·코스닥 네이버, 해외 Yahoo Finance (비공식)"}


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
            "gate_score", "setups", "run_pct", "today", "vol_ratio", "stage", "levels", "overhead_zone"]
    def slim(x):
        y = {k: x.get(k) for k in keep}
        b = x.get("base") or {}
        y["base"] = {k: b.get(k) for k in ("pivot", "pivot_date", "days", "depth_pct", "stage1_pct", "giveback_pct", "vol_dryup")} if b else None
        return y
    return {"as_of": d.get("as_of"), "made_at": d.get("made_at"), "count": d.get("count"), "rules": d.get("rules"),
            "source": d.get("source"), "watch": [slim(x) for x in d.get("watch", [])],
            "running": [slim(x) for x in d.get("running", [])], "near_miss": [slim(x) for x in d.get("near_miss", [])[:15]]}


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


def channel_feed(t, allp, hours=48):
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
    a = p.parse_args()
    now = datetime.now(KST)
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
                          "reports": rs[-8:][::-1], "n_reports": len(rs),
                          "up": sum(r.get("direction") == "상향" for r in rs), "down": sum(r.get("direction") == "하향" for r in rs),
                          "median_target": statistics.median(afters) if afters else None})
    comp_list.sort(key=lambda c: -c["n_reports"])

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
    WEB.mkdir(exist_ok=True)
    tpl = (WEB / "app.html").read_text(encoding="utf-8")
    blob = json.dumps(data, ensure_ascii=False).replace("</", "<\\/")
    (WEB / "index.html").write_text(tpl.replace("/*__DATA__*/null", blob), encoding="utf-8")
    print(json.dumps({"built_at": data["built_at"], "out": "web/index.html", "kb": round(len(blob) / 1024),
                      "briefs": len(brief_rows), "companies": len(comp_list), "channels": len(data["channels"]),
                      "watch": len((data["watch"] or {}).get("watch", []))}, ensure_ascii=False))


if __name__ == "__main__":
    main()
