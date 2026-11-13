#!/usr/bin/env python3
"""신고가 모아보기 (2026-11-13 사용자 확정): 60일·200일 신고가 종목 · 업종 묶음 · 최근 20일 개수 흐름.

기준 (사용자 확정): 고가 기준(오늘 고가가 직전 N거래일 최고가를 넘으면), 시총 2천억↑(감시 목록 일봉 캐시 범위),
웹에만 표시(텔레그램 없음). 장 마감 확정 + 장중 20분마다(09:20~15:40, 깃허브 알림 작업) 참고용.

  python3 tools/new_highs.py eod                  # 일봉 캐시로 계산 → JSON (web_build가 D.highs로 넣음)
  python3 tools/new_highs.py base --out x.json    # 장중 비교용 기준선 (종목별 직전 60·200일 최고가, 20일 평균 거래량)
  python3 tools/new_highs.py live --base x.json --out y.json   # 장중: 네이버 현재가와 비교 (토큰 0)

Claude 토큰을 쓰지 않는다. 주문 기능 없음. 시세는 네이버(비공식).
"""
import argparse, json, sys, time
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import CACHE, DATA, http_get  # noqa: E402
from strategy_prep import KST  # noqa: E402

WINDOWS = (60, 200)
MIN_CAP = 2000   # 억 원
POLLING = "https://polling.finance.naver.com/api/realtime/domestic/stock/"


def universe_info():
    """{코드: {name, group, cap, rs, pool, held}} — 시총 2천억↑, ETF·스팩 제외."""
    from universe import load
    from sector_map import custom_map
    cmap = custom_map()
    try:
        from backtest import is_etf
    except Exception:
        is_etf = lambda n: False  # noqa: E731
    try:
        rs = json.loads((DATA / "radar" / "company_rs.json").read_text(encoding="utf-8"))
    except Exception:
        rs = {}
    pool, held = set(), set()
    try:
        from common import load_toml, positions
        for th in (load_toml("watch_pool.toml") or {}).get("themes", []):
            pool |= {s.get("code") for s in th.get("stocks", [])}
        held = {p.get("code") for p in positions()}
    except Exception:
        pass
    out = {}
    for s in load()["stocks"]:
        n, cap = s["name"], s.get("market_cap_eok") or 0
        if cap < MIN_CAP or is_etf(n) or "스팩" in n:
            continue
        c = s["code"]
        out[c] = {"name": n, "group": cmap.get(c) or s.get("industry") or "기타", "cap": cap,
                  "rs": (rs.get(c) or {}).get("rs"), "pool": c in pool, "held": c in held}
    return out


def rs_map(data):
    """{코드: RS 0~99} — screener.rs_raw(12·6·3개월 가중) 백분위, 일봉 캐시 전 종목 기준."""
    from screener import rs_raw
    raw = {c: rs_raw([r["close"] for r in rows]) for c, rows in data.items() if len(rows) >= 130}
    vals = sorted(v for v in raw.values() if v is not None)
    return {c: round(sum(1 for y in vals if y <= v) / len(vals) * 99) for c, v in raw.items() if v is not None} if vals else {}


def load_rows(code):
    f = CACHE / "daily" / f"{code}.json"
    if not f.exists():
        return None
    try:
        return json.loads(f.read_text())["rows"]
    except Exception:
        return None


def hit(rows, i, n):
    """i번째 봉의 고가가 직전 n봉 최고가를 넘었나."""
    if i < n:
        return False
    return rows[i]["high"] > max(r["high"] for r in rows[i - n:i])


def streak(rows, i, n, look=20):
    """최근 look봉 안에서 n일 신고가가 몇 번 나왔나 (오늘 포함)."""
    return sum(hit(rows, j, n) for j in range(max(n, i - look + 1), i + 1))


def eod():
    info = universe_info()
    items, hist = [], {}
    data = {c: r for c in info if (r := load_rows(c)) and len(r) >= 61}
    as_of = max((r[-1]["date"] for r in data.values()), default=None)
    stale = [c for c, r in data.items() if r[-1]["date"] != as_of]   # 캐시가 오래된 종목은 빼고 센다 (깃허브 16:40 갱신은 전 종목 새로 받음)
    rsm = rs_map({c: r for c, r in data.items() if c not in stale})
    for code, rows in data.items():
        if rows[-1]["date"] != as_of:
            continue
        s = info[code]
        i = len(rows) - 1
        for k in range(max(0, i - 19), i + 1):   # 최근 20일 개수 흐름
            d = rows[k]["date"]
            h = hist.setdefault(d, {"date": d, "n60": 0, "n200": 0})
            h["n60"] += hit(rows, k, 60)
            h["n200"] += hit(rows, k, 200)
        flags = [n for n in WINDOWS if hit(rows, i, n)]
        recent = [n for n in WINDOWS if any(hit(rows, j, n) for j in range(max(n, i - 4), i + 1))]
        if not recent:
            continue
        r, p = rows[i], rows[i - 1]
        v20 = sum(x["volume"] for x in rows[i - 20:i]) / 20 or 1
        hi250 = max(x["high"] for x in rows[-250:])
        items.append({"code": code, **s, "rs": rsm.get(code, s["rs"]), "date": r["date"], "close": r["close"], "high": r["high"],
                      "chg": round((r["close"] / p["close"] - 1) * 100, 2),
                      "vol_x": round(r["volume"] / v20, 2),
                      "today": flags, "recent5": recent,
                      "hold": r["close"] >= max(x["high"] for x in rows[i - 60:i]) if flags else None,   # 종가도 직전 60일 최고가 위
                      "count20": {str(n): streak(rows, i, n) for n in WINDOWS},
                      "to_52w": round((r["close"] / hi250 - 1) * 100, 1)})   # 52주 고점 대비 (0 = 고점)
    days = sorted(hist.values(), key=lambda h: h["date"])
    days = [h for h in days if h["date"] <= (as_of or "")][-20:]
    return {"as_of": as_of, "made_at": datetime.now(KST).strftime("%Y-%m-%d %H:%M"), "mode": "eod",
            "universe": len(data) - len(stale), "stale": len(stale), "items": items, "history": days, "groups": groups(items),
            "rule": "고가가 직전 N거래일 최고가를 넘은 종목 · 시총 2천억↑ · 네이버 일봉(비공식)"}


def groups(items):
    g = {}
    for x in items:
        if x["today"]:
            e = g.setdefault(x["group"], {"group": x["group"], "n60": 0, "n200": 0, "names": []})
            e["n60"] += 60 in x["today"]
            e["n200"] += 200 in x["today"]
            e["names"].append(x["name"])
    return sorted(g.values(), key=lambda e: (-e["n60"], -e["n200"]))[:15]


def base():
    """장중 비교용 기준선: 마지막 '완성된' 봉까지의 직전 60·200일 최고가."""
    info = universe_info()
    now = datetime.now(KST)
    today = now.strftime("%Y%m%d")
    closed = now.hour * 100 + now.minute >= 1540
    out = {}
    data = {c: r for c in info if (r := load_rows(c)) and len(r) >= 61}
    rsm = rs_map(data)
    for code, rows in data.items():
        s = info[code]
        if rows[-1]["date"] == today and not closed:   # 장중에 받은 미완성 오늘 봉은 뺀다
            rows = rows[:-1]
        out[code] = {"n": s["name"], "g": s["group"], "rs": rsm.get(code, s["rs"]), "p": int(s["pool"]), "h": int(s["held"]),
                     "h60": max(r["high"] for r in rows[-60:]), "h200": max(r["high"] for r in rows[-200:]) if len(rows) >= 200 else None,
                     "v20": round(sum(r["volume"] for r in rows[-20:]) / 20), "c": rows[-1]["close"], "d": rows[-1]["date"],
                     "hi250": max(r["high"] for r in rows[-250:])}
    return {"made_at": now.strftime("%Y-%m-%d %H:%M"), "stocks": out}


def vol_frac(now):
    """장 시작부터 지금까지 하루 거래량의 대략 몇 %가 지났나 (장 초반에 몰리는 모양을 단순 근사)."""
    m = (now.hour * 60 + now.minute) - 9 * 60
    return min(1.0, max(0.08, (max(m, 1) / 390) ** 0.7))


def live(base_path, out_path, prev_path=None):
    b = json.loads(Path(base_path).read_text(encoding="utf-8"))
    st = b["stocks"]
    now = datetime.now(KST)
    q, codes = {}, list(st)
    for i in range(0, len(codes), 100):
        try:
            d = json.loads(http_get(POLLING + ",".join(codes[i:i + 100])))
        except Exception:
            continue
        for x in d.get("datas", []):
            try:
                num = lambda k: float(str(x[k]).replace(",", ""))  # noqa: E731
                q[x["itemCode"]] = (num("closePrice"), num("highPrice"), num("accumulatedTradingVolume"), float(x["fluctuationsRatio"]))
            except Exception:
                pass
        time.sleep(0.2)
    prev = set()   # 직전 회차(같은 날) 목록 → 새로 들어온 종목 🆕
    try:
        pj = json.loads(Path(prev_path).read_text(encoding="utf-8")) if prev_path else {}
        if str(pj.get("made_at", ""))[:10] == now.strftime("%Y-%m-%d"):
            prev = {x["code"] for x in pj.get("items", [])}
    except Exception:
        pass
    f = vol_frac(now)
    items = []
    for code, s in st.items():
        if code not in q:
            continue
        price, high, vol, chg = q[code]
        flags = [n for n in WINDOWS if s.get(f"h{n}") and high > s[f"h{n}"]]
        if not flags:
            continue
        items.append({"code": code, "name": s["n"], "group": s["g"], "rs": s["rs"], "pool": bool(s["p"]), "held": bool(s["h"]),
                      "close": price, "high": high, "chg": chg, "vol_x": round(vol / (s["v20"] * f), 2) if s["v20"] else None,
                      "today": flags, "recent5": flags, "hold": price > s["h60"], "new": bool(prev) and code not in prev,
                      "to_52w": round((price / max(s["hi250"], high) - 1) * 100, 1)})
    o = {"made_at": now.strftime("%Y-%m-%d %H:%M"), "mode": "live", "quoted": len(q), "universe": len(st),
         "items": items, "groups": groups(items), "base_at": b["made_at"],
         "rule": "장중 참고: 오늘 고가가 직전 N거래일 최고가를 넘음 · 거래량 배수는 시간 보정 추정 · 네이버 현재가(비공식) 20분 간격"}
    Path(out_path).write_text(json.dumps(o, ensure_ascii=False), encoding="utf-8")
    if prev_path:
        Path(prev_path).write_text(json.dumps({"made_at": o["made_at"], "items": [{"code": x["code"]} for x in items]}), encoding="utf-8")
    return {"made_at": o["made_at"], "quoted": len(q), "n60": sum(60 in x["today"] for x in items), "n200": sum(200 in x["today"] for x in items)}


def main():
    ap = argparse.ArgumentParser(description="60·200일 신고가 모아보기")
    sp = ap.add_subparsers(dest="cmd", required=True)
    sp.add_parser("eod")
    b = sp.add_parser("base"); b.add_argument("--out", required=True)
    lv = sp.add_parser("live"); lv.add_argument("--base", required=True); lv.add_argument("--out", required=True)
    lv.add_argument("--force", action="store_true", help="장 시간이 아니어도 실행")
    lv.add_argument("--prev", help="직전 회차 목록 파일 (🆕 표시용, 실행 후 이번 목록으로 덮어씀)")
    a = ap.parse_args()
    if a.cmd == "eod":
        o = eod()
        print(json.dumps({k: o[k] for k in ("as_of", "universe")} | {"n": len(o["items"]), "today60": sum(60 in x["today"] for x in o["items"]),
                          "today200": sum(200 in x["today"] for x in o["items"]), "history": o["history"][-5:]}, ensure_ascii=False))
    elif a.cmd == "base":
        o = base()
        Path(a.out).write_text(json.dumps(o, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
        print(json.dumps({"made_at": o["made_at"], "stocks": len(o["stocks"])}, ensure_ascii=False))
    else:
        now = datetime.now(KST)
        hm = now.hour * 100 + now.minute
        if not a.force and (now.weekday() >= 5 or not 920 <= hm <= 1545):
            print(json.dumps({"skipped": "09:20~15:45 평일만", "at": now.strftime("%H:%M")}, ensure_ascii=False)); return
        print(json.dumps(live(a.base, a.out, a.prev), ensure_ascii=False))


if __name__ == "__main__":
    main()
