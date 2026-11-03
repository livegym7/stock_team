"""감시 목록 만들기 (저녁 실행): 시총 2,000억↑ 종목을 훑어 공통 관문 → 셋업 판정 → 돌파 기준가·알림가·1R 계산.

규칙은 docs/setups.md. 숫자는 아래 RULES에 모아 두었다 (사용자 확정값 표시).
데이터: 네이버 일봉(수정주가) 1년치를 종목마다 1번 받는다 (약 1,100번 호출, 몇 분 걸림).
같은 날 다시 실행하면 data/cache/daily/에 받아 둔 것을 쓴다.

사용법:
    python3 tools/screener.py                    # 전체 훑기 → data/bus/오늘/screener.json + 요약 출력
    python3 tools/screener.py --stock 005930     # 한 종목만 자세히 (판정 확인용)
    python3 tools/screener.py --send             # 끝나고 텔레그램으로 감시 목록 보내기

장중에 실행하면 오늘 봉이 아직 확정되지 않은 값이다. 저녁(장마감 후) 실행이 기준.
판정은 규칙 대입 결과일 뿐 매수·매도 추천이 아니다.
"""
import argparse
import json
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from common import CACHE, DATA, ROOT, http_get
from universe import load as load_universe

KST = timezone(timedelta(hours=9))
SISE = "https://api.finance.naver.com/siseJson.naver"

RULES = {
    "min_mcap_eok": 2000,       # 사용자 확정
    "min_value_eok": 100,       # 20일 평균 하루 거래대금, 사용자 확정
    "max_off_high": -50,        # 52주 고점 대비 %, 사용자 확정
    "min_rs": 70,               # RS 백분위 [책]
    "min_stage1": 50,           # 1stage 상승률 % [책]
    "max_giveback": 50,         # 조정이 1stage 상승분의 몇 %까지 [책]
    "min_base_days": 5,         # 조정 최소 1주, 사용자 확정
    "breakout_vol": 1.5,        # 돌파 거래량 (50일 평균 대비) [기본값]
    "alert_gap": 0.02,          # 알림가 = 기준가 -2% [책]
    "one_r": 0.08,              # 1R = 손절 8%, 사용자 확정 (책 예시는 7%)
    "ma": (20, 60, 120),        # 정배열 이평선 [기본값]
}


# ---------- 데이터 ----------
def fetch_daily(code, days=400):
    """일봉 1년여치. 같은 날 받은 캐시가 있으면 그걸 쓴다. 거래정지일(가격 0)은 뺀다."""
    now = datetime.now(KST)
    today = now.strftime("%Y%m%d")
    path = CACHE / "daily" / f"{code}.json"
    if path.exists():
        d = json.loads(path.read_text())
        got = datetime.fromisoformat(d["fetched_at"]) if "fetched_at" in d else None
        # 같은 날 받은 것만 재사용. 단 장마감(15:40) 전에 받은 건 오늘 봉이 미완성이라, 장마감 뒤에는 새로 받는다
        closed = now.replace(hour=15, minute=40, second=0, microsecond=0)
        if got and got.strftime("%Y%m%d") == today and (got >= closed or now < closed):
            return d["rows"]
    start = (datetime.now(KST) - timedelta(days=int(days * 1.5))).strftime("%Y%m%d")
    for attempt in range(3):
        try:
            raw = http_get(SISE, {"symbol": code, "requestType": 1, "timeframe": "day",
                                  "startTime": start, "endTime": today}).decode("utf-8", "replace")
            break
        except Exception:
            if attempt == 2:
                return []
            time.sleep(2)
    rows = []
    for line in re.findall(r"\[\"(\d{8})\",\s*([^\]]+)\]", raw):
        vals = [float(x) for x in line[1].split(",")[:5]]
        o, h, l, c, v = vals
        if o and h and l and c:
            rows.append({"date": line[0], "open": o, "high": h, "low": l, "close": c, "volume": v})
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"fetched_at": now.isoformat(timespec="seconds"), "rows": rows}))
    return rows


# ---------- 계산 도우미 ----------
def sma(a, n, end=None):
    end = len(a) if end is None else end
    return sum(a[end - n:end]) / n if end >= n else None


def ret(c, n):
    return c[-1] / c[-1 - n] - 1 if len(c) > n else None


def weekly_closes(rows):
    out, key = [], None
    for r in rows:
        d = date(int(r["date"][:4]), int(r["date"][4:6]), int(r["date"][6:]))
        k = d.isocalendar()[:2]
        if k == key:
            out[-1] = r["close"]
        else:
            out.append(r["close"]); key = k
    return out


def volume_zones(rows, nb=40):
    """거래대금 매물대: 평균의 1.5배 넘는 가격 칸을 붙여서 구간으로 (chart.py와 같은 방식)."""
    lo, hi = min(r["low"] for r in rows), max(r["high"] for r in rows)
    if hi <= lo:
        return []
    step = (hi - lo) / nb
    b = [0.0] * nb
    for r in rows:
        a, c = r["low"], r["high"]
        for i in range(max(0, int((a - lo) / step)), min(nb, int((c - lo) / step) + 1)):
            ov = min(c, lo + (i + 1) * step) - max(a, lo + i * step)
            if ov > 0 and c > a:
                b[i] += r["volume"] * (a + c) / 2 * ov / (c - a)
    avg = sum(b) / nb
    zones, cur = [], None
    for i in range(nb):
        if b[i] >= 1.5 * avg:
            if cur and i == cur[1] + 1:
                cur[1] = i
            else:
                cur = [i, i]; zones.append(cur)
    return [(round(lo + a * step), round(lo + (z + 1) * step)) for a, z in zones]


def swing_pullbacks(h, l, start, k=3):
    """start(피벗) 이후 고점→저점 되돌림 폭(%)들을 순서대로. 고점·저점은 앞뒤 k일 안 최고·최저."""
    n = len(h)
    highs = [i for i in range(start, n) if h[i] == max(h[max(start, i - k):min(n, i + k + 1)])]
    out = []
    for j, i in enumerate(highs):
        nxt = highs[j + 1] if j + 1 < len(highs) else n
        if nxt - i < 2:
            continue
        lo = min(l[i:nxt])
        out.append(round((1 - lo / h[i]) * 100, 1))
    return out


# ---------- 판정 ----------
def analyze(rows):
    """마지막 봉 기준으로 베이스(조정 구간)와 셋업을 판정한다."""
    h = [r["high"] for r in rows]; l = [r["low"] for r in rows]
    c = [r["close"] for r in rows]; v = [r["volume"] for r in rows]
    n = len(rows)
    out = {}
    # 피벗 = 그 뒤로 한 번도 넘지 못한 가장 최근의 의미 있는 고점(앞뒤 10일 최고)이면서 베이스가 1주 이상
    piv = None
    for i in range(n - 1 - RULES["min_base_days"], max(0, n - 260), -1):
        if h[i] == max(h[max(0, i - 10):i + 11]) and h[i] >= max(h[i:]):
            piv = i
            break
    hi52 = max(h[-250:])
    if piv is None:
        out["base"] = None  # 계속 신고가를 내는 중이라 쉬는 구간이 아직 없음 = 1stage 진행 중
        out["run_pct"] = round((c[-1] / min(l[-250:]) - 1) * 100)
        out["setups"] = []
        return out
    pivot = h[piv]
    lo1 = min(l[max(0, piv - 250):piv + 1])
    base_low = min(l[piv:])
    base_days = n - 1 - piv
    stage1 = (pivot / lo1 - 1) * 100
    depth = (1 - base_low / pivot) * 100
    giveback = (pivot - base_low) / (pivot - lo1) * 100 if pivot > lo1 else 100
    pulls = swing_pullbacks(h, l, piv)
    vol10, vol50 = sma(v, 10), sma(v, 50)
    out["base"] = {
        "pivot": round(pivot), "pivot_date": rows[piv]["date"], "days": base_days, "low": round(base_low),
        "depth_pct": round(depth, 1), "stage1_pct": round(stage1), "giveback_pct": round(giveback),
        "pullbacks": pulls, "vol_dryup": round(vol10 / vol50, 2) if vol50 else None,
        "is_52w_high": pivot >= hi52,
    }
    setups = []
    ok_base = base_days >= RULES["min_base_days"] and giveback <= RULES["max_giveback"]
    if ok_base:
        setups.append("A")  # 박스·깃발: 건전한 조정 (가장 넓은 정의)
    # B 컵 앤 핸들: 컵 7~65주, 깊이 12~33%, 바닥이 가운데쯤, 오른쪽 회복 후 손잡이
    if 35 <= base_days <= 325 and 12 <= depth <= 33:
        low_i = piv + l[piv:].index(base_low)
        if 0.2 <= (low_i - piv) / base_days <= 0.8:
            r_i = low_i + h[low_i:].index(max(h[low_i:]))
            handle_days = n - 1 - r_i
            handle_depth = (1 - min(l[r_i:]) / h[r_i]) * 100
            if h[r_i] >= pivot * 0.85 and 5 <= handle_days <= 25 and handle_depth <= min(15, depth / 2):
                setups.append("B")
                out["handle_high"] = round(h[r_i])
    # C VCP: 되돌림 2번 이상 연속 감소, 마지막 한 자릿수, 거래량 감소
    if len(pulls) >= 2 and all(pulls[i] < pulls[i - 1] for i in range(len(pulls) - 2, len(pulls))) \
            and pulls[-1] < 10 and vol10 and vol50 and vol10 < vol50:
        setups.append("C")
    # D HTF: 피벗 전 40일 안에 +100%, 조정 5~15일, 깊이 20% 이내
    lo40 = min(l[max(0, piv - 40):piv + 1])
    if pivot / lo40 >= 2 and 5 <= base_days <= 15 and depth <= 20:
        setups.append("D")
    # E 신고가 대기: 피벗이 52주 고점이고 5% 이내까지 올라옴
    if out["base"]["is_52w_high"] and c[-1] >= pivot * 0.95:
        setups.append("E")
    # F 로우 치트: 베이스 아래쪽 40% 안에서 최근 5일 폭 6% 이내로 쉬는 중
    pos = (c[-1] - base_low) / (pivot - base_low) if pivot > base_low else 1
    rng5 = max(h[-5:]) / min(l[-5:]) - 1
    if ok_base and pos <= 0.4 and rng5 <= 0.06:
        setups.append("F")
        out["low_cheat_trigger"] = round(max(h[-5:]))
    out["setups"] = setups
    return out


def today_events(rows, prev):
    """오늘 봉에서 일어난 일: 돌파 / 포켓 피봇 / 이벤트. prev = 어제까지로 판정한 analyze 결과."""
    c = [r["close"] for r in rows]; v = [r["volume"] for r in rows]
    t = rows[-1]
    ev = []
    vol50 = sma(v, 50, len(v) - 1)
    vr = t["volume"] / vol50 if vol50 else None
    base = prev.get("base")
    if base and t["close"] > base["pivot"] and vr and vr >= RULES["breakout_vol"]:
        ev.append("돌파")
    # G 포켓 피봇: 상승일 거래량 > 직전 10일 하락일 최대 거래량, 10일선 근처
    downs = [v[i] for i in range(len(v) - 11, len(v) - 1) if c[i] < c[i - 1]]
    ma10 = sma(c, 10)
    if c[-1] > c[-2] and downs and t["volume"] > max(downs) and ma10 and 0.97 <= c[-1] / ma10 <= 1.05:
        ev.append("G")
    if c[-1] / c[-2] - 1 >= 0.05 and vr and vr >= 2:
        ev.append("H")
    return ev, (round(vr, 2) if vr else None)


def gate(rows, info, rs):
    c = [r["close"] for r in rows]
    a, b, d = RULES["ma"]
    m = [sma(c, a), sma(c, b), sma(c, d)]
    wc = weekly_closes(rows)
    w10, w30 = sma(wc, 10), sma(wc, 30)
    value20 = sum(r["close"] * r["volume"] for r in rows[-20:]) / 20 / 1e8
    off_high = (c[-1] / max(r["high"] for r in rows[-250:]) - 1) * 100
    checks = {
        "정배열(일봉)": bool(m[2] and c[-1] > m[0] > m[1] > m[2]),
        "정배열(주봉)": bool(w30 and wc[-1] > w10 > w30),
        "RS": rs is not None and rs >= RULES["min_rs"],
        "고점 위치": off_high >= RULES["max_off_high"],
        "시총": info["market_cap_eok"] >= RULES["min_mcap_eok"],
        "거래대금": value20 >= RULES["min_value_eok"],
    }
    return checks, {"value20_eok": round(value20), "off_high_pct": round(off_high, 1)}


def rs_raw(c):
    """12M 20% / 6M 30% / 3M 50% 가중 수익률 [책]. 1년이 안 된 종목은 None."""
    r12, r6, r3 = ret(c, 249), ret(c, 125), ret(c, 62)
    if r12 is None:
        return None
    return 0.2 * r12 + 0.3 * r6 + 0.5 * r3


def run(codes_info, workers=4):
    def one(s):
        rows = fetch_daily(s["code"])
        time.sleep(0.2)
        return s, rows
    with ThreadPoolExecutor(workers) as ex:
        data = [x for x in ex.map(one, codes_info) if len(x[1]) >= 130]
    raws = {s["code"]: rs_raw([r["close"] for r in rows]) for s, rows in data}
    vals = sorted(x for x in raws.values() if x is not None)
    pct = lambda x: None if x is None else round(sum(1 for y in vals if y <= x) / len(vals) * 99)
    companies = json.loads((DATA / "companies.json").read_text(encoding="utf-8"))
    results = []
    for s, rows in data:
        rs = pct(raws[s["code"]])
        checks, extra = gate(rows, s, rs)
        a = analyze(rows)
        prev = analyze(rows[:-1])
        ev, vr = today_events(rows, prev)
        stage1 = a["base"]["stage1_pct"] if a.get("base") else a.get("run_pct", 0)
        stage1_ok = stage1 >= RULES["min_stage1"]
        checks["1stage 상승"] = stage1_ok
        card = companies.get(s["code"])
        item = {
            "stock": s["name"], "code": s["code"], "market": s["market"],
            "sector": f"{card['sector']} > {card['detail']}" if card else s["industry"],
            "close": rows[-1]["close"], "date": rows[-1]["date"], "rs": rs, **extra,
            "checks": checks, "gate_pass": all(checks.values()), "gate_score": sum(checks.values()),
            "setups": a.get("setups", []), "run_pct": a.get("run_pct"), "base": a.get("base"), "today": ev, "vol_ratio": vr,
            "stage": "1stage 진행 중" if not a.get("base") else "2stage 조정 중",
        }
        b = a.get("base")
        if b:
            pivot = a.get("handle_high", b["pivot"])
            item["levels"] = {
                "breakout": pivot, "alert": round(pivot * (1 - RULES["alert_gap"])),
                "stop_1r": round(pivot * (1 - RULES["one_r"])),
                "distance_pct": round((pivot / rows[-1]["close"] - 1) * 100, 1),
            }
            if "low_cheat_trigger" in a:
                item["levels"]["low_cheat_trigger"] = a["low_cheat_trigger"]
            above = [z for z in volume_zones(rows[-250:]) if z[1] > rows[-1]["close"]]
            item["overhead_zone"] = above[0] if above else None
        results.append(item)
    return results


def grade(it):
    core = set(it["setups"]) & set("ABCDE")
    if it["gate_pass"] and ("돌파" in it["today"] and core or "G" in it["today"]):
        return "✅"  # 업종 동반 여부는 장중 감시에서 🔥로 올린다
    if it["gate_pass"] and (core or "F" in it["setups"]):
        d = (it.get("levels") or {}).get("distance_pct")
        return "👀" if d is not None and d <= RULES["alert_gap"] * 100 else "대기"
    return None


SETUP_NAMES = {"A": "박스", "B": "컵핸들", "C": "VCP", "D": "HTF", "E": "신고가", "F": "로우치트", "G": "포켓피봇", "H": "이벤트"}
CSS = """
*{box-sizing:border-box} body{margin:0;background:#fff;color:#1b1f24;font-family:'Noto Sans CJK KR','Noto Sans KR','WenQuanYi Zen Hei',sans-serif;font-size:15px;width:%dpx}
.wrap{padding:18px 20px} h1{font-size:21px;margin:0 0 4px} .sub{color:#6b7280;font-size:13px}
.funnel{display:flex;gap:6px;margin:10px 0 4px;font-size:13px} .funnel span{background:#f1f3f6;border-radius:999px;padding:3px 10px} .funnel b{color:#d62728}
h2{font-size:16px;margin:18px 0 6px} table{width:100%%;border-collapse:collapse}
th{font-size:12px;color:#6b7280;font-weight:normal;text-align:right;padding:5px 6px;border-bottom:2px solid #e5e7eb;white-space:nowrap}
th:first-child,th.l{text-align:left} td{padding:7px 6px;border-bottom:1px solid #eef0f3;text-align:right;white-space:nowrap;font-variant-numeric:tabular-nums}
td.l{text-align:left} .nm{font-weight:700} .sec{display:block;font-size:11px;color:#6b7280;max-width:230px;overflow:hidden;text-overflow:ellipsis}
.pill{font-size:12px;padding:2px 8px;border-radius:999px;background:#f1f3f6} .sig{background:#fde8e8;color:#d62728;font-weight:700} .near{background:#fff3e0;color:#b45309;font-weight:700}
tr.hot td{background:#fff8f0} .bar{display:inline-block;width:60px;height:7px;background:#eef0f3;border-radius:4px;vertical-align:middle;margin-left:6px;overflow:hidden} .bar i{display:block;height:7px;background:#e8833a}
.st{display:inline-block;font-size:11px;border:1px solid #cbd5e1;border-radius:4px;padding:0 4px;margin-left:2px} .up{color:#d62728} .dn{color:#1f5fbf}
.legend{margin-top:14px;font-size:12px;color:#6b7280;line-height:1.7} .foot{margin-top:8px;font-size:11px;color:#9aa3ad}
"""


def _pill(r):
    g = grade(r)
    if g == "✅":
        return '<span class="pill sig">✅ 신호</span>'
    lv = r.get("levels") or {}
    if lv and r["close"] >= lv["alert"]:
        return '<span class="pill near">👀 임박</span>'
    return '<span class="pill">대기</span>'


def render_html(results, as_of, width=900):
    watch = sorted((r for r in results if r["gate_pass"] and (r["setups"] or r["today"]) and r.get("levels")),
                   key=lambda r: r["levels"]["distance_pct"])
    running = sorted((r for r in results if r["gate_pass"] and r["stage"] == "1stage 진행 중"), key=lambda r: -(r["rs"] or 0))
    near = sorted((r for r in results if r["gate_score"] == 6 and not r["gate_pass"]), key=lambda r: -(r["rs"] or 0))
    d = f"{as_of[:4]}-{as_of[4:6]}-{as_of[6:]}"
    h = [f"<!doctype html><meta charset='utf-8'><style>{CSS % width}</style><div class='wrap'>",
         f"<h1>📋 감시 목록</h1><div class='sub'>{d} 종가 기준 · 출처: 네이버 증권 일봉(수정주가) · 시총 2,000억↑</div>",
         f"<div class='funnel'><span>훑은 종목 {len(results):,}</span><span>→ 관문 통과 <b>{sum(r['gate_pass'] for r in results)}</b></span>"
         f"<span>→ 셋업 <b>{len(watch)}</b></span><span>1stage 진행 중 <b>{len(running)}</b></span></div>"]
    rows_n = 0
    if watch:
        h.append("<h2>📍 내일 알림 걸 가격 <span class='sub'>(기준가 가까운 순)</span></h2><table><tr><th>상태</th><th class='l'>종목 · 섹터</th>"
                 "<th>현재가</th><th>알림가</th><th>기준가</th><th>남은 거리</th><th>1R 손절</th><th class='l'>셋업</th><th>RS</th></tr>")
        for r in watch[:20]:
            lv = r["levels"]
            dist = lv["distance_pct"]
            fill = max(0, min(100, 100 - dist * 4))  # 0%면 꽉 참, 25% 이상이면 빈 막대
            setups = "".join(f"<span class='st'>{x} {SETUP_NAMES[x]}</span>" for x in r["setups"])
            setups += "".join(f"<span class='st up'>오늘 {SETUP_NAMES.get(x, x)}</span>" for x in r["today"])
            hot = " class='hot'" if grade(r) == "✅" or r["close"] >= lv["alert"] else ""
            h.append(f"<tr{hot}><td class='l'>{_pill(r)}</td><td class='l'><span class='nm'>{r['stock']}</span><span class='sec'>{r['sector']}</span></td>"
                     f"<td>{r['close']:,.0f}</td><td>{lv['alert']:,}</td><td><b>{lv['breakout']:,}</b></td>"
                     f"<td>{'+' if dist >= 0 else ''}{dist}%<span class='bar'><i style='width:{fill:.0f}%'></i></span></td>"
                     f"<td class='dn'>{lv['stop_1r']:,}</td><td class='l'>{setups or '-'}</td><td>{r['rs']}</td></tr>")
            rows_n += 1
        h.append("</table>")
    else:
        h.append("<h2>📍 내일 알림 걸 가격</h2><div class='sub'>관문을 모두 통과한 셋업 종목이 없습니다.</div>")
    if running:
        h.append("<h2>🚀 1stage 진행 중 <span class='sub'>(신고가 행진 · 조정에 들어가면 감시 대상)</span></h2><table>"
                 "<tr><th class='l'>종목 · 섹터</th><th>현재가</th><th>1년 저점 대비</th><th>고점 대비</th><th>거래대금(20일)</th><th>RS</th></tr>")
        for r in running[:10]:
            h.append(f"<tr><td class='l'><span class='nm'>{r['stock']}</span><span class='sec'>{r['sector']}</span></td><td>{r['close']:,.0f}</td>"
                     f"<td class='up'>+{r.get('run_pct') or 0}%</td><td>{r['off_high_pct']}%</td><td>{r['value20_eok']:,}억</td><td>{r['rs']}</td></tr>")
            rows_n += 1
        h.append("</table>")
    if near:
        h.append("<h2>🔸 관문 1개 부족 <span class='sub'>(RS 순, 상위 8)</span></h2><table><tr><th class='l'>종목 · 섹터</th><th>현재가</th><th class='l'>부족한 조건</th><th>RS</th></tr>")
        for r in near[:8]:
            miss = ", ".join(k for k, ok in r["checks"].items() if not ok)
            h.append(f"<tr><td class='l'><span class='nm'>{r['stock']}</span><span class='sec'>{r['sector']}</span></td><td>{r['close']:,.0f}</td>"
                     f"<td class='l'>{miss}</td><td>{r['rs']}</td></tr>")
            rows_n += 1
        h.append("</table>")
    h.append("<div class='legend'>셋업: A 박스·깃발 · B 컵앤핸들 · C VCP · D HTF · E 신고가 대기 · F 로우치트 · G 포켓피봇 · H 거래량 터진 장대양봉<br>"
             "알림가 = 기준가 -2% · 1R 손절 = 기준가 -8% · RS = 시총 2,000억↑ 종목 중 시장 대비 강도 순위(99가 최고)</div>"
             "<div class='foot'>규칙 대입 결과이며 매수·매도 추천이 아닙니다. 차트를 직접 확인하고 판단은 본인이 합니다.</div></div>")
    sections = sum(1 for x in (watch, running, near) if x)
    height = 150 + sections * 75 + rows_n * 47 + 110
    return "\n".join(h), height


def caption(results, as_of):
    watch = sorted((r for r in results if r["gate_pass"] and (r["setups"] or r["today"]) and r.get("levels")),
                   key=lambda r: r["levels"]["distance_pct"])
    sig = [r for r in watch if grade(r) == "✅"]
    lines = [f"📋 감시 목록 ({as_of[4:6]}/{as_of[6:]} 종가) · 셋업 {len(watch)}개"]
    if sig:
        lines.append("✅ 오늘 신호: " + ", ".join(r["stock"] for r in sig))
    if watch:
        lines.append("기준가 가까운 순: " + ", ".join(f"{r['stock']}(+{r['levels']['distance_pct']}%)" for r in watch[:3]))
    lines.append("※ 추천 아님, 판단은 본인")
    return "\n".join(lines)


def message(results, as_of):
    watch = [r for r in results if r["gate_pass"] and (r["setups"] or r["today"])]
    watch.sort(key=lambda r: (r.get("levels") or {}).get("distance_pct", 99))
    today = [r for r in watch if grade(r) == "✅"]
    lines = [f"📋 감시 목록 ({as_of} 종가 기준, 출처: 네이버 일봉)",
             f"훑은 종목 {len(results)}개 → 관문 통과 {sum(r['gate_pass'] for r in results)}개 → 셋업 {len(watch)}개", ""]
    if today:
        lines.append("✅ 오늘 신호")
        for r in today:
            lines.append(f"- {r['stock']} {r['close']:,.0f} · {'/'.join(r['today'])} · 거래량 {r['vol_ratio']}배 · {r['sector']}")
        lines.append("")
    lines.append("📍 내일 알림 걸 가격 (기준가 가까운 순)")
    for r in watch[:20]:
        lv = r.get("levels") or {}
        if not lv:
            continue
        tag = "임박 " if r["close"] >= lv["alert"] else ""
        setup = ",".join(r["setups"]) or "없음(오늘 " + "/".join(r["today"]) + ")"
        lines.append(f"- {tag}{r['stock']} 현재 {r['close']:,.0f} → 알림 {lv['alert']:,} / 기준 {lv['breakout']:,} (+{lv['distance_pct']}%) "
                     f"· 셋업 {setup} · RS {r['rs']} · {r['sector']}")
    if not watch:
        near = sorted((r for r in results if r["gate_score"] >= 6), key=lambda r: -(r["rs"] or 0))[:10]
        lines.append("- 없음 (관문을 모두 통과한 셋업 종목이 없음)")
        if near:
            lines += ["", "관문 1개 부족한 종목 (RS 순)"]
            for r in near:
                miss = [k for k, ok in r["checks"].items() if not ok]
                lines.append(f"- {r['stock']} RS {r['rs']} · 부족: {', '.join(miss)} · {r['sector']}")
    running = sorted((r for r in results if r["gate_pass"] and r["stage"] == "1stage 진행 중"), key=lambda r: -(r["rs"] or 0))
    if running:
        lines += ["", f"🚀 1stage 진행 중 (신고가 행진, 조정 들어가면 감시 대상) {len(running)}개"]
        lines += [f"- {r['stock']} RS {r['rs']} · 1년 저점 대비 +{r.get('run_pct', '?')}% · {r['sector']}" for r in running[:10]]
    lines += ["", "※ 규칙 대입 결과이며 추천이 아닙니다. 판단은 본인이 합니다."]
    return "\n".join(lines)


def main():
    p = argparse.ArgumentParser(description="감시 목록 만들기 (추세추종 셋업 스크리너)")
    p.add_argument("--stock", help="한 종목만 (종목코드)")
    p.add_argument("--send", action="store_true", help="텔레그램으로 감시 목록 보내기")
    p.add_argument("--workers", type=int, default=4)
    a = p.parse_args()

    uni = load_universe()["stocks"]
    from backtest import is_etf  # ETF·ETN은 개별 종목이 아니라 감시 목록에서 뺀다 (2026-11-03)
    pool = [s for s in uni if s["market_cap_eok"] >= RULES["min_mcap_eok"] and not is_etf(s["name"])
            and not re.search(r"우$|우B$|우\(|스팩|리츠|ETN", s["name"])]
    if a.stock:
        # RS 백분위를 매기려면 비교 대상이 필요하므로 전체를 쓰되 (캐시 활용) 한 종목만 출력
        res = [r for r in run(pool, a.workers) if r["code"] == a.stock]
        print(json.dumps(res, ensure_ascii=False, indent=1))
        return
    t0 = time.time()
    results = run(pool, a.workers)
    as_of = max(r["date"] for r in results)
    out_dir = ROOT / "data" / "bus" / datetime.now(KST).strftime("%Y-%m-%d")
    out_dir.mkdir(parents=True, exist_ok=True)
    payload = {"source": "네이버 일봉 (비공식)", "as_of": as_of, "made_at": datetime.now(KST).isoformat(timespec="seconds"),
               "rules": RULES, "count": len(results),
               "watch": [r for r in results if r["gate_pass"] and (r["setups"] or r["today"])],
               "running": sorted((r for r in results if r["gate_pass"] and r["stage"] == "1stage 진행 중"),
                                 key=lambda r: -(r["rs"] or 0)),
               "near_miss": sorted((r for r in results if r["gate_score"] == 6 and not r["gate_pass"]),
                                   key=lambda r: -(r["rs"] or 0))[:30]}
    (out_dir / "screener.json").write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
    msg = message(results, as_of)
    print(msg)
    print(f"\n[{len(results)}종목, {time.time() - t0:.0f}초, 저장: {(out_dir / 'screener.json').relative_to(ROOT)}]", file=sys.stderr)
    rep_dir = ROOT / "reports" / datetime.now(KST).strftime("%Y-%m-%d")
    rep_dir.mkdir(parents=True, exist_ok=True)
    html, height = render_html(results, as_of)
    (rep_dir / "watchlist.html").write_text(html, encoding="utf-8")
    from render import html_to_png
    png = rep_dir / "watchlist.png"
    ok = html_to_png(rep_dir / "watchlist.html", png, 900, height)
    print(f"[표 그림: {png.relative_to(ROOT) if ok else '만들지 못함 (크롬 없음) → 글로 보냄'}]", file=sys.stderr)
    if a.send:
        from telegram_send import send, send_photo
        if ok:
            send_photo(png, caption(results, as_of))
        else:
            send(msg)


if __name__ == "__main__":
    main()
