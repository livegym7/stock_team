# 진행 상황

## 완료
- [x] 저장소 뼈대: `CLAUDE.md`, `docs/`, `config/`, `tools/`, `.gitignore`
- [x] 관심종목: 삼성전자(005930), SK하이닉스(000660)
- [x] 네트워크 허용 도메인 등록 (사용자)
- [x] 환경 변수 5개 등록 (사용자) — 값이 맞는지는 아직 확인 전
- [x] `tools/tg_channel.py`: 공개 채널 수집·분류·리포트 파싱·중복 표시 — 실제 채널(`ked_epic_ai`) 200개 글로 테스트 완료
- [x] `tools/telegram_send.py`: 전송, 4000자 넘으면 나눠 보내기 — 나누기 기능만 테스트, 실제 전송은 확인 전
- [x] `tools/dart.py`: 공시 목록, 주요 재무 — 코드만 작성, 실제 호출은 확인 전

## 다음 할 일 (순서대로)
1. [ ] **새 세션에서 키 확인**: `python3 tools/telegram_send.py --test` → 사용자 휴대폰에 메시지가 오는지 확인
2. [ ] `python3 tools/dart.py list --days 7` 실행해서 DART 동작 확인, 필요하면 수정
3. [ ] KIS 시세 조회 도구 (`tools/kis_quote.py`): 9443 포트 접속 확인, 토큰 캐시, 현재가·수급
4. [ ] yfinance 도구 (`tools/us_quote.py`)
5. [ ] 네이버 뉴스: PlayMCP 연결 확인 또는 네이버 검색 API로 대체
6. [ ] 서브에이전트 정의 (`.claude/agents/`)
7. [ ] 스킬: `/morning-brief`부터 → 직접 실행해서 텔레그램으로 받아 보기
8. [ ] `/close-review`, `/us-recap`, `/stock-report`
9. [ ] 예약 작업 등록 (평일 07:00 / 08:20 / 15:50)
10. [ ] 전략: 사용자에게 깡토 추세추종 규칙 받기 → 규칙화 → 백테스트

## 참고
- `.claude/settings.json`(자주 쓰는 명령 자동 허용 설정)은 첫 세션에서 자동 생성이 막혀 아직 만들지 않음. 필요하면 사용자 확인 후 추가.
