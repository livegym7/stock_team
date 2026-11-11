# 전략 보고서 제3호 (v4 양식 첫 정식 호) — 내용과 숫자를 여기 한 곳에 두고 JSON·HTML·마크다운·텔레그램 요약을 함께 만든다.
# 다음 호는 이 파일을 복사해 숫자·문장만 바꾼다. 스타일은 style.html (sample_tpl.html 머리 부분).
# 실행: python3 docs/strategy-v4/issue_2026-11-11.py  → data/strategy/draft.json, reports/2026-11-11/strategy.html·strategy.md·strategy_tg.md
import html, json, pathlib, re

ROOT = pathlib.Path(__file__).resolve().parents[2]
DAY = "2026-11-11"
OUTD = ROOT / "reports" / DAY
e = html.escape

# ---------------- 기준 숫자 (마감 뒤 다시 채움) ----------------
M = dict(
    at="11/11 종가", kospi="5,365.75", kospi_pct=2.42, kosdaq="704.41", kosdaq_pct=5.51,
    up=555, down=328, nh=76, nl=26, f_kospi="+4,491억", i_kospi="−3,557억", p_kospi="−6,340억", f_kosdaq="−1,268억",
)
ISSUE = "제3호 · 2026-W46"
MADE = "2026-11-11 15:40"

# ---------------- 헬퍼 ----------------
def act(a):
    cls = {"준비": "a-prep", "관찰": "a-watch", "회피": "a-avoid"}[a]
    return f'<span class="act {cls}">{a}</span>'

def dots(n, mx=2):
    return '<span class="dots" aria-label="%d점">%s</span>' % (n, "".join('<i class="on"></i>' if i < n else "<i></i>" for i in range(mx)))

def conv(n):
    return '<span class="conv" aria-label="확신도 %d/5">%s</span>' % (n, "".join('<i class="on"></i>' if i < n else "<i></i>" for i in range(5)))

def s(t):
    return f'<span class="src">{e(t)}</span>'

def pc(v):
    if v is None:
        return "–"
    c = "up" if v > 0 else "down" if v < 0 else ""
    return f'<span class="num {c}">{v:+.1f}%</span>'

def talkbars(vals, label):
    mx = max(vals)
    bars = "".join(f'<i style="height:{max(6, v / mx * 100):.0f}%" title="{v}건"></i>' for v in vals)
    return f'<span class="tb" role="img" aria-label="{e(label)} 주별 채널 글 수 {", ".join(map(str, vals))}">{bars}</span><span class="num tbv">{vals[-1]}건</span>'

def fill(t):
    t = re.sub(r"\{\{ACT:(.+?)\}\}", lambda m: act(m.group(1)), t)
    t = re.sub(r"\{\{DOTS:(\d)\}\}", lambda m: dots(int(m.group(1))), t)
    return re.sub(r"\{\{CONV:(\d)\}\}", lambda m: conv(int(m.group(1))), t)

# ---------------- 업종 5일 차트 ----------------
SECT = [("IT/소프트웨어", 13.97), ("통신서비스", 8.47), ("건설기계", 7.96), ("운송/물류", 6.25), ("게임", 4.85), ("바이오", 4.48),
        ("지주사", -12.67), ("반도체(메모리·대형)", -12.92), ("반도체 테스트·후공정", -14.26), ("전력기기", -14.86), ("반도체 설계·유통", -18.04), ("반도체 기판·전자부품", -20.65)]

def chart_sect():
    W, LW, RH, top = 680, 150, 24, 22
    lo, hi = -24.0, 16.0
    pw = W - LW - 50
    x = lambda v: LW + (v - lo) / (hi - lo) * pw
    H = top + RH * len(SECT) + 26
    o = [f'<svg viewBox="0 0 {W} {H}" role="img" aria-label="업종 5일 수익률 위·아래 6개" class="chart">']
    for t in (-20, -10, 0, 10):
        o.append(f'<line x1="{x(t):.1f}" x2="{x(t):.1f}" y1="{top - 6}" y2="{H - 22}" class="{"axis0" if t == 0 else "grid"}"/>')
        o.append(f'<text x="{x(t):.1f}" y="{H - 6}" class="tick" text-anchor="middle">{f"{t:+d}%" if t else "0"}</text>')
    for i, (n, v) in enumerate(SECT):
        y = top + i * RH
        if i == 6:
            o.append(f'<line x1="0" x2="{W}" y1="{y - 2}" y2="{y - 2}" class="sep"/>')
        x0, x1 = sorted((x(0), x(v)))
        o.append(f'<text x="{LW - 10}" y="{y + RH / 2 + 4:.1f}" class="lab" text-anchor="end">{e(n)}</text>')
        o.append(f'<rect x="{x0:.1f}" y="{y + 5}" width="{x1 - x0:.1f}" height="{RH - 10}" rx="2" class="{"bu" if v > 0 else "bd"}"/>')
        tx = x(v) + (6 if v > 0 else -6)
        o.append(f'<text x="{tx:.1f}" y="{y + RH / 2 + 4:.1f}" class="val" text-anchor="{"start" if v > 0 else "end"}">{v:+.1f}%</text>')
    o.append("</svg>")
    return "\n".join(o)

# ---------------- 랠리 일지 ----------------
RALLY = [("11/05", "−5.28%", "dn", "매도 사이드카"), ("11/06", "−6.02%", "dn", "서킷브레이커"), ("11/09", "−0.81%", "dn", "장중 +1.4% 반납"),
         ("11/10", "+4.39%", "up", "랠리 시도 D1"), ("11/11", f"{M['kospi_pct']:+.2f}%", "up", "D2 · 코스닥 +5%대"), ("11/13~18", "?", "wait", "팔로스루 창 D4~D7")]
rally_html = '<ol class="rally">' + "".join(f'<li class="{c}"><b class="num">{d}</b><span class="num">{r}</span><small>{e(t)}</small></li>' for d, r, c, t in RALLY) + "</ol>"

# ---------------- 업종 스코어카드 (점수가 띔보다 먼저) ----------------
SC = [
    ("IT/소프트웨어 (인터넷·AI DC)", 1, 2, 2, 2, "초기→확산", "준비", "5일 +14.0%·20일 +8.5%. NHN 목표가 7곳 상향. 외국인 +1,726억·기관 +2,248억"),
    ("운송/물류 (항공)", 1, 1, 2, 2, "확산", "준비", "20일 +19.9%로 상위. 다만 LCC 2곳은 하나 목표가를 이미 넘음"),
    ("바이오", 1, 1, 2, 1, "초기", "관찰", "20일 +12.5%. 기관 +8,724억, 외국인 −1,936억. 한미약품·한올 임상 소식"),
    ("음식료", 2, 1, 1, 1, "초기", "관찰", "글 47건으로 전주의 2.6배. 주가는 5일 +2.5%로 아직 약함"),
    ("통신서비스", 0, 1, 2, 1, "방어", "관찰", "5일 +8.5%. 글은 −40%. 방어 순환 성격"),
    ("은행", 1, 1, 1, 1, "방어", "관찰", "급락 주간 선방(하나 11/09). 제재·소송 변수"),
    ("신재생에너지", 1, 1, 1, 0, "초기", "관찰", "5일 +4.2%이나 20일 −18.0%. 외국인 −1,800억"),
    ("건설", 0, 1, 1, 1, "–", "관찰", "업종은 하향 63 > 상향 29. 삼성E&A만 서프라이즈·상향 21"),
    ("2차전지", 0, 1, 0, 1, "–", "관찰", "삼성SDI 서프라이즈에도 1주 −13.5%. 글 −78%"),
    ("반도체(메모리·대형)", 0, 1, 0, 0, "–", "관찰", "오늘 업종 +4.5%(174곳 중 163곳 상승)지만 5일 −12.9%, 외국인 5일 −4.7조"),
    ("화학", 2, 0, 0, 0, "소멸", "회피", "⚠️ 글 +400%인데 하향 22건, 20일 −13.6%"),
    ("반도체 기판·전자부품", 1, 0, 0, 0, "소멸", "회피", "5일 −20.7% 업종 꼴찌. 하향 24 > 상향 5"),
    ("증권", 1, 0, 0, 0, "소멸", "회피", "글은 가장 많지만 31일 하향 671건"),
    ("전력기기", 0, 0, 0, 0, "소멸", "회피", "5일 −14.9%. LS ELECTRIC RS 16, 하향 11·상향 0"),
]
sc_rows = "".join(
    f'<tr><td class="l"><b>{e(g)}</b><small class="mnote">{e(n)}</small></td><td>{dots(a)}</td><td>{dots(b)}</td><td>{dots(c)}</td><td>{dots(d)}</td>'
    f'<td class="num tot">{a + b + c + d}</td><td>{e(st)}</td><td>{act(ac)}</td><td class="l wnote">{e(n)}</td></tr>' for g, a, b, c, d, st, ac, n in SC)

# ---------------- 관찰 풀 ----------------
# (이름, 코드, 띔, 역할, RS, 1주, 고점대비, 셋업, 볼 것, 행동)
POOL = [
    ("NAVER", "035420", "T1", "선도 후보", 54, 12.3, -36.4, "베이스 형성 중", "11/12 IR 뒤 외국인 순매수 이어지는지", "준비"),
    ("삼성에스디에스", "018260", "T1", "확산 후보", 87, 11.7, -40.8, "베이스 형성 중", "IR(11/16·18) 뒤 RS 85↑ 유지", "준비"),
    ("삼성E&A", "028050", "T1", "확산 후보(시공)", 95, -0.9, -2.1, "고점 근처 · 돌파 대기(기준가 67,700)", "67,700 돌파 때 거래대금·업종 동행", "준비"),
    ("NHN", "181710", "T1", "선도", None, 64.3, -9.7, "셋업 없음 · 오늘 장중 반전", "89,100 고점 뒤 5일 이상 옆걸음이 생기는지", "관찰"),
    ("카카오", "035720", "T1", "후속", None, 8.3, -54.2, "셋업 없음", "20일선 위 5일 유지", "관찰"),
    ("GS건설", "006360", "T1", "후속(시공)", 75, 4.5, -32.6, "베이스 형성 중", "11/17 IR · 동해 DC 착공식", "관찰"),
    ("혜인", "003010", "T1", "원천(비상전력)", 95, 26.0, -27.4, "셋업 없음 · 급등", "DC 수주 공시 확인", "관찰"),
    ("대한항공", "003490", "T2", "선도", None, 5.5, -4.3, "고점 근처 · 돌파 대기(기준가 32,800)", "32,800 돌파 + WTI 주간 하락 유지", "준비"),
    ("진에어", "272450", "T2", "선도", None, 40.8, -4.5, "셋업 없음 · 수직 상승", "하나 목표가 7,000원 이미 넘음. 첫 눌림에서 20일선", "관찰"),
    ("제주항공", "089590", "T2", "후속", None, 29.1, -4.6, "셋업 없음 · 수직 상승", "하나 목표가 7,500원 넘음. 첫 눌림에서 20일선", "관찰"),
    ("SK하이닉스", "000660", "T3", "선도", 85, -10.1, -57.2, "셋업 없음 · 20일선 −2.5%", "20일선 종가 회복 + 외국인 3일 순매수", "관찰"),
    ("삼성전자", "005930", "T3", "선도", 83, -7.1, -45.1, "셋업 없음 · 20일선 −4.3%", "17만 원 종가 지지 / 20일선 회복", "관찰"),
    ("티에프이", "425420", "T3", "원천(테스트)", 97, -4.4, -14.4, "베이스 형성 중", "업종이 버티는 동안 RS 95↑", "관찰"),
    ("엑시콘", "092870", "T3", "원천(테스트)", 98, 6.2, -14.4, "베이스 형성 중", "RS 95↑ 유지 + 20일선 위", "관찰"),
    ("심텍", "222800", "T3", "후속(기판)", 90, -2.8, -33.5, "셋업 없음", "20일선 위 유지", "관찰"),
    ("한올바이오파마", "009420", "–", "바이오", None, 32.6, -32.0, "셋업 없음 · 급등", "2상 뒤 첫 눌림", "관찰"),
    ("한미약품", "128940", "–", "바이오", None, 18.9, -21.6, "셋업 없음", "MASH 2b 뒤 20일선 지지", "관찰"),
    ("나노신소재", "121600", "–", "신재생", 90, 4.0, -20.9, "베이스 형성 중", "RS 90 유지 + 업종 동행", "관찰"),
    ("삼성SDI", "006400", "–", "2차전지", 73, -13.5, -34.2, "셋업 없음 · 20일선 아래", "4Q ESS 마진 가이던스", "관찰"),
    ("KT", "030200", "–", "통신", None, 2.2, -26.8, "셋업 없음", "방어 순환이 끝나는지(5일 수익률)", "관찰"),
    ("삼양식품", "003230", "–", "음식료", None, 1.9, -22.2, "셋업 없음", "말이 주가로 이어지는지(5일 +3%↑)", "관찰"),
    ("LS ELECTRIC", "010120", "기각", "전력기기", 16, -20.8, -63.7, "이탈", "RS 50 회복 전까지 보지 않음", "회피"),
]
pool_rows = "".join(
    f'<tr><td class="l"><b>{e(n)}</b> <small class="num muted">{c}</small></td><td>{t}</td><td class="l">{e(r)}</td>'
    f'<td class="num">{rs if rs is not None else "–"}</td><td>{pc(w)}</td><td>{pc(h)}</td>'
    f'<td class="l">{e(st)}</td><td class="l">{e(wf)}</td><td>{act(a)}</td></tr>' for n, c, t, r, rs, w, h, st, wf, a in POOL)
n_prep = sum(1 for p in POOL if p[-1] == "준비"); n_watch = sum(1 for p in POOL if p[-1] == "관찰"); n_avoid = sum(1 for p in POOL if p[-1] == "회피")

# ---------------- 본문 ----------------
STYLE = (pathlib.Path(__file__).with_name("style.html").read_text(encoding="utf-8")
         .replace("<title>Balance Lab 주간 전략 샘플</title>", "<title>Balance Lab 주간 전략</title>"))

COVER = f"""
<div class="paper">
<div class="mast">
  <div class="brand"><span class="logo">B</span>Balance Lab Research · 주간 전략</div>
  <div>{ISSUE} · 새 양식(v4) 첫 정식 호 · 2026.11.11(수) 장 마감 기준</div>
</div>
<div class="cover">
  <aside class="meta">
    <div>
      <h4>시장 판단 (데스크 결론)</h4>
      <div class="rating">
        <div class="big">관찰</div>
        <div class="sig"><i></i>신호등 빨강 · 하락 추세</div>
        <small class="muted">권장 노출(표시만): 신규 0~소량<br>랠리 시도 2일째 · 팔로스루 창 11/13~18</small>
      </div>
    </div>
    <div>
      <h4>KEY DATA</h4>
      <table class="kd">
        <tr><td>코스피</td><td class="num">{M['kospi']} <span class="up">{M['kospi_pct']:+.2f}%</span></td></tr>
        <tr><td>코스닥</td><td class="num">{M['kosdaq']} <span class="up">{M['kosdaq_pct']:+.2f}%</span></td></tr>
        <tr><td>20일선 대비</td><td class="num down">−6.5%</td></tr>
        <tr><td>6월 고점 대비</td><td class="num down">−44.2%</td></tr>
        <tr><td>오른/내린 종목</td><td class="num">{M['up']} / {M['down']}</td></tr>
        <tr><td>신고가/신저가</td><td class="num">{M['nh']} / {M['nl']}</td></tr>
        <tr><td>외국인 코스피</td><td class="num up">{M['f_kospi']}</td></tr>
        <tr><td>미 10년물</td><td class="num">4.98%</td></tr>
      </table>
      <small class="src">네이버 {M['at']} · 수급은 마감 잠정치 · 20일선·고점은 11/10 종가 기준 · 미 10년물 Yahoo 11/10</small>
    </div>
    <div>
      <h4>참여 데스크</h4>
      <ul class="team">
        <li><b>리스크 매니저</b> 국면·규칙</li>
        <li><b>매크로</b> 금리·유가·미국</li>
        <li><b>플로우</b> 채널 흐름·수급</li>
        <li><b>리서치</b> 카드 166장·원문 3건</li>
        <li><b>전략가</b> 띔 피치</li>
        <li><b>반론가</b> 반대 근거</li>
      </ul>
      <small class="src">한 대화가 역할을 바꿔 가며 씀</small>
    </div>
  </aside>
  <div class="main">
    <div class="eyebrow">INVESTMENT STRATEGY · WEEKLY</div>
    <h1 class="title">반등 2일째, 돈은 '덜 오른 곳'을 찾기 시작했다<br>— 준비는 NAVER·삼성에스디에스·대한항공, 급등주는 관찰</h1>
    <p class="subtitle">지수 판단은 팔로스루(랠리 4~7일째 강한 상승) 뒤로 미룬다. 그 사이 수직으로 오른 종목보다 고점 근처에서 쉬는 종목을 먼저 준비한다.</p>
    <ul class="sum">
      <li><span><b>국면은 아직 빨강이다.</b> 코스피는 20일선보다 6.5% 아래다. 6월 고점에서 44.2% 내려와 있다. {s('(네이버 11/10 종가)')}</span></li>
      <li><span><b>오늘은 반도체가 돌아왔다.</b> 반도체 업종이 +4.5%였다. 174곳 중 163곳이 올랐다. 코스닥은 {M['kosdaq_pct']:+.1f}%다. {s('(네이버 업종 11/11 15:15 장중)')}</span></li>
      <li><span><b>메인 띔 T1은 AI 인프라 운영·소프트웨어다.</b> 업종 5일 +14.0%다. 외국인·기관이 함께 샀다. NHN 3Q 영업이익은 컨센서스보다 9% 많았다. {s('(도구 11/11 · 교보 11/11 p.1, 원문 확인)')}</span></li>
      <li><span><b>다만 NHN은 오늘 장중 89,100원에서 80,500원으로 밀렸다.</b> 고점 대비 −9.7%다. 그래서 준비는 덜 오른 NAVER·삼성에스디에스에 둔다. {s('(네이버 일봉 11/11)')}</span></li>
      <li><span><b>서브 띔 T2 항공은 대한항공만 준비한다.</b> 진에어·제주항공은 하나증권 목표가(7,000·7,500원)를 이미 넘었다. {s('(하나 11/10 p.1, 원문 확인)')}</span></li>
      <li><span><b>전력기기 반등론은 기각했다.</b> 업종 5일 −14.9%다. 기대를 건 미국 법안(BAAJA)의 연내 통과 확률도 20~25%로 낮다. {s('(DS 11/11 p.2, 원문 확인)')}</span></li>
    </ul>
    <div class="decision">
      <h3>이번 회의의 결정 — 행동은 준비·관찰·회피 세 가지로만 씁니다</h3>
      <div class="dgrid">
        <div><h4>{{{{ACT:준비}}}} 셋업 생기면 바로 본다</h4><ul><li>NAVER · 삼성에스디에스 (T1)</li><li>삼성E&amp;A (T1, 고점 −2.1%)</li><li>대한항공 (T2, 고점 −4.3%)</li></ul></div>
        <div><h4>{{{{ACT:관찰}}}} 조건이 맞을 때까지</h4><ul><li>NHN (오늘 장중 반전) · 진에어 · 제주항공</li><li>SK하이닉스 · 삼성전자 (T3, 20일선 바로 아래)</li><li>바이오 · 음식료 · 통신</li></ul></div>
        <div><h4>{{{{ACT:회피}}}} 지금은 손대지 않는다</h4><ul><li>전력기기 (LS ELECTRIC RS 16)</li><li>반도체 기판·전자부품</li><li>화학 · 증권 (말만 많음)</li></ul></div>
      </div>
      <div class="dnote">새 매수는 규칙상 '돌파 신호 + 인더스트리 액션'이 먼저다. 이 표는 무엇을 먼저 볼지 정하는 순서표다. 매수·매도 권유가 아니며 판단은 본인이 한다.</div>
    </div>
  </div>
</div>
<div class="pad" style="padding-top:20px;padding-bottom:20px">
  <ol class="agenda">
    <li><b>국면 점검</b><span>무엇을 할 수 있는 장인가</span></li>
    <li><b>지난 가설 채점</b><span>11/09 띔 3개는 맞았나</span></li>
    <li><b>데스크 보고</b><span>매크로·플로우·리서치</span></li>
    <li><b>아이디어 피치</b><span>띔 3개 + 기각 1개</span></li>
    <li><b>반론 라운드</b><span>틀린다면 왜 틀리나</span></li>
    <li><b>결정</b><span>스코어카드·관찰 풀·시나리오</span></li>
  </ol>
</div>
"""

AG1 = f"""
<section class="pad">
  <div class="sh"><span class="no">안건 1</span><h2>국면 점검 — 추세추종을 해도 되는 장인가</h2><span class="who">발표: 리스크 매니저</span></div>
  <p class="lead">아직 아니다. 그래도 이틀 연속 올랐고 외국인도 이틀 연속 샀다. 다음 주 팔로스루가 이번 호에서 가장 큰 확인 지점이다.</p>
  <div class="kpis">
    <div><small>코스피 20일선 대비</small><b class="num down">−6.5%</b><em>11/10 종가</em></div>
    <div><small>코스피 1주 / 1개월</small><b class="num down">−7.3% / −17.9%</b><em>11/10 종가</em></div>
    <div><small>외국인 코스피</small><b class="num up">+4,177억 → {M['f_kospi']}</b><em>11/10 → 11/11</em></div>
    <div><small>신고가 / 신저가</small><b class="num">{M['nh']} / {M['nl']}</b><em>코스피 {M['at']}</em></div>
    <div><small>코스닥 외국인</small><b class="num down">{M['f_kosdaq']}</b><em>11/11, 기관이 받음</em></div>
    <div><small>12월 미 금리 인상 확률</small><b class="num">80.5%</b><em>대신 11/09 카드</em></div>
  </div>
  <h3 style="font-size:14px;margin-bottom:2px">랠리 시도 일지 (오닐 방식: 1일째 뒤 4~7일째에 거래량 실린 강한 상승 = 팔로스루)</h3>
  {rally_html}
  <div class="cols">
    <div>
      <p><b>좋아진 것.</b> 외국인이 코스피를 이틀 연속 샀다. 신고가 종목(76)이 신저가(26)의 약 세 배다. 오늘은 반도체도 같이 올라 상승 폭이 넓어졌다.</p>
      <p><b>아직인 것.</b> 지수는 20일선 아래다. 코스닥은 외국인이 {M['f_kosdaq']}을 팔았다. 코스피 기관도 {M['i_kospi']} 순매도다. {s('(네이버 ' + M['at'] + ')')}</p>
    </div>
    <div>
      <p><b>내 계좌.</b> 보유 0, 위험 노출(CR) 0%다. 지난 5건은 모두 손절이었다. 평균 −1.29R, 합계 −6.47R이다. {s('(trades.py)')}</p>
      <p>신호등별 권장 노출은 <b>표시만</b> 한다. 매매 규칙은 2027-01-31까지 고정이다. 다음 신호도 같은 규칙으로 본다.</p>
    </div>
  </div>
  <div class="flip"><b>국면이 바뀌는 조건.</b> ① 11/13~11/18 중 코스피 +1.5% 이상 + 전날보다 많은 거래량(팔로스루) ② 코스피 종가가 20일선 위 ③ 외국인 3일 연속 순매수(11/12에 달성 여부). ①+②면 신호등 노랑으로 본다. 11/09 종가 5,018.85를 깨면 랠리 시도는 무효다.</div>
</section>
"""

AG2 = f"""
<section class="pad">
  <div class="sh"><span class="no">안건 2</span><h2>지난 가설 채점 — 11/09 호의 띔 3개</h2><span class="who">발표: 반론가 (strategy_prep score)</span></div>
  <p class="lead">세 개 중 하나만 절반쯤 맞았다. 오른 것은 데이터센터 '설비'가 아니라 '운영·소프트웨어'였다. 이번 호는 이 차이를 T1에 반영했다.</p>
  <div class="tw"><table class="t">
    <tr><th class="l">지난 띔 (11/09)</th><th>판정</th><th class="l">숫자 (5거래일 수익률, 11/11 기준)</th><th class="l">배운 것</th></tr>
    <tr><td class="l"><b>T1 미국 DC 규제 → 한국 DC·전력</b><br><small class="muted">초기 · 확신 3</small></td><td><span class="st mid">절반 맞음</span></td>
      <td class="l wrap">혜인 +26.0% · SGC에너지 +18.0% · NAVER +12.3% · 삼성에스디에스 +11.7% · GS건설 +4.5% / 상신이디피 −15.2% · LS ELECTRIC −20.8%</td>
      <td class="l wrap">운영·소형 수주주는 올랐다. 전력기기 대형주는 더 빠졌다. 'DC'를 한 덩어리로 보면 안 된다.</td></tr>
    <tr><td class="l"><b>T2 북미 ESS 셀</b><br><small class="muted">확산 · 확신 3</small></td><td><span class="st no">틀림(진행)</span></td>
      <td class="l wrap">삼성SDI −13.5% · LG에너지솔루션 −6.4% · 한중엔시에스 −17.5% / 나노신소재 +4.0%</td>
      <td class="l wrap">삼성SDI 3Q 영업이익은 예상의 2배였다(4,078억 vs 1,912억). 그래도 주가는 빠졌다. 이익보다 'AI 인프라 베타'로 거래됐다.</td></tr>
    <tr><td class="l"><b>T3 메모리 밸류에이션 바닥론</b><br><small class="muted">초기 · 확신 2</small></td><td><span class="st no">틀림(진행)</span></td>
      <td class="l wrap">삼성전자 −7.1% · SK하이닉스 −10.1% · 삼성전기 −18.1% · 디아이 −11.7%. 무효 조건(삼성전자 17만 원 종가 이탈)은 아님(205,750원)</td>
      <td class="l wrap">싸다는 이유만으로는 바닥이 안 된다. 외국인 매도가 멈추는 것을 먼저 봐야 했다. 오늘 반등(+4~7%)은 그 시험이다.</td></tr>
    <tr><td class="l"><b>체크포인트: BAAJA 절차표결</b></td><td><span class="st ok">확인</span></td>
      <td class="l wrap">11/09 상원 클로처 73:25 가결. 남은 절차는 본안 표결 → 하원 동의 → 2027.1.3 전 서명</td>
      <td class="l wrap">통과돼도 미국 송전망 공기가 6~10년에서 2년으로 준다는 전망이다. T1의 '미국 밖' 논리에는 반대 방향이다. {s('(DS 11/11 p.1·p.2, 원문 확인)')}</td></tr>
  </table></div>
  <small class="src">출처: strategy_prep score 11/11 15:16, 네이버 일봉 11/11. T2는 이번 호에서 띔에서 내리고 스코어카드(2차전지)로만 본다.</small>
</section>
"""

AG3 = f"""
<section class="pad">
  <div class="sh"><span class="no">안건 3</span><h2>데스크 보고 — 세 출처가 같은 방향을 가리키는가</h2><span class="who">매크로 · 플로우 · 리서치</span></div>
  <div class="cols">
    <div class="desk">
      <h3>매크로 데스크</h3><div class="role">금리 · 유가 · 미국 일정</div>
      <ul>
        <li>10월 CPI는 전월 +0.4%로 예상(+0.3%)보다 높았다. 근원도 +0.3%로 예상을 넘었다. {s('(TradingView·채널 11/10 22:30)')}</li>
        <li>미 10년물은 4.98%로 하루 +0.12%p 올랐다. S&amp;P500은 −0.38%, 필라델피아 반도체는 −0.35%였다. {s('(Yahoo 11/10 종가)')}</li>
        <li>WTI는 한 주에 −9.5%다. 호르무즈 원유 수출은 전쟁 전의 76%까지 회복했다. {s('(유진 11/10 카드)')}</li>
        <li>원/달러는 1,334.7원으로 −0.7%다. 원화 강세는 항공 비용에 유리하다. {s('(Yahoo 11/11 15:17)')}</li>
        <li>다음 분기점: 11/13 미국 PPI, 11/18 엔비디아 실적.</li>
      </ul>
    </div>
    <div class="desk">
      <h3>플로우 데스크</h3><div class="role">채널 흐름 · 수급 (2차 자료)</div>
      <ul>
        <li><b>🤫 조용히 오름</b>: IT/소프트웨어·운송·바이오·통신·게임. 글은 줄었는데 주가와 수급이 올랐다.</li>
        <li><b>⚠️ 말은 많은데 주가 ↓</b>: 반도체 장비(글 +350%)·화학(+400%)·원전(+127%)·헬스케어.</li>
        <li><b>🔥 말·주가·수급 모두 ↑</b>: 음식료(글 +161%)·의류. 다만 주가 상승 폭은 +2.5% 안팎이다.</li>
        <li>반도체 대형주 5일 수급은 −4.7조 원이다. SK하이닉스만 외국인 −4조 4,880억이다. 기관은 +1조 4,226억을 받았다.</li>
      </ul>
      <small class="src">채널 요약 11/04~11/11 · 수급은 strategy_prep 5일 합계</small>
    </div>
    <div class="desk">
      <h3>리서치 데스크</h3><div class="role">카드 166장 · 원문 확인 3건</div>
      <ul>
        <li>31일 목표가는 상향 164건, 하향 936건이다. 하향이 5.7배다. {s('(채널 리포트 요약)')}</li>
        <li>인터넷·SW 카드 27장: 강세 14, 약세 6. NHN 원문: 기술 부문 가치를 1.5조→2.37조 원으로 올렸다. {s('(교보 11/11 p.1, 원문 확인)')}</li>
        <li>운송 원문: "유류비 상승분의 70%를 보전하려면 운임이 약 20% 올라야 한다." 유가가 내리면 이익 모멘텀이 더 강해진다는 논리다. {s('(하나 11/10 p.3, 원문 확인)')}</li>
        <li>반도체 카드 13장: 강세 6, 약세 3. 2027 범용 D램 값 +40% 중후반 가능. {s('(대신 11/10 카드)')}</li>
      </ul>
    </div>
  </div>
  <figure style="margin-top:18px">
    <h3 style="font-size:14px;margin-bottom:6px">업종 5일 수익률 — 위 6개 · 아래 6개</h3>
    <div class="tw" style="border:0;margin:0">{chart_sect()}</div>
    <figcaption class="figcap">출처: strategy_prep 업종 5일 수익률 (사용자 업종 분류, 11/11 15:11). 같은 기간 코스피 1주는 −7.3%(11/10 종가). 위쪽 6개가 모두 반도체·AI 하드웨어 밖이다. 다만 오늘 하루는 반도체가 +4.5%로 되돌렸다.</figcaption>
  </figure>
</section>
"""

T1 = f"""
  <article class="pitch">
    <div class="ph">
      <div><div class="tag">T1 · 메인 띔 · 초기→확산 · 확신 {{{{CONV:3}}}}</div>
        <h3>AI 인프라가 '미국 밖'으로 흩어질 때, 돈은 설비보다 운영·소프트웨어로 먼저 간다</h3>
        <div class="who">지난 호 T1에서 좁힘 · 전력기기·소형 부품은 빼고 운영·플랫폼·시공만 남김</div></div>
      <div class="pscore"><span>말</span><span>이익</span><span>가격</span><span>돈</span><b class="num">7/8</b>{{{{DOTS:1}}}}{{{{DOTS:2}}}}{{{{DOTS:2}}}}{{{{DOTS:2}}}}</div>
    </div>
    <div class="pb">
      <p class="thesis">미국 안에서 데이터센터를 짓기 어려워지면 GPU 임대 가격이 오른다. 국내에서 GPU와 전력을 확보한 플랫폼·클라우드 사업자는 그 값을 받는다. 시장은 이것을 소프트웨어 업종 주가로 먼저 보여 주고 있다.</p>
      <dl class="qa">
        <dt>왜 지금인가</dt><dd>NHN 3Q 영업이익은 588억 원으로 컨센서스 539억 원을 넘었다. AI DC 확보 계획은 2027년 말 100MW로 약 30MW 늘었다. 교보는 목표가를 64,000원에서 92,000원으로 올렸다. {s('(교보 11/11 p.1, 원문 확인)')} 같은 날 7곳이 목표가를 올렸다. {s('(채널 리포트 요약 11/11)')}</dd>
        <dt>시장이 놓친 것</dt><dd>채널 글은 오히려 줄었다(52→41건). 말보다 주가·수급이 앞선 '조용한 상승'이다. 사람들은 아직 반도체 얘기를 더 한다.</dd>
        <dt>채널 글 4주</dt><dd>{talkbars([22, 20, 52, 41], "IT/소프트웨어")} {s('IT/소프트웨어, 10/19~11/09 주')}</dd>
      </dl>
      <ol class="flow">
        <li><em>확인</em><b>미국 DC 인허가 지연</b>텍사스 신규 허가 보류 발언 {s('(채널 11/06, 3곳)')}</li>
        <li><em>확인</em><b>GPU 임대가 상승</b>아이렌 5년 계약 MW당 연매출 약 2,200만 달러, 상반기 평균보다 +80% {s('(유진 11/10 카드)')}</li>
        <li class="h"><em>가설</em><b>국내 GPU 클라우드 매출</b>NHN 2027년 1월 6MW 가동, 2027년 1,082억 원 매출 추정 {s('(교보 p.1)')}</li>
        <li class="h"><em>가설</em><b>플랫폼 전반 재평가</b>NAVER·삼성에스디에스로 확산 — IR 숫자로 확인 필요</li>
      </ol>
      <div class="ev">
        <div><h4>말 {{{{DOTS:1}}}}</h4>IT/SW 글 41건. 전주 52건보다 적고 4주 평균(34건)보다는 조금 많다.</div>
        <div><h4>이익 {{{{DOTS:2}}}}</h4>NHN 상향 7곳·서프라이즈. 삼성에스디에스 하나 240,000→290,000 상향. 업종 31일은 상향 12·하향 26으로 부담.</div>
        <div><h4>가격 {{{{DOTS:2}}}}</h4>업종 5일 +14.0%, 20일 +8.5%. 코스피를 크게 앞선다. 삼성에스디에스 RS 87.</div>
        <div><h4>돈 {{{{DOTS:2}}}}</h4>업종 5일 외국인 +1,726억, 기관 +2,248억. NAVER 외국인 +1,669억·기관 +1,688억.</div>
      </div>
      <div class="tw"><table class="t">
        <tr><th class="l">기업 지도</th><th>역할</th><th>RS</th><th>1주</th><th>고점 대비</th><th class="l">볼 것</th><th>행동</th></tr>
        <tr><td class="l"><b>NHN</b></td><td>선도</td><td class="num">–</td><td>{pc(64.3)}</td><td>{pc(-9.7)}</td><td class="l wrap">오늘 82,900원에 열고 89,100원까지 간 뒤 80,500원에 마감했다. 5일 이상 옆걸음(베이스)이 생기는지</td><td>{{{{ACT:관찰}}}}</td></tr>
        <tr><td class="l"><b>NAVER</b></td><td>선도 후보</td><td class="num">54</td><td>{pc(12.3)}</td><td>{pc(-36.4)}</td><td class="l wrap">11/12 IR에서 GPU·DC 숫자. 컨센 303,333원(6곳)과 종가 193,300원</td><td>{{{{ACT:준비}}}}</td></tr>
        <tr><td class="l"><b>삼성에스디에스</b></td><td>확산 후보</td><td class="num">87</td><td>{pc(11.7)}</td><td>{pc(-40.8)}</td><td class="l wrap">IR(11/16·18) 뒤 RS 85 이상 유지. 대신 "2028년 이후 DC 가동 효과" {s('(채널 요약 11/10)')}</td><td>{{{{ACT:준비}}}}</td></tr>
        <tr><td class="l"><b>삼성E&amp;A</b></td><td>확산 후보(시공)</td><td class="num">95</td><td>{pc(-0.9)}</td><td>{pc(-2.1)}</td><td class="l wrap">3Q 영업이익 5,006억(예상 2,492억), 31일 상향 21·하향 0. 67,700원 돌파 때 업종 동행</td><td>{{{{ACT:준비}}}}</td></tr>
        <tr><td class="l"><b>카카오</b></td><td>후속</td><td class="num">–</td><td>{pc(8.3)}</td><td>{pc(-54.2)}</td><td class="l">20일선 위 5일 유지</td><td>{{{{ACT:관찰}}}}</td></tr>
        <tr><td class="l"><b>GS건설</b></td><td>후속(시공)</td><td class="num">75</td><td>{pc(4.5)}</td><td>{pc(-32.6)}</td><td class="l">11/17 IR · 동해 100MW 착공식</td><td>{{{{ACT:관찰}}}}</td></tr>
      </table></div>
      <small class="src">RS·수급: strategy_prep 11/11 15:11 · NHN·카카오·NAVER 주가: 네이버 일봉 11/11 (RS '–'는 감시 목록에 없어 비움)</small>
      <div class="debate">
        <div class="c"><span class="r c">반론 1</span><span>NHN은 1주 +64%다. 오늘은 장중 고점에서 약 10% 밀렸다. 신고가 수직 상승 뒤 장중 반전은 단기 고점 신호일 수 있다.</span></div>
        <div><span class="r a">답변</span><span>인정한다. NHN은 '관찰'로 둔다. 띔의 근거는 NHN 하나가 아니라 업종 수급이다. 준비는 아직 덜 오른 NAVER·삼성에스디에스에 둔다.</span></div>
        <div class="c"><span class="r c">반론 2</span><span>BAAJA가 통과되면 미국 송전망 공기가 6~10년에서 2년으로 준다. 미국 안에서 짓기가 쉬워지면 '미국 밖' 논리는 약해진다. {s('(DS 11/11 p.1, 원문 확인)')}</span></div>
        <div><span class="r a">답변</span><span>같은 자료가 레임덕 통과 확률을 20~25%로 본다. 미통과면 다음 의회로 넘어가지도 않는다. {s('(DS p.2)')} 통과돼도 실제 효과는 FERC 규칙까지 시차가 있다. 다만 상원 본안 통과는 무효 신호에 넣는다.</span></div>
        <div class="c"><span class="r c">반론 3</span><span>오늘 반도체가 +4.5%로 돌아왔다. 순환매가 다시 반도체로 가면 소프트웨어는 자금이 빠질 수 있다.</span></div>
        <div><span class="r a">답변</span><span>그럴 수 있다. 그래서 확신도를 4로 올리지 않는다. IT/SW 20일 수익률이 코스피 아래로 내려가면 띔을 내린다.</span></div>
        <div class="c"><span class="r c">반론 4</span><span>12월 금리 인상 확률이 80%다. 10년물이 5%에 붙었다. 성장주 밸류에이션이 다시 눌릴 수 있다.</span></div>
        <div><span class="r a">답변</span><span>11/13 PPI가 또 예상을 넘으면 준비 종목도 관찰로 내린다.</span></div>
      </div>
      <div class="kill">
        <div class="k"><h4>무효 신호 (틀렸다고 인정할 조건)</h4>IT/SW 업종 20일 수익률이 코스피 아래로 내려감 · NAVER IR 뒤 외국인 3일 연속 순매도 · BAAJA 상원 본안 통과</div>
        <div class="v"><h4>실적 반영 시점 · 촉매</h4>2027년 상반기(NHN 6MW 1월 가동). 11/12 NAVER IR · 11/16·18 삼성에스디에스 IR · 11/17 GS건설 IR · 11/18 엔비디아 실적</div>
      </div>
      <div class="verdict"><b>데스크 결정</b>{{{{ACT:준비}}}} NAVER · 삼성에스디에스 · 삼성E&amp;A {{{{ACT:관찰}}}} NHN · 카카오 · GS건설 <span class="muted">— 찬성 4 · 보류 2 (반론가·리스크 매니저: 국면 빨강)</span></div>
    </div>
  </article>
"""

T2 = f"""
  <article class="pitch">
    <div class="ph">
      <div><div class="tag">T2 · 서브 띔 · 확산 · 확신 {{{{CONV:2}}}}</div>
        <h3>유가가 꺾이면 항공 이익이 먼저 오른다 — 하지만 LCC는 목표가를 벌써 넘었다</h3>
        <div class="who">새 띔 · 지난 호에 없음</div></div>
      <div class="pscore"><span>말</span><span>이익</span><span>가격</span><span>돈</span><b class="num">6/8</b>{{{{DOTS:1}}}}{{{{DOTS:1}}}}{{{{DOTS:2}}}}{{{{DOTS:2}}}}</div>
    </div>
    <div class="pb">
      <p class="thesis">항공사 비용의 큰 몫은 연료다. 유가가 한 주에 9.5% 빠졌고 원화도 강하다. 비용은 줄고 일본·중국 노선 수요는 버틴다. 2027년 이익 추정치가 오를 자리다.</p>
      <dl class="qa">
        <dt>왜 지금인가</dt><dd>미-이란 종전 기대로 유가가 급락했다. 하나는 "항공유 가격이 내릴 때 이익 모멘텀이 더 강해진다"고 썼다. 유류할증료보다 유가가 먼저 비용에 반영되기 때문이다. {s('(하나 11/10 p.3, 원문 확인)')}</dd>
        <dt>시장이 놓친 것</dt><dd>대한항공은 덜 올랐다. 1주 +5.5%로 LCC(+29~41%)보다 훨씬 적다. 하나 목표가 41,000원은 종가 31,400원보다 31% 위다. {s('(하나 11/10 p.1, 원문 확인 · 네이버 11/11)')}</dd>
        <dt>채널 글 4주</dt><dd>{talkbars([9, 9, 46, 35], "운송/물류")} {s('운송/물류')}</dd>
      </dl>
      <div class="ev">
        <div><h4>말 {{{{DOTS:1}}}}</h4>글 35건. 전주 46건보다 줄었지만 11/02 주부터 늘어난 수준을 유지한다.</div>
        <div><h4>이익 {{{{DOTS:1}}}}</h4>31일 상향 18·하향 13. 하나는 운송 Overweight, Top Pick 대한항공.</div>
        <div><h4>가격 {{{{DOTS:2}}}}</h4>업종 5일 +6.3%, 20일 +19.9%. 진에어·제주항공은 고점 −5% 안쪽.</div>
        <div><h4>돈 {{{{DOTS:2}}}}</h4>업종 5일 외국인 +848억, 기관 +1,761억.</div>
      </div>
      <div class="tw"><table class="t">
        <tr><th class="l">기업 지도</th><th>역할</th><th>1주</th><th>1개월</th><th>고점 대비</th><th class="l">하나 목표가</th><th class="l">볼 것</th><th>행동</th></tr>
        <tr><td class="l"><b>대한항공</b></td><td>선도</td><td>{pc(5.5)}</td><td>{pc(4.5)}</td><td>{pc(-4.3)}</td><td class="l num">41,000 (+31%)</td><td class="l wrap">32,800원 돌파 + 유가 주간 하락 유지. 오늘 −3.7%로 쉬었다</td><td>{{{{ACT:준비}}}}</td></tr>
        <tr><td class="l"><b>진에어</b></td><td>선도</td><td>{pc(40.8)}</td><td>{pc(35.2)}</td><td>{pc(-4.5)}</td><td class="l num">7,000 (−14%)</td><td class="l wrap">종가 8,110원이 목표가를 넘었다. 첫 눌림에서 20일선</td><td>{{{{ACT:관찰}}}}</td></tr>
        <tr><td class="l"><b>제주항공</b></td><td>후속</td><td>{pc(29.1)}</td><td>{pc(37.6)}</td><td>{pc(-4.6)}</td><td class="l num">7,500 (−1%)</td><td class="l wrap">종가 7,540원으로 목표가를 조금 넘었다. 첫 눌림에서 20일선</td><td>{{{{ACT:관찰}}}}</td></tr>
      </table></div>
      <small class="src">주가: 네이버 일봉 11/11 · 목표가: 하나 11/10 p.1 표(현재가 11/9 기준), 괄호는 11/11 주가 대비</small>
      <div class="debate">
        <div class="c"><span class="r c">반론 1</span><span>이 띔은 변수 하나(유가)에 기댄다. 이란 협상이 깨지면 하루 만에 뒤집힌다.</span></div>
        <div><span class="r a">답변</span><span>그래서 확신도는 2다. 메인이 아니라 서브로 둔다. 유가 반등을 숫자로 무효 조건에 넣는다.</span></div>
        <div class="c"><span class="r c">반론 2</span><span>LCC 주가가 증권사 목표가를 이미 넘었다. 리포트가 그린 그림은 가격에 다 들어갔다.</span></div>
        <div><span class="r a">답변</span><span>맞다. LCC는 관찰이다. 준비는 목표가까지 여유가 있고 고점 −4%에서 쉬는 대한항공 하나다.</span></div>
        <div class="c"><span class="r c">반론 3</span><span>하나 원문도 "모든 항공사가 2027년 호황을 누리지는 못한다"고 썼다. 동남아·유럽 노선은 약하다. {s('(하나 p.3)')}</span></div>
        <div><span class="r a">답변</span><span>그래서 화물·미주 비중이 큰 대한항공을 고른다. 노선 약세는 LCC 쪽 위험으로 적어 둔다.</span></div>
      </div>
      <div class="kill">
        <div class="k"><h4>무효 신호</h4>WTI 주간 +8% 이상 반등 · 운송 업종 5일 수익률이 2주 연속 코스피 아래 · 진에어·제주항공 20일선 종가 이탈</div>
        <div class="v"><h4>실적 반영 시점 · 촉매</h4>4Q26 실적(2027년 2월). 매주 유가, 11월 국제선 여객 통계(12월 초)</div>
      </div>
      <div class="verdict"><b>데스크 결정</b>{{{{ACT:준비}}}} 대한항공 {{{{ACT:관찰}}}} 진에어 · 제주항공 <span class="muted">— 찬성 3 · 보류 3 (매크로: 유가 단일 변수)</span></div>
    </div>
  </article>
"""

T3 = f"""
  <article class="pitch">
    <div class="ph">
      <div><div class="tag">T3 · 관찰 띔 · 확신 {{{{CONV:1}}}} (2에서 내림)</div>
        <h3>메모리: 이익 전망은 위, 수급은 아래 — 오늘 반등이 '매도 끝'인지는 사흘을 더 본다</h3>
        <div class="who">지난 호 T3 유지 · 단계 '초기'에서 '관찰'로 강등</div></div>
      <div class="pscore"><span>말</span><span>이익</span><span>가격</span><span>돈</span><b class="num">1/8</b>{{{{DOTS:0}}}}{{{{DOTS:1}}}}{{{{DOTS:0}}}}{{{{DOTS:0}}}}</div>
    </div>
    <div class="pb">
      <p class="thesis">리포트는 2027년 공급 부족이 더 심해진다고 본다. 외국인은 지난 5일 동안 크게 팔았다. 오늘 SK하이닉스 +6.6%, 삼성전자 +4.3%로 20일선 바로 아래까지 왔다. 할 일은 매도가 멈추는 날을 기록하는 것이다.</p>
      <dl class="qa">
        <dt>찬성 근거</dt><dd>2027 범용 D램 값 +40% 중후반 가능(기존 +30% 후반). 메모리 업체는 다운사이클에도 피크 이익의 70%를 지킨다. {s('(대신·반도체 카드 11/10)')} 메리츠·신한은 11/11 삼성전자·SK하이닉스 목표가를 유지했다. {s('(채널 리포트 요약 11/11)')}</dd>
        <dt>반대 근거</dt><dd>모건스탠리는 SK하이닉스 D램 이익률 가정을 60%에서 32%로 낮췄다. {s('(채널 요약 11/10)')} 반도체 장비 목표가는 12건이 내려갔다(원익IPS 3곳 등). {s('(리포트 정리 11/11)')}</dd>
        <dt>채널 글 4주</dt><dd>{talkbars([44, 115, 61, 39], "반도체")} {s('반도체(메모리·대형), 10/26 주 정점 뒤 감소')}</dd>
      </dl>
      <div class="ev">
        <div><h4>말 {{{{DOTS:0}}}}</h4>글 39건. 4주 전 115건의 3분의 1이다.</div>
        <div><h4>이익 {{{{DOTS:1}}}}</h4>SK하이닉스 상향 4·하향 3, 삼성전자 상향 1·하향 2. 엇갈림.</div>
        <div><h4>가격 {{{{DOTS:0}}}}</h4>업종 5일 −12.9%, 20일 −16.6%. 둘 다 20일선 아래(−2.5%·−4.3%). RS는 85·83.</div>
        <div><h4>돈 {{{{DOTS:0}}}}</h4>5일 외국인 SK하이닉스 −4조 4,880억, 삼성전자 −2조 2,146억. 기관이 약 2조 원을 받았다.</div>
      </div>
      <div class="kill">
        <div class="k"><h4>무효 신호 (띔 폐기)</h4>삼성전자 17만 원 종가 이탈 · 리포트 정리에서 메모리 목표가 하향이 3일 연속</div>
        <div class="v"><h4>다시 올리는 조건</h4>외국인 3일 연속 순매수 + 두 종목 20일선 종가 회복. 첫 시험대는 11/18 엔비디아 실적(국내 11/19 아침)</div>
      </div>
      <div class="verdict"><b>데스크 결정</b>{{{{ACT:관찰}}}} SK하이닉스 · 삼성전자 · 테스트 장비(티에프이·엑시콘, RS 97·98) <span class="muted">— 만장일치</span></div>
    </div>
  </article>
"""

REJ = f"""
  <article class="pitch rejected">
    <div class="ph">
      <div><div class="tag">기각된 피치 · 리서치 데스크 제안</div>
        <h3>전력기기 반등 1순위? — 리포트는 먼저 와 있고, 가격은 거절 중</h3></div>
      <div class="pscore"><span>말</span><span>이익</span><span>가격</span><span>돈</span><b class="num">0/8</b>{{{{DOTS:0}}}}{{{{DOTS:0}}}}{{{{DOTS:0}}}}{{{{DOTS:0}}}}</div>
    </div>
    <div class="pb">
      <dl class="qa">
        <dt>제안 근거</dt><dd>DS는 BAAJA가 통과되면 "계약 수요가 발주로 넘어간다"며 전력기기 비중확대를 유지했다. {s('(DS 11/11 p.1, 원문 확인)')} 2027년 정책 적용 시 실제 발주 전방시장 +50% 전망도 있다. {s('(DS 11/10 카드)')}</dd>
        <dt>기각 이유</dt><dd>업종 5일 −14.9%다. LS ELECTRIC은 RS 16으로 4주 동안 70 내려갔다. 1개월 −30.9%다. 31일 목표가는 하향 11, 상향 0이다. 채널 글도 37건에서 17건으로 줄었다. {talkbars([33, 26, 37, 17], "전력기기")} 게다가 근거로 든 법안의 연내 통과 확률은 20~25%다. {s('(DS p.2)')}</dd>
        <dt>다시 볼 조건</dt><dd>LS ELECTRIC RS 50 회복 · 전력기기 업종 5일 수익률이 코스피 위 · BAAJA 상원 본안 통과 · 외국인·기관 동반 순매수</dd>
      </dl>
      <div class="verdict"><b>데스크 결정</b>{{{{ACT:회피}}}} <span class="muted">— 찬성 1(리서치) · 반대 5. '싸 보인다'와 '법이 통과되면'은 추세추종의 근거가 아니다.</span></div>
    </div>
  </article>
"""

AG4 = f"""
<section class="pad">
  <div class="sh"><span class="no">안건 4</span><h2>아이디어 피치 — 띔 3개, 기각 1개</h2><span class="who">발표: 전략가 · 반박: 반론가</span></div>
  <p class="lead">피치마다 같은 순서로 묻는다. 무엇을 믿나, 왜 지금인가, 시장이 무엇을 놓쳤나, 4검증 점수, 반론, 틀렸다고 인정할 조건.</p>
{T1}{T2}{T3}{REJ}
</section>
"""

AG5 = """
<section class="pad">
  <div class="sh"><span class="no">안건 5</span><h2>반론 라운드 — 3주 뒤 이 보고서가 틀렸다면 왜일까</h2><span class="who">발표: 반론가 (사전 부검)</span></div>
  <ol class="pm">
    <li><span><b>랠리 시도가 또 실패했다.</b> 11/09처럼 반등이 무너지고 5,018을 깬다. 그러면 신고가 종목도 같이 끌려 내려간다. NHN의 오늘 장중 반전이 그 첫 신호였을 수 있다.</span></li>
    <li><span><b>'조용한 상승'은 피난처였다.</b> 반도체를 판 돈이 잠시 소프트웨어·항공·통신으로 피했을 수 있다. 오늘처럼 반도체가 돌아오면 그 돈이 다시 빠진다.</span></li>
    <li><span><b>같은 생각의 메아리였다.</b> 'DC 아시아 이전' 자료는 여러 증권사가 같은 주에 냈다. 독립된 근거 여러 개가 아니라 하나의 생각일 수 있다.</span></li>
    <li><span><b>금리가 다시 올랐다.</b> PPI도 강하면 12월 인상이 굳어진다. 10년물 5%를 넘으면 성장주 T1이 먼저 맞는다.</span></li>
    <li><span><b>항공은 이미 가격에 들어 있었다.</b> LCC 주가가 목표가를 넘었다. 대한항공만 남은 이유가 '덜 좋아서'일 수도 있다.</span></li>
  </ol>
  <p style="margin-top:12px"><b>조정 결과.</b> T1 확신도는 3에서 올리지 않는다. T2는 2로 둔다. T3는 2에서 1로 내린다. 반론으로 확신도를 올리는 일은 없다. 올리려면 원문 확인 근거가 필요하다.</p>
</section>
"""

CHK = [
    ("11/12 09:00", "NAVER IR — GPU 확보·DC 숫자가 나오는지. 끝난 뒤 외국인 방향", "T1"),
    ("11/12 장 마감", "외국인 코스피 3일 연속 순매수인지 (11/10 +4,177억, 11/11 " + M["f_kospi"] + ")", "국면 · T3"),
    ("11/13 22:30", "미국 PPI·근원 PPI — 12월 인상 확률 80.5%가 오르는지", "국면 · T1"),
    ("11/13~18", "팔로스루 창(랠리 시도 4~7일째) — 코스피 +1.5%↑ + 거래량 증가", "국면"),
    ("11/16·18", "삼성에스디에스 IR — RS 85 이상 유지", "T1"),
    ("11/17 15:30", "GS건설 IR · 동해 DC 착공식 일정", "T1"),
    ("11/18 (미국)", "엔비디아 실적 → 11/19 아침 국내 반도체 반응", "T3"),
    ("매주", "WTI 주간 등락 — +8% 이상 반등이면 T2 무효", "T2"),
    ("수시", "BAAJA 상원 본안 표결 — 통과 시 T1 무효 신호, 전력기기 다시 보기", "T1 · 기각"),
]
chk_html = "".join(f'<li><span class="d">{e(d)}</span><span>{e(t)}</span><span class="tg">{e(g)}</span></li>' for d, t, g in CHK)

SCN = [
    ("강세", 30, "11/13~18 팔로스루 + 외국인 3일 연속 순매수", "준비 4종목(NAVER·삼성에스디에스·삼성E&A·대한항공)의 돌파 신호부터 확인. 신호등 노랑이면 규칙대로 노출 허용"),
    ("기본", 45, "코스피 5,000~5,500 박스, 팔로스루 없음", "관찰 유지. 수직 상승 종목(NHN·LCC)의 첫 눌림(20일선)만 기록"),
    ("약세", 25, "PPI 상회 또는 엔비디아 실망 → 5,018 이탈", "신규 0. 풀을 10종목 이하로 줄이고 T3 폐기 여부 판단"),
]
scn_html = "".join(f'<div><h4>{n} <span class="num">{p}%</span></h4><div class="prob"><i style="width:{p}%"></i></div><dl><dt>트리거</dt><dd>{e(t)}</dd><dt>관찰 풀은</dt><dd>{e(i)}</dd></dl></div>' for n, p, t, i in SCN)

AG6 = f"""
<section class="pad">
  <div class="sh"><span class="no">안건 6</span><h2>결정 — 스코어카드 · 관찰 풀 · 시나리오 · 체크리스트</h2><span class="who">정리: 편집자</span></div>
  <h3 style="font-size:15px;margin-bottom:4px">업종 스코어카드 (4축 0~2점, 합계 순)</h3>
  <p class="muted" style="font-size:13px">점수가 띔보다 먼저다. 1·2위 업종이 T1·T2와 같은지 확인했다.</p>
  <div class="tw"><table class="t">
    <tr><th class="l">업종</th><th>말</th><th>이익</th><th>가격</th><th>돈</th><th>합계</th><th>단계</th><th>행동</th><th class="l wnote">근거</th></tr>
    {sc_rows}
  </table></div>
  <small class="src">말=채널 주별 글 수 · 이익=31일 목표가 상향/하향·실적 · 가격=업종 5/20일 수익률 vs 코스피, 선도주 RS · 돈=외국인·기관 5일 합계 (strategy_prep 11/11 15:11). 연속 매수일은 도구가 아직 세지 않아 합계로만 채점.</small>

  <h3 style="font-size:15px;margin:24px 0 6px">관찰 풀 {len(POOL)}종목</h3>
  <div class="book">
    <div><small>준비</small><b class="num">{n_prep}</b></div>
    <div><small>관찰</small><b class="num">{n_watch}</b></div>
    <div><small>회피 표시</small><b class="num">{n_avoid}</b><br><small>LS ELECTRIC (기각 피치)</small></div>
    <div><small>지난 호에서 뺌</small><b class="num">9</b><br><small>SGC에너지 · 비나텍 · 상신이디피 · 라온텍 · LG에너지솔루션 · 한중엔시에스 · 디아이 · 삼성전기 · 대덕전자 (T3 축소)</small></div>
    <div><small>새로 넣음</small><b class="num">9</b><br><small>NHN · 카카오 · 대한항공 · 진에어 · 제주항공 · 한올바이오파마 · 한미약품 · KT · 삼양식품</small></div>
  </div>
  <div class="tw"><table class="t">
    <tr><th class="l">종목</th><th>띔</th><th class="l">역할</th><th>RS</th><th>1주</th><th>고점 대비</th><th class="l">셋업</th><th class="l">볼 것</th><th>행동</th></tr>
    {pool_rows}
  </table></div>
  <small class="src">RS·1주·고점: strategy_prep 11/11 15:11 · RS '–' 종목은 네이버 일봉 11/11로 계산. 셋업 판정은 감시 목록이 확정한다(모니터링은 지금 중단 중이라 표시만).</small>

  <h3 style="font-size:15px;margin:24px 0 8px">시나리오 (다음 2주)</h3>
  <div class="scn">{scn_html}</div>

  <h3 style="font-size:15px;margin:24px 0 8px">다음 주 체크리스트</h3>
  <ul class="chk">{chk_html}</ul>
</section>
"""

REFS = [
    ("교보증권 「어닝 호조와 함께 밟은 AI DC 확장 엑셀」(NHN) 11/11", "https://stock.naver.com/research/company/98021", "1차 · 원문 확인 (p.1)"),
    ("하나증권 「혼란을 떠나보낼 2027년」(운송) 11/10", "https://stock.naver.com/research/industry/46935", "1차 · 원문 확인 (p.1·p.3)"),
    ("DS투자증권 「BAAJA, 절차표결 통과, 이 앞엔 무엇이 남아있나」 11/11", "https://stock.naver.com/research/industry/46958", "1차 · 원문 확인 (p.1·p.2)"),
    ("유진투자증권 「글로벌 테크 — 조정 이후를 결정할 변수」 11/10", "", "1차 요약 (자료실)"),
    ("유안타증권 「2027 운송 산업전망」 11/06", "", "1차 요약 (자료실)"),
    ("iM증권 「LCC 구하러 온 유가 하락」 11/09", "", "1차 요약 (자료실)"),
    ("대신증권 시장 전략·반도체 11/09·11/10", "", "1차 요약 (리포트 카드)"),
    ("NHN 목표가 변경 7건 · 메모리 목표가 유지 11/11", "", "2차 · 채널 요약"),
    ("채널 정리·리포트 정리 11/06~11/11", "", "2차 · 채널 요약"),
    ("네이버 증권 시세·수급·업종 (비공식) 11/11", "", "데이터"),
    ("Yahoo Finance 미국 지수·금리·환율 11/10~11", "", "데이터"),
    ("strategy_prep prep·score 11/11 15:11", "", "데이터"),
]
refs_html = "".join(f'<li>{e(n)} · {e(t)}</li>' for n, u, t in REFS)

RISKS = [
    "시세는 11/11 장 마감 직후 숫자다. 20일선·1주·1개월·고점 대비는 11/10 종가로 계산한 도구 값이 섞여 있다.",
    "원문 확인은 3건이다(교보 NHN p.1, 하나 운송 p.1·p.3, DS BAAJA p.1·p.2). 나머지는 리포트 카드·자료실 요약(1차 요약)과 채널 요약(2차)이다.",
    "데스크 표결은 한 대화가 역할을 나눠 쓴 결과다. 서로 다른 사람의 표가 아니다.",
    "RS가 '–'인 종목(NHN·항공·바이오 일부)은 감시 목록 계산에 없어 비웠다. 모니터링은 11/04부터 중단 중이다.",
    "KOSPI 선행 PER 3.54배(카드 숫자)는 출처가 섞여 있어 이번 호에서는 쓰지 않았다.",
]
risks_html = "".join(f"<li>{e(r)}</li>" for r in RISKS)
METHOD = "4검증(말·이익·가격·돈)은 축마다 0~2점이다. 말은 채널 주별 글 수, 이익은 31일 목표가 상향·하향과 실적, 가격은 업종 5·20일 수익률과 선도주 RS(코스피 대비 상대 강도 순위, 1~99), 돈은 외국인·기관 5일 합계다. 단계는 초기·확산·과열·소멸로 쓴다. 행동은 준비·관찰·회피 세 가지뿐이다."

APX = f"""
<section class="pad disc">
  <div class="cols">
    <div>
      <h3>이 보고서의 한계</h3>
      <ul style="margin:0;padding-left:16px">{risks_html}</ul>
      <h3 style="margin-top:14px">방법론</h3>
      <p style="margin:0">{e(METHOD)}</p>
    </div>
    <div>
      <h3>주요 출처</h3>
      <ul class="refs">{refs_html}</ul>
    </div>
  </div>
  <p style="margin-top:16px;border-top:1px solid var(--rule);padding-top:12px">본 자료는 개인 투자 공부용으로 만든 내부 자료다. 특정 종목의 매수·매도를 권유하지 않는다. '준비·관찰·회피'는 무엇을 먼저 볼지 정하는 표시다. 실제 매매는 고정된 매매 규칙(docs/rules.md, 2027-01-31까지)과 본인 판단으로 한다. 증권사 리포트 원문은 저장하지 않고 요약과 출처만 적었다.</p>
</section>
<div class="foot"><span>Balance Lab Research · 주간 전략 {e(ISSUE)}</span><span>재료 기간 10/19~11/11 · 시세 {M['at']}</span></div>
</div>
"""

page = fill(STYLE + COVER + AG1 + AG2 + AG3 + AG4 + AG5 + AG6 + APX)

# ---------------- JSON (v3 칸) ----------------
def comp(name, code, role, point, stats, check, action, against=""):
    return {"name": name, "code": code, "role": role, "exposure": "직접", "point": point, "stats": stats, "against": against, "check": check, "action": action}

HEAD = "반등 2일째, 돈은 '덜 오른 곳'을 찾기 시작했다 — 준비는 NAVER·삼성에스디에스·대한항공, 급등주는 관찰"
BULLETS = [
    "국면은 아직 빨강. 코스피 20일선 −6.5%, 6월 고점 대비 −44.2% (네이버 11/10 종가)",
    f"오늘은 반도체가 돌아왔다. 업종 +4.5%(174곳 중 163곳 상승), 코스닥 {M['kosdaq_pct']:+.1f}% (네이버 11/11)",
    "T1 AI 인프라 운영·SW: 업종 5일 +14.0%, 외국인·기관 동반 순매수. NHN 3Q 영업이익 588억(컨센 539억) (도구 · 교보 11/11 p.1, 원문 확인)",
    "NHN은 오늘 장중 89,100 → 종가 80,500원(−9.7%) 반전. 준비는 덜 오른 NAVER·삼성에스디에스 (네이버 11/11)",
    "T2 항공은 대한항공만 준비. 진에어·제주항공은 하나 목표가(7,000·7,500원)를 이미 넘음 (하나 11/10 p.1, 원문 확인)",
    "전력기기 반등론 기각. 업종 5일 −14.9%, BAAJA 연내 통과 확률 20~25% (DS 11/11 p.2, 원문 확인)",
]
THEMES = [
    {"id": "T1", "rank": "메인 띔", "name": "AI 인프라 '미국 밖' 재배치 → 운영·소프트웨어·시공", "stage": "초기→확산", "conviction": 3,
     "thesis": "미국 안에서 데이터센터를 짓기 어려워지면 GPU 임대 가격이 오른다. 국내에서 GPU와 전력을 확보한 플랫폼·클라우드 사업자는 그 값을 받는다. 시장은 이것을 소프트웨어 업종 주가로 먼저 보여 주고 있다.",
     "logic": ["① NHN 3Q 영업이익 588억 원으로 컨센서스 539억 원 상회, AI DC 계획 2027년 말 100MW로 약 30MW 상향, 교보 목표가 64,000→92,000원 (교보 11/11 p.1, 원문 확인)",
               "② GPU 임대가: 아이렌 5년 계약 MW당 연매출 약 2,200만 달러, 상반기 평균 대비 +80% (유진 11/10 카드)",
               "③ 업종 5일 +14.0%·20일 +8.5%, 외국인 +1,726억·기관 +2,248억 (strategy_prep 11/11)",
               "④ 반대: BAAJA 통과 시 미국 송전망 공기 6~10년 → 2년. 다만 레임덕 통과 확률 20~25% (DS 11/11 p.1·p.2, 원문 확인)"],
     "flow": [{"node": "미국 DC 인허가 지연", "status": "확인", "note": "채널 11/06, 3곳"}, {"node": "GPU 임대가 상승", "status": "확인", "note": "유진 11/10"},
              {"node": "국내 GPU 클라우드 매출", "status": "가설", "note": "NHN 2027 1,082억 추정 (교보 p.1)"}, {"node": "플랫폼 전반 재평가", "status": "가설", "note": "IR로 확인"}],
     "evidence": [{"axis": "말", "score": "→", "text": "IT/SW 글 41건, 전주 52건", "trend": [22, 20, 52, 41]},
                  {"axis": "이익", "score": "↑", "text": "NHN 상향 7곳·서프라이즈, 업종 31일 상향 12·하향 26"},
                  {"axis": "가격", "score": "↑", "text": "업종 5일 +14.0%, 20일 +8.5%, 삼성에스디에스 RS 87"},
                  {"axis": "돈", "score": "↑", "text": "외국인 +1,726억·기관 +2,248억 (5일)"}],
     "score": {"talk": 1, "profit": 2, "price": 2, "money": 2, "total": 7},
     "catalysts": [{"date": "2026-11-12", "event": "NAVER IR", "why": "GPU·DC 숫자"}, {"date": "2026-11-16", "event": "삼성에스디에스 IR", "why": "DC 계획"},
                   {"date": "2026-11-17", "event": "GS건설 IR", "why": "동해 DC"}, {"date": "2026-11-18", "event": "엔비디아 실적", "why": "AI 수요"}],
     "companies": [comp("NAVER", "035420", "선도 후보", "외국인 +1,669억·기관 +1,688억(5일)", "RS 54 · 1주 +12.3% · 고점 −36.4%", "11/12 IR 뒤 외국인 순매수 유지", "준비"),
                   comp("삼성에스디에스", "018260", "확산 후보", "하나 240,000→290,000 상향(채널 요약 11/09)", "RS 87 · 1주 +11.7% · 고점 −40.8%", "IR 뒤 RS 85↑", "준비"),
                   comp("삼성E&A", "028050", "확산 후보 (시공)", "3Q 영업이익 5,006억 vs 예상 2,492억, 상향 21·하향 0", "RS 95 · 고점 −2.1%", "67,700원 돌파 + 업종 동행", "준비"),
                   comp("NHN", "181710", "선도", "3Q 서프라이즈, 목표가 7곳 상향", "1주 +64.3% · 오늘 장중 89,100→종가 80,500", "5일 이상 베이스", "관찰", "장중 반전·수직 상승"),
                   comp("카카오", "035720", "후속", "업종 동행", "1주 +8.3% · 고점 −54.2%", "20일선 위 5일", "관찰"),
                   comp("GS건설", "006360", "후속 (시공)", "동해 100MW 착공 기대(하나 카드)", "RS 75 · 1주 +4.5%", "11/17 IR", "관찰"),
                   comp("혜인", "003010", "원천 (비상전력)", "DC 비상발전기(하나 11/09)", "RS 95 · 1주 +26.0%", "수주 공시", "관찰")],
     "against": ["NHN 1주 +64% 뒤 오늘 장중 −10% 반전", "BAAJA 통과 시 미국 안 공급 개선", "반도체로 순환매 복귀 시 자금 이탈", "금리 인상 확률 80%·10년물 5%"],
     "invalid": "IT/SW 업종 20일 수익률이 코스피 아래로 내려가거나, NAVER IR 뒤 외국인 3일 연속 순매도, 또는 BAAJA 상원 본안 통과",
     "horizon": "2027년 상반기 (NHN 6MW 1월 가동)"},
    {"id": "T2", "rank": "서브 띔", "name": "유가 하락 → 항공 이익 추정 상향 (대한항공 중심)", "stage": "확산", "conviction": 2,
     "thesis": "유가가 한 주에 9.5% 빠졌고 원화도 강하다. 비용은 줄고 일본·중국 노선 수요는 버틴다. 2027년 이익 추정치가 오를 자리다. 다만 LCC는 목표가를 이미 넘었다.",
     "logic": ["① 유가가 내릴 때 이익 모멘텀이 더 강하다: 유류할증료보다 유가가 먼저 비용에 반영 (하나 11/10 p.3, 원문 확인)",
               "② 하나 운송 Overweight, 대한항공 TP 41,000원 vs 11/11 31,400원 (하나 p.1, 원문 확인)",
               "③ 진에어 8,110원 > TP 7,000원, 제주항공 7,540원 ≈ TP 7,500원 (하나 p.1 · 네이버 11/11)",
               "④ 업종 20일 +19.9%, 외국인 +848억·기관 +1,761억 (strategy_prep)"],
     "flow": [{"node": "유가 급락", "status": "확인", "note": "WTI 주간 −9.5%"}, {"node": "비용 감소", "status": "가설", "note": "4Q 실적에서 확인"}],
     "evidence": [{"axis": "말", "score": "→", "text": "글 35건, 전주 46건", "trend": [9, 9, 46, 35]}, {"axis": "이익", "score": "→", "text": "31일 상향 18·하향 13"},
                  {"axis": "가격", "score": "↑", "text": "5일 +6.3%, 20일 +19.9%"}, {"axis": "돈", "score": "↑", "text": "외국인 +848억·기관 +1,761억"}],
     "score": {"talk": 1, "profit": 1, "price": 2, "money": 2, "total": 6},
     "companies": [comp("대한항공", "003490", "선도", "하나 Top Pick, TP 41,000", "1주 +5.5% · 고점 −4.3%", "32,800원 돌파 + 유가 하락 유지", "준비"),
                   comp("진에어", "272450", "선도", "일본 노선 강세", "1주 +40.8% · TP 넘음", "첫 눌림 20일선", "관찰", "목표가 초과"),
                   comp("제주항공", "089590", "후속", "중국 노선·원가 개선", "1주 +29.1% · TP 넘음", "첫 눌림 20일선", "관찰", "목표가 도달")],
     "against": ["유가 단일 변수", "LCC 목표가 초과 = 기대 선반영", "동남아·유럽 노선 약세(하나 p.3)"],
     "invalid": "WTI 주간 +8% 이상 반등, 운송 업종 5일 수익률 2주 연속 코스피 하회, 진에어·제주항공 20일선 종가 이탈",
     "horizon": "4Q26 실적 (2027년 2월)"},
    {"id": "T3", "rank": "관찰 띔", "name": "메모리 — 이익 전망은 위, 수급은 아래", "stage": "관찰", "conviction": 1,
     "thesis": "리포트는 2027년 공급 부족이 더 심해진다고 본다. 외국인은 5일 동안 크게 팔았다. 오늘 반등으로 두 종목이 20일선 바로 아래까지 왔다. 매도가 멈추는 날을 기록한다.",
     "logic": ["① 2027 범용 D램 ASP +40% 중후반 가능 (대신 11/10 카드)", "② 외국인 5일 SK하이닉스 −4조 4,880억·삼성전자 −2조 2,146억 (strategy_prep)",
               "③ 오늘 SK하이닉스 +6.6%·삼성전자 +4.3%, 20일선 대비 −2.5%·−4.3% (네이버 11/11 종가)"],
     "flow": [{"node": "외국인 매도 멈춤", "status": "가설", "note": "3일 연속 순매수로 확인"}],
     "evidence": [{"axis": "말", "score": "↓", "text": "글 39건, 4주 전 115건", "trend": [44, 115, 61, 39]}, {"axis": "이익", "score": "→", "text": "하이닉스 상향 4·하향 3"},
                  {"axis": "가격", "score": "↓", "text": "5일 −12.9%, 20일선 아래"}, {"axis": "돈", "score": "↓", "text": "외국인 5일 −4.7조"}],
     "score": {"talk": 0, "profit": 1, "price": 0, "money": 0, "total": 1},
     "companies": [comp("SK하이닉스", "000660", "선도", "메리츠 3,200,000 유지", "RS 85 · 20일선 −2.5%", "20일선 회복 + 외국인 3일", "관찰"),
                   comp("삼성전자", "005930", "선도", "메리츠 500,000 유지", "RS 83 · 20일선 −4.3%", "17만 원 지지", "관찰"),
                   comp("티에프이", "425420", "원천 (테스트)", "3Q 컨센 상회 예상(현대차 11/02)", "RS 97", "RS 95↑", "관찰"),
                   comp("엑시콘", "092870", "원천 (테스트)", "업종 대비 강함", "RS 98", "RS 95↑", "관찰"),
                   comp("심텍", "222800", "후속 (기판)", "3Q 영업이익 1,018억 vs 예상 851억", "RS 90", "20일선 위", "관찰")],
     "against": ["모건스탠리 D램 이익률 60→32%", "장비 목표가 하향 12건"],
     "invalid": "삼성전자 17만 원 종가 이탈 또는 메모리 목표가 하향 3일 연속",
     "horizon": "2027년"},
]
DRAFT = {
    "version": 3, "issue": ISSUE, "title": HEAD, "subtitle": "지수 판단은 팔로스루 뒤로. 수직 상승주보다 고점 근처에서 쉬는 종목을 먼저 준비한다.",
    "made_at": MADE, "period": f"재료 10/19~11/11 · 시세 {M['at']}", "analysts": ["전략가", "반론가", "리스크 매니저", "데이터(도구)"],
    "page": "reports/2026-11-11/strategy.html",
    "conclusion": HEAD,
    "summary": {"headline": HEAD, "bullets": BULLETS,
                "stance": {"regime": "🔴 하락 추세 (코스피 20일선 −6.5%, 11/10 종가) · 랠리 시도 2일째", "exposure": "권장 노출(표시만): 신규 0~소량", "mode": "관찰"},
                "top_sectors": [{"name": g, "score": a + b + c + d, "stage": st, "action": ac} for g, a, b, c, d, st, ac, _ in SC[:5]],
                "changes": ["T1을 'DC·전력'에서 '운영·소프트웨어·시공'으로 좁힘 (전력기기·소형 부품 제외)", "T2 북미 ESS 셀 → 띔에서 내림, 새 T2 항공", "T3 메모리 확신도 2 → 1",
                            "전력기기 반등론 기각 피치로 기록", "관찰 풀: 9종목 새로 넣고 9종목 뺌 (LS ELECTRIC은 회피 표시로 남김)"]},
    "regime": {"title": "빨강 유지 · 랠리 시도 2일째", "numbers": [{"label": "코스피 20일선 대비", "value": "−6.5%", "note": "11/10 종가"}, {"label": "코스피", "value": f"{M['kospi']} ({M['kospi_pct']:+.2f}%)", "note": M["at"]},
               {"label": "외국인 코스피", "value": M["f_kospi"], "note": M["at"]}, {"label": "신고가/신저가", "value": f"{M['nh']}/{M['nl']}", "note": M["at"]}],
               "body": ["외국인 이틀 연속 순매수, 신고가가 신저가의 약 3배", "지수는 20일선 아래, 코스닥 외국인 순매도"],
               "phase": "급락 → 랠리 시도 2일째 / 팔로스루 확인 전",
               "what_flips": "11/13~18 코스피 +1.5%↑ + 거래량 증가, 20일선 위 종가, 외국인 3일 연속 순매수. 5,018.85 이탈 시 랠리 시도 무효"},
    "themes": THEMES,
    "rejected": {"name": "전력기기 반등 1순위", "why": "업종 5일 −14.9%, LS ELECTRIC RS 16, 하향 11·상향 0, BAAJA 연내 통과 확률 20~25%(DS p.2)", "revisit": "RS 50 회복·업종 5일 코스피 상회·BAAJA 상원 통과"},
    "sector_scorecard": [{"group": g, "talk": a, "profit": b, "price": c, "money": d, "total": a + b + c + d, "stage": st, "action": ac, "note": n} for g, a, b, c, d, st, ac, n in SC],
    "pool": [{"name": n, "code": c, "theme": t, "role": r, "rs": rs, "r1w": w, "off_high": h, "setup": st, "watch_for": wf, "action": a} for n, c, t, r, rs, w, h, st, wf, a in POOL],
    "scenarios": [{"name": n, "prob": f"{p}%", "trigger": t, "implication": i} for n, p, t, i in SCN],
    "watch": [{"name": "음식료", "status": "🔥 말이 앞섬", "why": "글 +161%, 주가 +2.5%"}, {"name": "화학", "status": "⚠️ 말이 앞섬", "why": "글 +400%, 하향 22"},
              {"name": "IT/소프트웨어", "status": "🤫 조용히 오름", "why": "글 −21%, 5일 +14%"}],
    "portfolio": {"title": "내 보유 종목과 띔의 정렬", "rows": [], "note": "보유 0, CR 0%"},
    "scorecard": [
        {"made": "2026-11-09", "hypothesis": "T1 미국 DC 규제 → 한국 DC·전력", "status": "진행", "numbers": "혜인 +26.0%, NAVER +12.3%, 삼성에스디에스 +11.7% / LS ELECTRIC −20.8%", "note": "절반 맞음: 운영·SW는 오르고 전력기기는 빠짐"},
        {"made": "2026-11-09", "hypothesis": "T2 북미 ESS 셀", "status": "틀림", "numbers": "삼성SDI −13.5%, LG에너지솔루션 −6.4%", "note": "이익 서프라이즈보다 AI 인프라 베타로 거래"},
        {"made": "2026-11-09", "hypothesis": "T3 메모리 바닥론", "status": "진행", "numbers": "삼성전자 −7.1%, SK하이닉스 −10.1%, 무효 조건 미발동(205,750원)", "note": "외국인 매도 멈춤을 먼저 봐야 함"},
        {"made": "2026-11-09", "hypothesis": "체크포인트 BAAJA 절차표결", "status": "맞음", "numbers": "11/09 클로처 73:25 (DS 11/11 p.2)", "note": "레임덕 통과 확률 20~25%"}],
    "checkpoints": [f"{d} {t}" for d, t, _ in CHK],
    "calendar": [{"date": "2026-11-12", "event": "NAVER IR", "relevance": "T1"}, {"date": "2026-11-13", "event": "미국 PPI", "relevance": "국면"},
                 {"date": "2026-11-16", "event": "삼성에스디에스 IR", "relevance": "T1"}, {"date": "2026-11-17", "event": "GS건설 IR", "relevance": "T1"}, {"date": "2026-11-18", "event": "엔비디아 실적", "relevance": "T3"}],
    "risks": RISKS, "method": METHOD,
    "references": [{"name": n, "url": u, "type": t} for n, u, t in REFS],
    "agents": [{"role": "리스크 매니저", "did": "국면·랠리 일지·계좌"}, {"role": "매크로", "did": "금리·유가·환율"}, {"role": "플로우", "did": "채널 흐름·수급"},
               {"role": "리서치", "did": "카드 166장·원문 3건"}, {"role": "전략가", "did": "띔 3개·기각 1개"}, {"role": "반론가", "did": "반론·사전 부검·채점"}],
    "sources": {"reports": 166, "originals": 3, "memos": 4, "data": f"네이버 {M['at']} · Yahoo 11/10"},
}

# ---------------- 텔레그램 요약 ----------------
TG = "\n".join([
    f"📊 전략 보고서 {ISSUE} (11/11 수, 새 양식 첫 호)",
    f"💡 {HEAD}",
    "",
    "핵심",
    *[f"- {b}" for b in BULLETS[:5]],
    "",
    f"국면: 🔴 하락 추세 · 랠리 시도 2일째 · 권장 노출(표시만) 신규 0~소량",
    f"오늘: 코스피 {M['kospi']}({M['kospi_pct']:+.2f}%), 코스닥 {M['kosdaq']}({M['kosdaq_pct']:+.2f}%), 외국인 코스피 {M['f_kospi']} ({M['at']}, 수급 잠정, 네이버)",
    "",
    "상위 업종 (4검증 점수)",
    *[f"- {g} {a + b + c + d}/8 · {ac}" for g, a, b, c, d, st, ac, _ in SC[:4]],
    "",
    "이번 회의의 결정",
    "- 준비: NAVER · 삼성에스디에스 · 삼성E&A · 대한항공",
    "- 관찰: NHN · 진에어 · 제주항공 · SK하이닉스 · 삼성전자",
    "- 회피: 전력기기 · 반도체 기판 · 화학 · 증권",
    "",
    "지난 호 대비",
    "- T1을 운영·소프트웨어·시공으로 좁힘 (전력기기 제외)",
    "- 북미 ESS 띔 내림, 항공 새로 · 메모리 확신도 2→1",
    "",
    "다음 주: 11/12 NAVER IR · 11/13 미 PPI · 11/13~18 팔로스루 창 · 11/18 엔비디아",
    f"관찰 풀 {len(POOL)}종목 · 전체 보고서: https://claude.ai/artifact/7MjetxpGd9tuniuTok1ZmS",
    "원문 확인 3건(교보·하나·DS, 쪽수 표기), 나머지는 요약·채널 요약",
    "범례: 준비/관찰/회피는 볼 순서 표시 (매수·매도 권유 아님) · 규칙 고정 ~2027-01-31",
])

# ---------------- 읽기용 마크다운 ----------------
MD = [f"# 주간 전략 {ISSUE}", f"_{MADE} · 시세 {M['at']}_", "", f"## 결론\n{HEAD}", "", *[f"- {b}" for b in BULLETS], "",
      "## 국면", DRAFT["regime"]["phase"], "", f"바뀌는 조건: {DRAFT['regime']['what_flips']}", ""]
for th in THEMES:
    MD += [f"## {th['id']} {th['name']} (확신 {th['conviction']}/5, 점수 {th['score']['total']}/8)", th["thesis"], "", *[f"- {l}" for l in th["logic"]], "",
           "| 종목 | 역할 | 숫자 | 볼 것 | 행동 |", "|---|---|---|---|---|", *[f"| {c['name']} | {c['role']} | {c['stats']} | {c['check']} | {c['action']} |" for c in th["companies"]], "",
           f"무효: {th['invalid']}", ""]
MD += ["## 기각: 전력기기", DRAFT["rejected"]["why"], "", "## 업종 스코어카드", "| 업종 | 말 | 이익 | 가격 | 돈 | 합계 | 행동 |", "|---|---|---|---|---|---|---|",
       *[f"| {g} | {a} | {b} | {c} | {d} | {a + b + c + d} | {ac} |" for g, a, b, c, d, st, ac, _ in SC], "",
       "## 관찰 풀", "| 종목 | 띔 | RS | 1주 | 고점 대비 | 볼 것 | 행동 |", "|---|---|---|---|---|---|---|",
       *[f"| {n} | {t} | {rs if rs is not None else '–'} | {w:+.1f}% | {h:+.1f}% | {wf} | {a} |" for n, c, t, r, rs, w, h, st, wf, a in POOL], "",
       "## 시나리오", *[f"- {n} {p}%: {t} → {i}" for n, p, t, i in SCN], "", "## 지난 가설 채점", *[f"- {x['hypothesis']}: {x['status']} — {x['numbers']}" for x in DRAFT["scorecard"]], "",
       "## 체크리스트", *[f"- {c}" for c in DRAFT["checkpoints"]], "", "## 한계", *[f"- {r}" for r in RISKS], "", "## 출처", *[f"- {n} · {t}" for n, u, t in REFS], "",
       "매수·매도 권유가 아니다. 판단은 본인이 한다."]

OUTD.mkdir(parents=True, exist_ok=True)
(OUTD / "strategy.html").write_text(page, encoding="utf-8")
(OUTD / "strategy.md").write_text("\n".join(MD), encoding="utf-8")
(OUTD / "strategy_tg.md").write_text(TG, encoding="utf-8")
(ROOT / "data" / "strategy" / "draft.json").write_text(json.dumps(DRAFT, ensure_ascii=False, indent=1), encoding="utf-8")
print(json.dumps({"html": len(page), "json": len(json.dumps(DRAFT, ensure_ascii=False)), "tg_lines": TG.count("\n") + 1, "pool": len(POOL)}, ensure_ascii=False))
