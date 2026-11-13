---
name: weekly-review
description: 주간 리뷰 (금요일 16:47 예약). 한 주의 시장·섹터 강도 변화, 채널 주요 흐름, 리포트 상향·하향, 잠정실적, 딥리서치 아이디어 성적, 보유 종목·리스크, 다음 주 일정을 정리해 텔레그램으로 보낸다. "주간 리뷰", /weekly-review 요청 때 쓴다.
---

# /weekly-review — 주간 리뷰

## 1. 재료
```bash
python3 tools/naver_quote.py daily --stock 069500 --days 10     # KODEX 200 한 주 흐름 (시장 대용)
python3 tools/us_quote.py daily --symbol ^IXIC --days 10
python3 tools/sector_radar.py                                    # 업종 강도 순위 (지난주 대비 변화는 history)
python3 tools/risk.py
python3 tools/earnings.py
python3 tools/report_digest.py --collect
python3 tools/tg_channel.py summary --hours 120
python3 tools/research.py context                                # 딥리서치 아이디어 (성적은 web/last_data.json research.ideas)
```
- 이번 주 브리핑 파일들(`reports/이번주 날짜/*.md`)의 💡 첫 줄로 한 주 분위기 흐름을 만든다.
- 검증실 감시 목록 성적표(data/backtest)와 이번 주 신호가 있으면 함께.
- `config/calendar.toml`에서 다음 주 일정.

## 2. 쓰기 — `reports/YYYY-MM-DD/weekly.md` (금요일 날짜)
이모지 표기 `docs/brief-style.md`, 3,000~5,000자. **글은 `docs/brief-style.md`의 '읽기 쉬운 글쓰기' 규칙(한 문장 한 줄·짧게·의견 라벨 4줄)을 따른다.**
```
🗓️ 주간 리뷰 · MM/DD~MM/DD
KODEX 200 ▲▼x% · 나스닥 ▲▼x% · 원/달러 (기준 시각·출처)

💡 Claude 의견 3~5줄 — 이번 주 핵심과 다음 주에 주는 의미 (근거·반대 근거)
🌡️ 한 주 분위기 흐름: 월 → 화 → 수 → 목 → 금

🏭 업종 강도: 레이더 상위 5와 지난주 대비 오른/내린 업종, 확정 주도 섹터와 비교
📡 이번 주 채널 큰 흐름 3~5개 (🔥 여러 채널)
📑 리포트: 🔺 상향 많은 종목 · 🔽 하향 많은 종목 (상향 먼저)
🧾 잠정실적: 이번 주 🔴 서프라이즈 / 🔵 쇼크 주요
🔬 딥리서치 아이디어 성적: 아이디어별 수익률 vs 시장, 새로 나온 아이디어
💼 내 종목·리스크: 손익·R·손절가, 다음 주 규칙상 확인할 가격
👀 감시 목록: 이번 주 신호·후보, 성적표
📅 다음 주 일정
※ 판단은 본인이 합니다.
```

## 3. 보내고 저장
```bash
python3 tools/telegram_send.py --file reports/YYYY-MM-DD/weekly.md
git add reports data && git commit -m "주간 리뷰 MM/DD" && git push -u origin main
```

## 어투 (사용자 확정 2026-11-13)
모든 문장은 **"~입니다"**로 맺습니다. `~다 / ~한다 / ~이다`로 끝내지 않습니다. 짧게 끊고, 어미가 단조로우면 명사로 끝내도 됩니다. 자세한 규칙은 `docs/brief-style.md`.
