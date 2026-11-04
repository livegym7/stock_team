"""채널 실적 공시 글(잠정실적 양식)에서 실제 실적 vs 예상(컨센서스)을 뽑아 정리한다. Claude 없이 규칙으로만.

글 양식 예 (maddingStock 등):
  기업명: 심텍(222800) … 공시명: 연결재무제표기준영업(잠정)실적
  매출액: 5,359억(예상: 5,575억, -3.9%) | QoQ 4.2% | YoY 43.7%
  영업익: 1,018억(예상: 851억, 19.6%) | …
  ✦최근 실적 추이 … 2026.3Q | …
결과: data/earnings/latest.json (종목·분기별 1건, 처음 올라온 글 기준). 출처는 채널 요약(2차 자료).

사용법:
    python3 tools/earnings.py                 # 전체 다시 정리
    python3 tools/earnings.py --stock 심텍     # 한 종목 보기
"""
import argparse
import json
import re

from common import DATA

OUT = DATA / "earnings" / "latest.json"
NUM = r"(-?[\d,]+(?:\.\d+)?)\s*(조|억)"


def won_eok(v, unit):
    x = float(v.replace(",", ""))
    return round(x * 10000 if unit == "조" else x, 1)


def parse(text):
    m = re.search(r"기업명\s*[:：]\s*([^\s(]+)\((\d{6})\)", text)
    if not m or "실적" not in text[:400]:
        return None
    out = {"name": m.group(1), "code": m.group(2)}
    per = re.search(r"(20\d\d)\.([1-4])Q", text)
    out["period"] = f"{per.group(1)}.{per.group(2)}Q" if per else None
    for key, label in (("sales", "매출액"), ("op", "영업익"), ("net", "순이익")):
        r = re.search(label + r"\s*[:：]\s*" + NUM + r"(?:\s*\(예상\s*[:：]\s*" + NUM + r"\s*,\s*(-?[\d.]+)%\))?", text)
        if r:
            out[key] = won_eok(r.group(1), r.group(2))
            if r.group(3):
                out[key + "_est"] = won_eok(r.group(3), r.group(4))
                out[key + "_surprise"] = float(r.group(5))
            yy = re.search(label + r"[^\n]*?YoY\s*(-?[\d.]+)%", text)
            if yy:
                out[key + "_yoy"] = float(yy.group(1))
    if "op" not in out:
        return None
    s = out.get("op_surprise")
    out["verdict"] = None if s is None else ("서프라이즈" if s >= 10 else "쇼크" if s <= -10 else "부합")
    return out


def build():
    import tg_channel as t
    rows = {}
    for c in t.channels():
        for p in sorted(t.load_store(c["id"]).values(), key=lambda x: x["time"]):
            e = parse(p["text"])
            if not e:
                continue
            key = (e["code"], e["period"])
            if key in rows:      # 같은 공시는 먼저 올라온 글만
                continue
            e.update({"time": p["time"][:16].replace("T", " "), "channel": p["channel"], "url": p.get("url")})
            rows[key] = e
    data = sorted(rows.values(), key=lambda x: x["time"], reverse=True)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps({"rows": data, "source": "채널 실적 공시 요약(2차 자료) · 예상 = 글에 적힌 컨센서스"}, ensure_ascii=False, indent=1), encoding="utf-8")
    return data


def main():
    p = argparse.ArgumentParser(description="채널 실적 공시 정리")
    p.add_argument("--stock")
    a = p.parse_args()
    data = build()
    if a.stock:
        data = [x for x in data if x["name"] == a.stock]
    print(json.dumps({"n": len(data), "with_estimate": sum(1 for x in data if x.get("op_est") is not None),
                      "rows": data[:20]}, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
