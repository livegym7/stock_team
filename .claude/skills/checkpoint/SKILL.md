---
name: checkpoint
description: 체크포인트 (Balance Lab 2.0, 평일 07:00·12:30·18:30 예약, Sonnet 데스크). 직전 체크포인트 이후 바뀐 것 → 지금 상태 → 다음까지 볼 것 세 칸과 지난 '볼 것' 채점을 한 장으로 써서 웹 '오늘' 맨 위에 올리고 텔레그램으로 보낸다. 아침 브리핑·인사이트·리포트 브리핑의 텔레그램 역할을 대신한다. 사용자가 /checkpoint, "체크포인트 써줘"라고 하거나 예약이 부를 때 쓴다.
---

# /checkpoint — 하루 세 번 한 장

텔레그램으로 정기 발송하는 글은 이것뿐이다(2026-11-12 사용자 확정 Q2). 짧고, 결론 먼저, 채점이 있다.

## 순서 (저장소 루트)
1. `git pull origin main`
2. `python3 tools/checkpoint.py prep > data/cache/checkpoint_prep.md` 후 Read (약 2.5만 자). 슬롯은 시각으로 자동(07/12/18), 다르면 `--slot`.
   - 07시: 간밤 미국(해외 칸)·오늘 일정·보유 위험이 중심. 12시: 오전 변화. 18시: 오늘 마감·감시 목록(16:07)·관찰 풀 기준가 근접·리포트 흐름(14:53 브리핑 대신).
3. JSON을 스크래치에 쓴다:
```json
{"made_at":"YYYY-MM-DD HH:MM","slot":"18","title":"32자 이내 한 줄 결론",
 "graded":[{"watch":"지난 체크포인트의 볼 것 원문","result":"맞음|틀림|진행","note":"숫자 한 줄"}],
 "changed":["직전 이후 바뀐 것 1~3"],"now":["지금 상태 1~3 (국면·수급·주도 업종)"],
 "mine":["보유·관찰 풀에 주는 뜻 0~2 (손절까지 %·기준가 근접)"],
 "watch":["다음 체크포인트까지 볼 것 1~3 (날짜·숫자 조건)"],
 "sources":"네이버 16:15 마감 · 채널 요약 · 감시 목록 11/12 …"}
```
   - **짧게**: 항목 110자 이내, 문장은 "~다."로 맺는다. 칸마다 1~3개. 뉴스 나열 금지, 숫자 두 개를 이어 '그래서 무엇'을 말한다.
   - `graded`: 지난 체크포인트(재료 맨 위)의 '볼 것'을 모두 채점. 첫 회면 빈 목록.
   - 보유 종목이 손절가 −3% 안이거나 규칙 알림(3R·20일선)이 있으면 `mine` 첫 줄에 쓴다. 매수·매도는 단정하지 않는다(규칙대로라는 사실만).
4. `python3 tools/checkpoint.py save --file <스크래치>.json` (형식 검사 → `reports/날짜/checkpoint_HHMM.md`)
5. `python3 tools/checkpoint.py send` — 텔레그램 발송(유일하게 허용된 정기 글)
6. `python3 tools/web_build.py --only channels` → `git add data/checkpoint reports && git commit -m "체크포인트 HH:MM" && git push -u origin main` (웹은 푸시하면 자동 배포). Artifact는 11/19까지만: https://claude.ai/artifact/C8B5Dd1zwtyyqP3c4e3ric 를 read 후 같은 url로 publish(icon 없이).
7. 실패하면 실패 단계·오류(키 값 없이)를 `python3 tools/telegram_send.py "체크포인트 실패: …"`로.

## 지키는 선
- 숫자마다 출처·시각은 `sources` 한 줄로 모은다(웹이 문장마다 줄을 바꿔 괄호가 떨어짐). 채널 글은 2차 자료.
- 지난 실행 내용을 다시 읽지 않는다. 재료 파일만 본다.
- 매매 규칙은 2027-01-31까지 고정. 행동은 준비·관찰·회피.
