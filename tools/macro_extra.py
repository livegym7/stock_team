#!/usr/bin/env python3
"""전략 보고서 매크로 보강 (2026-11-20 사용자 확정, 토큰 0): '이익을 미리 알려 주는' 지표 세 가지.
  ① 한국 수출: 월간 수출 증가율·무역수지·수출물가(실제 vs 예상, TradingView 경제 캘린더) + 1~10일·1~20일·품목별은 뉴스 제목(2차 자료)
  ② 메모리 현물가: D램·낸드 (DRAMeXchange 첫 화면, 비공식) — 보고서 회차(토·수)마다 data/strategy/memory_hist.jsonl에 쌓아 1주·1개월 변화 계산
  ③ 유동성: 예탁금·신용잔고·반대매매 (금융투자협회, tools/macro_board.py가 모은 data/market/macro_board.json 재사용)

  python3 tools/macro_extra.py            # → data/market/macro_extra.json (strategy_tf.py prep · strategy_prep.py prep가 부름)

한계: 수출의 10일 단위·품목별 숫자는 관세청 공식 자료를 직접 받지 못해 뉴스 제목으로만 본다(숫자를 쓸 때 "출처: 뉴스 제목"으로 표시).
      메모리 가격은 현물가(소량 거래)라 고정거래가(대형 계약)와 다를 수 있다. 기록이 쌓이기 전에는 1주·1개월 변화가 비어 있다.
"""
import json, re, subprocess, sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import ROOT, http_get  # noqa: E402

KST = timezone(timedelta(hours=9))
OUT = ROOT / "data" / "market" / "macro_extra.json"
HIST = ROOT / "data" / "strategy" / "memory_hist.jsonl"   # data/strategy는 보고서 회차가 커밋함 (토·수 기록 → 1주·1개월 변화)
MEM = [("DDR5 16Gb (2Gx8) 4800/5600", "D램 DDR5 16Gb 현물"), ("DDR4 16Gb (2Gx8) 3200", "D램 DDR4 16Gb 현물"), ("DDR4 8Gb (1Gx8) 3200", "D램 DDR4 8Gb 현물"),
       ("DDR5 RDIMM 32GB 4800/5600", "서버 모듈 DDR5 RDIMM 32GB"), ("512Gb TLC", "낸드 웨이퍼 512Gb TLC"), ("256Gb TLC", "낸드 웨이퍼 256Gb TLC")]
EXP = {"Exports YoY": "수출 증가율(전년 대비)", "Balance of Trade": "무역수지(십억 달러)", "Export Prices YoY": "수출물가(전년 대비)", "Imports YoY": "수입 증가율(전년 대비)"}
NEWS_Q = ["관세청 1~10일 수출", "관세청 1~20일 수출", "월간 수출입동향 반도체 수출", "화장품 수출 월간"]


def exports():
    now = datetime.now(timezone.utc)
    d = json.loads(http_get("https://economic-calendar.tradingview.com/events", {
        "from": (now - timedelta(days=400)).strftime("%Y-%m-%dT00:00:00.000Z"), "to": (now + timedelta(days=20)).strftime("%Y-%m-%dT23:59:59.000Z"),
        "countries": "KR"}, timeout=20, headers={"Origin": "https://www.tradingview.com", "User-Agent": "Mozilla/5.0"}))
    ser = {}
    for x in d.get("result") or []:
        if x.get("title") in EXP:
            ser.setdefault(x["title"], []).append({"date": x["date"][:10], "period": x.get("period"), "actual": x.get("actual"), "forecast": x.get("forecast"), "previous": x.get("previous")})
    out = []
    for k, nm in EXP.items():
        L = sorted(ser.get(k) or [], key=lambda r: r["date"])
        done = [r for r in L if r["actual"] is not None]
        if done:
            out.append({"key": k, "name": nm, "last": done[-1], "series": [{"period": r["period"], "actual": r["actual"], "forecast": r["forecast"]} for r in done[-13:]],
                        "next": next((r["date"] for r in L if r["actual"] is None), None)})
    return {"rows": out, "source": "TradingView 경제 캘린더(비공식) · 원자료 산업통상자원부·한국은행 · 예상 = 시장 컨센서스"}


def export_news(hours=24 * 21):
    seen, out = set(), []
    for q in NEWS_Q:
        try:
            j = json.loads(subprocess.run([sys.executable, str(ROOT / "tools" / "news.py"), "search", "--query", q, "--hours", str(hours)], capture_output=True, text=True, timeout=60).stdout)
        except Exception:
            continue
        for it in ((j.get("results") or [{}])[0].get("items") or [])[:8]:
            t = re.sub(r"\s+-\s+[^-]+$", "", it.get("title") or "")
            if t and t not in seen and re.search(r"수출", t) and re.search(r"\d", t) and re.search(r"%|증가|감소|억|최대|급증|급감", t) and not re.search(r"청장|점검|격려|동정|제주|[가-힣]+(시|군|도) 수출", t):
                seen.add(t); out.append({"time": (it.get("time") or "")[:16], "press": it.get("press") if not str(it.get("press", "")).startswith("http") else "", "title": t, "q": q})
    out.sort(key=lambda r: r["time"], reverse=True)
    return {"items": out[:20], "source": "구글 뉴스 RSS 제목(2차 자료) — 관세청 10일 단위·품목별 수출은 공식 자료를 직접 받지 못해 제목으로만 봄"}


def memory():
    h = http_get("https://www.dramexchange.com/", timeout=25, headers={"User-Agent": "Mozilla/5.0"})
    if isinstance(h, bytes):
        h = h.decode("utf-8", "ignore")
    upd = re.search(r"Last Update:\s*([A-Za-z]+\.?\s*\d+\s+\d{4})", h)
    got = {}
    for m in re.finditer(r"<tr[^>]*>(.*?)</tr>", h, re.S):
        t = [re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", c)).strip() for c in re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", m.group(1), re.S)]
        if len(t) >= 7 and t[0] not in got:
            try:
                got[t[0]] = {"avg": float(t[5]), "chg": float(t[6].replace("%", "").strip())}
            except ValueError:
                pass
    today = datetime.now(KST).strftime("%Y-%m-%d")
    hist = [json.loads(x) for x in HIST.read_text(encoding="utf-8").splitlines() if x.strip()] if HIST.exists() else []
    row = {"date": today, "p": {k: got[k]["avg"] for k, _ in MEM if k in got}}
    if row["p"]:
        hist = [x for x in hist if x["date"] != today] + [row]
        HIST.parent.mkdir(parents=True, exist_ok=True)
        HIST.write_text("\n".join(json.dumps(x, ensure_ascii=False) for x in hist[-400:]) + "\n", encoding="utf-8")

    def back(k, days):
        cut = (datetime.now(KST) - timedelta(days=days)).strftime("%Y-%m-%d")
        old = [x for x in hist if x["date"] <= cut and k in x["p"]]
        return round((got[k]["avg"] / old[-1]["p"][k] - 1) * 100, 1) if old and old[-1]["p"][k] else None
    rows = [{"item": k, "name": nm, "usd": got[k]["avg"], "chg_pct": got[k]["chg"], "w1_pct": back(k, 7), "m1_pct": back(k, 30)} for k, nm in MEM if k in got]
    return {"rows": rows, "updated": upd.group(1) if upd else "", "hist_days": len(hist),
            "source": "DRAMeXchange 현물가 평균(달러, 비공식) · chg = 직전 회차 대비 · 1주·1개월 변화는 이 도구가 날마다 쌓은 기록 기준(쌓이기 전에는 빈칸)"}


def liquidity():
    j = json.loads((ROOT / "data" / "market" / "macro_board.json").read_text(encoding="utf-8")).get("liquidity") or {}
    last, pos, m1, d1 = j.get("last") or {}, j.get("pos") or {}, j.get("m1_pct") or {}, j.get("d1") or {}
    eok = lambda v: None if v is None else round(v / 10000, 1)   # 억 → 조  # noqa: E731
    return {"as_of": j.get("as_of"), "rows": [
        {"name": "고객 예탁금(조 원)", "now": eok(last.get("deposit")), "d1": eok(d1.get("deposit")), "m1_pct": m1.get("deposit"), "pos_1y": pos.get("deposit"), "read": "주식 살 대기 자금"},
        {"name": "신용융자 잔고(조 원)", "now": eok(last.get("credit")), "d1": eok(d1.get("credit")), "m1_pct": m1.get("credit"), "pos_1y": pos.get("credit"), "read": "빚내서 산 주식 — 높으면 급락 때 매물"},
        {"name": "예탁금 대비 신용(%)", "now": last.get("ratio"), "pos_1y": pos.get("ratio"), "read": "레버리지 정도"},
        {"name": "반대매매(억 원)", "now": last.get("forced"), "pos_1y": pos.get("forced"), "read": "강제 청산 — 급증 뒤 바닥이 나오기도 함"}],
        "source": "금융투자협회 종합통계(freesis) · 1년 위치 = 1년 최저 0% ~ 최고 100%"}


def build():
    def safe(f):
        try:
            return f()
        except Exception as e:
            return {"error": str(e)[:120]}
    o = {"made_at": datetime.now(KST).strftime("%Y-%m-%d %H:%M"), "exports": safe(exports), "export_news": safe(export_news), "memory": safe(memory), "liquidity": safe(liquidity)}
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(o, ensure_ascii=False, indent=1), encoding="utf-8")
    return o


if __name__ == "__main__":
    print(json.dumps(build(), ensure_ascii=False, indent=1))
