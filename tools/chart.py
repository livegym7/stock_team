"""주봉 캔들 + 매물대(가격대별 거래대금) 겹친 차트. 표준 라이브러리로 SVG를 만들고, 가능하면 PNG로도 바꾼다.

매물대는 캔들 뒤에 연하게 깔아서 캔들을 가리지 않게 한다. 거래가 가장 많은 3칸만 조금 진하게 + 점선(붙어 있으면 한 구간으로 표시).
매물대 계산: 하루 거래대금을 그날 고가~저가 사이에 고르게 나눠 가격 칸에 쌓는다 (일봉 기준 근사).
주식 '수량'이 아니라 '금액' 기준이다 (수량으로 하면 가격이 쌌던 시기가 부풀려짐).

사용법:
    python3 tools/chart.py                         # 관심종목(국내) 전체
    python3 tools/chart.py --stock 005930
    python3 tools/chart.py --days 400 --profile-days 250 --out reports/2026-11-02/charts

PNG 변환은 Chromium + Playwright(node)가 있을 때만 한다. 없으면 SVG만 만든다.
"""
import argparse
import json
import subprocess
import time
from datetime import date, datetime
from pathlib import Path

from common import ROOT
from naver_quote import KST, daily, targets

W, H, L, R, T, B = 1000, 580, 80, 110, 56, 120   # 그림 크기와 여백
NB = 48                                           # 매물대 가격 칸 수
PROFILE_MAX = 0.40                                # 매물대 막대 최대 길이 (차트 폭 대비)


def weekly(rows):
    out = []
    for r in rows:
        d = date(int(r["date"][:4]), int(r["date"][4:6]), int(r["date"][6:]))
        k = d.isocalendar()[:2]
        if out and out[-1]["k"] == k:
            w = out[-1]
            w["h"] = max(w["h"], r["high"]); w["l"] = min(w["l"], r["low"]); w["c"] = r["close"]; w["v"] += r["volume"]
        else:
            out.append({"k": k, "d": r["date"], "o": r["open"], "h": r["high"], "l": r["low"], "c": r["close"], "v": r["volume"]})
    return out


def profile(rows, lo, hi, nb=NB):
    step = (hi - lo) / nb
    bins = [0.0] * nb
    for r in rows:
        a, b = r["low"], r["high"]
        if b <= a:
            bins[min(nb - 1, int((a - lo) / step))] += r["volume"] * r["close"]
            continue
        for i in range(max(0, int((a - lo) / step)), min(nb, int((b - lo) / step) + 1)):
            ov = min(b, lo + (i + 1) * step) - max(a, lo + i * step)
            if ov > 0:
                bins[i] += r["volume"] * (a + b) / 2 * ov / (b - a)
    return bins, step


def build_svg(name, code, rows, profile_days):
    wk = weekly(rows)
    lo = min(w["l"] for w in wk) * 0.97
    hi = max(w["h"] for w in wk) * 1.02
    ph = H - T - B
    y = lambda p: T + (hi - p) / (hi - lo) * ph
    cw = (W - L - R) / len(wk)
    bins, step = profile(rows[-profile_days:], lo, hi)
    mx = max(bins) or 1
    top = sorted(range(NB), key=lambda i: -bins[i])[:3]
    last = rows[-1]["close"]
    s = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" font-family="Noto Sans KR, WenQuanYi Zen Hei, sans-serif">',
         f'<rect width="{W}" height="{H}" fill="#fff"/>',
         f'<text x="{L}" y="26" font-size="19" font-weight="bold">{name} ({code}) 주봉 + 매물대</text>',
         f'<text x="{L}" y="45" font-size="12" fill="#666">캔들 {rows[0]["date"]}~{rows[-1]["date"]} · 매물대 최근 {profile_days}거래일 거래대금 · 출처: 네이버 증권 일봉(수정주가) · 만든 시각 {datetime.now(KST):%Y-%m-%d %H:%M}</text>']
    for k in range(6):  # 가격 눈금
        p = lo + (hi - lo) * k / 5
        s.append(f'<line x1="{L}" x2="{W-R}" y1="{y(p):.1f}" y2="{y(p):.1f}" stroke="#f0f0f0"/>'
                 f'<text x="{L-6}" y="{y(p)+4:.1f}" font-size="11" text-anchor="end" fill="#777">{p:,.0f}</text>')
    # 매물대: 캔들 뒤에 연하게, 오른쪽 끝에서 왼쪽으로
    bh = ph / NB
    for i in range(NB):
        bw = bins[i] / mx * (W - L - R) * PROFILE_MAX
        strong = i in top
        s.append(f'<rect x="{W-R-bw:.1f}" y="{y(lo+(i+1)*step):.1f}" width="{bw:.1f}" height="{max(1, bh-1):.1f}" '
                 f'fill="{"#f0a35e" if strong else "#a9bfd8"}" opacity="{0.32 if strong else 0.18}"/>')
    for i in top:
        p = lo + (i + 0.5) * step
        s.append(f'<line x1="{L}" x2="{W-R}" y1="{y(p):.1f}" y2="{y(p):.1f}" stroke="#e8833a" stroke-dasharray="3 5" opacity="0.35"/>')
    # 주봉 캔들 + 거래량 (매물대 위에 그림)
    vmax = max(w["v"] for w in wk) or 1
    for j, w in enumerate(wk):
        x = L + j * cw + cw / 2
        col = "#d62728" if w["c"] >= w["o"] else "#1f5fbf"
        y1, y2 = sorted([y(w["o"]), y(w["c"])])
        vh = w["v"] / vmax * (B - 34)
        s.append(f'<line x1="{x:.1f}" x2="{x:.1f}" y1="{y(w["h"]):.1f}" y2="{y(w["l"]):.1f}" stroke="{col}"/>'
                 f'<rect x="{x-cw*0.36:.1f}" y="{y1:.1f}" width="{cw*0.72:.1f}" height="{max(1, y2-y1):.1f}" fill="{col}"/>'
                 f'<rect x="{x-cw*0.36:.1f}" y="{H-12-vh:.1f}" width="{cw*0.72:.1f}" height="{vh:.1f}" fill="{col}" opacity="0.45"/>')
    s.append(f'<line x1="{L}" x2="{W-R}" y1="{y(last):.1f}" y2="{y(last):.1f}" stroke="#222" stroke-width="1"/>'
             f'<text x="{W-R+6}" y="{y(last)+4:.1f}" font-size="12" font-weight="bold">{last:,}</text>')
    zones = merge_zones(top, bins, lo, step)
    for z in zones:  # 붙어 있는 상위 칸은 한 구간으로 묶어 이름표 1개
        s.append(f'<text x="{L+6}" y="{y(z["high"])-4:.1f}" font-size="11" fill="#c56a1e">'
                 f'매물대 {z["low"]:,}~{z["high"]:,} ({z["share_pct"]}%)</text>')
    s.append(f'<text x="{L}" y="{H-B+18}" font-size="11" fill="#777">주간 거래량</text></svg>')
    return "\n".join(s), zones


def merge_zones(top, bins, lo, step):
    """거래대금 상위 칸들 중 서로 붙은 것은 하나의 구간으로 합친다. 비중(%)은 최근 기간 전체 거래대금 대비."""
    total = sum(bins) or 1
    zones, cur = [], None
    for i in sorted(top):
        if cur and i == cur[1] + 1:
            cur[1] = i
        else:
            cur = [i, i]; zones.append(cur)
    return sorted(({"low": round(lo + a * step), "high": round(lo + (b + 1) * step),
                    "share_pct": round(sum(bins[a:b + 1]) / total * 100, 1)} for a, b in zones), key=lambda z: -z["low"])


PNG_JS = """const {chromium}=require('playwright');(async()=>{const b=await chromium.launch();
const p=await b.newPage({viewport:{width:%d,height:%d}});for(const f of process.argv.slice(1)){
await p.goto('file://'+f);await p.screenshot({path:f.replace(/\\.svg$/,'.png')});}await b.close();})();"""


def to_png(svgs):
    try:
        subprocess.run(["node", "-e", PNG_JS % (W, H), *map(str, svgs)], check=True, capture_output=True, timeout=120)
        return True
    except (OSError, subprocess.SubprocessError):
        return False


def main():
    p = argparse.ArgumentParser(description="주봉 캔들 + 매물대 차트")
    p.add_argument("--stock", help="종목코드 6자리 (없으면 관심종목(국내) 전체)")
    p.add_argument("--days", type=int, default=400, help="캔들 거래일 수")
    p.add_argument("--profile-days", type=int, default=250, help="매물대 계산 거래일 수")
    p.add_argument("--out", help="저장 폴더 (기본 reports/오늘/charts)")
    a = p.parse_args()

    out = Path(a.out) if a.out else ROOT / "reports" / datetime.now(KST).strftime("%Y-%m-%d") / "charts"
    out.mkdir(parents=True, exist_ok=True)
    results, svgs = [], []
    for code, name in targets(a.stock):
        rows = daily(code, name, a.days)["rows"]
        svg, zones = build_svg(name, code, rows, a.profile_days)
        f = out / f"{code}_weekly_vp.svg"
        f.write_text(svg, encoding="utf-8")
        svgs.append(f.resolve())
        results.append({"stock": name, "code": code, "last_date": rows[-1]["date"], "close": rows[-1]["close"],
                        "volume_profile_zones": zones, "svg": str(f.relative_to(ROOT) if f.resolve().is_relative_to(ROOT) else f)})
        time.sleep(0.3)
    png = to_png(svgs)
    for r in results:
        r["png"] = r["svg"][:-4] + ".png" if png else None
    print(json.dumps({"source": "네이버 증권 일봉 (비공식)", "fetched_at": datetime.now(KST).isoformat(timespec="seconds"),
                      "results": results}, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
