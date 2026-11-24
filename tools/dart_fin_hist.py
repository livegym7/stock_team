#!/usr/bin/env python3
"""과거 분기 실적 붙이기 (토큰 0, 2026-11-23 사용자 요청): 백테스트 신호에 '그날 이미 발표돼 있던 실적'으로 펀더 점수를 매긴다.
DART 다중회사 주요계정(fnlttMultiAcnt)은 회사 하나에 0.6초쯤 걸려 전 종목·전 분기를 받을 수 없다(약 29시간). 그래서 **신호가 뜬 종목·그 시점의 보고서만** 받는다.
어느 보고서가 '그날 나와 있었나'는 법정 제출 기한으로 정한다(보수적 — 기한 전에 일찍 낸 보고서는 못 쓴 것으로 침):
  1/1~3/31 → 전년 3분기 · 4/1~5/15 → 전년 사업보고서 · 5/16~8/14 → 1분기 · 8/15~11/14 → 반기 · 11/15~12/31 → 3분기
  받은 보고서의 접수일(rcept_no 앞 8자리)이 신호일 이후면(늦게 냈거나 정정) '확인 불가'로 둔다.
보고서 한 장에 '당기'와 '전년 같은 기간' 값이 함께 있어 전년 대비를 그 보고서만으로 계산한다(사업보고서의 4분기는 연간 − 3분기 누적).
펀더 점수(0~3, 실전 strategy_tf의 펀더 점수와 같은 뜻 — 추정치 대신 발표된 실적):
  ① 최근 분기 영업이익 전년 대비 +20%↑ 또는 흑자전환 ② 최근 분기 영업이익률이 1년 전보다 높음 ③ 올해 누적 영업이익 전년 대비 +20%↑ 또는 흑자전환
책 기준 점수(book, 2026-11-23): 최근 분기 매출 · 영업이익 · 순이익이 각각 1년 전 같은 분기보다 늘었는가(문턱 없음, 흑자이면서 증가). 순이익은 EPS 대신 쓴다(주식 수 변화는 반영 못 함)
쓰는 곳: tools/backtest_long.py --fund. 필요한 환경 변수: DART_API_KEY
"""
import json, sys, time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import CACHE  # noqa: E402

DIR = CACHE / "dart_fin"
NAMES = CACHE / "dart_corp_names.json"
Q = {"11013": 1, "11012": 2, "11014": 3, "11011": 4}


def _n(v):
    try:
        return float(str(v).replace(",", ""))
    except Exception:
        return None


def report_for(day):
    """신호일(YYYYMMDD)에 나와 있었다고 볼 보고서 (연도, 보고서 코드)."""
    y, md = int(day[:4]), day[4:]
    if md <= "0331":
        return y - 1, "11014"
    if md <= "0515":
        return y - 1, "11011"
    if md <= "0814":
        return y, "11013"
    if md <= "1114":
        return y, "11012"
    return y, "11014"


def needs(signals):
    """[(code, day)] → {(year, rc): {code}} (사업보고서는 4분기 계산용으로 같은 해 3분기도)."""
    need = {}
    for code, day in signals:
        y, rc = report_for(day)
        need.setdefault((y, rc), set()).add(code)
        if rc == "11011":
            need.setdefault((y, "11014"), set()).add(code)
    return need


def _load(year, rc):
    f = DIR / f"{year}_{rc}.json"
    return json.loads(f.read_text()) if f.exists() else {}


def fetch(need, workers=3, log=print):
    """need의 (연도, 보고서)마다 아직 없는 종목만 받아 data/cache/dart_fin/연도_보고서.json에 합친다(이어 받기 가능). 자료가 없으면 null로 적어 다시 묻지 않는다."""
    import dart
    names = json.loads(NAMES.read_text())
    DIR.mkdir(parents=True, exist_ok=True)

    def one(key):
        year, rc = key
        have = _load(year, rc)
        todo = sorted(c for c in need[key] if c in names and (c not in have or (have[c] and have[c].get("v") != 2)))   # v2 = 순이익까지 받은 것
        for i in range(0, len(todo), 50):
            part = todo[i:i + 50]
            L = []
            for attempt in range(3):
                try:
                    L = dart.api_json("fnlttMultiAcnt.json", corp_code=",".join(names[c]["corp"] for c in part), bsns_year=str(year), reprt_code=rc).get("list", [])
                    break
                except SystemExit as e:
                    if "020" in str(e):
                        log(f"요청 한도 초과: {e}"); return key, -1
                    break
                except Exception:
                    time.sleep(3)
            res = {}
            for x in L:
                k = {"매출액": "s", "영업이익": "o"}.get(x.get("account_nm")) or ("n" if str(x.get("account_nm", "")).startswith("당기순이익") else None)
                if not k:
                    continue
                r = res.setdefault(x["stock_code"], {})
                fs = x.get("fs_div")
                if r.get("fs") == "CFS" and fs != "CFS":          # 연결이 있으면 연결만
                    continue
                if fs == "CFS" and r.get("fs") != "CFS":
                    r.clear()
                if k in r:                                         # 순이익은 같은 줄이 두 번 온다 → 첫 줄만
                    continue
                r.update({"fs": fs, "v": 2, "filed": x["rcept_no"][:8], k: _n(x.get("thstrm_amount")), k + "a": _n(x.get("thstrm_add_amount")),
                          "p" + k: _n(x.get("frmtrm_amount")), "p" + k + "a": _n(x.get("frmtrm_add_amount"))})
            for c in part:
                have[c] = res.get(c)
            (DIR / f"{year}_{rc}.json").write_text(json.dumps(have, ensure_ascii=False))
        log(f"{year} {rc}: +{len(todo)}종목 (모두 {len(have)})")
        return key, len(todo)
    with ThreadPoolExecutor(workers) as ex:
        return dict(ex.map(one, sorted(need)))


def _score(op, pop, sales, psales, ytd, pytd):
    pts, why = 0, []
    if op is not None and pop is not None:
        if pop <= 0 < op:
            pts += 1; why.append("분기 흑자전환")
        elif pop > 0 and op / pop - 1 >= 0.2:
            pts += 1; why.append(f"분기 영업이익 {round((op / pop - 1) * 100):+}%")
    if op is not None and pop is not None and sales and psales and sales > 0 and psales > 0 and op / sales > pop / psales:
        pts += 1; why.append("영업이익률 개선")
    if ytd is not None and pytd is not None:
        if pytd <= 0 < ytd:
            pts += 1; why.append("누적 흑자전환")
        elif pytd > 0 and ytd / pytd - 1 >= 0.2:
            pts += 1; why.append(f"누적 영업이익 {round((ytd / pytd - 1) * 100):+}%")
    return pts, why


_mem = {}


NEXT = {"11013": "11012", "11012": "11014", "11014": "11011"}


def next_report(day):
    """신호일 기준 '다음에 발표될' 보고서 (연도, 코드) — 컨센서스가 완벽히 맞았다고 칠 때의 최대치 비교용(미래 자료)."""
    y, rc = report_for(day)
    return (y + 1, "11013") if rc == "11011" else (y, NEXT[rc])


def needs_next(signals):
    need = {}
    for code, day in signals:
        y, rc = next_report(day)
        need.setdefault((y, rc), set()).add(code)
        if rc == "11011":
            need.setdefault((y, "11014"), set()).add(code)
    return need


def score_next(code, day):
    """다음에 발표될 분기 실적으로 매긴 점수(미래를 미리 본 값 — 실전에서는 쓸 수 없고, 컨센서스 효과의 최대치를 가늠하는 용도). 아직 안 나온 분기면 None."""
    y, rc = next_report(day)
    return _score_report(code, y, rc, None)


def score_at(code, day):
    """신호일에 나와 있던 보고서로 매긴 펀더 점수. 자료가 없거나 접수일이 신호일 이후면 None."""
    y, rc = report_for(day)
    return _score_report(code, y, rc, day)


def _score_report(code, y, rc, day):
    D = _mem.setdefault((y, rc), _load(y, rc))
    r = D.get(code)
    if not r or r.get("o") is None or not r.get("filed") or (day and r["filed"] >= day):
        return None
    if rc != "11011":
        op, pop, sales, psales = r.get("o"), r.get("po"), r.get("s"), r.get("ps")
        ytd, pytd = (r["oa"] if r.get("oa") is not None else op), (r["poa"] if r.get("poa") is not None else pop)
    else:
        c = _mem.setdefault((y, "11014"), _load(y, "11014")).get(code) or {}
        c = c if c.get("filed") else {}
        ytd, pytd = r.get("o"), r.get("po")
        if c.get("oa") is not None and c.get("poa") is not None and ytd is not None and pytd is not None:
            op, pop = ytd - c["oa"], pytd - c["poa"]
            sales = r["s"] - c["sa"] if r.get("s") is not None and c.get("sa") is not None else None
            psales = r["ps"] - c["psa"] if r.get("ps") is not None and c.get("psa") is not None else None
        else:
            op, pop, sales, psales = ytd, pytd, r.get("s"), r.get("ps")
    pts, why = _score(op, pop, sales, psales, ytd, pytd)
    # 책 기준(2026-11-23 사용자 확정): 매출·영업이익·순이익이 함께 늘었는가 — 숫자 문턱 없이 1년 전 같은 분기보다 늘면 통과(흑자전환·적자 축소 포함 안 함: 적자→적자는 통과 아님)
    if rc != "11011":
        net, pnet = r.get("n"), r.get("pn")
    else:
        net, pnet = r.get("n"), r.get("pn")
        if net is not None and pnet is not None and c.get("na") is not None and c.get("pna") is not None:
            net, pnet = net - c["na"], pnet - c["pna"]
    up = lambda a, b: None if a is None or b is None else (a > b and a > 0)  # noqa: E731
    book = {"sales": up(sales, psales), "op": up(op, pop), "net": up(net, pnet)}
    return {"pts": pts, "why": why, "book": book, "period": f"{y}Q{Q[rc]}", "filed": r["filed"]}
