"""주도 섹터 레이더: 업종(사용자 분류 custom 53개)별 점수를 매겨 '지금 돈이 몰리는 업종'을 찾는다.

점수 = 아래 5개 지표의 업종 간 순위(0~100)를 평균한 값
  1. 1개월 상대 강도: 업종 종목 1개월 수익률 중앙값 − 전체 중앙값
  2. 1주 상대 강도: 같은 방식, 1주
  3. 확산도: 업종 종목 중 20일선 위 비율
  4. 신고가: 최근 5일 안에 60일 신고가를 낸 종목 비율 (2026-11-25 사용자 확정: 신고가 탭·매매 보드와 같은 60일로 통일, 전에는 55일 — 기간은 screener.NH_DAYS)
  5. 돈의 쏠림: 업종 거래대금 최근 5일 평균 ÷ 직전 60일 평균
(지금 시점에는 채널 언급·리포트 상향 수를 참고로 붙인다 — 점수에는 넣지 않음)

대상: 시총 2천억↑ 개별 종목(ETF·코넥스 제외), 종목 4개 이상인 업종. 데이터: 네이버 일봉(백테스트 캐시 재사용).
레이더는 숫자만 제시한다. '주도 섹터'로 확정하는 것은 사용자 (config/leading.toml).

사용법:
    python3 tools/sector_radar.py                      # 오늘 기준 → data/radar/latest.json (최근 12주 주간 순위 포함)
    python3 tools/sector_radar.py --date 20260814      # 그날 기준 (검증용)
    python3 tools/sector_radar.py --history 20260701 20261031   # 기간 동안 주간 상위 5개 (검증용)
"""
import argparse
import json
import statistics
from collections import defaultdict
from datetime import datetime, timedelta

from common import DATA, ROOT, load_toml
from naver_quote import KST

OUT = DATA / "radar"


def load_data(source="daily"):
    """source='daily'면 감시 목록(screener)이 같은 날 받아 둔 일봉 캐시를 재사용, 'long'이면 백테스트용 3년치."""
    import backtest as B
    import screener as S
    from sector_map import custom_map
    from universe import load
    cmap = custom_map()
    uni = [s for s in load()["stocks"] if (s.get("market_cap_eok") or 0) >= 2000 and not B.is_etf(s["name"])
           and s.get("market") not in ("KONEX", "2")]
    data = {}
    for s in uni:
        rows = B.fetch_long(s["code"]) if source == "long" else S.fetch_daily(s["code"])
        if len(rows) >= 80:
            data[s["code"]] = {"name": s["name"], "group": cmap.get(s["code"]) or "네이버:" + s["industry"],
                               "rows": rows, "idx": {r["date"]: i for i, r in enumerate(rows)}}
    return data


def pct_rank(vals):
    """{키: 값} → {키: 0~100 순위}"""
    keys = sorted(vals, key=lambda k: vals[k])
    n = len(keys)
    return {k: round(i / (n - 1) * 100) if n > 1 else 50 for i, k in enumerate(keys)}


def score_on(data, day, min_members=4):
    per = {}
    from screener import NH_DAYS
    for code, d in data.items():
        i = d["idx"].get(day)
        if i is None or i < 65:
            continue
        r = d["rows"]
        c = [x["close"] for x in r]
        ma20 = sum(c[i - 19:i + 1]) / 20
        hi55 = [max(x["high"] for x in r[k - NH_DAYS:k]) for k in range(i - 4, i + 1)]
        nh = any(r[k]["close"] > hi55[j] for j, k in enumerate(range(i - 4, i + 1)))
        val5 = sum(x["close"] * x["volume"] for x in r[i - 4:i + 1]) / 5
        val60 = sum(x["close"] * x["volume"] for x in r[i - 64:i - 4]) / 60
        per[code] = {"r1m": c[i] / c[i - 21] - 1, "r1w": c[i] / c[i - 5] - 1, "above20": c[i] > ma20, "nh55": nh,
                     "val5": val5, "val60": val60}
    if not per:
        return []
    mkt1m = statistics.median(x["r1m"] for x in per.values())
    mkt1w = statistics.median(x["r1w"] for x in per.values())
    groups = defaultdict(list)
    for code, x in per.items():
        groups[data[code]["group"]].append(code)
    raw = {}
    for g, codes in groups.items():
        if len(codes) < min_members:
            continue
        xs = [per[c] for c in codes]
        raw[g] = {"n": len(codes),
                  "rel1m": statistics.median(x["r1m"] for x in xs) - mkt1m,
                  "rel1w": statistics.median(x["r1w"] for x in xs) - mkt1w,
                  "breadth": sum(x["above20"] for x in xs) / len(xs),
                  "newhigh": sum(x["nh55"] for x in xs) / len(xs),
                  "money": (sum(x["val5"] for x in xs) / max(1, sum(x["val60"] for x in xs)))}
    keys = ["rel1m", "rel1w", "breadth", "newhigh", "money"]
    ranks = {k: pct_rank({g: v[k] for g, v in raw.items()}) for k in keys}
    out = []
    for g, v in raw.items():
        sc = round(sum(ranks[k][g] for k in keys) / len(keys))
        top = sorted(groups[g], key=lambda c: -per[c]["r1m"])[:4]
        out.append({"group": g.replace("네이버:", ""), "score": sc, "n": v["n"],
                    "rel1m_pct": round(v["rel1m"] * 100, 1), "rel1w_pct": round(v["rel1w"] * 100, 1),
                    "breadth_pct": round(v["breadth"] * 100), "newhigh_pct": round(v["newhigh"] * 100),
                    "money_x": round(v["money"], 2),
                    "leaders": [{"name": data[c]["name"], "code": c, "r1m_pct": round(per[c]["r1m"] * 100, 1)} for c in top]})
    out.sort(key=lambda x: -x["score"])
    for i, x in enumerate(out):
        x["rank"] = i + 1
    return out


def fridays(data, start, end):
    days = sorted({d for x in data.values() for d in x["idx"] if start <= d <= end})
    out, wk = [], None
    for d in days:
        k = datetime.strptime(d, "%Y%m%d").isocalendar()[:2]
        if k != wk:
            out.append(d); wk = k
        else:
            out[-1] = d
    return out


def narrative(groups_top):
    """지금 시점 참고: 최근 7일 채널 언급 수·리포트 상향/하향 (업종별)."""
    try:
        import tg_channel as t
        from sector_map import custom_map
        from universe import load
        cmap = custom_map()
        ind = {s["code"]: cmap.get(s["code"]) or s["industry"] for s in load()["stocks"]}
        since = datetime.now(KST) - timedelta(days=7)
        cnt, up, down = defaultdict(int), defaultdict(int), defaultdict(int)
        for c in t.channels():
            for p in t.load_store(c["id"]).values():
                if p.get("dup_of") or datetime.fromisoformat(p["time"]) < since:
                    continue
                for st in p.get("stocks", [])[:3]:
                    g = ind.get(st["code"])
                    if g in groups_top:
                        cnt[g] += 1
                        if p["type"] == "report" and p.get("stock") == st["name"]:
                            up[g] += p.get("direction") == "상향"
                            down[g] += p.get("direction") == "하향"
        return {g: {"mentions_7d": cnt[g], "reports_up_7d": up[g], "reports_down_7d": down[g]} for g in groups_top}
    except Exception:
        return {}


def build(day=None, source="daily"):
    data = load_data(source)
    return _build(data, day)


def main():
    p = argparse.ArgumentParser(description="주도 섹터 레이더")
    p.add_argument("--date")
    p.add_argument("--history", nargs=2, metavar=("시작", "끝"))
    p.add_argument("--long", action="store_true", help="3년치 백테스트 캐시 사용 (검증용)")
    a = p.parse_args()
    data = load_data("long" if (a.long or a.history) else "daily")
    if a.history:
        for d in fridays(data, *a.history):
            top = score_on(data, d)[:5]
            print(d, " | ".join(f"{x['group']} {x['score']}" for x in top))
        return
    out = _build(data, a.date)
    print(json.dumps({"as_of": out["as_of"], "top": [(x["group"], x["score"], x["rel1m_pct"], x["breadth_pct"], x["newhigh_pct"], x["money_x"])
                                                     for x in out["groups"][:8]], "confirmed": out["confirmed"]}, ensure_ascii=False, indent=1))


def _build(data, day=None):
    days = sorted({d for x in data.values() for d in x["idx"]})
    day = day or days[-1]
    now = score_on(data, day)
    hist = []
    for d in fridays(data, (datetime.strptime(day, "%Y%m%d") - timedelta(days=84)).strftime("%Y%m%d"), day):
        sc = score_on(data, d)
        hist.append({"date": d, "top": [{"group": x["group"], "score": x["score"]} for x in sc[:5]],
                     "ranks": {x["group"]: x["rank"] for x in sc}})
    nar = narrative({x["group"] for x in now[:8]})
    for x in now:
        x.update(nar.get(x["group"], {}))
    try:
        leading = load_toml("leading.toml")
    except FileNotFoundError:
        leading = {}
    out = {"made_at": datetime.now(KST).strftime("%Y-%m-%d %H:%M"), "as_of": day, "groups": now, "history": hist,
           "confirmed": leading.get("sectors", []), "confirmed_at": leading.get("set_at"), "confirmed_note": leading.get("note", ""),
           "source": "네이버 일봉(비공식) · 업종 = 사용자 분류(custom) · 계산 Claude",
           "how": "점수 = 1개월·1주 상대 강도, 20일선 위 비율, 60일 신고가 비율, 거래대금 쏠림의 업종 간 순위 평균(0~100)"}
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "latest.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    return out


if __name__ == "__main__":
    main()
