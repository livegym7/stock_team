# 설계 문서

## 목표
정보를 모으고 분석해서 텔레그램으로 브리핑을 보내는 "분석 팀". **자동 주문은 하지 않는다.**
매일 보고서를 `reports/`에 쌓아, 나중에 전략을 세울 때 근거 자료로 쓴다.

## 팀 구성 (Claude Code 서브에이전트, `.claude/agents/`에 만들 예정)
| 팀원 | 데이터 | 하는 일 |
|---|---|---|
| 팀장 (메인 세션) | 아래 전체 | 일을 나눠 주고, 결과를 모아 보고서 작성, 텔레그램 전송 |
| 국내시세 | 네이버 증권 (`naver_quote.py`), KIS·토스는 클라우드 접속 불가 | 현재가, 등락률, 거래량, 외국인·기관 수급, 52주 고저 |
| 해외시세 | Yahoo 차트 API (`us_quote.py`) | 미국 지수·관심종목, 환율, 미 10년물 금리, VIX |
| 뉴스 | 네이버 증권 종목 뉴스·구글 뉴스 RSS (`news.py`) | 종목별 주요 뉴스, 호재·악재 분류 |
| 공시 | DART | 신규 공시, 중요 공시(실적·증자·최대주주 변동 등) 표시 |
| 텔레그램 채널 | 공개 채널 (`config/channels.toml`) | 리포트 요약, 목표주가 변경, 시황, 입법예고 |
| 검증 | 위 결과 전체 | 반대 근거 찾기, 오래된 데이터·숫자 오류 점검, 채널 내용을 공식 출처와 대조 |
| 전략 (나중) | 과거 시세 | 사용자가 정한 추세추종 규칙의 신호 알림 |

## 정기 브리핑 (Claude Code 예약 작업, 평일, 한국시간)
| 시간 | 명령 | 내용 |
|---|---|---|
| 07:00 | `/us-recap` | 간밤 미국장 요약, 국내 영향 포인트 |
| 08:20 | `/morning-brief` | 신규 공시, 전날 리포트(목표가 변경), 뉴스, 오늘 일정, 검증 코멘트 |
| 15:50 | `/close-review` | 관심종목 종가·수급, 특이사항과 원인 추정 |
| 수시 | `/stock-report 종목명` | 시세·수급·재무·공시·뉴스·리포트 종합, 긍정/위험 요인 |

## 데이터 출처별 메모
### 텔레그램 공개 채널 (`ked_epic_ai`) — 연결 완료
- `https://t.me/s/채널아이디`를 로그인 없이 읽는다. 한 페이지에 약 20개, `?before=글번호`로 이전 페이지.
- 하루 20개 이상 올라온다. 대부분 `[✨ 리서치 요약]` (증권사 리포트 1건 요약).
- 리서치 요약 형식:
  ```
  [✨ 리서치 요약] 기아 목표주가 하향 리포트 요약
  목표주가 하향 | 기아 | "리포트 제목"
  목표주가 180,000원 >> 160,000원 | 투자의견 매수-유지 | KB증권
  ✅ 목표주가 하향 주요 요약
  - 근거 ...
  ```
- 그 외 글 종류: `[✨ 리서치]` 인기 보고서 순위, `[시황]` 장전/장마감 시황, `🎯` 시황 전망, `[퀀트 시그널]`, `[한국은행]`, `[종목 토론실 언급 증가]`, `[입법]` 입법예고, `💬 종목 | 현재가` 시세.
- 원문 PDF 링크가 없다 → 2차 자료로 표시. 같은 리포트가 중복으로 올라오기도 한다 → 자동 중복 표시.
- 리포트 요약은 주로 한국시간 오후~저녁에 올라온다 → 다음 날 장전 브리핑에 반영.

### DART — 코드 작성 완료, 키 테스트 필요
- 종목코드 → DART 고유번호 변환표(corpCode.xml)를 하루 한 번 받아 캐시.
- `list.json`(공시 목록), `fnlttSinglAcnt.json`(주요 재무).

### 네이버 증권 시세 — 사용 중 (`tools/naver_quote.py`, 비공식)
- 현재가: `polling.finance.naver.com/api/realtime/domestic/stock/코드,코드` (여러 종목 한 번에)
- 52주·PER·PBR·시총·외국인 소진율: `m.stock.naver.com/api/stock/코드/integration` (여기 거래량은 넥스트레이드 포함 통합값이라 쓰지 않음)
- 투자자별 순매수(개인·외국인·기관, 수량만): `m.stock.naver.com/api/stock/코드/trend?pageSize=60&bizdate=YYYYMMDD`
- 일봉: `api.finance.naver.com/siseJson.naver` — 가격 수정주가, 거래량 미수정
- robots.txt가 수집을 막고 있으므로 관심종목만 최소 호출.

### 토스증권 오픈API — 도구 작성, 클라우드에서는 허용 IP 때문에 막힘 (`tools/toss_quote.py`)
- 문서: `openapi.tossinvest.com/openapi-docs/overview.md`, `faq.md`, `latest/openapi.json`(정답 기준).
- 토큰: `POST /oauth2/token` (form 형식, client credentials). 24시간 유효, 클라이언트당 1개만 유효 → `data/cache/toss_token.json`에 저장해 재사용.
- 현재가 `GET /api/v1/prices?symbols=a,b` (가격·시각만), 일봉 `GET /api/v1/candles?symbol=&interval=1d&count=200&before=`, 투자자별 매매동향 `GET /api/v1/stocks/{종목}/investor-trading?count=100&until=` (수량만).
- 국내 시세는 KRX+NXT 통합. 52주·PER·PBR·시총은 없음 → 네이버.
- **허용 IP 등록 필수** (WTS 설정 > Open API > 허용 IP 관리). 클라우드 세션은 IP가 고정이 아니라 403. 고정 IP 컴퓨터에서 쓸 때만 의미 있음.
- 받은 데이터는 본인 투자 목적에만 쓰고 제3자 배포 금지(토스 이용 정책). 시세 조회만 쓰고 계좌·주문 API는 쓰지 않는다.

### KIS (한국투자증권) — 클라우드에서 접속 불가 (TLS reset)
- 실전투자 서버 `openapi.koreainvestment.com:9443`. 클라우드에서 9443 포트 접속 가능한지 먼저 확인.
- 접근 토큰은 자주 새로 받으면 제한이 걸리므로 `data/cache/`에 저장해 재사용 (24시간 유효).
- **조회 API만** 구현.

### Yahoo Finance — 사용 중 (`tools/us_quote.py`, 비공식)
- yfinance 패키지 없이 `query1.finance.yahoo.com/v8/finance/chart/티커?range=1mo&interval=1d`를 직접 호출 (키 불필요).
- 전일 종가는 meta의 `chartPreviousClose`(기간 시작 전 값)가 아니라 기준 시각 이전 마지막 일봉 종가로 계산.
- 지수 `^GSPC ^IXIC ^DJI ^SOX`, 환율 `KRW=X`(역외 시세), 금리 `^TNX`(% 그대로), `^VIX`. 일봉 가격은 수정주가 아님.

### 뉴스 — 사용 중 (`tools/news.py`, 키 불필요)
- PlayMCP는 클라우드 세션에 연결되지 않음(2026-10-31 확인).
- 종목 뉴스: `m.stock.naver.com/api/news/stock/코드?pageSize=30` — 같은 사건 기사가 묶음으로 오고 `total`이 기사 수. robots.txt가 막고 있으므로 최소 호출.
- 키워드: 구글 뉴스 RSS `news.google.com/rss/search?q=검색어 when:18h&hl=ko&gl=KR&ceid=KR:ko` (개인 피드 용도).
- 제목·언론사·시각·링크만 저장. 더 필요하면 네이버 검색 API(키 발급) 검토.

### 네이버 증권 주의: 등락률
- 현재가 API의 '전일'·등락률은 넥스트레이드 애프터마켓 포함 값이라 KRX 종가 기준과 다르다. `naver_quote.py price`는 KRX 일봉으로 다시 계산한다.

### 네이버증권 리서치 — 보조 수단
- 공식 API 없음. 텔레그램 채널로 대부분 보완되므로 우선순위 낮음.
- 만든다면: robots.txt 확인, 하루 1~2회, 제목·의견·목표가·링크만 저장 (PDF 원본 저장 금지).

### 비공개 텔레그램 채널 — 필요 시
- Telethon(사용자 계정) 필요, `api_id`/`api_hash` 발급. 세션 파일은 계정 열쇠이므로 절대 커밋 금지. 내 컴퓨터에서 실행 권장.

## 전략 (나중에)
- 사용자가 선호하는 전략: **깡토의 추세추종**. 구체 규칙은 사용자가 알려주기로 함 (추측으로 만들지 않는다).
- 순서: 규칙을 숫자로 정리 → 사용자 확인 → 과거 데이터로 백테스트(pykrx 또는 FinanceDataReader) → 장마감 후 신호 알림.
- 신호는 알림만 보낸다. 주문하지 않는다.

## 네트워크 허용 도메인
2026-10-31부터 **전체 허용**으로 바꿈. 아래는 그 전에 쓰던 목록(참고용).
```
t.me
finance.naver.com
stock.naver.com
m.stock.naver.com
api.finance.naver.com
polling.finance.naver.com
developers.tossinvest.com
openapi.tossinvest.com
corp.tossinvest.com
opendart.fss.or.kr
openapi.koreainvestment.com
api.telegram.org
query1.finance.yahoo.com
query2.finance.yahoo.com
fc.yahoo.com
```
