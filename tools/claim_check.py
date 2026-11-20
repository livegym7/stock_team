#!/usr/bin/env python3
"""채널 주장 검증 기록 (깊이 모드, 2026-11-20 사용자 확정). 채널 글은 2차 자료라, 중요한 주장을 1차 자료(공시·뉴스·시세)와 대조한 결과를 쌓는다.

  python3 tools/claim_check.py add --channel 채널 --claim "주장 한 줄" --verdict 확인|미확인|틀림 --source "DART 11/20 단일판매 공시" [--stock 종목] [--post 글번호] [--note 한 줄]
  python3 tools/claim_check.py stats [--days 30]     # 채널별 확인·미확인·틀림 건수와 확인 비율 (참고용 성적표)
  python3 tools/claim_check.py recent [--days 3]     # 최근 검증 목록 (정리·체크포인트가 다시 검증하지 않도록)

verdict: 확인 = 1차 자료와 숫자·사실이 맞음 / 미확인 = 1차 자료를 못 찾음(틀렸다는 뜻이 아님) / 틀림 = 1차 자료와 다름(무엇이 다른지 note에)
저장: data/telegram/claims.jsonl (한 줄에 한 건). 성적표는 표본이 적을 때 우연이 크다 — 채널마다 20건 넘게 쌓인 뒤에 본다.
"""
import argparse, json, sys
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import ROOT  # noqa: E402
from strategy_prep import KST  # noqa: E402

LOG = ROOT / "data" / "telegram" / "claims.jsonl"
VERDICTS = ("확인", "미확인", "틀림")


def rows(days=None):
    if not LOG.exists():
        return []
    R = [json.loads(x) for x in LOG.read_text(encoding="utf-8").splitlines() if x.strip()]
    if days:
        since = (datetime.now(KST) - timedelta(days=days)).strftime("%Y-%m-%d")
        R = [r for r in R if r.get("at", "") >= since]
    return R


def add(a):
    if a.verdict not in VERDICTS:
        raise SystemExit(f"verdict는 {' / '.join(VERDICTS)}")
    if a.verdict != "미확인" and not (a.source or "").strip():
        raise SystemExit("확인·틀림은 --source(1차 자료 이름·날짜)가 있어야 합니다")
    if not 6 <= len(a.claim) <= 160:
        raise SystemExit("claim은 6~160자 한 줄")
    r = {"at": datetime.now(KST).strftime("%Y-%m-%d %H:%M"), "channel": a.channel, "claim": a.claim.strip(), "verdict": a.verdict,
         "source": (a.source or "").strip(), "stock": a.stock or "", "post": a.post or "", "note": (a.note or "").strip()}
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with LOG.open("a", encoding="utf-8") as f:
        f.write(json.dumps(r, ensure_ascii=False) + "\n")
    return {"saved": True, "total": len(rows())}


def stats(days):
    by = {}
    for r in rows(days):
        b = by.setdefault(r["channel"], {v: 0 for v in VERDICTS})
        b[r["verdict"]] = b.get(r["verdict"], 0) + 1
    out = []
    for ch, b in by.items():
        n = sum(b.values()); known = b["확인"] + b["틀림"]
        out.append({"channel": ch, "n": n, **b, "confirm_pct": round(b["확인"] / known * 100) if known else None,
                    "note": "표본 적음(20건 미만)" if n < 20 else ""})
    out.sort(key=lambda x: -x["n"])
    return {"days": days, "total": sum(x["n"] for x in out), "channels": out,
            "source": "data/telegram/claims.jsonl · 확인 비율 = 확인 ÷ (확인 + 틀림), 미확인은 뺌 · 참고용"}


def main():
    ap = argparse.ArgumentParser(); sp = ap.add_subparsers(dest="cmd", required=True)
    p = sp.add_parser("add")
    for k in ("channel", "claim", "verdict"):
        p.add_argument("--" + k, required=True)
    for k in ("source", "stock", "post", "note"):
        p.add_argument("--" + k)
    p = sp.add_parser("stats"); p.add_argument("--days", type=int, default=30)
    p = sp.add_parser("recent"); p.add_argument("--days", type=int, default=3)
    a = ap.parse_args()
    o = add(a) if a.cmd == "add" else stats(a.days) if a.cmd == "stats" else rows(a.days)
    print(json.dumps(o, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
