#!/usr/bin/env python3
"""종목 기본 카드 (2026-11-13 사용자 확정 '3단계 카드' ①): 시총 2천억↑ 전 종목의 기업 개요 → data/stock_profiles.json.

  python3 tools/stock_profile.py update [--budget 240]   # 없는 것·60일 지난 것부터 받기 (병렬 4, 토큰 0)
  python3 tools/stock_profile.py show --stock 131290

출처: 네이버 증권 기업 정보(와이즈리포트) '기업 개요' 문단 — 사실 설명만, 의견 없음. 2~3문장으로 줄여 저장.
깊은 카드(Claude, ③)가 생기면 화면은 그쪽 사업 한 줄을 먼저 쓴다. 주문 기능 없음.
"""
import argparse, html, json, re, sys, time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import DATA, http_get  # noqa: E402
from strategy_prep import KST  # noqa: E402

PATH = DATA / "stock_profiles.json"
URL = "https://navercomp.wisereport.co.kr/v2/company/c1010001.aspx?cmp_cd="


def load():
    try:
        return json.loads(PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}


def fetch(code):
    try:
        h = http_get(URL + code).decode("utf-8", "replace")
    except Exception:
        return None
    m = re.search(r'class="cmp_comment"(.*?)</ul>', h, re.S)
    if not m:
        return ""
    lines = [html.unescape(re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", x))).strip(" >") for x in re.findall(r"<li[^>]*>(.*?)</li>", m.group(1), re.S)]
    text = " ".join(x for x in lines if x)
    sents = [s.strip() for s in re.split(r"(?<=[음임함됨])\.\s*", text) if s.strip()]
    return " ".join(s.rstrip(".") + "." for s in sents[:3])[:360]


def update(budget=None, workers=4):
    import new_highs
    prof, now = load(), datetime.now(KST)
    old_cut = (now - timedelta(days=60)).strftime("%Y-%m-%d")
    uni = new_highs.universe_info()
    todo = [c for c in uni if c not in prof or prof[c].get("at", "") < old_cut]
    todo.sort(key=lambda c: prof.get(c, {}).get("at", ""))
    t0, got = time.time(), 0

    def one(code):
        if budget and time.time() - t0 > budget:
            return code, None
        t = fetch(code)
        time.sleep(0.2)
        return code, t
    with ThreadPoolExecutor(workers) as ex:
        for code, t in ex.map(one, todo):
            if t is None:
                continue
            s = uni[code]
            prof[code] = {"name": s["name"], "summary": t, "group": s["group"], "cap": s["cap"], "at": now.strftime("%Y-%m-%d")}
            got += 1
    for c, s in uni.items():   # 시총·업종은 매번 최신으로
        if c in prof:
            prof[c].update({"name": s["name"], "group": s["group"], "cap": s["cap"]})
    PATH.write_text(json.dumps(dict(sorted(prof.items())), ensure_ascii=False, indent=0), encoding="utf-8")
    return {"updated": got, "total": len(prof), "universe": len(uni), "left": len(todo) - got, "sec": round(time.time() - t0)}


def main():
    ap = argparse.ArgumentParser(description="종목 기본 카드: 기업 개요(네이버 기업 정보) 받기")
    sp = ap.add_subparsers(dest="cmd", required=True)
    u = sp.add_parser("update"); u.add_argument("--budget", type=int)
    s = sp.add_parser("show"); s.add_argument("--stock", required=True)
    a = ap.parse_args()
    if a.cmd == "update":
        print(json.dumps(update(a.budget), ensure_ascii=False))
    else:
        print(json.dumps(load().get(a.stock) or fetch(a.stock), ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
