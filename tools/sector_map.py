"""종목 업종 분류표 (사용자 분류: config/sector_map.csv의 custom 열, 53개 테마형 분류).

인더스트리 액션(같은 업종이 함께 움직였나)을 판단할 때 네이버 업종(79개)보다 이 분류를 먼저 쓴다.
신규 상장처럼 표에 없는 종목은 Claude가 추론해 채우고(출처에 'Claude 추론'), 애매하면 메모에 '확인 필요'를 달아
브리핑 끝에서 사용자에게 묻는다. 사용자가 엑셀로 직접 고쳐도 된다 (UTF-8, 첫 줄 제목 그대로).

사용법:
    python3 tools/sector_map.py check                 # 표에 없는 종목(시총 2천억↑ 우선) · 확인 필요 · 상장 목록에서 사라진 종목
    python3 tools/sector_map.py check --all           # 시총 상관없이 전부
    python3 tools/sector_map.py set --code 0158S0 --custom "IT/소프트웨어" --source "Claude 추론(...)" [--note "확인 필요"]
    python3 tools/sector_map.py groups                # custom 분류 목록과 종목 수
"""
import argparse
import csv
import json
from collections import Counter

from common import ROOT

PATH = ROOT / "config" / "sector_map.csv"
FIELDS = ["티커", "종목명", "wi26", "custom", "출처", "메모"]


def load_rows():
    if not PATH.exists():
        return []
    with open(PATH, encoding="utf-8-sig", newline="") as f:
        return [r for r in csv.DictReader(f) if r.get("티커")]


def save_rows(rows):
    with open(PATH, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k, "") for k in FIELDS})


def custom_map():
    """{코드: custom 분류}. 비어 있으면 빠짐."""
    return {r["티커"].zfill(6): r["custom"] for r in load_rows() if r.get("custom")}


def group_of(code, naver_industry=None, cmap=None):
    """인더스트리 액션용 그룹: 사용자 분류 → 없으면 네이버 업종."""
    cmap = custom_map() if cmap is None else cmap
    c = cmap.get(code)
    return ("custom", c) if c else ("naver", naver_industry or "기타")


def check(all_caps=False):
    from universe import load
    from backtest import is_etf
    uni = [s for s in load()["stocks"] if not is_etf(s["name"]) and s.get("industry") != "기타"]
    rows = load_rows()
    have = {r["티커"].zfill(6) for r in rows if r.get("custom")}
    listed = {s["code"] for s in load()["stocks"]}
    min_cap = 0 if all_caps else 2000
    missing = sorted([{"code": s["code"], "name": s["name"], "market": s["market"], "naver_industry": s["industry"],
                       "market_cap_eok": s["market_cap_eok"]} for s in uni
                      if s["code"] not in have and (s.get("market_cap_eok") or 0) >= min_cap],
                     key=lambda x: -(x["market_cap_eok"] or 0))
    unsure = [{"code": r["티커"], "name": r["종목명"], "custom": r["custom"], "note": r["메모"]} for r in rows if "확인 필요" in (r.get("메모") or "")]
    gone = [{"code": r["티커"], "name": r["종목명"]} for r in rows if r["티커"].zfill(6) not in listed]
    return {"total": len(rows), "groups": len({r["custom"] for r in rows if r.get("custom")}),
            "missing": missing, "unsure": unsure, "delisted_or_changed": len(gone), "delisted_sample": gone[:10],
            "how": "missing은 Claude가 사업 내용을 확인해 set으로 채운다(출처 'Claude 추론'). 애매하면 --note '확인 필요' 후 사용자에게 묻는다"}


def set_one(code, custom, wi26=None, source="Claude 추론", note=""):
    from universe import load
    code = code.zfill(6)
    rows = load_rows()
    name = next((s["name"] for s in load()["stocks"] if s["code"] == code), "")
    for r in rows:
        if r["티커"].zfill(6) == code:
            r.update({"custom": custom, "출처": source, "메모": note, "종목명": r["종목명"] or name})
            if wi26:
                r["wi26"] = wi26
            break
    else:
        rows.append({"티커": code, "종목명": name, "wi26": wi26 or "", "custom": custom, "출처": source, "메모": note})
    save_rows(rows)
    return {"code": code, "name": name, "custom": custom, "source": source, "note": note}


def main():
    p = argparse.ArgumentParser(description="종목 업종 분류표 (사용자 custom 분류)")
    sub = p.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("check")
    c.add_argument("--all", action="store_true")
    s = sub.add_parser("set")
    s.add_argument("--code", required=True)
    s.add_argument("--custom", required=True)
    s.add_argument("--wi26")
    s.add_argument("--source", default="Claude 추론")
    s.add_argument("--note", default="")
    sub.add_parser("groups")
    a = p.parse_args()
    if a.cmd == "check":
        out = check(a.all)
    elif a.cmd == "set":
        out = set_one(a.code, a.custom, a.wi26, a.source, a.note)
    else:
        out = dict(Counter(r["custom"] for r in load_rows() if r.get("custom")).most_common())
    print(json.dumps(out, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
