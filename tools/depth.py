#!/usr/bin/env python3
"""분석 깊이 모드 (2026-11-20 사용자 확정): config/depth.toml 의 mode(deep|lean) 값을 스킬이 읽는 창구.

  python3 tools/depth.py            # 지금 모드와 값 (JSON) — 스킬이 맨 처음 부른다
  python3 tools/depth.py set lean   # 절약형으로 (낮은 요금제). 예약 켜고 끄기는 docs/plan-modes.md
  python3 tools/depth.py set deep   # 깊이 모드로

deep = 리포트 전문 읽기·업종 노트 매일·채널 주장 검증·보유/관찰 풀 종목 메모·전략 보고서 업종 분석가 + 수요일 중간 점검
lean = 2026-11-19까지의 절약형 (카드 15건 핵심 구간만·깊이 읽기 3건 발췌·검증 없음)
"""
import json, re, sys, tomllib
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import ROOT  # noqa: E402

CONF = ROOT / "config" / "depth.toml"


def load():
    c = tomllib.loads(CONF.read_text(encoding="utf-8"))
    mode = c.get("mode", "lean")
    if mode not in ("lean", "deep"):
        mode = "lean"
    return {"mode": mode, **c.get(mode, {}), "triggers": c.get("triggers", {})}


def get(key, default=None):
    """다른 도구가 값 하나만 필요할 때."""
    try:
        return load().get(key, default)
    except Exception:
        return default


def main():
    if len(sys.argv) >= 3 and sys.argv[1] == "set":
        m = sys.argv[2]
        if m not in ("lean", "deep"):
            raise SystemExit("mode는 lean 또는 deep")
        s = CONF.read_text(encoding="utf-8")
        s2, n = re.subn(r'(?m)^mode\s*=\s*"[a-z]+"', f'mode = "{m}"', s, count=1)
        if not n:
            raise SystemExit("config/depth.toml 에 mode 줄이 없습니다")
        CONF.write_text(s2, encoding="utf-8")
        o = load()
        o["note"] = "예약 켜고 끄기는 docs/plan-modes.md 순서대로 (triggers.lean_only / deep_only)"
        print(json.dumps(o, ensure_ascii=False, indent=1)); return
    print(json.dumps(load(), ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
