# 분석 깊이 모드 — 깊이(deep) ↔ 절약(lean)

2026-11-20 사용자 확정. 클로드 맥스 구독 중에는 **깊이 모드**로 돌리고, 낮은 요금제로 바꾸면 **절약 모드**(2026-11-19까지의 형태)로 돌아간다.
사용자가 "예전 형태로 돌아가 줘", "절약 모드로 바꿔 줘", "낮은 플랜으로 바꿨어"라고 하면 아래 **되돌리는 순서**대로 한다.

## 두 모드의 차이

| 항목 | 절약 (lean, ~2026-11-19) | 깊이 (deep, 2026-11-20~) |
|---|---|---|
| 리포트 카드 | Haiku, 하루 15건(월 20), 핵심 구간만 | Sonnet, 하루 30건(월 40), 가치 큰 것은 전문까지 |
| 깊이 읽기 | Sonnet 19:13, 3건, 질문 키워드 주변만 발췌 | Sonnet 20:15, 8건, 전문 끝까지, 반대 의견 2건↑ |
| 업종 노트 | 토요일 전략 보고서 때만 갱신 | 깊이 읽기 때 매일 덧붙임(숫자 시계열·갈리는 점) |
| 채널 글 | 요약만 | 사진 20장 읽기(표·차트 숫자). 주장 검증은 2026-11-20 사용자 결정으로 끔(`channel_verify = false`, 도구 `claim_check.py`는 남겨 둠) |
| 종목 메모 | 없음 (깊은 카드 한 줄 소개만) | Opus 평일 20:10, 보유·관찰 풀 하루 4종목 |
| 전략 보고서 | 전략가 → 반론가 → 편집자 | + 업종 담당 분석가 6명이 먼저 씀 |
| 수요일 중간 점검 | 없음 | Opus 수 21:40 |
| 체크포인트 | 평일 5회(07·10·12·15·18시), 텔레그램 3회 | 같음 (두 모드 공통) |
| 화면(웹) | 같음 | 같음 |

값은 `config/depth.toml`의 `[lean]`·`[deep]` 표에 있고, 스킬은 `python3 tools/depth.py`로 읽는다.

## 되돌리는 순서 (깊이 → 절약)

1. 모드 값 바꾸기: `python3 tools/depth.py set lean` → 커밋·푸시. 이것만으로 스킬의 '깊이 모드' 절은 모두 건너뛴다(채널 검증·업종 분석가·전문 읽기 포함).
2. 예약 끄기 (`config/depth.toml` `[triggers] deep_only`):
   - `trig_01BsPcnmvF54eikQU4tvYAGN` 리포트 카드 깊이 모드 (Sonnet 리서치 데스크 18:40)
   - `trig_01W6iN2ep5xi6AEJycG1kDo2` 자료실 깊이 읽기 8건 + 업종 노트 (20:15)
   - `trig_01PfwRLxDoWPMHr6Gy368SdR` 종목 메모 (Opus 20:10)
   - `trig_01Bf7D4YPuvLFnZqQH84Bdzh` 전략 중간 점검 (Opus 수 21:40)
3. 예약 다시 켜기 (`lean_only`):
   - `trig_01F4qx3sY6TzX49zg7Ymc8rt` 리포트 카드 (Haiku 18:40)
   - `trig_01AM1isJndYUigkeEM8tEevv` 자료실 3건 깊이 읽기 (Sonnet 19:13)
   - 주의: 이 19:13 예약의 지시문에는 옛 Artifact 게시 단계와 텔레그램 요약이 남아 있다. 스킬 문서가 우선이라 동작에는 영향이 없지만, 켠 뒤 첫 실행을 확인한다.
4. `config/automation.toml`의 리포트 카드·자료실 두 줄을 절약형 문구로 되돌리고, 종목 메모·전략 중간 점검 두 칸을 지운다.
5. CLAUDE.md 맨 아래 '분석 깊이 모드' 줄의 "지금: deep"을 "지금: lean"으로 고친다.
6. 예약은 끄기만 하고 지우지 않는다(지우면 그 대화의 기록이 같이 지워질 수 있다). 다시 맥스로 올리면 반대로 하면 된다.

예약 켜고 끄기는 Claude에게 말하면 된다(`update_trigger enabled`). 지시문 글은 그 예약이 묶인 대화에서만 고칠 수 있다.

## 다시 깊이 모드로 (절약 → 깊이)

위 순서를 반대로: `python3 tools/depth.py set deep` → `deep_only` 켜기 → `lean_only` 끄기 → automation.toml·CLAUDE.md 문구.

## 통째로 예전 코드로 돌아가야 할 때

- 깊이 모드를 넣기 직전 상태는 깃 가지 **`lean-2026-11-19`** (커밋 `c7ca367`)에 남겨 두었다. 보통은 위의 모드 전환으로 충분하고, 이 가지는 비상용이다.
- 쌓인 자료(업종 노트 `data/research/notes/`, 종목 메모 `data/stock_memos/`, 검증 기록 `data/telegram/claims.jsonl`, 업종 분석가 글 `data/strategy/analysts/`)는 절약 모드로 돌아가도 지우지 않는다. 다시 깊이 모드로 올 때 이어서 쓴다.

## 깊이 모드에서 새로 생긴 것

| 무엇 | 어디 |
|---|---|
| 모드 값 | `config/depth.toml`, `tools/depth.py` |
| 채널 주장 검증 기록·성적 | `tools/claim_check.py`, `data/telegram/claims.jsonl` |
| 종목 메모 | `tools/stock_memo.py`, `data/stock_memos/코드.json`, `.claude/skills/stock-memo/` |
| 업종 분석가 글 | `data/strategy/analysts/날짜_업종.md` |
| 수요일 중간 점검 | `reports/날짜/strategy_mid.md` (웹 '소식 › 정리'에 전략 글로) |
| 전용 대화 | 리서치 데스크 (Sonnet) `session_0122SASBt8bkHzv3iiiMfwKu` — 리포트 카드·깊이 읽기 |

## 지키는 선 (모드와 상관없이)

- 리포트 PDF 원문·전문은 저장하지 않는다(읽기만). 매수·매도는 단정하지 않는다. 숫자마다 출처·시각. 매매 규칙은 2027-01-31까지 고정.
- 최종 글(체크포인트·정리)의 길이는 늘리지 않는다. 깊이는 뒤에서 쌓고 화면에는 결론과 근거만.
