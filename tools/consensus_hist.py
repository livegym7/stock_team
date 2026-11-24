#!/usr/bin/env python3
"""컨센서스 추이 (토큰 0, 주문 기능 없음, 2026-11-24 사용자 요청): 증권사 추정치 평균이 달마다 어떻게 바뀌어 왔는지.

  python3 tools/consensus_hist.py fetch [--codes 192820,005930] [--signals] [--workers 3]   # 받아서 data/consensus/hist.json에 합침
  python3 tools/consensus_hist.py show --stock 192820
  python3 tools/consensus_hist.py at --stock 192820 --day 20260615                            # 그날 알 수 있었던 추정치와 1·3개월 변화

받는 것: 네이버 증권 종목분석(와이즈리포트) '컨센서스 추이' 그래프의 원자료(비공식) — 회계연도별 EPS·영업이익 추정치 평균, 월말 13개 점.
  올해·내년 회계연도는 최근 12개월, 지난 회계연도는 그해 2월~다음 해 2월까지 나온다(그보다 옛 연도는 주지 않음) → 지금은 2025-02부터.
저장: data/consensus/hist.json  {코드: {"fy_month": 12, "2025": {"d": [YYYYMMDD…], "op": […억 원], "eps": […원]}, "2026": {…}}}
  받을 때마다 날짜 기준으로 합치므로(지우지 않음) 날이 갈수록 길어진다. 증권사가 다루지 않는 종목은 빈 값.
쓰는 곳: 펀더 점수의 '기대가 올라가는 중인가'(strategy_tf) · 컨센서스 백테스트(backtest_long.py --cons).
"""
import argparse, json, sys, time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import CACHE, DATA, http_get  # noqa: E402
from naver_quote import KST  # noqa: E402

FILE = DATA / "consensus" / "hist.json"
BASE = "https://navercomp.wisereport.co.kr"
URL = BASE + "/company/ajax/cF5002.aspx?cmp_cd={c}&dt={dt}&yymm={ym}&frq=Y&acc_cd=121500&fingubun=MAIN&chartType=svg"


def load():
    try:
        return json.loads(FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _fy_month(code):
    """회계연도 끝 달 (네이버 재무 캐시의 연간 기간 표기 '2026.12'에서). 모르면 12."""
    try:
        A = json.loads((CACHE / "fund" / f"{code}.json").read_text()).get("annual") or []
        return int(A[-1]["p"][5:7])
    except Exception:
        return 12


def _one(code, year, month, today):
    raw = http_get(URL.format(c=code, dt=today, ym=f"{year}{month:02d}"), headers={"Referer": f"{BASE}/v2/company/c1050001.aspx?cmp_cd={code}", "User-Agent": "Mozilla/5.0"}, timeout=15)
    d = json.loads(raw)
    e, o = json.loads(d["chart1"]), json.loads(d["chart2"])
    if not o.get("categories") or o.get("item_name") != "영업이익":
        return None
    days = [x.replace("/", "") for x in o["categories"]]
    eps = dict(zip([x.replace("/", "") for x in e.get("categories") or []], e.get("avg") or [])) if e.get("item_name") == "EPS" else {}
    return {"d": days, "op": o["avg"], "eps": [eps.get(x) for x in days]}


def _merge(old, new):
    m = {d: (o, e) for d, o, e in zip(old.get("d", []), old.get("op", []), old.get("eps", []))} if old else {}
    for d, o, e in zip(new["d"], new["op"], new["eps"]):
        m[d] = (o, e)
    ds = sorted(m)
    return {"d": ds, "op": [m[d][0] for d in ds], "eps": [m[d][1] for d in ds]}


def fetch(codes, workers=3, log=print):
    H, now = load(), datetime.now(KST)
    today, y = now.strftime("%Y%m%d"), now.year

    def one(code):
        fm, out = _fy_month(code), {}
        for yr in (y - 1, y, y + 1):
            try:
                r = _one(code, yr, fm, today)
            except Exception:
                r = None
            if r:
                out[str(yr)] = r
            time.sleep(0.25)
        return code, fm, out
    n = 0
    with ThreadPoolExecutor(workers) as ex:
        for code, fm, out in ex.map(one, codes):
            cur = H.setdefault(code, {"fy_month": fm})
            cur["fy_month"] = fm
            for yr, r in out.items():
                cur[yr] = _merge(cur.get(yr), r)
            cur["at"] = today
            n += 1
            if n % 100 == 0:
                log(f"{n}/{len(codes)}")
                FILE.parent.mkdir(parents=True, exist_ok=True)
                FILE.write_text(json.dumps(H, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    FILE.parent.mkdir(parents=True, exist_ok=True)
    FILE.write_text(json.dumps(H, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    return {"stocks": len(codes), "with_data": sum(1 for c in codes if any(k.isdigit() for k in H.get(c, {})))}


def _val(s, day, back=0):
    """day 이전(포함) 가장 가까운 점에서 back개 앞의 (날짜, 영업이익, EPS)."""
    if not s:
        return None
    k = max((i for i, d in enumerate(s["d"]) if d <= day), default=None)
    if k is None or k - back < 0:
        return None
    return s["d"][k - back], s["op"][k - back], s["eps"][k - back]


def at(code, day, H=None):
    """그날 알 수 있었던 추정치: 그 회계연도(fy)와 직전 연도(prev_fy)의 영업이익·EPS 추정치, 1개월·3개월 전 대비 변화(%).
    회계연도 = day가 속한 해(12월 결산 기준, 결산 달이 다르면 그 달까지를 한 해로). 직전 연도는 발표 전이면 추정치, 발표 뒤면 마지막 추정치(실제에 가까움)."""
    h = (H or load()).get(code)
    if not h:
        return None
    fm = h.get("fy_month", 12)
    fy = int(day[:4]) + (1 if int(day[4:6]) > fm else 0)
    s, p = h.get(str(fy)), h.get(str(fy - 1))
    cur = _val(s, day)
    if not cur or cur[1] is None:
        return None
    out = {"fy": fy, "as_of": cur[0], "op": cur[1], "eps": cur[2]}
    for name, back in (("m1", 1), ("m3", 3)):
        b = _val(s, day, back)
        out["op_" + name] = round((cur[1] / b[1] - 1) * 100, 1) if b and b[1] and b[1] > 0 else None
        out["eps_" + name] = round((cur[2] / b[2] - 1) * 100, 1) if b and b[2] and cur[2] is not None and b[2] > 0 else None
    pv = _val(p, day) or (p and (p["d"][-1], p["op"][-1], p["eps"][-1]) if p and p["d"][0] > day else None)
    if pv:
        out["prev_op"], out["prev_eps"] = pv[1], pv[2]
    return out


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="컨센서스 추이 (네이버 증권·와이즈리포트, 비공식)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    f = sub.add_parser("fetch"); f.add_argument("--codes"); f.add_argument("--signals", action="store_true", help="백테스트 신호 종목(최근 2년)도 함께"); f.add_argument("--workers", type=int, default=3)
    s = sub.add_parser("show"); s.add_argument("--stock", required=True)
    a = sub.add_parser("at"); a.add_argument("--stock", required=True); a.add_argument("--day", required=True)
    g = ap.parse_args()
    if g.cmd == "fetch":
        if g.codes:
            codes = g.codes.split(",")
        else:
            codes = {p.stem for p in (CACHE / "fund").glob("[0-9A-Z]*.json")}
            if g.signals:
                for name in ("long_cand_vol_10y.json", "long_cand_zone_10y.json"):
                    try:
                        codes |= {t["code"] for t in json.loads((CACHE / name).read_text())["cand"] if t["date"] >= "20250201"}
                    except Exception:
                        pass
            codes = sorted(codes)
        print(json.dumps(fetch(codes, g.workers), ensure_ascii=False))
    elif g.cmd == "show":
        print(json.dumps(load().get(g.stock), ensure_ascii=False, indent=1))
    else:
        print(json.dumps(at(g.stock, g.day), ensure_ascii=False, indent=1))
