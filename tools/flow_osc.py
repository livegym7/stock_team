#!/usr/bin/env python3
"""수급 오실레이터 (2026-11-13 사용자 확정, 후보 B).

  하루 수급 비율 = (외국인 + 기관 순매수 수량) ÷ 상장주식수   (= 순매수 금액 ÷ 시가총액과 같음)
  오실레이터     = 비율의 6일 평균 − 22일 평균 → 3일 평균으로 한 번 더 부드럽게
  현재 위치 P    = 오늘 값이 최근 60개 값 중 몇 % 위치인지 (0 = 가장 비어 있음, 100 = 가장 차 있음)

사용자가 보내 준 차트 5종목(삼성전자·원익홀딩스·삼성E&A·티에스이·삼양식품)과 비교해 고른 식이다(P 평균 차이 6).
참고 표시만 한다: 매매 규칙(docs/rules.md)은 2027-01-31까지 고정, 진입·청산 신호로 쓰지 않는다.

  python3 tools/flow_osc.py update [--all]   # 투자자별 순매수 받기(캐시 data/cache/flows/, 처음 130일·이후 10일씩) → 보유·관찰 풀·기업 카드 종목
  python3 tools/flow_osc.py show --stock 005930
  (web_build가 캐시로 계산해 web/f/코드.json + D.flowosc를 만든다. 네트워크 없음)

시세는 네이버(비공식) 투자자별 매매동향. 토큰 0. 주문 기능 없음.
"""
import argparse, json, sys, time
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import CACHE, DATA, http_get  # noqa: E402
from strategy_prep import KST  # noqa: E402

FLOWS = CACHE / "flows"
MOBILE = "https://m.stock.naver.com/api/stock/"
POLL = "https://polling.finance.naver.com/api/realtime/domestic/stock/"
SHORT, LONG, SMOOTH, WINDOW = 6, 22, 3, 60


def _num(v):
    try:
        return float(str(v).replace(",", "").replace("+", ""))
    except Exception:
        return None


def _won_eok(t):
    """'2조 8,151억' → 28151 (억 원)"""
    t = str(t).replace(",", "").replace("억", "").strip()
    jo = 0
    if "조" in t:
        a, b = t.split("조")
        jo, t = int(a), b.strip()
    return jo * 10000 + (int(t) if t else 0)


def targets(all_=False):
    """보유 + 관찰 풀 + 기업 카드 종목 (--all이면 시총 2천억↑ 전부)."""
    codes = {}
    try:
        from common import load_toml, positions
        for p in positions():
            codes[p["code"]] = p["name"]
        for th in (load_toml("watch_pool.toml") or {}).get("themes", []):
            for s in th.get("stocks", []):
                if s.get("code"):
                    codes[s["code"]] = s.get("name", s["code"])
    except Exception:
        pass
    try:
        comp = json.loads((DATA / "companies.json").read_text(encoding="utf-8"))
        for k, v in comp.items():
            codes.setdefault(k, v.get("name", k))
    except Exception:
        pass
    try:   # 웹 기업 메뉴 종목(리포트가 나온 종목 포함)
        d = json.loads((Path(__file__).resolve().parent.parent / "web" / "last_data.json").read_text(encoding="utf-8"))
        for c in d.get("companies") or []:
            codes.setdefault(c["code"], c["name"])
        for x in (d.get("highs") or {}).get("items") or []:   # 최근 5일 신고가 종목도
            codes.setdefault(x["code"], x["name"])
    except Exception:
        pass
    if all_:
        import new_highs
        for k, s in new_highs.universe_info().items():
            codes.setdefault(k, s["name"])
    return codes


def fetch_trend(code, days, before=None):
    rows = []
    while len(rows) < days:
        q = f"?pageSize={min(60, days - len(rows))}" + (f"&bizdate={before}" if before else "")
        try:
            batch = json.loads(http_get(MOBILE + code + "/trend" + q))
        except Exception:
            break
        if not batch:
            break
        for r in batch:
            rows.append({"d": r["bizdate"], "c": _num(r.get("closePrice")),
                         "f": _num(r.get("foreignerPureBuyQuant")) or 0, "i": _num(r.get("organPureBuyQuant")) or 0,
                         "p": _num(r.get("individualPureBuyQuant"))})   # 개인 (2026-11-13, 최근 5일 수급 표)
        before = batch[-1]["bizdate"]
        time.sleep(0.25)
    return rows


def fetch_shares(code):
    try:
        j = json.loads(http_get(MOBILE + code + "/integration"))
        mv = next(x["value"] for x in j.get("totalInfos", []) if x.get("code") == "marketValue")
        q = json.loads(http_get(POLL + code))["datas"][0]
        price = _num(q["closePrice"])
        return round(_won_eok(mv) * 1e8 / price) if price else None
    except Exception:
        return None


def _one(code, name, now):
    f = FLOWS / f"{code}.json"
    old = json.loads(f.read_text()) if f.exists() else {}
    rows = {r["d"]: r for r in old.get("rows", [])}
    fresh = fetch_trend(code, 10 if len(rows) >= 100 else 130)
    if not fresh:
        return "fail"
    for r in fresh:
        rows[r["d"]] = r
    shares, sa = old.get("shares"), old.get("shares_at")
    if not shares or (sa or "") < (now - timedelta(days=30)).strftime("%Y-%m-%d"):
        shares, sa = fetch_shares(code) or shares, now.strftime("%Y-%m-%d")
    f.write_text(json.dumps({"code": code, "name": name, "shares": shares, "shares_at": sa,
                             "fetched_at": now.isoformat(timespec="seconds"),
                             "rows": sorted(rows.values(), key=lambda r: r["d"])[-200:]}, ensure_ascii=False))
    return "upd" if old else "new"


def update(all_=False, budget=None, workers=4):
    """오래된 것부터 받는다. budget(초)이 있으면 그 안에서 끊는다(깃허브 배포 시간 제한용, 다음 회차가 이어 받음)."""
    from concurrent.futures import ThreadPoolExecutor
    FLOWS.mkdir(parents=True, exist_ok=True)
    now = datetime.now(KST)
    today = now.strftime("%Y-%m-%d")
    def age(code):
        f = FLOWS / f"{code}.json"
        try:
            return json.loads(f.read_text()).get("fetched_at", "")
        except Exception:
            return ""
    todo = sorted(targets(all_).items(), key=lambda kv: age(kv[0]))
    todo = [kv for kv in todo if age(kv[0])[:10] != today or now.hour >= 18]   # 같은 날 이미 받은 건 저녁 확정 전까지 건너뜀
    t0, out = time.time(), {"new": 0, "upd": 0, "fail": 0, "skipped": 0}
    with ThreadPoolExecutor(workers) as ex:
        futs = []
        for code, name in todo:
            futs.append(ex.submit(lambda c=code, n=name: "skip" if budget and time.time() - t0 > budget else _one(c, n, now)))
        for fu in futs:
            r = fu.result()
            out["skipped" if r == "skip" else r] += 1
    return out | {"targets": len(todo), "at": now.strftime("%Y-%m-%d %H:%M"), "sec": round(time.time() - t0)}


def _sma(a, n):
    return [None if i < n - 1 or any(x is None for x in a[i - n + 1:i + 1]) else sum(a[i - n + 1:i + 1]) / n for i in range(len(a))]


def compute(d):
    """{dates, cap(억), osc, p, last} — 오실레이터 후보 B."""
    rows, sh = d.get("rows") or [], d.get("shares")
    if len(rows) < LONG + SMOOTH + 5 or not sh:
        return None
    s = [(r["f"] + r["i"]) / sh for r in rows]
    raw = [None if a is None or b is None else a - b for a, b in zip(_sma(s, SHORT), _sma(s, LONG))]
    osc = _sma(raw, SMOOTH)
    valid = [x for x in osc if x is not None][-WINDOW:]
    if not valid:
        return None
    last = osc[-1]
    p = round(sum(1 for x in valid if x <= last) / len(valid) * 100, 1)
    return {"dates": [r["d"] for r in rows], "cap": [round(r["c"] * sh / 1e8) if r["c"] else None for r in rows],
            "osc": [None if x is None else round(x, 7) for x in osc], "p": p, "last": last, "n": len(valid), "as_of": rows[-1]["d"]}


def build_web(out_dir):
    """web_build용: web/f/코드.json(최근 120일) + 요약 {코드: [P, 기준일]}."""
    out_dir.mkdir(exist_ok=True)
    summary = {}
    for f in FLOWS.glob("*.json") if FLOWS.exists() else []:
        try:
            d = json.loads(f.read_text())
            c = compute(d)
        except Exception:
            continue
        if not c:
            continue
        k = 120
        inv = [[r["d"], r["f"], r["i"], r.get("p"), r["c"]] for r in (d.get("rows") or [])[-5:]]   # 최근 5일 외국인·기관·개인 수량 + 종가
        (out_dir / f"{d['code']}.json").write_text(json.dumps({"d": c["dates"][-k:], "cap": c["cap"][-k:], "osc": c["osc"][-k:], "p": c["p"], "n": c["n"], "inv": inv},
                                                              separators=(",", ":")), encoding="utf-8")
        eok = lambda key: round(sum((x[key] or 0) * (x["c"] or 0) for x in inv5) / 1e8) if all(x.get(key) is not None for x in inv5) else None  # noqa: E731
        inv5 = (d.get("rows") or [])[-5:]
        summary[d["code"]] = [c["p"], c["as_of"], eok("f"), eok("i"), eok("p")]   # P · 기준일 · 5일 외국인·기관·개인 순매수(억, 수량×종가 추정)
    return summary


def main():
    ap = argparse.ArgumentParser(description="수급 오실레이터 (외국인+기관 순매수 ÷ 상장주식수, 6−22일 평균 차 + 3일 평활)")
    sp = ap.add_subparsers(dest="cmd", required=True)
    u = sp.add_parser("update"); u.add_argument("--all", action="store_true"); u.add_argument("--budget", type=int, help="최대 초 (넘으면 다음 회차에)")
    s = sp.add_parser("show"); s.add_argument("--stock", required=True)
    a = ap.parse_args()
    if a.cmd == "update":
        print(json.dumps(update(a.all, a.budget), ensure_ascii=False))
    else:
        f = FLOWS / f"{a.stock}.json"
        if not f.exists():
            raise SystemExit("캐시 없음 — 먼저 update")
        c = compute(json.loads(f.read_text()))
        print(json.dumps({k: c[k] for k in ("p", "last", "n", "as_of")} | {"recent": list(zip(c["dates"][-5:], c["osc"][-5:]))}, ensure_ascii=False))


if __name__ == "__main__":
    main()
