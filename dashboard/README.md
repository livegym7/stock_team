# 추세추종 대시보드

- 주소: https://claude.ai/artifact/6LDKCAjVkD2gUaZ1RYBP6C (Claude 아티팩트, 비공개. 웹·휴대폰 Claude 앱에서 열림)
- 화면 원본: `dashboard/index.html` (아티팩트 저장소의 `files/index.html`과 같은 내용)
- 데이터: `python3 tools/dashboard_data.py --collect` → `data/dashboard/*.json` 12개 → 아티팩트에 파일로 올리고 `datasets/<이름>` 문서의 `url`·`updated`를 바꾼다
- 데이터 이름: kospi_daily, market, flows, sectors, industries, watch, running, channel_mix, report_dirs, top_news, schedule, disclosures
- 계산(화면 안): kospi_ma(20·60일선), regime(신호등)
