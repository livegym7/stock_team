"""공시 요약 채널(darthacking 등) 거르기 (2026-11-16 사용자 확정, 토큰 0).

공시가 나오는 대로 모두 올라오는 채널이라 하루 수백 건이다. 모을 때 아래만 남기고 나머지는 저장하지 않는다.
  1) 우리 종목(보유·관찰 풀·핵심 후보) 공시 — 종류 상관없이
  2) 시총 2천억↑ + 실적 공시 중 영업이익이 예상치 대비 ±20% 이상
  3) 시총 2천억↑ + 촉매(공급계약·자사주·무상증자·합병 등) / 악재(유상증자·CB·BW·최대주주 변경·거래정지 등)
  4) 시총 2천억↑ + 대량보유 보고 중 '경영권' 목적 지분 증가
  5) 기업명 형식이 아닌 정리 글은 '어닝 서프라이즈'·'실적 발표 정리'만

python3 tools/disclosure_filter.py test --channel darthacking --days 4   # 최근 며칠 치로 시험 (저장 안 함)
"""
import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from common import CONFIG, load_toml

ROOT = Path(__file__).resolve().parent.parent
MIN_CAP_EOK = 2000
SURPRISE_PCT = 20   # 10%로 시험하니 실적 마감일에 하루 140건 → 20% (2026-11-16)

HEAD_RE = re.compile(r"기업명\s*:\s*(.+?)\s*\(\s*시가총액\s*:\s*([\d,]+조?\s*[\d,]*)\s*억?\s*\)")
REPORT_RE = re.compile(r"보고서명\s*:\s*(.+)")
OP_RE = re.compile(r"영업익\s*:\s*-?[\d,]+억\s*\(\s*예상치\s*:\s*-?[\d,]+억\s*,\s*([+-]?[\d.]+)%")

CATALYST = ("공급계약", "단일판매", "자기주식", "주식소각", "무상증자", "합병", "분할", "영업양수", "영업양도", "자산양수", "타법인주식", "투자판단")
RISK = ("유상증자", "전환사채", "신주인수권부사채", "교환사채", "최대주주변경", "최대주주 변경", "거래정지", "매매거래정지", "불성실공시", "감사의견", "관리종목", "상장폐지", "횡령", "배임", "회생")
SUMMARY = ("어닝 서프라이즈", "어닝서프라이즈", "실적 발표 정리")


def cap_eok(s):
    s = s.replace(",", "").replace(" ", "")
    if "조" in s:
        a, b = s.split("조", 1)
        return int(a or 0) * 10000 + int(b or 0)
    return int(s or 0)


def focus_names():
    """보유 + 관찰 풀 + 핵심 후보 이름 (live_brief.focus_names와 같은 범위, 파일에서 직접 읽음)"""
    n = set()
    for p in (load_toml("positions.toml") or {}).get("positions", []):
        if p.get("name"):
            n.add(p["name"])
    for th in (load_toml("watch_pool.toml") or {}).get("themes", []):
        n |= {x["name"] for x in th.get("stocks", []) if x.get("name")}
    try:
        core = json.loads((ROOT / "web" / "core.json").read_text(encoding="utf-8"))
        n |= {x["name"] for x in core.get("items", []) if x.get("core") and x.get("name")}
    except Exception:
        pass
    return {x for x in n if len(x) >= 2}


def judge(text, names):
    """(남길지, 이유) — 이유는 시험 출력·저장 글의 'why' 꼬리표에 씀"""
    h = HEAD_RE.search(text)
    if not h:
        return (any(k in text for k in SUMMARY), "정리 글" if any(k in text for k in SUMMARY) else "형식 아님")
    name, cap = h.group(1).strip(), cap_eok(h.group(2))
    rep = (REPORT_RE.search(text) or [None, ""])[1].strip() if REPORT_RE.search(text) else ""
    if name in names:
        return True, "우리 종목"
    if cap < MIN_CAP_EOK:
        return False, "소형주"
    if any(k in rep for k in RISK):
        return True, "악재 공시"
    if any(k in rep for k in CATALYST):
        return True, "촉매 공시"
    if "대량보유" in rep:
        up = re.search(r"보고전\s*:\s*([\d.]+)%.*?보고후\s*:\s*([\d.]+)%", text, re.S)
        if "경영권" in text and up and float(up.group(2)) > float(up.group(1)):
            return True, "경영권 지분 증가"
        return False, "대량보유(단순)"
    m = OP_RE.search(text)
    if m and abs(float(m.group(1))) >= SURPRISE_PCT:
        return True, "실적 " + ("서프라이즈" if float(m.group(1)) > 0 else "쇼크")
    return False, "실적 무난·예상치 없음" if ("보고서" in rep or "실적" in rep) else "기타 공시"


def op_pct(text):
    m = OP_RE.search(text or "")
    return float(m.group(1)) if m else None


def test(channel, days):
    import time
    from datetime import datetime, timedelta, timezone
    from tg_channel import fetch_page
    kst = timezone(timedelta(hours=9))
    since = (datetime.now(kst) - timedelta(days=days)).strftime("%Y-%m-%d")
    names, posts, before = focus_names(), {}, None
    for _ in range(80):
        page = fetch_page(channel, before)
        if not page:
            break
        for p in page:
            posts[p["id"]] = p
        before = min(p["id"] for p in page)
        if min(p["time"] for p in page)[:10] < since:
            break
        time.sleep(0.5)
    rows = [p for p in posts.values() if p["time"][:10] >= since]
    by_day, why_keep, why_drop, kept = Counter(), Counter(), Counter(), []
    for p in sorted(rows, key=lambda x: x["time"]):
        k, why = judge(p["text"], names)
        by_day[(p["time"][:10], k)] += 1
        (why_keep if k else why_drop)[why] += 1
        if k:
            kept.append({"time": p["time"][5:16], "why": why, "text": re.sub(r"\s+", " ", p["text"])[:110]})
    days_ = sorted({d for d, _ in by_day})
    print(json.dumps({"channel": channel, "since": since, "total": len(rows),
                      "by_day": {d: {"전체": by_day[(d, True)] + by_day[(d, False)], "남김": by_day[(d, True)]} for d in days_},
                      "keep_reasons": why_keep.most_common(), "drop_reasons": why_drop.most_common(),
                      "kept_sample": kept[-40:]}, ensure_ascii=False, indent=1))


def main():
    ap = argparse.ArgumentParser()
    sp = ap.add_subparsers(dest="cmd", required=True)
    t = sp.add_parser("test")
    t.add_argument("--channel", default="darthacking")
    t.add_argument("--days", type=int, default=4)
    a = ap.parse_args()
    if a.cmd == "test":
        test(a.channel, a.days)


if __name__ == "__main__":
    main()
