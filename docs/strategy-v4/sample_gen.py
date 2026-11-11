# 전략 보고서 샘플 페이지 생성 (프랍 데스크 회의 구조 + 증권사 리포트 양식)
import html, pathlib
OUT = pathlib.Path(__file__).with_name("sample_out.html")
e = html.escape

def act(a):
    cls = {"준비": "a-prep", "관찰": "a-watch", "회피": "a-avoid"}[a]
    return f'<span class="act {cls}">{a}</span>'

def dots(n, mx=2):
    return '<span class="dots" aria-label="%d점">%s</span>' % (n, "".join('<i class="on"></i>' if i < n else "<i></i>" for i in range(mx)))

def conv(n):
    return '<span class="conv" aria-label="확신도 %d/5">%s</span>' % (n, "".join('<i class="on"></i>' if i < n else "<i></i>" for i in range(5)))

def src(t):
    return f'<span class="src">{e(t)}</span>'

def pc(v):
    if v is None: return "–"
    c = "up" if v > 0 else "down" if v < 0 else ""
    return f'<span class="num {c}">{v:+.1f}%</span>'

# ---------- 차트 1: 업종 5일 수익률 (위·아래 6개) ----------
sect = [("IT/소프트웨어", 13.97), ("통신서비스", 8.47), ("건설기계", 7.96), ("운송/물류", 6.25), ("게임", 4.85), ("바이오", 4.48),
        ("지주사", -12.67), ("반도체(메모리·대형)", -12.92), ("반도체 테스트·후공정", -14.26), ("전력기기", -14.86), ("반도체 설계·유통", -18.04), ("반도체 기판·전자부품", -20.65)]
W, LW, RH, top = 680, 150, 24, 22
lo, hi = -24.0, 16.0
pw = W - LW - 50
x = lambda v: LW + (v - lo) / (hi - lo) * pw
H = top + RH * len(sect) + 26
svg = [f'<svg viewBox="0 0 {W} {H}" role="img" aria-label="업종 5일 수익률 위·아래 6개" class="chart">']
for t in (-20, -10, 0, 10):
    svg.append(f'<line x1="{x(t):.1f}" x2="{x(t):.1f}" y1="{top-6}" y2="{H-22}" class="{"axis0" if t==0 else "grid"}"/>')
    svg.append(f'<text x="{x(t):.1f}" y="{H-6}" class="tick" text-anchor="middle">{t:+d}%</text>' if t else f'<text x="{x(t):.1f}" y="{H-6}" class="tick" text-anchor="middle">0</text>')
for i, (n, v) in enumerate(sect):
    y = top + i * RH
    if i == 6:
        svg.append(f'<line x1="0" x2="{W}" y1="{y-2}" y2="{y-2}" class="sep"/>')
    x0, x1 = sorted((x(0), x(v)))
    svg.append(f'<text x="{LW-10}" y="{y+RH/2+4:.1f}" class="lab" text-anchor="end">{e(n)}</text>')
    svg.append(f'<rect x="{x0:.1f}" y="{y+5}" width="{x1-x0:.1f}" height="{RH-10}" rx="2" class="{"bu" if v>0 else "bd"}"/>')
    tx = x(v) + (6 if v > 0 else -6)
    svg.append(f'<text x="{tx:.1f}" y="{y+RH/2+4:.1f}" class="val" text-anchor="{"start" if v>0 else "end"}">{v:+.1f}%</text>')
svg.append("</svg>")
chart_sect = "\n".join(svg)

# ---------- 차트 2: 주별 채널 글 수 (피치 업종) ----------
def talkbars(vals, label):
    mx = max(vals)
    bars = "".join(f'<i style="height:{max(6, v/mx*100):.0f}%" title="{v}건"></i>' for v in vals)
    return f'<span class="tb" role="img" aria-label="{e(label)} 주별 채널 글 수 {", ".join(map(str, vals))}">{bars}</span><span class="num tbv">{vals[-1]}건</span>'

# ---------- 랠리 시도 타임라인 ----------
days = [("11/05", "−5.3%", "dn", "급락"), ("11/06", "−6.0%", "dn", "서킷브레이커"), ("11/09", "−0.8%", "dn", "반등 실패"),
        ("11/10", "+4.4%", "up", "랠리 시도 D1"), ("11/11", "+2.6%", "up", "D2 (장중)"), ("11/13~18", "?", "wait", "팔로스루 창 D4~D7")]
rally = '<ol class="rally">' + "".join(f'<li class="{c}"><b class="num">{d}</b><span class="num">{r}</span><small>{e(t)}</small></li>' for d, r, c, t in days) + "</ol>"

# ---------- 업종 스코어카드 ----------
sc = [
 ("IT/소프트웨어 (인터넷·AI DC)", 1, 2, 2, 2, "초기→확산", "준비", "5일 +14.0%·20일 +8.5%, NHN 목표가 7곳 상향, 외·기 동반 순매수"),
 ("운송/물류 (항공)", 1, 1, 2, 2, "초기", "준비", "20일 +19.9% 업종 1위권, LCC 신고가, 유가 주간 −9.5%"),
 ("음식료", 2, 1, 1, 1, "초기", "관찰", "글 +161%로 말이 커짐, 주가 5일 +2.5%로 아직 약함"),
 ("바이오", 1, 0, 2, 1, "초기", "관찰", "20일 +12.5%·기관 +8,724억, 상향 6 < 하향 11"),
 ("통신서비스", 0, 1, 2, 1, "방어", "관찰", "5일 +8.5% 방어 순환, 말·이익 변화 없음"),
 ("은행", 1, 1, 1, 1, "방어", "관찰", "급락 주간 선방, 제재·소송 변수"),
 ("건설", 0, 1, 1, 1, "–", "관찰", "업종은 하향 63 > 상향 29, 삼성E&A만 서프라이즈"),
 ("신재생에너지", 1, 1, 1, 0, "초기", "관찰", "블루웨이브 세액공제 기대, 외국인 −1,800억"),
 ("2차전지", 0, 1, 0, 1, "–", "관찰", "삼성SDI 서프라이즈에도 1주 −15.5%"),
 ("화학", 2, 0, 0, 0, "소멸", "회피", "⚠️ 말은 +400%인데 하향 22건, 20일 −13.6%"),
 ("반도체(메모리·대형)", 0, 1, 0, 0, "–", "관찰", "이익 전망은 위, 외국인 5일 −4.7조"),
 ("반도체 기판·전자부품", 1, 0, 0, 0, "소멸", "회피", "5일 −20.7% 업종 꼴찌, 하향 24 > 상향 5"),
 ("증권", 1, 0, 0, 0, "소멸", "회피", "글은 가장 많지만 하향 670건"),
 ("전력기기", 0, 0, 0, 0, "소멸", "회피", "리포트는 반등 1순위, 가격은 5일 −14.9%"),
]
sc_rows = "".join(
    f'<tr><td class="l"><b>{e(g)}</b><small class="mnote">{e(n)}</small></td><td>{dots(a)}</td><td>{dots(b)}</td><td>{dots(c)}</td><td>{dots(d)}</td>'
    f'<td class="num tot">{a+b+c+d}</td><td>{e(st)}</td><td>{act(ac)}</td><td class="l wnote">{e(n)}</td></tr>'
    for g, a, b, c, d, st, ac, n in sc)

# ---------- 관찰 풀 ----------
pool = [
 ("NHN", "181710", "T1", "선도", None, 64.1, 0.0, "신고가 수직 상승 · 기준가 없음", "5일 이상 옆걸음(베이스) 생기는지", "관찰"),
 ("NAVER", "035420", "T1", "선도 후보", 54, 12.0, -36.6, "베이스 형성 중", "11/12 IR 뒤 외국인 순매수 유지", "준비"),
 ("삼성에스디에스", "018260", "T1", "확산 후보", 88, 11.9, -40.7, "베이스 형성 중", "IR(11/16·18) 뒤 RS 85↑ 유지", "준비"),
 ("삼성E&A", "028050", "T1", "확산 후보", 95, -0.4, -1.6, "고점 근처 · 돌파 대기", "고점 돌파 때 거래대금·업종 동행", "준비"),
 ("카카오", "035720", "T1", "후속", None, 8.1, -53.0, "셋업 없음", "20일선 위 5일 유지", "관찰"),
 ("혜인", "003010", "T1", "원천(전력)", 95, 27.5, -28.4, "셋업 없음 · 급등", "DC 수주 공시 확인", "관찰"),
 ("GS건설", "006360", "T1", "후속", 81, 8.5, -30.0, "베이스 형성 중", "11/17 IR", "관찰"),
 ("대한항공", "003490", "T2", "선도", None, 5.0, -4.1, "고점 근처 · 돌파 대기", "고점 돌파 + 유가 주간 하락 유지", "준비"),
 ("진에어", "272450", "T2", "선도", None, 40.5, 0.0, "신고가 수직 상승 · 기준가 없음", "첫 눌림에서 20일선 지키는지", "관찰"),
 ("제주항공", "089590", "T2", "후속", None, 29.6, 0.0, "신고가 수직 상승 · 기준가 없음", "첫 눌림에서 20일선 지키는지", "관찰"),
 ("SK하이닉스", "000660", "T3", "선도", 85, -11.9, -58.1, "셋업 없음 · 20일선 아래", "외국인 3일 연속 순매수", "관찰"),
 ("삼성전자", "005930", "T3", "선도", 82, -8.0, -45.6, "셋업 없음 · 20일선 아래", "17만 원 종가 지지 / 20일선 회복", "관찰"),
 ("티에프이", "425420", "T3", "원천(테스트)", 98, -4.9, -14.9, "베이스 형성 중", "업종이 버티는 동안 RS 95↑ 유지", "관찰"),
 ("엑시콘", "092870", "T3", "원천(테스트)", 99, -4.4, -23.5, "베이스 형성 중", "20일선 회복", "관찰"),
 ("심텍", "222800", "T3", "후속(기판)", 89, -6.2, -35.9, "셋업 없음", "20일선 위 유지", "관찰"),
 ("한올바이오파마", "009420", "–", "바이오", None, 32.4, -29.8, "셋업 없음 · 급등", "2상 뒤 첫 눌림", "관찰"),
 ("나노신소재", "121600", "–", "신재생", 90, 4.0, -20.9, "베이스 형성 중", "RS 90 유지 + 업종 동행", "관찰"),
 ("삼성SDI", "006400", "–", "2차전지", 71, -15.5, -35.7, "셋업 없음 · 20일선 아래", "4Q ESS 마진 가이던스", "관찰"),
]
pool_rows = "".join(
    f'<tr><td class="l"><b>{e(n)}</b> <small class="num muted">{c}</small></td><td>{t}</td><td class="l">{e(r)}</td>'
    f'<td class="num">{rs if rs is not None else "–"}</td><td>{pc(w)}</td><td>{pc(h) if h else "<span class=\"num hi\">신고가</span>"}</td>'
    f'<td class="l">{e(s)}</td><td class="l">{e(wf)}</td><td>{act(a)}</td></tr>'
    for n, c, t, r, rs, w, h, s, wf, a in pool)

tpl = pathlib.Path(__file__).with_name("sample_tpl.html").read_text(encoding="utf-8")
out = (tpl.replace("{{CHART_SECT}}", chart_sect).replace("{{RALLY}}", rally).replace("{{SC_ROWS}}", sc_rows).replace("{{POOL_ROWS}}", pool_rows)
       .replace("{{PCT_NHN}}", pc(64.1)).replace("{{TB_SW}}", talkbars([22, 20, 52, 40], "IT/소프트웨어")).replace("{{TB_TR}}", talkbars([9, 9, 46, 35], "운송/물류"))
       .replace("{{TB_SEMI}}", talkbars([44, 115, 61, 38], "반도체")).replace("{{TB_PW}}", talkbars([33, 26, 37, 12], "전력기기")))
import re
for m in re.findall(r"\{\{ACT:(.+?)\}\}", out): out = out.replace("{{ACT:%s}}" % m, act(m))
for m in re.findall(r"\{\{DOTS:(\d)\}\}", out): out = out.replace("{{DOTS:%s}}" % m, dots(int(m)))
for m in re.findall(r"\{\{CONV:(\d)\}\}", out): out = out.replace("{{CONV:%s}}" % m, conv(int(m)))
OUT.write_text(out, encoding="utf-8")
print(OUT, len(out))
