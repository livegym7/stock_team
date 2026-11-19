"""업종 지도 발자취 (2026-11-19 사용자 요청, 토큰 0): 업종별 강도 점수·순위를 지난 60거래일 다시 계산해 궤적·날짜 되감기·추이 표 재료를 만든다.

  세로축 = 강도 점수(sector_radar.score_on, 가격·거래대금만으로 계산 → 과거 날짜도 똑같이 다시 계산됨)
  가로축 = 올해 영업이익 증가율(strategy_tf.daily_market의 matrix) — 과거 값이 따로 없어 지금 값으로 고정
  분면 = strategy_tf.quad 와 같은 문턱(이익 +20% · 강도 65)

python3 tools/sector_track.py          # → data/market/sector_track.json
"""
import json
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from common import DATA
from naver_quote import KST

DAYS = 60


def build(matrix=None):
    import new_highs
    import sector_radar as R
    import strategy_tf as T
    daily, uni = T._daily(), new_highs.universe_info()
    data = {c: {"name": uni[c]["name"], "group": uni[c]["group"] or "기타", "rows": rows, "idx": {r["date"]: i for i, r in enumerate(rows)}}
            for c, rows in daily.items() if c in uni and len(rows) >= 80}
    dates = [r["date"] for r in daily["KOSPI"]][-DAYS:]
    if matrix is None:
        matrix = T.daily_market()["matrix"]
    fund = {m["group"]: m for m in matrix}
    G = {}
    used = []
    for d in dates:
        sc = R.score_on(data, d)
        if not sc:
            continue
        used.append(d)
        for x in sc:
            G.setdefault(x["group"], {})[d] = [x["score"], x["rank"], x["breadth_pct"], x["rel1m_pct"]]
    cnt = {d: sum(1 for by in G.values() if d in by) for d in used}   # 일봉이 덜 받아진 날(업종 수가 평소의 80% 미만)은 뺌
    used = [d for d in used if cnt[d] >= 0.8 * max(cnt.values())]
    groups = []
    for g, by in G.items():
        f = fund.get(g) or {}
        groups.append({"group": g, "opg": f.get("opg"), "n_fund": f.get("n_fund"), "n": f.get("n"),
                       "pts": [by.get(d) for d in used]})   # 날짜마다 [점수, 순위, 20일선 위 %, 시장 대비 1개월 %] (없으면 null)
    out = {"made_at": datetime.now(KST).strftime("%Y-%m-%d %H:%M"), "dates": used, "xq": T.XQ, "yq": T.YQ, "groups": groups,
           "source": "네이버 일봉(비공식)으로 다시 계산 · 이익 증가율은 지금 값(네이버 재무·컨센서스)으로 고정"}
    p = DATA / "market" / "sector_track.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(out, ensure_ascii=False), encoding="utf-8")
    return out


if __name__ == "__main__":
    o = build()
    g = next((x for x in o["groups"] if "후공정" in x["group"]), o["groups"][0])
    print(json.dumps({"dates": [o["dates"][0], o["dates"][-1], len(o["dates"])], "groups": len(o["groups"]),
                      "sample": {"group": g["group"], "opg": g["opg"], "first": g["pts"][0], "last": g["pts"][-1]}}, ensure_ascii=False))
