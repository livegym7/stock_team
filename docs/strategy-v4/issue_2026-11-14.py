# 전략 보고서 제4호 (2026-11-14 토, 정기 발간) — 숫자·문장은 이 파일에만 두고 JSON·HTML·마크다운·텔레그램 요약을 함께 만든다.
# 다음 호: 이 파일을 복사해 DAY·M·SECT·RALLY·SC·POOL·PITCHES·본문 문장만 바꾼다. 어투는 '~입니다'(2026-11-13 사용자 확정).
# 실행: python3 docs/strategy-v4/issue_2026-11-14.py → data/strategy/draft.json, reports/2026-11-14/strategy.html·.md·_tg.md
import html, json, pathlib, re

ROOT = pathlib.Path(__file__).resolve().parents[2]
DAY = "2026-11-14"
OUTD = ROOT / "reports" / DAY
ART = "https://claude.ai/artifact/7MjetxpGd9tuniuTok1ZmS"
e = html.escape

M = dict(at="11/13(금) 종가", kospi="5,290.53", kospi_pct=-0.98, kosdaq="699.66", kosdaq_pct=0.45, up=454, down=420, nh=79, nl=81,
         f_kospi="−5,419억", i_kospi="−59억", gap20="−4.5%", w1="+4.6%", m1="−4.7%", off="−43.6%")
ISSUE = "제4호 · 2026-11-14(토)"
MADE = "2026-11-14 09:40"

# ---------------- 헬퍼 ----------------
def act(a):
    cls = {"준비": "a-prep", "관찰": "a-watch", "회피": "a-avoid", "보유": "a-prep"}[a]
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
SECT = [("광통신", 29.14), ("반도체 소재·부품", 21.66), ("반도체 테스트·후공정", 21.23), ("반도체 장비", 16.53), ("전력기기", 11.13), ("건설", 9.11),
        ("의류/패션", -4.14), ("IT/소프트웨어", -3.65), ("화장품", -5.09), ("신재생에너지", -5.52), ("유통", -6.10), ("게임", -11.40)]
SECT[6], SECT[7] = SECT[7], SECT[6]

def chart_sect():
    W, LW, RH, top = 680, 150, 24, 22
    lo = min(-12.0, min(v for _, v in SECT) - 2); hi = max(v for _, v in SECT) + 6
    pw = W - LW - 50
    x = lambda v: LW + (v - lo) / (hi - lo) * pw
    H = top + RH * len(SECT) + 26
    o = [f'<svg viewBox="0 0 {W} {H}" role="img" aria-label="업종 5일 수익률 위·아래 6개" class="chart">']
    for t in (-10, 0, 10, 20, 30):
        if lo <= t <= hi:
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
RALLY = [("11/09", "−0.81%", "dn", "저점 5,018.85"), ("11/10", "+4.39%", "up", "랠리 시도 D1"), ("11/11", "+2.60%", "up", "D2"),
         ("11/12", "−0.61%", "dn", "D3"), ("11/13", "−0.98%", "dn", "D4 · 장중 +2.19% 반납"), ("11/16~18", "?", "wait", "D5~D7 남은 창")]
rally_html = '<ol class="rally">' + "".join(f'<li class="{c}"><b class="num">{d}</b><span class="num">{r}</span><small>{e(t)}</small></li>' for d, r, c, t in RALLY) + "</ol>"

# ---------------- 업종 스코어카드 (점수가 띔보다 먼저) ----------------
SC = [
    ("운송/물류 (항공)", 2, 2, 1, 2, "확산", "준비", "글 53건(전주 21건). 제주항공 3Q 영업이익 549억(예상 145억). 20일 +18.0%, 외국인 +1,420억·기관 +346억"),
    ("건설 (국내 DC·반도체 팹)", 2, 1, 2, 1, "확산", "준비", "5일 +9.1%·20일 +15.4%. 삼성E&A 고점 −0.4%. 하나 건설 Overweight(11/13). 외국인 −519억·기관 +919억"),
    ("반도체(메모리·대형)", 2, 0, 2, 2, "초기", "관찰", "5일 +6.6%·20일 −3.2%로 코스피 앞섬. 외국인 +1,146억·기관 +2,620억. 다만 목표가 하향 9 > 상향 1"),
    ("K-엔터", 2, 1, 1, 2, "초기", "관찰", "글 2주 연속 증가(47→55건). JYP 3Q 역대 최대. 5일 +6.3%, 20일 −7.2%"),
    ("반도체 장비·테스트·소재", 2, 1, 1, 1, "초기", "관찰", "5일 +16~22%로 1위권. 3Q 서프라이즈 4곳(채널 요약). 20일은 아직 −13~−18%. 외국인 −1,954억"),
    ("IT/소프트웨어", 2, 1, 1, 1, "소멸", "관찰", "⚠️ 글은 +33%인데 5일 −3.7%. NAVER IR 뒤 목표가 하향 9곳"),
    ("바이오", 1, 1, 1, 2, "–", "관찰", "20일 +5.7%. 외국인 +870억·기관 +1,198억. 5일은 −1.5%"),
    ("은행", 1, 1, 1, 1, "방어", "관찰", "20일 −2.1%로 코스피보다 나음. 외국인 +1,539억, 기관 −1,114억"),
    ("통신서비스", 0, 1, 1, 2, "방어", "관찰", "20일 +4.2%. 외국인·기관 동반 순매수. 말은 조용함"),
    ("전력기기", 1, 0, 1, 1, "반등", "관찰", "5일 +11.1%로 반등. 외국인 +1,247억. 다만 20일 −16.1%, 하향 49·상향 3"),
    ("증권", 2, 0, 0, 1, "–", "회피", "글 571건으로 최다. 31일 하향 727건. 20일 −10.9%"),
    ("화장품", 2, 0, 0, 0, "소멸", "회피", "⚠️ 글 +152%인데 5일 −5.1%·20일 −17.9%. 하향 20 > 상향 9"),
    ("게임", 2, 0, 0, 0, "소멸", "회피", "⚠️ 글 +83%인데 5일 −11.4%로 꼴찌. 하향 19"),
    ("2차전지", 0, 0, 0, 1, "–", "회피", "글 −58%, 20일 −15.0%"),
]
SC.sort(key=lambda r: -(r[1] + r[2] + r[3] + r[4]))
sc_rows = "".join(
    f'<tr><td class="l"><b>{e(g)}</b><small class="mnote">{e(n)}</small></td><td>{dots(a)}</td><td>{dots(b)}</td><td>{dots(c)}</td><td>{dots(d)}</td>'
    f'<td class="num tot">{a + b + c + d}</td><td>{e(st)}</td><td>{act(ac)}</td><td class="l wnote">{e(n)}</td></tr>' for g, a, b, c, d, st, ac, n in SC)

# ---------------- 관찰 풀 ----------------
# (이름, 코드, 띔, 역할, RS, 1주, 고점대비, 셋업, 볼 것, 행동)
POOL = [
    ("삼성E&A", "028050", "T1", "선도(플랜트·팹)", 95, 13.2, -0.4, "돌파 대기 (기준가 69,700)", "11/17 IR 뒤 준비 후보. 69,700 돌파 때 거래대금 + 업종 동행", "관찰"),
    ("GS건설", "006360", "T1", "선도(DC·주택)", 76, 6.2, -29.4, "베이스 형성 중 (단기 고점 32,750)", "11/17 IR 뒤 준비 후보. 32,750 돌파", "관찰"),
    ("계룡건설", "013580", "T1", "후속(공공주택)", None, 14.5, -18.3, "셋업 없음 · 급등", "첫 눌림에서 20일선", "관찰"),
    ("대한항공", "003490", "T2", "선도", 89, 7.1, -3.7, "돌파 대기 (기준가 32,800)", "32,800 돌파 + WTI 주간 하락 유지", "준비"),
    ("제주항공", "089590", "T2", "후속", 95, 7.2, -13.2, "셋업 없음 · 눌림 중", "3Q 서프라이즈 뒤 20일선 지지", "관찰"),
    ("진에어", "272450", "T2", "후속", 92, 30.3, -9.0, "셋업 없음 · 눌림 중", "20일선(약 6,160원) 지지", "관찰"),
    ("삼성전자", "005930", "T3", "선도", 83, 8.0, -44.2, "셋업 없음 · 20일선 −2.7%", "20일선 종가 회복 + 외국인 3일 순매수", "관찰"),
    ("SK하이닉스", "000660", "T3", "선도", 85, 4.8, -58.7, "셋업 없음 · 20일선 −5.8%", "20일선 종가 회복", "관찰"),
    ("티에프이", "425420", "T3", "원천(테스트) ⭐보유", 98, 41.8, -0.9, "보유 중 · 3R까지 +6.2%", "3R 97,588원 도달 시 규칙대로 절반 익절·본전 손절", "보유"),
    ("엑시콘", "092870", "T3", "원천(테스트)", 99, 40.1, -8.1, "셋업 없음 · 급등", "3Q 서프라이즈 뒤 첫 눌림", "관찰"),
    ("피에스케이홀딩스", "031980", "T3", "장비", None, 22.6, -31.0, "셋업 없음 · 20일선 −6.5%", "하나 Top Pick(11/12). 20일선 회복", "관찰"),
    ("이오테크닉스", "039030", "T3", "장비", None, 22.2, -42.5, "셋업 없음 · 20일선 −5.3%", "3Q 서프라이즈 뒤 20일선 회복", "관찰"),
    ("심텍", "222800", "T3", "기판", 90, 29.3, -30.8, "셋업 없음", "20일선 위 유지", "관찰"),
    ("이수페타시스", "007660", "T3", "기판(TPU)", None, 40.9, -44.6, "셋업 없음 · 급등", "TPU 반사이익은 전망(삼성증권, 채널 요약)", "관찰"),
    ("삼성에스디에스", "018260", "T4", "운영·SW", 88, 9.5, -39.4, "베이스 형성 중 (단기 고점 240,000)", "IR(11/16·18)이 끝난 뒤 판단. 이벤트 직전 준비는 하지 않음", "관찰"),
    ("NHN", "181710", "T4", "운영·SW", 98, 14.9, -25.5, "셋업 없음 · 89,100 고점 뒤 −25%", "베이스가 생기는지", "관찰"),
    ("JYP Ent.", "035900", "–", "K-엔터 ⭐보유", None, 8.0, -49.8, "보유 중 · 손절가까지 −6.8%", "손절가 41,446원", "보유"),
    ("하이브", "352820", "–", "K-엔터", None, 7.1, -61.5, "셋업 없음 · 20일선 −2.9%", "20일선 회복", "관찰"),
    ("한올바이오파마", "009420", "–", "바이오", None, 41.5, -29.7, "셋업 없음 · 급등", "첫 눌림에서 20일선", "관찰"),
    ("KB금융", "105560", "–", "은행", None, 3.8, -18.8, "셋업 없음", "업종 20일 수익률이 코스피 위 유지", "관찰"),
    ("LS ELECTRIC", "010120", "–", "전력기기", 16, 5.0, -62.7, "이탈 · 20일선 −13.9%", "RS 50 회복 · BAAJA 상원 통과", "관찰"),
    ("일진전기", "103590", "–", "전력기기", None, 30.4, -60.7, "셋업 없음 · 급반등", "20일선 위 유지", "관찰"),
    ("NAVER", "035420", "기각", "인터넷", 54, -8.0, -42.9, "이탈 · 20일선 −3.2%", "목표가 하향 9곳. 베이스 다시 생길 때까지 보지 않음", "회피"),
]
pool_rows = "".join(
    f'<tr><td class="l"><b>{e(n)}</b> <small class="num muted">{c}</small></td><td>{t}</td><td class="l">{e(r)}</td>'
    f'<td class="num">{rs if rs is not None else "–"}</td><td>{pc(w)}</td><td>{pc(h)}</td>'
    f'<td class="l">{e(st)}</td><td class="l">{e(wf)}</td><td>{act(a)}</td></tr>' for n, c, t, r, rs, w, h, st, wf, a in POOL)
cnt = lambda a: sum(1 for p in POOL if p[-1] == a)

STYLE = (pathlib.Path(__file__).with_name("style.html").read_text(encoding="utf-8").replace("<title>Balance Lab 주간 전략 샘플</title>", "<title>Balance Lab 주간 전략</title>"))

# ---------------- 표지 ----------------
HEAD = "돈은 반도체 장비·건설로 옮겨 갔습니다 — 건설은 IR(11/17) 뒤 준비 후보, 지금 준비는 대한항공 하나입니다"
SUB = "랠리 시도는 4일째까지 팔로스루 없이 살아 있습니다. 남은 사흘(11/16~18)은 엔비디아 실적과 겹칩니다. 지난 호에서 배운 대로 IR·실적 직전 종목은 준비에 넣지 않습니다."
BULLETS = [
    ("국면은 아직 빨강입니다.", f"코스피는 20일선보다 4.5% 아래입니다. 11/13 신저가(81)가 신고가(79)보다 많았습니다.", "(네이버 11/13 종가)"),
    ("지난 호 메인 띔(운영·소프트웨어)은 틀렸습니다.", "준비로 꼽은 NAVER가 IR 뒤 10.2% 빠졌습니다. 목표가 하향은 9곳입니다. 이번 호에서 관찰 띔으로 내립니다.", "(네이버 일봉 · 채널 리포트 요약 11/13)"),
    ("새 T1은 국내 데이터센터·반도체 팹 건설입니다.", "업종 5일 +9.1%, 20일 +15.4%입니다. 하나증권은 데이터센터 4GW, 30조~40조 원 수주를 전망했습니다.", "(도구 · 하나 11/13 p.2, 원문 확인)"),
    ("항공(T2)은 스코어카드 1위라 유지합니다.", "제주항공 3Q 영업이익은 549억 원으로 예상 145억 원의 3.8배입니다. 대한항공은 고점 −3.7%입니다.", "(채널 리포트 요약 · 네이버 11/13)"),
    ("반도체는 확신도를 1에서 2로 올립니다.", "업종이 5일 +6.6%이고 외국인·기관이 함께 샀습니다. 하나증권 원문은 2028년까지 수급이 타이트하다고 봅니다.", "(도구 · 하나 11/12 p.2, 원문 확인)"),
    ("지난 호 기각한 전력기기는 5일 +11.1%로 반등했습니다.", "기각 판단은 가격으로는 일렀습니다. 다만 20일선 아래라 '회피'에서 '관찰'로만 바꿉니다.", "(도구 11/14)"),
]
sum_html = "".join(f'<li><span><b>{e(a)}</b> {e(b)} {s(c)}</span></li>' for a, b, c in BULLETS)

COVER = f"""
<div class="paper">
<div class="mast">
  <div class="brand"><span class="logo">B</span>Balance Lab Research · 주간 전략</div>
  <div>{ISSUE} · 정기 발간 · {M['at']} 기준</div>
</div>
<div class="cover">
  <aside class="meta">
    <div>
      <h4>시장 판단 (데스크 결론)</h4>
      <div class="rating">
        <div class="big">관찰</div>
        <div class="sig"><i></i>신호등 빨강 · 하락 추세</div>
        <small class="muted">권장 노출(표시만): 신규 0~소량<br>랠리 시도 4일째 · 남은 창 11/16~18</small>
      </div>
    </div>
    <div>
      <h4>KEY DATA</h4>
      <table class="kd">
        <tr><td>코스피</td><td class="num">{M['kospi']} <span class="down">{M['kospi_pct']:+.2f}%</span></td></tr>
        <tr><td>코스피 1주</td><td class="num up">{M['w1']}</td></tr>
        <tr><td>20일선 대비</td><td class="num down">{M['gap20']}</td></tr>
        <tr><td>6월 고점 대비</td><td class="num down">{M['off']}</td></tr>
        <tr><td>오른/내린 종목</td><td class="num">{M['up']} / {M['down']}</td></tr>
        <tr><td>신고가/신저가</td><td class="num">{M['nh']} / {M['nl']}</td></tr>
        <tr><td>외국인 코스피</td><td class="num down">{M['f_kospi']}</td></tr>
        <tr><td>미 10년물</td><td class="num">5.15%</td></tr>
      </table>
      <small class="src">네이버 11/13 종가·확정 수급 · 미 10년물 Yahoo 11/13</small>
    </div>
    <div>
      <h4>참여 데스크</h4>
      <ul class="team">
        <li><b>리스크 매니저</b> 국면·규칙</li>
        <li><b>매크로</b> 금리·미국</li>
        <li><b>플로우</b> 채널 흐름·수급</li>
        <li><b>리서치</b> 카드 218장·원문 3건</li>
        <li><b>전략가</b> 띔 피치</li>
        <li><b>반론가</b> 채점·반대 근거</li>
      </ul>
      <small class="src">한 대화가 역할을 바꿔 가며 씀</small>
    </div>
  </aside>
  <div class="main">
    <div class="eyebrow">INVESTMENT STRATEGY · WEEKLY</div>
    <h1 class="title">돈은 반도체 장비·건설로 옮겨 갔습니다<br>— 건설은 IR 뒤 준비 후보, 지금 준비는 대한항공 하나입니다</h1>
    <p class="subtitle">{e(SUB)}</p>
    <ul class="sum">{sum_html}</ul>
    <div class="decision">
      <h3>이번 회의의 결정 — 행동은 준비·관찰·회피 세 가지로만 씁니다</h3>
      <div class="dgrid">
        <div><h4>{{{{ACT:준비}}}} 셋업 생기면 바로 봅니다</h4><ul><li>대한항공 (T2, 고점 −3.7%, 기준가 32,800)</li><li>IR(11/17) 통과 뒤 준비 후보: 삼성E&amp;A (고점 −0.4%) · GS건설</li></ul></div>
        <div><h4>{{{{ACT:관찰}}}} 조건이 맞을 때까지</h4><ul><li>삼성전자 · SK하이닉스 (T3, 20일선 회복 전)</li><li>엑시콘 · 피에스케이홀딩스 · 이오테크닉스</li><li>삼성에스디에스 (IR 뒤 판단) · 전력기기</li></ul></div>
        <div><h4>{{{{ACT:회피}}}} 지금은 손대지 않습니다</h4><ul><li>NAVER (IR 뒤 이탈, 하향 9곳)</li><li>게임 · 화장품 (말만 많음)</li><li>증권 · 2차전지</li></ul></div>
      </div>
      <div class="dnote">새 매수는 규칙상 '돌파 신호 + 인더스트리 액션'이 먼저입니다. 이 표는 무엇을 먼저 볼지 정하는 순서표입니다. 매수·매도 권유가 아니며 판단은 본인이 합니다.</div>
    </div>
  </div>
</div>
<div class="pad" style="padding-top:20px;padding-bottom:20px">
  <ol class="agenda">
    <li><b>국면 점검</b><span>무엇을 할 수 있는 장인가</span></li>
    <li><b>지난 가설 채점</b><span>11/11 띔 3개는 맞았나</span></li>
    <li><b>데스크 보고</b><span>매크로·플로우·리서치</span></li>
    <li><b>아이디어 피치</b><span>띔 4개 + 기각 1개</span></li>
    <li><b>반론 라운드</b><span>틀린다면 왜 틀리나</span></li>
    <li><b>결정</b><span>스코어카드·관찰 풀·시나리오</span></li>
  </ol>
</div>
"""

AG1 = f"""
<section class="pad">
  <div class="sh"><span class="no">안건 1</span><h2>국면 점검 — 추세추종을 해도 되는 장인가</h2><span class="who">발표: 리스크 매니저</span></div>
  <p class="lead">아직 아닙니다. 한 주로는 +4.6%였지만 목·금 이틀 연속 밀렸습니다. 랠리 시도는 살아 있고 남은 창은 사흘입니다.</p>
  <div class="kpis">
    <div><small>코스피 20일선 대비</small><b class="num down">{M['gap20']}</b><em>11/13 종가 (지난 호 −6.5%)</em></div>
    <div><small>코스피 1주 / 1개월</small><b class="num">{M['w1']} / {M['m1']}</b><em>11/13 종가</em></div>
    <div><small>외국인 코스피</small><b class="num">3일 순매수 → {M['f_kospi']}</b><em>11/10~12 → 11/13</em></div>
    <div><small>신고가 / 신저가</small><b class="num">{M['nh']} / {M['nl']}</b><em>코스피 11/13 (지난 호 76/26)</em></div>
    <div><small>미 10년물</small><b class="num down">5.15%</b><em>Yahoo 11/13, 한 주 +0.29%p</em></div>
    <div><small>필라델피아 반도체</small><b class="num down">−3.43%</b><em>Yahoo 11/13 종가</em></div>
  </div>
  <h3 style="font-size:14px;margin-bottom:2px">랠리 시도 일지 (오닐 방식: 1일째 뒤 4~7일째에 거래량 실린 강한 상승 = 팔로스루)</h3>
  {rally_html}
  <div class="cols">
    <div>
      <p><b>좋아진 것.</b> 외국인이 11/10~12 사흘 연속 코스피를 샀습니다. 지난 호가 꼽은 조건 ③이 한 번은 채워졌습니다. 11/09 저점 5,018.85는 지켜졌습니다.</p>
      <p><b>나빠진 것.</b> 11/13 신저가 종목(81)이 신고가(79)보다 많아졌습니다. 외국인은 다시 {M['f_kospi']}을 팔았습니다. 금요일 밤 필라델피아 반도체는 −3.43%였습니다. {s('(네이버 · Yahoo 11/13)')}</p>
    </div>
    <div>
      <p><b>내 계좌.</b> 티에프이(+2.10R)와 JYP Ent.(−0.17R)를 보유 중입니다. CR은 1.33%로 한도 6% 안입니다. {s('(risk.py 11/14 09:12)')}</p>
      <p>종료한 6건은 모두 손실입니다(합계 −7.48R). 이번 주 NAVER가 1R에서 정리됐습니다. '연속 손절 3건 뒤 쉬기'는 <b>표시만</b> 합니다. 규칙은 2027-01-31까지 고정입니다. {s('(trades.py review)')}</p>
    </div>
  </div>
  <div class="flip"><b>국면이 바뀌는 조건.</b> ① 11/16~18 중 코스피 +1.5% 이상 + 전날보다 많은 거래량(팔로스루) ② 코스피 종가가 20일선 위 ③ 외국인 3일 연속 순매수 재개. ①+②면 신호등 노랑으로 봅니다. 11/09 종가 5,018.85를 깨면 랠리 시도는 무효이고 새 바닥을 다시 셉니다.</div>
</section>
"""

AG2 = f"""
<section class="pad">
  <div class="sh"><span class="no">안건 2</span><h2>지난 가설 채점 — 11/11 호의 띔 3개</h2><span class="who">발표: 반론가 (strategy_prep score · 네이버 일봉)</span></div>
  <p class="lead">'관찰'로 둔 급등주 판단은 맞았습니다. '준비'로 꼽은 NAVER는 틀렸습니다. 이벤트(IR) 직전 종목을 준비에 넣은 것이 원인입니다.</p>
  <div class="tw"><table class="t">
    <tr><th class="l">지난 띔 (11/11)</th><th>판정</th><th class="l">숫자 (11/11 종가 → 11/13 종가, 코스피 −1.4%)</th><th class="l">배운 것</th></tr>
    <tr><td class="l"><b>T1 운영·소프트웨어</b><br><small class="muted">확신 3</small></td><td><span class="st no">틀림</span></td>
      <td class="l wrap">준비: NAVER −10.2% · 삼성에스디에스 +2.0% · 삼성E&amp;A +3.9% / 관찰: NHN −17.5% · GS건설 +3.5%. 업종 5일 −3.7%</td>
      <td class="l wrap">IR 하루 전 종목을 준비에 넣었습니다. 이번 호부터 IR·실적 직전 종목은 '이벤트 뒤 판단'으로 둡니다.</td></tr>
    <tr><td class="l"><b>T2 항공 (대한항공 중심)</b><br><small class="muted">확신 2</small></td><td><span class="st ok">맞음(진행)</span></td>
      <td class="l wrap">대한항공 +0.3% · 진에어 −4.1% · 제주항공 −9.0%. 업종 20일 +18.0%</td>
      <td class="l wrap">'LCC는 목표가를 넘었으니 관찰'이 맞았습니다. 준비로 둔 대한항공은 고점 −3.7%에서 버팁니다.</td></tr>
    <tr><td class="l"><b>T3 메모리 관찰</b><br><small class="muted">확신 1</small></td><td><span class="st mid">진행</span></td>
      <td class="l wrap">삼성전자 +0.6%(이후 209,000원) · SK하이닉스 −4.3%. 테스트 장비 티에프이 +15.5% · 엑시콘 +5.7%</td>
      <td class="l wrap">메모리 본체보다 장비·테스트가 먼저 움직였습니다. 무효 조건(삼성전자 17만 원 이탈)은 아닙니다.</td></tr>
    <tr><td class="l"><b>기각: 전력기기</b></td><td><span class="st no">일렀음</span></td>
      <td class="l wrap">업종 5일 +11.1% · 일진전기 1주 +30.4% · LS ELECTRIC +5.0%(20일선 −13.9%)</td>
      <td class="l wrap">가격은 기각 직후 반등했습니다. 다만 20일선 아래라 규칙상 셋업은 아닙니다.</td></tr>
    <tr><td class="l"><b>무효 조건 'BAAJA 상원 통과'</b></td><td><span class="st no">잘못 설정</span></td>
      <td class="l wrap">신한은 BAAJA를 "숨겨진 AI 투심 회복의 카드"로 봤습니다. 최종 표결은 다음 주 추진입니다. {s('(신한 11/13 p.1·p.2, 원문 확인)')}</td>
      <td class="l wrap">시장은 이 법을 '미국 안 공급 개선 = AI 호재'로 읽습니다. T1 무효 조건으로 쓴 것은 방향이 틀렸습니다. 이번 호에서 뺍니다.</td></tr>
  </table></div>
  <small class="src">출처: strategy_prep score 11/14 09:08, 네이버 일봉 11/13 종가. 내 매매의 NAVER(11/11 193,900원 → 11/13 178,300원, −1.01R)는 trades.py 기록입니다.</small>
</section>
"""

AG3 = f"""
<section class="pad">
  <div class="sh"><span class="no">안건 3</span><h2>데스크 보고 — 세 출처가 같은 방향을 가리키는가</h2><span class="who">매크로 · 플로우 · 리서치</span></div>
  <div class="cols">
    <div class="desk">
      <h3>매크로 데스크</h3><div class="role">금리 · 물가 · 미국 일정</div>
      <ul>
        <li>10월 PPI는 +0.3%로 예상(+0.4%)보다 낮았습니다. 근원은 +0.3%로 예상과 같았습니다. {s('(TradingView 11/13 22:30)')}</li>
        <li>그래도 미 10년물은 5.15%로 올랐습니다. 한 주 전 4.86%였습니다. {s('(Yahoo 11/13)')}</li>
        <li>12월 인상 기대는 90%를 넘었다는 해석입니다. {s('(신한 11/13 p.1, 원문 확인)')}</li>
        <li>다음 주: 11/17 미 소매판매·FOMC 의사록, 11/18 아침 엔비디아 실적, 11/19 앤트로픽 IPO 추진. {s('(신한 p.1)')}</li>
      </ul>
    </div>
    <div class="desk">
      <h3>플로우 데스크</h3><div class="role">채널 흐름 · 수급 (2차 자료)</div>
      <ul>
        <li><b>🔥 말·주가·수급 모두 ↑</b>: 반도체 메모리·건설·K-엔터·전력기기·반도체 소재.</li>
        <li><b>⚠️ 말은 많은데 주가 ↓</b>: IT/소프트웨어(글 +33%, 5일 −3.7%)·화장품·게임·바이오.</li>
        <li>반도체 장비 글이 61건으로 전주(10건)의 6배입니다. 테스트·후공정도 6→34건입니다.</li>
        <li>🔥 여러 채널: 엔비디아 CEO 해임 준비 보도(11/12), 지엔씨에너지 수주잔고(11/12).</li>
      </ul>
      <small class="src">채널 요약 11/09~11/13 · 수급은 strategy_prep 5일 합계</small>
    </div>
    <div class="desk">
      <h3>리서치 데스크</h3><div class="role">카드 218장 · 원문 확인 3건</div>
      <ul>
        <li>31일 목표가는 상향 139건, 하향 970건입니다. 하향이 7배입니다. {s('(채널 리포트 요약)')}</li>
        <li>하나 반도체: "2027년 DRAM CAPA +15%, 증설 물량의 공급 기여는 2028년 이후." {s('(하나 11/12 p.2, 원문 확인)')}</li>
        <li>하나 건설: "상반기는 데이터센터와 공공주택." Top Pick GS건설·계룡건설, 관심 삼성E&amp;A. {s('(하나 11/13 p.1·p.2, 원문 확인)')}</li>
        <li>반도체 카드 17장: 강세 10, 약세 3입니다. 인터넷·SW 카드 34장: 강세 18, 약세 6입니다. {s('(리포트 카드 7일)')}</li>
      </ul>
    </div>
  </div>
  <figure style="margin-top:18px">
    <h3 style="font-size:14px;margin-bottom:6px">업종 5일 수익률 — 위 6개 · 아래 6개</h3>
    <div class="tw" style="border:0;margin:0">{chart_sect()}</div>
    <figcaption class="figcap">출처: strategy_prep 업종 5일 수익률 (사용자 업종 분류, 11/13 종가). 같은 기간 코스피는 +4.6%입니다. 지난주 꼴찌권이던 반도체 장비·후공정이 맨 위로 왔습니다. 지난주 1위 IT/소프트웨어는 아래로 내려갔습니다.</figcaption>
  </figure>
</section>
"""

# ---------------- 피치 ----------------
COLS = ["기업 지도", "역할", "RS", "1주", "고점 대비", "볼 것", "행동"]
def pitch(p):
    sc = p["score"]
    ev = "".join(f'<div><h4>{a} {{{{DOTS:{n}}}}}</h4>{t}</div>' for a, n, t in p.get("ev", []))
    qa = "".join(f"<dt>{a}</dt><dd>{b}</dd>" for a, b in p["qa"])
    flow = ('<ol class="flow">' + "".join(f'<li{" class=\"h\"" if st == "가설" else ""}><em>{st}</em><b>{e(t)}</b>{n}</li>' for st, t, n in p["flow"]) + "</ol>") if p.get("flow") else ""
    tbl = ""
    if p.get("rows"):
        tbl = ('<div class="tw"><table class="t"><tr>' + "".join(f'<th{" class=\"l\"" if i in (0, len(p.get("cols", COLS)) - 2) else ""}>{c}</th>' for i, c in enumerate(p.get("cols", COLS))) + "</tr>"
               + "".join("<tr>" + "".join(f'<td{" class=\"l wrap\"" if i in (0, len(r) - 2) else ""}>{c}</td>' for i, c in enumerate(r)) + "</tr>" for r in p["rows"]) + "</table></div>"
               + f'<small class="src">{e(p["rsrc"])}</small>')
    deb = '<div class="debate">' + "".join(f'<div class="c"><span class="r c">반론 {i + 1}</span><span>{c}</span></div><div><span class="r a">답변</span><span>{a}</span></div>' for i, (c, a) in enumerate(p.get("debate", []))) + "</div>"
    return f"""
  <article class="pitch{' rejected' if p.get('rejected') else ''}">
    <div class="ph">
      <div><div class="tag">{p['tag']}</div><h3>{e(p['title'])}</h3><div class="who">{e(p['who'])}</div></div>
      <div class="pscore"><span>말</span><span>이익</span><span>가격</span><span>돈</span><b class="num">{sum(sc)}/8</b>{''.join('{{DOTS:%d}}' % x for x in sc)}</div>
    </div>
    <div class="pb">
      {f'<p class="thesis">{e(p["thesis"])}</p>' if p.get('thesis') else ''}
      <dl class="qa">{qa}</dl>
      {flow}
      {f'<div class="ev">{ev}</div>' if p.get('ev') else ''}
      {tbl}
      {deb if p.get('debate') else ''}
      <div class="kill"><div class="k"><h4>{p.get('killh', '무효 신호 (틀렸다고 인정할 조건)')}</h4>{p['invalid']}</div><div class="v"><h4>{p.get('horh', '실적 반영 시점 · 촉매')}</h4>{p['horizon']}</div></div>
      <div class="verdict"><b>데스크 결정</b>{p['verdict']}</div>
    </div>
  </article>"""

PITCHES = [
 dict(id="T1", rank="메인 띔", stage="확산", conviction=3, name="국내 데이터센터·반도체 팹 건설 — 2027년 일감이 국내로 돌아온다",
      tag="T1 · 메인 띔 · 확산 · 확신 {{CONV:3}}", title="2027년 건설의 무대는 국내입니다 — 데이터센터·반도체 팹 일감이 실적으로 보이기 시작했습니다",
      who="새 메인 띔 · 지난 호 T1의 '시공' 칸을 독립시킴", score=(2, 1, 2, 1),
      thesis="주택은 아직 착공이 돌아서지 않았습니다. 대신 데이터센터와 반도체 팹 같은 비주택 수주가 크게 늘었습니다. 수주가 보이는 회사부터 이익 추정치가 오릅니다. 시장은 이것을 건설 업종 20일 +15.4%로 먼저 보여 주고 있습니다.",
      qa=[("왜 지금인가", f"하나증권이 건설 Overweight를 냈습니다. 삼성전자 평택 P5 공사 재개와 P5 Fab2 물량으로 발주가 크게 늘었다고 썼습니다. 데이터센터는 2030년까지 4GW, 30조~40조 원 수주가 더 나올 수 있다고 봤습니다. {s('(하나 11/13 p.2, 원문 확인)')}"),
          ("시장이 놓친 것", "업종 목표가는 31일 하향 62 > 상향 29로 아직 나쁩니다. 주택 리포트가 섞여 있기 때문입니다. 비주택 비중이 큰 회사만 따로 보면 그림이 다릅니다. 삼성E&A는 31일 상향 22·하향 0입니다."),
          ("채널 글 4주", f"{talkbars([40, 29, 51, 54], '건설')} {s('건설, 10/19~11/09 주')}")],
      flow=[("확인", "반도체 팹 발주 재개", s("평택 P5·P5 Fab2 (하나 p.2)")), ("확인", "DC 파이프라인 1GW 확보", s("하나 p.2")),
            ("가설", "수주 → 추정치 상향", "11/17 삼성E&A·GS건설 IR 숫자로 확인"), ("가설", "하반기 민간주택", "착공 회복은 아직 신호 없음 (하나 p.3)")],
      ev=[("말", 2, "글 54건, 전주 51건. 전주 대비 +117%(채널 흐름 기준)."), ("이익", 1, "삼성E&A 3Q 영업이익 5,006억(예상 2,492억), 상향 22·하향 0. 업종 전체는 하향 우세."),
          ("가격", 2, "업종 5일 +9.1%, 20일 +15.4%로 코스피를 앞섭니다. 삼성E&A RS 95, 고점 −0.4%."), ("돈", 1, "외국인 −519억, 기관 +919억 (5일). 한쪽만 순매수입니다.")],
      rows=[["<b>삼성E&amp;A</b>", "선도(플랜트·팹)", "95", pc(13.2), pc(-0.4), "기준가 69,700. 11/17 IR 뒤 준비 후보", "{{ACT:관찰}}"],
            ["<b>GS건설</b>", "선도(DC·주택)", "76", pc(6.2), pc(-29.4), "단기 고점 32,750. 하나 TP 46,000(p.1). IR 뒤 준비 후보", "{{ACT:관찰}}"],
            ["<b>계룡건설</b>", "후속(공공주택)", "–", pc(14.5), pc(-18.3), "1주 +14.5%로 빠름. 첫 눌림 20일선", "{{ACT:관찰}}"]],
      rsrc="RS: strategy_prep 11/14 · 주가: 네이버 일봉 11/13 종가 · 목표가: 하나 11/13 p.1(현재가 11/12 기준)",
      debate=[("주택은 아직 나쁩니다. 하나도 민간 착공 회복은 '더딜 것'이라고 썼습니다. 금리 5%대가 길어지면 건설주 전체가 눌립니다.", "그래서 주택 비중이 큰 회사는 넣지 않았습니다. 플랜트·팹·데이터센터 비중이 큰 삼성E&A·GS건설만 준비 후보로 둡니다."),
              ("삼성E&A는 1개월 +59%입니다. 고점 근처라 이미 다 오른 것일 수 있습니다.", "맞습니다. 그래서 IR(11/17)이 지나기 전에는 관찰입니다. IR 뒤 기준가 69,700원을 거래대금과 함께 넘을 때 준비로 올립니다."),
              ("외국인은 5일 동안 건설을 팔았습니다(−519억).", "인정합니다. 돈 점수는 1점입니다. 외국인 순매수 전환이 오면 확신도를 올릴 근거가 됩니다.")],
      invalid="건설 업종 20일 수익률이 코스피 아래로 내려감 · 삼성E&A가 IR 뒤 20일선(약 60,300원) 종가 이탈 · 동해 DC 착공 연기",
      horizon="2027년 상반기 (팹·DC 기성). 11/17 삼성E&A·GS건설 IR · 동해 DC 100MW 착공식(11월 말~12월 초, 하나 카드)",
      verdict="{{ACT:관찰}} 삼성E&amp;A · GS건설 (IR 11/17 뒤 준비 후보) · 계룡건설 <span class=\"muted\">— 찬성 4 · 보류 2 (매크로: 금리 5%대 · 반론가: IR 직전)</span>",
      companies=[("삼성E&A", "028050", "선도", "관찰"), ("GS건설", "006360", "선도", "관찰"), ("계룡건설", "013580", "후속", "관찰")],
      against=["민간 주택 착공 회복이 더딤(하나 p.3)", "삼성E&A 1개월 +59%로 고점 근처", "외국인 5일 −519억"]),
 dict(id="T2", rank="서브 띔", stage="확산", conviction=2, name="유가 하락 → 항공 이익 추정 상향 (대한항공 중심)",
      tag="T2 · 서브 띔 · 확산 · 확신 {{CONV:2}}", title="항공은 스코어카드 1위입니다 — 이익이 숫자로 나오기 시작했습니다",
      who="지난 호 T2 유지 · 판정 '맞음(진행)'", score=(2, 2, 1, 2),
      thesis="유가가 꺾이고 원화가 강하면 항공 비용이 먼저 줄어듭니다. 이번 주 제주항공 3Q 실적이 예상의 3.8배로 나오며 숫자로 확인됐습니다. 준비는 여전히 고점 근처에서 쉬는 대한항공 하나입니다.",
      qa=[("이번 주 바뀐 것", f"제주항공 3Q 영업이익 549억 원, 예상 145억 원입니다. 목표가 상향 6곳이 나왔습니다. {s('(채널 리포트 요약 11/12~13)')}"),
          ("가격", "LCC 2곳은 고점에서 9~13% 눌렸습니다. 대한항공은 1주 +7.1%, 고점 −3.7%입니다. 업종 20일은 +18.0%입니다."),
          ("채널 글 4주", f"{talkbars([9, 9, 46, 55], '운송/물류')} {s('운송/물류')}")],
      ev=[("말", 2, "글 55건. 2주 연속 증가했습니다."), ("이익", 2, "31일 상향 19·하향 13, 제주항공 서프라이즈."),
          ("가격", 1, "20일 +18.0%는 앞서지만 5일 +1.8%는 코스피(+4.6%)보다 낮습니다."), ("돈", 2, "외국인 +1,420억, 기관 +346억 (5일).")],
      rows=[["<b>대한항공</b>", "선도", "89", pc(7.1), pc(-3.7), "기준가 32,800 돌파 + WTI 주간 하락 유지", "{{ACT:준비}}"],
            ["<b>제주항공</b>", "후속", "95", pc(7.2), pc(-13.2), "3Q 서프라이즈 뒤 20일선 지지", "{{ACT:관찰}}"],
            ["<b>진에어</b>", "후속", "92", pc(30.3), pc(-9.0), "20일선 지지", "{{ACT:관찰}}"]],
      rsrc="RS: strategy_prep 11/14 · 주가: 네이버 일봉 11/13 종가",
      debate=[("유가 하나에 기대는 띔입니다. 이란 협상이 깨지면 바로 뒤집힙니다.", "그래서 확신도 2를 유지합니다. 유가 반등은 숫자로 무효 조건에 둡니다."),
              ("5일 수익률은 코스피보다 낮습니다. 반도체로 돈이 돌면서 항공은 쉬고 있습니다.", "맞습니다. 가격 점수는 1점입니다. 대한항공이 기준가를 넘을 때만 다시 봅니다.")],
      invalid="WTI 주간 +8% 이상 반등 · 운송 업종 5일 수익률 2주 연속 코스피 하회 · 대한항공 20일선(약 28,300원) 종가 이탈",
      horizon="4Q26 실적(2027년 2월). 매주 유가 · 11월 국제선 여객 통계(12월 초)",
      verdict="{{ACT:준비}} 대한항공 {{ACT:관찰}} 제주항공 · 진에어 <span class=\"muted\">— 찬성 4 · 보류 2</span>",
      companies=[("대한항공", "003490", "선도", "준비"), ("제주항공", "089590", "후속", "관찰"), ("진에어", "272450", "후속", "관찰")],
      against=["유가 단일 변수", "5일 수익률 코스피 하회"]),
 dict(id="T3", rank="서브 띔", stage="초기", conviction=2, name="AI 공급 부족 → 반도체 장비·테스트·메모리 (2028년까지 타이트)",
      tag="T3 · 서브 띔 · 초기 · 확신 {{CONV:2}} (1에서 올림)", title="AI 수요보다 공급이 모자랍니다 — 장비·테스트가 먼저 움직였고, 메모리는 20일선 회복을 기다립니다",
      who="지난 호 T3(메모리 관찰)를 넓힘 · 장비·테스트 추가 · 확신도 1→2", score=(2, 1, 2, 2),
      thesis="미국 데이터센터 걱정에도 반도체 공급은 수요를 못 따라갑니다. 2027년 새 공장이 열려도 실제 공급은 2028년 이후입니다. 그 사이 장비·테스트 회사의 실적이 먼저 나옵니다. 이번 주 장비 4곳이 3Q 서프라이즈를 냈습니다.",
      qa=[("왜 지금인가", f"하나증권은 2027년 DRAM CAPA가 +15% 늘어도 장비 반입·셋업에 1년 이상 걸려 공급 기여는 2028년 이후라고 썼습니다. 2028년까지 수급이 타이트하다고 봤습니다. {s('(하나 11/12 p.2·p.3, 원문 확인)')}"),
          ("이번 주 숫자", f"엑시콘 영업이익 151억(예상 +67~69%), 이오테크닉스 471억(+31~37%), 피에스케이 677억(+21~22%), 원익QnC 444억(+32.1%)입니다. {s('(채널 요약 11/13, 예상치는 채널마다 다름)')}"),
          ("반대 근거", f"하나도 삼성전자 목표가를 400,000원, SK하이닉스를 2,800,000원으로 내렸습니다. 이유는 글로벌 반도체 배수 하향입니다. {s('(하나 p.1, 원문 확인)')} 금요일 밤 필라델피아 반도체는 −3.43%였습니다."),
          ("채널 글 4주", f"{talkbars([44, 115, 61, 85], '반도체')} {s('반도체(메모리·대형)')}")],
      ev=[("말", 2, "메모리 글 85건(+39%), 장비 61건(전주 10건)."), ("이익", 1, "장비 서프라이즈 4곳. 메모리 목표가는 하향 9 > 상향 1."),
          ("가격", 2, "메모리 업종 5일 +6.6%, 20일 −3.2%로 코스피(−4.7%)를 앞섭니다. 선도주 RS 83·85, 테스트 98·99."), ("돈", 2, "메모리 외국인 +1,146억·기관 +2,620억 (5일).")],
      rows=[["<b>삼성전자</b>", "선도", "83", pc(8.0), pc(-44.2), "20일선(−2.7%) 종가 회복 + 외국인 3일 순매수", "{{ACT:관찰}}"],
            ["<b>SK하이닉스</b>", "선도", "85", pc(4.8), pc(-58.7), "20일선(−5.8%) 종가 회복", "{{ACT:관찰}}"],
            ["<b>티에프이</b> ⭐", "원천(테스트)", "98", pc(41.8), pc(-0.9), "보유 중. 3R 97,588원 규칙", "{{ACT:보유}}"],
            ["<b>엑시콘</b>", "원천(테스트)", "99", pc(40.1), pc(-8.1), "1주 +40%. 첫 눌림 뒤 베이스", "{{ACT:관찰}}"],
            ["<b>피에스케이홀딩스</b>", "장비", "–", pc(22.6), pc(-31.0), "하나 TP 255,000 상향(p.1). 20일선 회복", "{{ACT:관찰}}"],
            ["<b>이오테크닉스</b>", "장비", "–", pc(22.2), pc(-42.5), "20일선(−5.3%) 회복", "{{ACT:관찰}}"]],
      rsrc="RS: strategy_prep 11/14 · 주가: 네이버 일봉 11/13 종가 · 티에프이는 risk.py 11/14",
      debate=[("장비주는 1주 +20~40% 급등입니다. 20일 수익률은 아직 −13~−18%입니다. 낙폭 되돌림일 뿐일 수 있습니다.", "인정합니다. 장비는 모두 '관찰'입니다. 20일선 위에 베이스가 생겨야 셋업입니다."),
              ("엔비디아 CEO 교체와 실적(11/18)이 남았습니다. 금요일 밤 반도체는 −3.4%였습니다.", "그래서 확신도는 2에서 멈춥니다. 엔비디아 실적 뒤 국내 반응이 첫 시험대입니다."),
              ("목표가는 계속 내려갑니다. 이익 점수 1점은 후하지 않나.", "메모리만 보면 0점입니다. 장비 서프라이즈를 반영해 1점으로 둡니다. 원문 확인 근거(하나)가 있어 확신도를 올렸습니다.")],
      invalid="삼성전자 17만 원 종가 이탈 · 반도체 장비 업종 5일 수익률이 다시 코스피 아래 · 메모리 목표가 하향 3일 연속",
      horizon="2027년 (장비 반입 1Q27~3Q27, 하나 p.2). 11/18 아침 엔비디아 실적 · 11/18 삼성전자 IR",
      verdict="{{ACT:관찰}} 삼성전자 · SK하이닉스 · 엑시콘 · 피에스케이홀딩스 · 이오테크닉스 · 심텍 <span class=\"muted\">— 찬성 4 · 보류 2 (리스크 매니저: 20일선 아래)</span>",
      companies=[("삼성전자", "005930", "선도", "관찰"), ("SK하이닉스", "000660", "선도", "관찰"), ("티에프이", "425420", "원천(테스트)", "보유"), ("엑시콘", "092870", "원천(테스트)", "관찰"),
                 ("피에스케이홀딩스", "031980", "장비", "관찰"), ("이오테크닉스", "039030", "장비", "관찰"), ("심텍", "222800", "기판", "관찰")],
      against=["장비 20일 수익률 아직 마이너스", "엔비디아 CEO·실적 변수", "메모리 목표가 하향 지속"]),
 dict(id="T4", rank="관찰 띔", stage="소멸", conviction=1, name="AI 인프라 운영·소프트웨어 (지난 호 메인 → 관찰로 강등)",
      tag="T4 · 관찰 띔 · 확신 {{CONV:1}} (3에서 내림)", title="운영·소프트웨어 — NAVER가 무너졌고 삼성에스디에스만 남깁니다",
      who="지난 호 T1 · 판정 '틀림'", score=(2, 1, 1, 1),
      thesis="GPU 임대가 상승이라는 논리는 남아 있습니다. 하지만 업종 가격이 꺾였습니다. 대표로 꼽은 NAVER가 IR 뒤 무너졌습니다. 남은 것은 RS 88의 삼성에스디에스 하나이고, 그것도 IR이 끝난 뒤에 봅니다.",
      qa=[("무엇이 틀렸나", "NAVER를 IR 하루 전에 준비로 넣었습니다. IR 뒤 −10.2%였고 목표가 하향이 9곳 나왔습니다. 업종 5일은 −3.7%입니다."),
          ("남은 근거", f"신한은 앤트로픽 상장이 삼성에스디에스 같은 파트너십 SI사의 재평가 요인이라고 봤습니다. {s('(신한 11/13 p.1, 원문 확인)')}")],
      ev=[("말", 2, "글 71건으로 2주 연속 증가. 그러나 주가는 반대."), ("이익", 1, "상향 10·하향 10."), ("가격", 1, "5일 −3.7%, 20일 −0.0%."), ("돈", 1, "외국인 +380억, 기관 −642억.")],
      rows=[["<b>삼성에스디에스</b>", "운영·SW", "88", pc(9.5), pc(-39.4), "IR(11/16·18) 뒤 단기 고점 240,000 돌파 여부", "{{ACT:관찰}}"],
            ["<b>NHN</b>", "운영·SW", "98", pc(14.9), pc(-25.5), "89,100 고점 뒤 −25%. 베이스", "{{ACT:관찰}}"],
            ["<b>NAVER</b>", "인터넷", "54", pc(-8.0), pc(-42.9), "목표가 하향 9곳. 보지 않음", "{{ACT:회피}}"]],
      rsrc="RS: strategy_prep 11/14 · 주가: 네이버 일봉 11/13 종가",
      debate=[("앤트로픽 IPO(11/19)가 오면 AI 소프트웨어가 다시 주목받을 수 있습니다.", "가능성은 열어 둡니다. 그래서 띔을 폐기하지 않고 관찰로 남깁니다. 가격이 먼저 확인해 줘야 합니다.")],
      invalid="삼성에스디에스 IR 뒤 20일선(약 213,000원) 종가 이탈이면 띔 폐기",
      killh="폐기 조건", horh="다시 올리는 조건", horizon="IT/SW 업종 5일 수익률이 코스피 위로 + 삼성에스디에스 240,000 돌파",
      verdict="{{ACT:관찰}} 삼성에스디에스 · NHN {{ACT:회피}} NAVER <span class=\"muted\">— 만장일치</span>",
      companies=[("삼성에스디에스", "018260", "운영·SW", "관찰"), ("NHN", "181710", "운영·SW", "관찰")],
      against=["NAVER IR 뒤 −10.2%", "업종 5일 −3.7%"]),
]
REJ = dict(rejected=True, tag="기각된 피치 · 플로우 데스크 제안", title="NAVER 낙폭 과대 — 목표가 대비 67% 싸다? 가격이 먼저입니다", who="", score=(2, 0, 0, 1),
           qa=[("제안 근거", f"컨센서스 290,200원(15곳) 대비 현재가 173,600원입니다. IBK는 2026 PER 15.2배로 업종 저평가를 짚었습니다. {s('(채널 리포트 요약 · 리포트 카드)')}"),
               ("기각 이유", "IR 뒤 목표가 하향이 9곳입니다. 주가는 20일선 아래(−3.2%)이고 고점 대비 −42.9%입니다. 내 매매에서도 이번 주 1R 손절이 나왔습니다. '싸다'는 추세추종의 근거가 아닙니다."),
               ("다시 볼 조건", "목표가 하향이 멈추고 20일선 위에서 5일 이상 베이스 · 외국인·기관 동반 순매수")],
           invalid="—", horizon="—", killh="", horh="",
           verdict="{{ACT:회피}} <span class=\"muted\">— 찬성 1(플로우) · 반대 5</span>")

AG4 = f"""
<section class="pad">
  <div class="sh"><span class="no">안건 4</span><h2>아이디어 피치 — 띔 4개, 기각 1개</h2><span class="who">발표: 전략가 · 반박: 반론가</span></div>
  <p class="lead">스코어카드 1~3위(항공·건설·반도체)가 띔과 같습니다. 건설은 점수로는 준비감이지만 IR(11/17) 직전이라 이번 주는 관찰로 둡니다. 지난 호 메인이던 운영·소프트웨어는 점수가 내려가 관찰 띔으로 남깁니다.</p>
{''.join(pitch(p) for p in PITCHES)}
{pitch(REJ).replace('<div class="kill"><div class="k"><h4></h4>—</div><div class="v"><h4></h4>—</div></div>', '')}
</section>
"""

AG5 = """
<section class="pad">
  <div class="sh"><span class="no">안건 5</span><h2>반론 라운드 — 3주 뒤 이 보고서가 틀렸다면 왜일까</h2><span class="who">발표: 반론가 (사전 부검)</span></div>
  <ol class="pm">
    <li><span><b>팔로스루 없이 랠리 시도가 끝났습니다.</b> 11/18까지 강한 날이 없고 5,018을 깹니다. 그러면 건설·장비의 급등도 함께 되돌려집니다. 금요일 신저가가 신고가보다 많았던 것이 첫 신호였을 수 있습니다.</span></li>
    <li><span><b>순환매가 너무 빨랐습니다.</b> 지난주는 소프트웨어, 이번 주는 장비였습니다. 1~2주마다 주도가 바뀌는 장에서는 돌파가 이어지지 않습니다. 지난 호 NAVER가 그 예입니다.</span></li>
    <li><span><b>금리 5.15%가 모든 것을 눌렀습니다.</b> PPI가 낮았는데도 금리가 올랐습니다. 12월 인상이 굳어지면 건설(금리)과 장비(배수) 모두 맞습니다.</span></li>
    <li><span><b>엔비디아 실적이 실망이었습니다.</b> CEO 교체 뒤 첫 실적입니다. 반도체 띔(T3)이 가장 먼저 맞습니다.</span></li>
    <li><span><b>같은 리포트를 두 번 셌습니다.</b> 건설과 반도체의 근거가 모두 '삼성전자 팹 투자'입니다. 독립된 두 띔이 아니라 한 띔일 수 있습니다.</span></li>
  </ol>
  <p style="margin-top:12px"><b>조정 결과.</b> T1 건설은 3에서 올리지 않습니다. T3 반도체는 원문 확인 근거(하나 11/12)가 있어 1→2로 올렸고, 더는 올리지 않습니다. T4는 3→1로 내렸습니다. 5번 반론 때문에 T1·T3 준비 종목을 같은 날 함께 사는 일은 피해야 합니다(복기: 같은 날 몰아 산 날 2번, 합계 −6.47R).</p>
</section>
"""

CHK = [
    ("11/16 09:00", "삼성에스디에스 IR — 끝난 뒤 RS 85↑·240,000 돌파 여부. 끝나기 전에는 준비에 넣지 않음", "T4"),
    ("11/16~18", "랠리 시도 5~7일째 — 코스피 +1.5%↑ + 거래량 증가면 팔로스루. 5,018.85 이탈이면 무효", "국면"),
    ("11/17", "삼성E&A IR · GS건설 IR(15:30) — 팹·DC 수주 숫자", "T1"),
    ("11/17 (미국)", "소매판매·FOMC 의사록 — 미 10년물 5.15%가 더 오르는지", "국면"),
    ("11/18 아침", "엔비디아 실적 → 국내 반도체·장비 반응. 같은 날 삼성전자 IR(13:00)", "T3"),
    ("11/19", "앤트로픽 IPO 추진 — AI 소프트웨어 재평가 여부", "T4"),
    ("매주", "WTI 주간 등락 — +8% 이상 반등이면 T2 무효", "T2"),
    ("수시", "BAAJA 상원 최종 표결 — 통과 시 전력기기 '다시 볼 조건' 하나 충족", "관찰"),
    ("보유", "티에프이 3R 97,588원(+6.2%) · JYP Ent. 손절가 41,446원(−6.8%)", "계좌"),
]
chk_html = "".join(f'<li><span class="d">{e(d)}</span><span>{e(t)}</span><span class="tg">{e(g)}</span></li>' for d, t, g in CHK)

SCN = [
    ("강세", 25, "11/16~18 팔로스루 + 엔비디아 실적 무난 + 외국인 순매수 재개", "대한항공과 IR을 통과한 건설 2종목의 돌파 신호부터 확인. 신호등 노랑이면 규칙대로 노출 허용. 같은 날 몰아 사지 않음"),
    ("기본", 45, "코스피 5,000~5,500 박스, 팔로스루 없음", "관찰 유지. 장비·테스트 급등주의 첫 눌림만 기록"),
    ("약세", 30, "금리 상승 + 엔비디아 실망 → 5,018 이탈", "신규 0. 풀을 10종목 이하로 줄이고 T3·T4 폐기 판단"),
]
scn_html = "".join(f'<div><h4>{n} <span class="num">{p}%</span></h4><div class="prob"><i style="width:{p}%"></i></div><dl><dt>트리거</dt><dd>{e(t)}</dd><dt>관찰 풀은</dt><dd>{e(i)}</dd></dl></div>' for n, p, t, i in SCN)

AG6 = f"""
<section class="pad">
  <div class="sh"><span class="no">안건 6</span><h2>결정 — 스코어카드 · 관찰 풀 · 시나리오 · 체크리스트</h2><span class="who">정리: 편집자</span></div>
  <h3 style="font-size:15px;margin-bottom:4px">업종 스코어카드 (4축 0~2점, 합계 순)</h3>
  <p class="muted" style="font-size:13px">점수가 띔보다 먼저입니다. 1~3위(운송·건설·메모리)가 T1~T3과 같습니다.</p>
  <div class="tw"><table class="t">
    <tr><th class="l">업종</th><th>말</th><th>이익</th><th>가격</th><th>돈</th><th>합계</th><th>단계</th><th>행동</th><th class="l wnote">근거</th></tr>
    {sc_rows}
  </table></div>
  <small class="src">말=채널 주별 글 수 · 이익=31일·7일 목표가 상향/하향·실적 · 가격=업종 5/20일 수익률 vs 코스피(5일 +4.6%, 1개월 −4.7%), 선도주 RS · 돈=외국인·기관 5일 합계 (strategy_prep 11/14 09:08, 11/13 종가).</small>

  <h3 style="font-size:15px;margin:24px 0 6px">관찰 풀 {len(POOL)}종목</h3>
  <div class="book">
    <div><small>준비</small><b class="num">{cnt('준비')}</b></div>
    <div><small>관찰</small><b class="num">{cnt('관찰')}</b></div>
    <div><small>보유</small><b class="num">{cnt('보유')}</b><br><small>티에프이 · JYP Ent.</small></div>
    <div><small>회피 표시</small><b class="num">{cnt('회피')}</b><br><small>NAVER (기각 피치)</small></div>
    <div><small>뺀 종목</small><b class="num">7</b><br><small>카카오 · 혜인 · 한미약품 · 나노신소재 · 삼성SDI · KT · 삼양식품</small></div>
    <div><small>새로 넣음</small><b class="num">10</b><br><small>계룡건설 · 피에스케이홀딩스 · 이오테크닉스 · 이수페타시스 · JYP Ent. · 하이브 · KB금융 · 일진전기 · LS ELECTRIC(회피→관찰) · NAVER(준비→회피)</small></div>
  </div>
  <div class="tw"><table class="t">
    <tr><th class="l">종목</th><th>띔</th><th class="l">역할</th><th>RS</th><th>1주</th><th>고점 대비</th><th class="l">셋업</th><th class="l">볼 것</th><th>행동</th></tr>
    {pool_rows}
  </table></div>
  <small class="src">RS: strategy_prep 11/14(감시 목록 계산에 없으면 '–') · 1주·고점 대비: 네이버 일봉 11/13 종가로 계산 · 셋업 판정은 평일 16:07 감시 목록이 확정합니다.</small>

  <h3 style="font-size:15px;margin:24px 0 8px">시나리오 (다음 2주)</h3>
  <div class="scn">{scn_html}</div>

  <h3 style="font-size:15px;margin:24px 0 8px">다음 주 체크리스트</h3>
  <ul class="chk">{chk_html}</ul>
</section>
"""

REFS = [
    ("하나증권 「AI 수요대비 부족한 공급 능력」(반도체) 11/12", "https://stock.naver.com/research/industry/46977", "1차 · 원문 확인 (p.1·p.2·p.3)"),
    ("하나증권 「2027년의 무대는 국내다!」(건설) 11/13", "https://stock.naver.com/research/industry/46988", "1차 · 원문 확인 (p.1·p.2·p.3)"),
    ("신한투자증권 「신한 M.R.I: 숨겨진 AI 투심 회복의 카드, BAAJA법」 11/13", "https://stock.naver.com/research/invest/40813", "1차 · 원문 확인 (p.1·p.2)"),
    ("iM증권 「MLCC와 PCB, 센티먼트와 펀더멘털」 11/13", "", "1차 요약 (자료실)"),
    ("유진투자증권 「이미 많은 것이 반영된 주가」(반도체) 11/12", "", "1차 요약 (자료실)"),
    ("대신증권 「블루웨이브와 AIDC 규제: 공급은 지속, 속도는 조절」 11/12", "", "1차 요약 (자료실)"),
    ("네이버 산업·전략 리포트 카드 7일 218장", "", "1차 요약 (리포트 카드)"),
    ("제주항공·NAVER·메모리 목표가 변경 · 장비 3Q 잠정실적", "", "2차 · 채널 요약"),
    ("채널 정리·리포트 정리·마감 리뷰 11/09~11/13 · 주간 리뷰 11/13", "", "2차 · 채널 요약"),
    ("네이버 증권 시세·수급·업종 (비공식) 11/13 종가", "", "데이터"),
    ("Yahoo Finance 미국 지수·금리 11/13 · TradingView 경제지표", "", "데이터"),
    ("strategy_prep prep·score 11/14 09:08 · risk.py · trades.py review", "", "데이터"),
]
refs_html = "".join(f'<li>{e(n)} · {e(t)}</li>' for n, u, t in REFS)
RISKS = [
    "시세는 11/13(금) 종가입니다. 관찰 풀의 1주·고점 대비는 네이버 일봉으로 따로 계산했고, 도구의 일부 값(11/11 일봉 캐시)은 쓰지 않았습니다.",
    "원문 확인은 3건입니다(하나 반도체 p.1~3, 하나 건설 p.1~3, 신한 BAAJA p.1·2). 장비 3Q 실적은 채널 요약(2차)이라 예상치가 채널마다 다릅니다.",
    "이번 주 네이버 리서치 후보 목록(candidates)은 주말이라 0건이었습니다. 원문은 11/12~13 목록에서 직접 골랐습니다.",
    "데스크 표결은 한 대화가 역할을 나눠 쓴 결과입니다. 서로 다른 사람의 표가 아닙니다.",
    "건설(T1)과 반도체(T3)는 '삼성전자 팹 투자'라는 같은 근거를 일부 공유합니다. 두 띔을 독립된 근거로 세면 과대평가입니다.",
]
risks_html = "".join(f"<li>{e(r)}</li>" for r in RISKS)
METHOD = "4검증(말·이익·가격·돈)은 축마다 0~2점입니다. 말은 채널 주별 글 수, 이익은 목표가 상향·하향과 실적, 가격은 업종 5·20일 수익률과 선도주 RS(코스피 대비 상대 강도 순위, 1~99), 돈은 외국인·기관 5일 합계입니다. 단계는 초기·확산·과열·소멸로 씁니다. 행동은 준비·관찰·회피 세 가지뿐이고, 보유 종목은 '보유'로 표시합니다."

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
  <p style="margin-top:16px;border-top:1px solid var(--rule);padding-top:12px">본 자료는 개인 투자 공부용으로 만든 내부 자료입니다. 특정 종목의 매수·매도를 권유하지 않습니다. '준비·관찰·회피'는 무엇을 먼저 볼지 정하는 표시입니다. 실제 매매는 고정된 매매 규칙(docs/rules.md, 2027-01-31까지)과 본인 판단으로 합니다. 증권사 리포트 원문은 저장하지 않고 요약과 출처만 적었습니다.</p>
</section>
<div class="foot"><span>Balance Lab Research · 주간 전략 {e(ISSUE)}</span><span>재료 기간 10/19~11/13 · 시세 {M['at']}</span></div>
</div>
"""

page = fill(STYLE + COVER + AG1 + AG2 + AG3 + AG4 + AG5 + AG6 + APX)

# ---------------- JSON (v3 칸) ----------------
pool_by = {p[0]: p for p in POOL}
def comp(nm, code, role, action):
    p = pool_by.get(nm)
    return {"name": nm, "code": code, "role": role, "exposure": "직접", "point": p[3] if p else "", "stats": f"RS {p[4] if p and p[4] else '–'} · 1주 {p[5]:+.1f}% · 고점 {p[6]:+.1f}% (11/13)" if p else "",
            "against": "", "check": p[8] if p else "", "action": action if action != "보유" else "관찰"}
THEMES = []
for p in PITCHES:
    THEMES.append({"id": p["id"], "rank": p["rank"], "name": p["name"], "stage": p["stage"], "conviction": p["conviction"],
                   "thesis": p["thesis"], "logic": [re.sub("<[^>]+>", "", b) for a, b in p["qa"] if a != "채널 글 4주"],
                   "flow": [{"node": t, "status": st, "note": re.sub("<[^>]+>", "", n)} for st, t, n in p.get("flow", [])],
                   "evidence": [{"axis": a, "score": n, "text": t} for a, n, t in p["ev"]],
                   "score": dict(zip(("talk", "profit", "price", "money"), p["score"]), total=sum(p["score"])),
                   "companies": [comp(*c) for c in p["companies"]], "against": p["against"],
                   "invalid": re.sub("<[^>]+>", "", p["invalid"]), "horizon": re.sub("<[^>]+>", "", p["horizon"])})
plain = lambda t: re.sub("<[^>]+>", "", t).replace("&amp;", "&")
BUL = [f"{a} {b} {c}" for a, b, c in BULLETS]
DRAFT = {
    "version": 3, "issue": ISSUE, "title": HEAD, "subtitle": SUB, "made_at": MADE, "period": f"재료 10/19~11/13 · 시세 {M['at']}",
    "analysts": ["전략가", "반론가", "리스크 매니저", "데이터(도구)"], "page": f"reports/{DAY}/strategy.html", "artifact": ART, "conclusion": HEAD,
    "summary": {"headline": HEAD, "bullets": BUL,
                "stance": {"regime": f"🔴 하락 추세 (코스피 20일선 {M['gap20']}, 11/13 종가) · 랠리 시도 4일째", "exposure": "권장 노출(표시만): 신규 0~소량", "mode": "관찰"},
                "top_sectors": [{"name": g, "score": a + b + c + d, "stage": st, "action": ac} for g, a, b, c, d, st, ac, _ in SC[:5]],
                "changes": ["메인 띔 교체: 운영·SW(틀림) → 국내 DC·팹 건설", "운영·SW는 T4 관찰 띔으로 강등(확신 3→1), NAVER 회피", "반도체 띔을 장비·테스트까지 넓히고 확신 1→2",
                            "항공 T2 유지(맞음)", "전력기기 회피 → 관찰, 'BAAJA 통과' 무효 조건 삭제", "IR·실적 직전 종목은 준비에 넣지 않기로 함(삼성E&A·GS건설은 IR 뒤)"]},
    "regime": {"title": "빨강 유지 · 랠리 시도 4일째", "numbers": [{"label": "코스피 20일선 대비", "value": M["gap20"], "note": "11/13 종가"}, {"label": "코스피", "value": f"{M['kospi']} ({M['kospi_pct']:+.2f}%)", "note": M["at"]},
               {"label": "외국인 코스피", "value": M["f_kospi"], "note": "11/13 확정"}, {"label": "신고가/신저가", "value": f"{M['nh']}/{M['nl']}", "note": "11/13"}, {"label": "미 10년물", "value": "5.15%", "note": "Yahoo 11/13"}],
               "body": ["외국인 11/10~12 사흘 순매수 뒤 11/13 순매도", "신저가가 신고가보다 많아짐", "PPI는 예상 하회지만 금리 상승"],
               "phase": "급락 → 랠리 시도 4일째(D4 하락) / 팔로스루 확인 전, 남은 창 11/16~18",
               "what_flips": "11/16~18 코스피 +1.5%↑ + 거래량 증가, 20일선 위 종가, 외국인 3일 연속 순매수 재개. 5,018.85 이탈 시 랠리 시도 무효"},
    "themes": THEMES,
    "rejected": {"name": "NAVER 낙폭 과대", "why": "IR 뒤 목표가 하향 9곳, 20일선 −3.2%, 고점 −42.9%", "revisit": "하향 멈춤 + 20일선 위 5일 베이스 + 외국인·기관 동반 순매수"},
    "sector_scorecard": [{"group": g, "talk": a, "profit": b, "price": c, "money": d, "total": a + b + c + d, "stage": st, "action": ac, "note": n} for g, a, b, c, d, st, ac, n in SC],
    "pool": [{"name": n, "code": c, "theme": t, "role": r, "rs": rs, "r1w": w, "off_high": h, "setup": st, "watch_for": wf, "action": a} for n, c, t, r, rs, w, h, st, wf, a in POOL],
    "scenarios": [{"name": n, "prob": f"{p}%", "trigger": t, "implication": i} for n, p, t, i in SCN],
    "watch": [{"name": "IT/소프트웨어", "status": "⚠️ 말이 앞섬", "why": "글 +33%, 5일 −3.7%"}, {"name": "화장품·게임", "status": "⚠️ 말이 앞섬", "why": "글 +83~152%, 주가 하락"},
              {"name": "전력기기", "status": "🔄 반등", "why": "5일 +11.1%, 20일 −16.1%"}],
    "portfolio": {"title": "내 보유 종목과 띔의 정렬", "rows": [{"name": "티에프이", "fit": "높음", "note": "T3 원천(테스트), +2.10R, 3R까지 +6.2%"}, {"name": "JYP Ent.", "fit": "중간", "note": "K-엔터(스코어 6점), 띔 밖, −0.17R"}], "note": "CR 1.33% (risk.py 11/14 09:12)"},
    "scorecard": [
        {"made": "2026-11-11", "hypothesis": "T1 운영·소프트웨어", "status": "틀림", "numbers": "NAVER −10.2%, 삼성에스디에스 +2.0%, 삼성E&A +3.9%, NHN −17.5% (11/11→11/13)", "note": "IR 직전 종목을 준비에 넣음"},
        {"made": "2026-11-11", "hypothesis": "T2 항공", "status": "진행", "numbers": "대한항공 +0.3%, 진에어 −4.1%, 제주항공 −9.0%", "note": "LCC 관찰 판단은 맞음"},
        {"made": "2026-11-11", "hypothesis": "T3 메모리 관찰", "status": "진행", "numbers": "삼성전자 +0.6%, SK하이닉스 −4.3%, 티에프이 +15.5%", "note": "장비·테스트가 먼저 움직임"},
        {"made": "2026-11-11", "hypothesis": "기각: 전력기기", "status": "틀림", "numbers": "업종 5일 +11.1%", "note": "가격 기준으로는 기각이 일렀음"},
        {"made": "2026-11-11", "hypothesis": "체크포인트: 외국인 3일 연속 순매수", "status": "맞음", "numbers": "11/10~12 순매수, 11/13 −5,419억", "note": "한 번 충족 뒤 끊김"}],
    "checkpoints": [f"{d} {t}" for d, t, _ in CHK],
    "calendar": [{"date": "2026-11-16", "event": "삼성에스디에스 IR", "relevance": "T4"}, {"date": "2026-11-17", "event": "삼성E&A·GS건설 IR", "relevance": "T1"},
                 {"date": "2026-11-17", "event": "미 소매판매·FOMC 의사록", "relevance": "국면"}, {"date": "2026-11-18", "event": "엔비디아 실적·삼성전자 IR", "relevance": "T3"}, {"date": "2026-11-19", "event": "앤트로픽 IPO 추진", "relevance": "T4"}],
    "risks": RISKS, "method": METHOD, "references": [{"name": n, "url": u, "type": t} for n, u, t in REFS],
    "agents": [{"role": "리스크 매니저", "did": "국면·랠리 일지·계좌"}, {"role": "매크로", "did": "금리·물가·일정"}, {"role": "플로우", "did": "채널 흐름·수급"},
               {"role": "리서치", "did": "카드 218장·원문 3건"}, {"role": "전략가", "did": "띔 4개·기각 1개"}, {"role": "반론가", "did": "채점·사전 부검"}],
    "sources": {"reports": 218, "originals": 3, "memos": 5, "data": "네이버 11/13 종가 · Yahoo 11/13"},
}

TG = "\n".join([
    f"📊 전략 보고서 {ISSUE}",
    f"💡 {HEAD}",
    "",
    "핵심",
    *[f"- {a} {b}" for a, b, _ in BULLETS[:5]],
    "",
    f"국면: 🔴 하락 추세 · 랠리 시도 4일째(남은 창 11/16~18) · 권장 노출(표시만) 신규 0~소량",
    f"지난주: 코스피 {M['kospi']}(1주 {M['w1']}), 외국인 11/13 {M['f_kospi']}, 미 10년물 5.15% (네이버·Yahoo 11/13)",
    "",
    "상위 업종 (4검증 점수)",
    *[f"- {g} {a + b + c + d}/8 · {ac}" for g, a, b, c, d, st, ac, _ in SC[:4]],
    "",
    "이번 회의의 결정",
    "- 준비: 대한항공 (삼성E&A·GS건설은 11/17 IR 뒤 준비 후보)",
    "- 관찰: 삼성E&A · GS건설 · 삼성전자 · SK하이닉스 · 엑시콘 · 삼성에스디에스",
    "- 회피: NAVER · 게임 · 화장품 · 증권",
    "",
    "지난 호 채점",
    "- 틀림: 운영·SW(NAVER IR 뒤 −10.2%) → 관찰 띔으로 강등",
    "- 맞음: LCC 관찰, 대한항공 버팀 · 기각한 전력기기는 5일 +11%로 일렀음",
    "",
    "다음 주: 11/16 삼성에스디에스 IR · 11/17 삼성E&A·GS건설 IR · 11/18 엔비디아 실적",
    f"관찰 풀 {len(POOL)}종목 · 전체 보고서: {ART}",
    "원문 확인 3건(하나 반도체·하나 건설·신한 BAAJA, 쪽수 표기)",
    "범례: 준비/관찰/회피는 볼 순서 표시입니다 (매수·매도 권유 아님) · 규칙 고정 ~2027-01-31",
])

MD = [f"# 주간 전략 {ISSUE}", f"_{MADE} · 시세 {M['at']}_", "", f"## 결론\n{HEAD}", "", *[f"- {x}" for x in BUL], "",
      "## 국면", DRAFT["regime"]["phase"], "", f"바뀌는 조건: {DRAFT['regime']['what_flips']}", ""]
for th in THEMES:
    MD += [f"## {th['id']} {th['name']} (확신 {th['conviction']}/5, 점수 {th['score']['total']}/8)", th["thesis"], "", *[f"- {l}" for l in th["logic"]], "",
           "| 종목 | 역할 | 숫자 | 볼 것 | 행동 |", "|---|---|---|---|---|", *[f"| {c['name']} | {c['role']} | {c['stats']} | {c['check']} | {c['action']} |" for c in th["companies"]], "",
           f"무효: {th['invalid']}", ""]
MD += ["## 기각: NAVER 낙폭 과대", DRAFT["rejected"]["why"], "", "## 업종 스코어카드", "| 업종 | 말 | 이익 | 가격 | 돈 | 합계 | 행동 |", "|---|---|---|---|---|---|---|",
       *[f"| {g} | {a} | {b} | {c} | {d} | {a + b + c + d} | {ac} |" for g, a, b, c, d, st, ac, _ in SC], "",
       "## 관찰 풀", "| 종목 | 띔 | RS | 1주 | 고점 대비 | 볼 것 | 행동 |", "|---|---|---|---|---|---|---|",
       *[f"| {n} | {t} | {rs if rs is not None else '–'} | {w:+.1f}% | {h:+.1f}% | {wf} | {a} |" for n, c, t, r, rs, w, h, st, wf, a in POOL], "",
       "## 시나리오", *[f"- {n} {p}%: {t} → {i}" for n, p, t, i in SCN], "", "## 지난 가설 채점", *[f"- {x['hypothesis']}: {x['status']} — {x['numbers']}" for x in DRAFT["scorecard"]], "",
       "## 체크리스트", *[f"- {c}" for c in DRAFT["checkpoints"]], "", "## 한계", *[f"- {r}" for r in RISKS], "", "## 출처", *[f"- {n} · {t}" for n, u, t in REFS], "",
       "매수·매도 권유가 아닙니다. 판단은 본인이 합니다."]

OUTD.mkdir(parents=True, exist_ok=True)
(OUTD / "strategy.html").write_text(page, encoding="utf-8")
(OUTD / "strategy.md").write_text("\n".join(MD), encoding="utf-8")
(OUTD / "strategy_tg.md").write_text(TG, encoding="utf-8")
(ROOT / "data" / "strategy" / "draft.json").write_text(json.dumps(DRAFT, ensure_ascii=False, indent=1), encoding="utf-8")
print(json.dumps({"html": len(page), "json": len(json.dumps(DRAFT, ensure_ascii=False)), "tg_lines": TG.count("\n") + 1, "pool": len(POOL), "left_tokens": len(re.findall(r"\{\{", page))}, ensure_ascii=False))
