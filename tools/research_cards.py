#!/usr/bin/env python3
"""네이버 리서치 산업·전략 리포트 깔때기 (docs/naver-research-plan.md). PDF 원문은 저장소에 두지 않는다 — 본문 글자는 data/cache/naver_text/(커밋 안 함), 저장소에는 카드(요약·숫자·링크)만.

Tier 0 (토큰 0)
    python3 tools/research_cards.py build [--days 2]            # 본문 받기(캐시) + 자동 카드 초안: 업종·종목·숫자·표·시리즈 diff·신규성·반대 의견 신호 → data/research/cards/날짜.json
Tier 1 (Haiku가 씀)
    python3 tools/research_cards.py queue [--top 15]            # 카드 쓸 리포트 + 핵심 구간(3,500자 안팎)을 마크다운으로
    python3 tools/research_cards.py save --cat industry --nid 46926 --file card.json   # Haiku가 채운 칸 저장 (status card)
Tier 2 (Sonnet 자료실)
    python3 tools/research_cards.py pick-deep [--top 3]         # 깊이 읽을 3건 (1건은 반대 의견·비주류 업종 고정)
    python3 tools/research_cards.py questions                   # 전략 보고서(띔)에서 질문 뽑기 → data/research/questions.json
    python3 tools/research_cards.py excerpt --cat industry --nid 46926 --q "DRAM|계약가|LTA" [--window 600]   # 질문 키워드 주변 발췌 (토큰 절약)
Tier 3 (전략 보고서 재료)
    python3 tools/research_cards.py weekly [--days 7]           # 업종별 집계표(카드 수·입장·반복 주장·새 주장·숫자) → data/research/cards/weekly_latest.json + 마크다운
"""
import argparse
import json
import re
import sys
import time
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import CACHE, CONFIG, DATA, ROOT, load_toml  # noqa: E402
import naver_research as NR  # noqa: E402
from naver_quote import KST  # noqa: E402

TEXT = CACHE / "naver_text"
CARDS = DATA / "research" / "cards"
NOTES = DATA / "research" / "notes"
CATS = ("industry", "invest")   # 산업분석·투자전략만 (사용자 결정 2026-11-11). 기업 리포트는 채널 요약이 맡음

# 네이버 '기타' 업종을 세부 섹터로 보내는 키워드표 (제목+본문 앞부분). 큰 섹터 이름은 config/sector_taxonomy.toml
KEYS = [
    ("반도체", r"반도체|메모리|DRAM|D램|HBM|낸드|NAND|파운드리|소부장|웨이퍼|후공정|테스트|기판|소캠|SOCAMM"),
    ("전자부품·IT하드웨어", r"MLCC|전기전자|전자부품|PCB|카메라|디스플레이|OLED|스마트폰|가전"),
    ("2차전지", r"2차전지|이차전지|배터리|양극재|음극재|분리막|전해|ESS|BESS|리튬|CATL|LFP"),
    ("전력·에너지", r"전력기기|변압기|전선|원전|원자력|SMR|발전|가스터빈|태양광|풍력|신재생|수소|에너지|정유|LNG|유가|석유"),
    ("조선·해운", r"조선|선박|해운|컨테이너|탱커|LNG선|해양"),
    ("방산·우주", r"방산|국방|무기|우주|위성|발사체|K-?방산"),
    ("자동차", r"자동차|완성차|전기차|EV|타이어|자동차부품|모빌리티"),
    ("바이오·헬스케어", r"바이오|제약|신약|CDMO|시밀러|의료기기|미용|임상|헬스케어"),
    ("인터넷·소프트웨어", r"인터넷|플랫폼|소프트웨어|SaaS|보안|AI|데이터센터|클라우드|게임|광고|미디어|콘텐츠|엔터"),
    ("금융", r"은행|증권|보험|금융|지주|카드|핀테크|금리"),
    ("소비재", r"화장품|뷰티|음식료|식품|유통|백화점|편의점|여행|항공|레저|호텔|의류|섬유"),
    ("소재·산업재", r"화학|석유화학|철강|비철|구리|알루미늄|건설|건자재|시멘트|기계|로봇|운송|물류|택배|통신|유틸리티|지주회사|해상운임"),
    ("시장·전략", r"전략|자산배분|코스피|KOSPI|지수|매크로|금리|환율|FOMC|연준|중간선거|수급|밸류에이션|퀀트|ETF|배당"),
]
NAVER2BIG = {"반도체": "반도체", "전기전자": "전자부품·IT하드웨어", "디스플레이": "전자부품·IT하드웨어", "IT": "인터넷·소프트웨어", "인터넷포탈": "인터넷·소프트웨어", "게임": "인터넷·소프트웨어",
             "미디어": "인터넷·소프트웨어", "자동차": "자동차", "자동차부품": "자동차", "타이어": "자동차", "건설": "소재·산업재", "철강금속": "소재·산업재", "석유화학": "소재·산업재",
             "유틸리티": "소재·산업재", "통신": "소재·산업재", "지주회사": "소재·산업재", "해운": "조선·해운", "조선": "조선·해운", "항공운송": "소비재", "여행": "소비재",
             "화장품": "소비재", "음식료": "소비재", "유통": "소비재", "섬유의류": "소비재", "제약": "바이오·헬스케어", "바이오": "바이오·헬스케어", "은행": "금융", "증권": "금융",
             "보험": "금융", "금융": "금융", "에너지": "전력·에너지"}
SERIES_RE = re.compile(r"Daily|데일리|Weekly|위클리|주간|Monthly|월간|Morning|모닝|Week|Flash|Comment|코멘트|A/S|\bQ&A\b", re.I)
NEG = r"하향|보수적|과도|리스크|둔화|우려|약세|부정|축소|감익|쇼크|하회|공급 과잉|경쟁 심화|비중 ?축소|Underperform|Reduce|고점"
POS = r"상향|확대|호조|증익|서프라이즈|상회|쇼티지|가격 인상|턴어라운드|성장|수혜|비중 ?확대|Top ?Pick|Outperform|저점"
NUM_RE = re.compile(r"(?<![\w.])([+\-−]?\d[\d,]*(?:\.\d+)?)\s?(%p|%|조\s?원|억\s?원|억|조|달러|\$|원|톤|GWh|GW|MW|배|bp|만\s?대|만\s?톤|만)")
BOILER = re.compile(r"Compliance|컴플라이언스|본 자료는|본 조사분석자료|투자판단의 최종 책임|무단 복제|저작권|당사는 .{0,40}(보유|이해관계)|Disclaimer|고지 ?사항|이해상충|분석자 확인|애널리스트 확인|투자등급|Rating|이메일|@[a-z0-9.-]+\.(com|co\.kr)|02\)\s?\d{3,4}", re.I)


# ---------- 본문 ----------
def text_path(cat, nid):
    return TEXT / f"{cat}_{nid}.txt"


def clean_text(txt):
    """머리말·꼬리말·고지 문단 제거, 빈 줄 정리. 2단 레이아웃은 -layout 결과를 그대로 둔다."""
    out = []
    for l in txt.split("\n"):
        s = l.rstrip()
        if not s.strip():
            out.append(""); continue
        if BOILER.search(s) and len(s) < 220:
            continue
        if re.fullmatch(r"[\s\d\-–|·/]+", s):   # 쪽 번호·구분선
            continue
        out.append(re.sub(r"[ \t]{3,}", "  ", s))
    t = "\n".join(out)
    return re.sub(r"\n{3,}", "\n\n", t).strip()


def fetch_text(cat, nid, force=False):
    p = text_path(cat, nid)
    if p.exists() and not force:
        return p.read_text(encoding="utf-8")
    d = NR.pdf_text(cat, nid)
    txt = clean_text(d.get("text") or "")
    if not txt and d.get("summary"):
        txt = "[본문 비공개 — 네이버 요약]\n" + d["summary"]
    TEXT.mkdir(parents=True, exist_ok=True)
    p.write_text(txt, encoding="utf-8")
    time.sleep(0.4)
    return txt


# ---------- 카드 저장소 ----------
def cards_path(day):
    return CARDS / f"{day}.json"


def load_cards(day):
    p = cards_path(day)
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}


def save_cards(day, cards):
    CARDS.mkdir(parents=True, exist_ok=True)
    cards_path(day).write_text(json.dumps(cards, ensure_ascii=False, indent=1), encoding="utf-8")


def all_cards(days=45):
    since = (datetime.now(KST) - timedelta(days=days)).strftime("%Y-%m-%d")
    out = {}
    for p in sorted(CARDS.glob("2*.json")):
        if p.stem >= since:
            out.update(load_cards(p.stem))
    return out


def key(cat, nid):
    return f"{cat}:{nid}"


# ---------- Tier 0 분석 ----------
def sector_of(title, industry, text):
    probe = (title or "") + " " + (industry or "") + " " + text[:1500]
    if industry and industry != "기타" and industry in NAVER2BIG:
        big = NAVER2BIG[industry]
    else:
        best, bn = None, 0
        for name, pat in KEYS:
            n = len(re.findall(pat, probe))
            if n > bn:
                best, bn = name, n
        big = best or "기타"
    return big


def paragraphs(text):
    return [re.sub(r"\s+", " ", p).strip() for p in re.split(r"\n\s*\n", text) if len(p.strip()) >= 40]


def grams(text, n=3):
    w = re.findall(r"[가-힣A-Za-z0-9]{2,}", text)
    return {" ".join(w[i:i + n]) for i in range(max(0, len(w) - n + 1))}


def jaccard(a, b):
    return len(a & b) / len(a | b) if a and b else 0.0


def numbers(text, limit=10):
    out, seen, last = [], set(), -10 ** 6
    for m in NUM_RE.finditer(text):
        val = m.group(0).strip()
        if val in seen or len(val) < 2 or m.start() - last < 90:
            continue
        last = m.start()
        s = max(0, m.start() - 38); e = min(len(text), m.end() + 30)
        ctx = re.sub(r"\s+", " ", text[s:e]).strip()
        if re.search(r"\d{4}\.\d{1,2}\.\d{1,2}|전화|팩스", ctx):
            continue
        seen.add(val); out.append(ctx)
        if len(out) >= limit:
            break
    return out


def tables(text, min_nums=3, max_rows=20):
    rows = []
    for l in text.split("\n"):
        if len(NUM_RE.findall(l)) >= min_nums and len(l.strip()) > 20:
            rows.append(re.sub(r"\s{2,}", " | ", l.strip())[:200])
        if len(rows) >= max_rows:
            break
    return rows


def series_key(r):
    t = re.sub(r"\(.*?\)|\[.*?\]|\d{1,2}/\d{1,2}|\d{4}[.\-]\d{1,2}[.\-]?\d{0,2}|#\d+|\d+호|\d+주차|Vol\.?\s?\d+", "", r["title"], flags=re.I)
    head = re.split(r"[:|·\-–—]", t)[0].strip()
    return f"{r['broker']}|{r.get('industry') or ''}|{head[:14]}" if SERIES_RE.search(r["title"]) else None


def theme_words():
    """현재 띔·관찰 풀 키워드 (반대 의견·관련성 판정용)."""
    words = set()
    f = DATA / "strategy" / "latest.json"
    if f.exists():
        L = json.loads(f.read_text(encoding="utf-8"))
        for th in L.get("themes", []):
            for w in re.findall(r"[가-힣A-Za-z]{2,}", th.get("name", "")):
                if len(w) >= 2 and w not in ("미국", "한국", "이동", "구축", "조달", "확인", "전엔", "곳만", "바꿀"):
                    words.add(w)
            for c in th.get("companies", []):
                words.add(c["name"].split("(")[0].strip())
    wp = CONFIG / "watch_pool.toml"
    if wp.exists():
        import tomllib
        for th in tomllib.loads(wp.read_text(encoding="utf-8")).get("themes", []):
            for s in th.get("stocks", []):
                words.add(s["name"]); words.add(s.get("group") or "")
    return {w for w in words if w}


def build(days=2, force=False):
    import tg_channel
    today = datetime.now(KST)
    since = (today - timedelta(days=days)).strftime("%Y-%m-%d")
    hist = all_cards(45)
    tw = theme_words()
    made, by_day = 0, defaultdict(dict)
    for cat in CATS:
        for nid, r in NR.load(cat).items():
            if r["date"] < since:
                continue
            k = key(cat, nid)
            if k in hist and not force and hist[k].get("status") != "draft":
                by_day[r["date"]][k] = hist[k]; continue
            try:
                txt = fetch_text(cat, nid)
            except Exception as e:
                txt = ""
                err = f"{type(e).__name__}: {str(e)[:80]}"
            else:
                err = None
            body_ok = len(txt) >= 1500 and not txt.startswith("[본문 비공개")
            big = sector_of(r["title"], r.get("industry"), txt)
            skey = series_key(r)
            # 시리즈 diff: 같은 시리즈의 직전 호와 문단 겹침
            new_ratio, prev_nid = 1.0, None
            if skey:
                prev = sorted((c for c in hist.values() if c.get("series_key") == skey and c["date"] < r["date"]), key=lambda c: c["date"])
                if prev:
                    prev_nid = prev[-1]["nid"]
                    pt = text_path(prev[-1]["cat"], prev[-1]["nid"])
                    if pt.exists() and body_ok:
                        a, b = grams(txt[:12000]), grams(pt.read_text(encoding="utf-8")[:12000])
                        new_ratio = round(1 - jaccard(a, b), 2)
            # 신규성: 지난 30일 같은 큰 섹터 카드와 3-gram 유사도 (제목+요약+본문 앞 3천자)
            g = grams((r["title"] + " " + (r.get("summary") or "") + " " + txt[:3000]))
            sims = []
            for c in hist.values():
                if c.get("sector") == big and c["date"] < r["date"] and c.get("grams_n"):
                    sims.append(jaccard(g, set(c["grams_n"])))
            novelty = round(1 - max(sims), 2) if sims else 1.0
            probe = r["title"] + " " + (r.get("summary") or "") + " " + txt[:4000]
            neg, pos = len(re.findall(NEG, probe)), len(re.findall(POS, probe))
            theme_hit = sorted({w for w in tw if w and w in probe})[:6]
            card = {
                "nid": nid, "cat": cat, "date": r["date"], "broker": r["broker"], "analyst": r.get("analyst"), "title": r["title"],
                "industry": r.get("industry"), "sector": big, "url": f"https://stock.naver.com/research/{cat}/{nid}",
                "summary": (r.get("summary") or "")[:500], "reads": r.get("reads", 0),
                "chars": len(txt), "body": body_ok, "series_key": skey, "prev_nid": prev_nid, "new_ratio": new_ratio, "novelty": novelty,
                "stance_hint": "약세" if neg >= pos + 2 else "강세" if pos >= neg + 2 else "중립", "neg": neg, "pos": pos,
                "contrarian": bool(theme_hit) and neg >= pos + 2, "theme_hit": theme_hit,
                "stocks": [s["name"] for s in tg_channel.find_stocks(txt[:6000]) if not re.search(r"증권$|금융지주$", s["name"])] if body_ok else [],
                "numbers": numbers(txt) if body_ok else [], "tables": tables(txt) if body_ok else [],
                "grams_n": sorted(g)[:400], "status": "draft", "built_at": today.strftime("%Y-%m-%d %H:%M"), "error": err,
            }
            by_day[r["date"]][k] = card; hist[k] = card; made += 1
    for day, cs in by_day.items():
        old = load_cards(day); old.update(cs); save_cards(day, old)
    return {"built": made, "days": sorted(by_day), "cards_total": sum(len(v) for v in by_day.values())}


# ---------- Tier 1 큐 ----------
def core_excerpt(txt, tw, head=1800, tail=600, win=500, cap=3500):
    """핵심 구간: 앞 1,800자(요약·결론) + 숫자 표 줄 + 띔 키워드 주변 + 마지막 600자."""
    parts = [txt[:head]]
    tb = tables(txt, max_rows=8)
    if tb:
        parts.append("[표]\n" + "\n".join(tb))
    hits = []
    for w in tw:
        i = txt.find(w, head)
        if i > 0:
            hits.append(txt[max(0, i - win // 2): i + win // 2].replace("\n", " "))
        if len(hits) >= 2:
            break
    if hits:
        parts.append("[띔 키워드 주변]\n" + "\n…\n".join(hits))
    if len(txt) > head + tail:
        parts.append("[끝부분]\n" + txt[-tail:])
    out = re.sub(r"[ \t]{2,}", " ", "\n\n".join(parts))
    return out[:cap]


def rank(c):
    s = 0
    s += 40 * (c.get("novelty") or 0) + 25 * (c.get("new_ratio") or 0)
    s += 15 if c.get("theme_hit") else 0
    s += 15 if c.get("contrarian") else 0
    s += 10 if c["cat"] == "industry" else 5
    s += min(10, (c.get("reads") or 0) // 50)
    s -= 15 if (c.get("series_key") and (c.get("new_ratio") or 1) < 0.4) else 0
    s -= 30 if re.search(r"Daily|데일리|Morning|모닝|Start with|Brief\b|Commodity Weekly|금리·환율 전망|Market Monitor|주간 전망", c["title"], re.I) else 0   # 시황 정리류는 채널 정리가 이미 함
    return round(s, 1)


def queue(top=15, day=None):
    cards = all_cards(3)
    day = day or datetime.now(KST).strftime("%Y-%m-%d")
    pool = [c for c in cards.values() if c["status"] == "draft" and c.get("body") and c["date"] >= (datetime.fromisoformat(day) - timedelta(days=1)).strftime("%Y-%m-%d")]
    pool.sort(key=lambda c: -rank(c))
    per, picked = Counter(), []
    for c in pool:   # 섹터당 최대 4건 — 시장·전략 리포트가 큐를 다 차지하지 않게
        if per[c["sector"]] >= 4:
            continue
        per[c["sector"]] += 1; picked.append(c)
        if len(picked) >= top:
            break
    pool = picked
    tw = theme_words()
    L = [f"# Tier 1 카드 큐 {day} — {min(top, len(pool))}/{len(pool)}건 (초안 draft 중 본문 있는 것, 점수 순). 카드 형식은 .claude/skills/research-cards/SKILL.md"]
    for c in pool:
        txt = text_path(c["cat"], c["nid"]).read_text(encoding="utf-8")
        prev = f" · 시리즈 직전 호 {c['prev_nid']} 대비 새 문단 {int((c.get('new_ratio') or 1) * 100)}%" if c.get("prev_nid") else ""
        L.append(f"\n## [{c['cat']}:{c['nid']}] {c['title']} — {c['broker']} {c['date']} · 섹터 {c['sector']}({c.get('industry')}) · 신규성 {c['novelty']} · 추정 입장 {c['stance_hint']}{prev} · 띔 키워드 {', '.join(c.get('theme_hit') or []) or '-'} · 종목 {', '.join(c.get('stocks') or [])[:80]}")
        L.append(f"네이버 요약: {c['summary'][:300]}")
        L.append("```\n" + core_excerpt(txt, c.get("theme_hit") or list(tw)[:10]) + "\n```")
    return "\n".join(L)


def save_card(cat, nid, fields):
    cards = all_cards(60)
    k = key(cat, nid)
    if k not in cards:
        raise SystemExit(f"카드 초안 없음: {k} (먼저 build)")
    c = cards[k]
    allowed = ("thesis", "stance", "numbers3", "reasons", "risks", "new_claim", "depth_value", "depth_why", "sectors_fine", "stocks_key", "horizon", "filled_by")
    c.update({a: fields[a] for a in allowed if a in fields})
    c["status"] = "card"; c["filled_at"] = datetime.now(KST).strftime("%Y-%m-%d %H:%M")
    day = c["date"]; d = load_cards(day); d[k] = c; save_cards(day, d)
    return {"saved": k, "status": "card"}


# ---------- Tier 2 ----------
WEEKQ = DATA / "strategy" / "questions_week.json"   # 토요일 보고서가 남기는 '이번 주 확인할 질문' (2026-11-15)


def _pool_targets():
    """관찰 풀(테크노펀더 지면이 씀): C1 핵심 후보 코드·이름, 리더 업종(C1·C4 그룹)과 그 종목 이름"""
    wp = load_toml("watch_pool.toml") or {}
    core, groups = {}, defaultdict(set)
    for th in wp.get("themes", []):
        for st in th.get("stocks", []):
            # 2026-11-20: 풀이 '큰 줄기의 기업 지도'로 바뀜 → 핵심 = 행동 '준비'(옛 C1), 업종은 풀 전체(옛 C1·C4)
            if th.get("id") == "C1" or st.get("action") == "준비":
                core[st["code"]] = st["name"]
            if (th.get("id") in ("C1", "C4") or th.get("stage") == "큰 줄기") and st.get("group"):
                groups[st["group"]].add(st["name"])
    return core, groups


def _week_q():
    if not WEEKQ.exists():
        return []
    d = json.loads(WEEKQ.read_text(encoding="utf-8"))
    try:
        if (datetime.now(KST).date() - datetime.fromisoformat(d.get("issue_date", "2000-01-01")).date()).days > 8:
            return []
    except Exception:
        return []
    return d.get("items") or []


def _deep_done_ids():
    docs = DATA / "research" / "docs"
    return {f.stem for f in docs.glob("*.json")} if docs.exists() else set()


def pick_deep(top=3, days=2):
    """깊이 읽기 3칸 (2026-11-15 사용자 확정): ① 핵심 후보 종목 리포트 ② 리더 업종 산업 리포트 ③ 반대 의견(고정).
    '이번 주 질문'(questions_week.json)에 걸리는 리포트를 먼저. 칸이 비면 옛 점수 순으로 채움."""
    core, groups = _pool_targets()
    wq = _week_q()
    qkw = "|".join(x.get("kw", "") for x in wq if x.get("kw")) or None
    qre = re.compile(qkw, re.I) if qkw else None
    done = _deep_done_ids()
    picked = []
    # ① 핵심 후보 종목 리포트 (네이버 국내종목, 45일, 아직 안 읽은 것, 최신·질문 일치 우선)
    comp = [r for r in NR.load("company").values() if r.get("code") in core and f"naver_company_{r['nid']}" not in done]
    comp.sort(key=lambda r: ((1 if qre and qre.search(r.get("title", "") + r.get("summary", "")) else 0), r.get("date", "")), reverse=True)
    if comp:
        r = comp[0]
        picked.append({"slot": "① 핵심 후보 종목", "cat": "company", "nid": r["nid"], "title": r["title"], "broker": r.get("broker"), "date": r.get("date"),
                       "sector": r.get("name"), "why": f"핵심 후보 {r.get('name')} 리포트 · 목표가 {r.get('target') or '-'}", "url": f"https://stock.naver.com/research/company/{r['nid']}"})
    cards = all_cards(max(days, 7))
    pool = [c for c in cards.values() if c["status"] in ("card", "draft") and c.get("body") and f"naver_{c['cat']}_{c['nid']}" not in done and c["status"] != "deep"]
    val = {"상": 30, "중": 10, "하": -20}

    def sc(c):
        q = 20 if qre and qre.search(c["title"] + " " + (c.get("summary") or "")) else 0
        return rank(c) + val.get(c.get("depth_value"), 0) + (10 if c["status"] == "card" else 0) + q

    # ② 리더 업종 산업 리포트: 카드의 종목·제목이 리더 업종 이름이나 그 업종 종목과 겹치는 것
    def hit_group(c):
        txt = c["title"] + " " + (c.get("industry") or "") + " " + " ".join(c.get("stocks") or [])
        for g, names in groups.items():
            toks = [t for t in re.split(r"[·/\s]+", g) if len(t) >= 2]
            if any(t in txt for t in toks) or any(n in txt for n in names):
                return g
        return None
    lead = sorted((c for c in pool if hit_group(c)), key=lambda c: -sc(c))
    if lead:
        c = lead[0]
        picked.append({"slot": "② 리더 업종", "cat": c["cat"], "nid": c["nid"], "title": c["title"], "broker": c["broker"], "date": c["date"], "sector": hit_group(c),
                       "why": f"리더 업종 {hit_group(c)} · 점수 {sc(c)}", "url": c["url"]})
    # ③ 반대 의견 (기존 규칙)
    is_contra = lambda c: bool(c.get("theme_hit") or hit_group(c)) and (c.get("stance") or c.get("stance_hint")) == "약세" and c.get("depth_value") != "하"  # noqa: E731
    used = {x["nid"] for x in picked}
    cont = sorted((c for c in pool if is_contra(c) and c["nid"] not in used), key=lambda c: -sc(c))
    if not cont:
        cont = sorted((c for c in pool if not c.get("theme_hit") and not hit_group(c) and c.get("depth_value") != "하" and c["nid"] not in used), key=lambda c: -sc(c))
    if cont:
        c = cont[0]
        picked.append({"slot": "③ 반대 의견", "cat": c["cat"], "nid": c["nid"], "title": c["title"], "broker": c["broker"], "date": c["date"], "sector": c["sector"],
                       "why": f"반대 의견·비주류 고정 · 입장 {c.get('stance') or c['stance_hint']}", "url": c["url"]})
    # 빈 칸은 옛 점수 순
    used = {x["nid"] for x in picked}
    for c in sorted((c for c in pool if c["nid"] not in used), key=lambda c: -sc(c)):
        if len(picked) >= top:
            break
        picked.append({"slot": "보충", "cat": c["cat"], "nid": c["nid"], "title": c["title"], "broker": c["broker"], "date": c["date"], "sector": c["sector"], "why": f"점수 {sc(c)}", "url": c["url"]})
    return picked[:top]


def answers(days=7):
    """한 주 깊이 읽기에서 질문에 답이 나온 것 (토요일 보고서 필수 재료, 2026-11-15)"""
    docs = DATA / "research" / "docs"
    since = (datetime.now(KST) - timedelta(days=days)).strftime("%Y-%m-%d")
    out = []
    for f in sorted(docs.glob("*.json")) if docs.exists() else []:
        d = json.loads(f.read_text(encoding="utf-8"))
        if (d.get("analyzed_at") or "")[:10] < since:
            continue
        for q in d.get("questions") or []:
            a = str(q.get("answer") or "")
            if a and not a.startswith("없음"):
                out.append({"q": q.get("q"), "answer": a, "from": f"{d.get('broker', '')} {d.get('title', '')}".strip(), "file_id": d.get("file_id")})
    return {"days": days, "n": len(out), "items": out}


def _old_pick_deep(top=3, days=2):
    cards = all_cards(days)
    done = {c["nid"] for c in cards.values() if c["status"] == "deep"}
    pool = [c for c in cards.values() if c["status"] in ("card", "draft") and c.get("body") and c["nid"] not in done]
    val = {"상": 30, "중": 10, "하": -20}
    def sc(c):
        return rank(c) + val.get(c.get("depth_value"), 0) + (10 if c["status"] == "card" else 0)
    # 반대 의견 판정: 카드가 있으면 카드 입장(stance) 우선, 없으면 초안의 추정 입장 — 띔 관련 + 약세
    is_contra = lambda c: bool(c.get("theme_hit")) and (c.get("stance") or c.get("stance_hint")) == "약세" and c.get("depth_value") != "하"
    cont = sorted((c for c in pool if is_contra(c)), key=lambda c: -sc(c))
    if not cont:   # 반대 의견이 없으면 띔 밖(비주류) 업종 중 깊이 가치 '하'가 아닌 것
        cont = sorted((c for c in pool if not c.get("theme_hit") and c.get("depth_value") != "하"), key=lambda c: -sc(c))
    main = sorted((c for c in pool if c not in cont[:1]), key=lambda c: -sc(c))
    chosen = main[:max(1, top - 1)] + cont[:1]
    return [{"cat": c["cat"], "nid": c["nid"], "title": c["title"], "broker": c["broker"], "date": c["date"], "sector": c["sector"], "why": ("반대 의견·비주류 고정" if c in cont[:1] else "") + f" 점수 {sc(c)} 신규성 {c['novelty']} 입장 {c.get('stance') or c['stance_hint']} 깊이 {c.get('depth_value') or '-'}", "url": c["url"]} for c in chosen]


def mark_deep(cat, nid, file_id=None):
    cards = all_cards(60)
    k = key(cat, nid)
    if k not in cards:
        raise SystemExit(f"카드 없음: {k}")
    c = cards[k]; c["status"] = "deep"; c["deep_file"] = file_id or f"naver_{cat}_{nid}"; c["deep_at"] = datetime.now(KST).strftime("%Y-%m-%d %H:%M")
    d = load_cards(c["date"]); d[k] = c; save_cards(c["date"], d)
    return {"marked": k}


def questions():
    wq = _week_q()
    if wq:   # 토요일 보고서가 남긴 '이번 주 질문'이 있으면 그것 (2026-11-15)
        out = {"made_at": datetime.now(KST).strftime("%Y-%m-%d %H:%M"), "source": "questions_week.json",
               "themes": [{"id": "W", "name": "이번 주 확인할 질문 (전략 보고서)", "questions": [{"q": x["q"], "kw": x.get("kw") or kw(x["q"])} for x in wq]}]}
        (DATA / "research").mkdir(parents=True, exist_ok=True)
        (DATA / "research" / "questions.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
        return out
    f = DATA / "strategy" / "latest.json"
    out = {"made_at": datetime.now(KST).strftime("%Y-%m-%d %H:%M"), "themes": []}
    if f.exists():
        L = json.loads(f.read_text(encoding="utf-8"))
        for th in L.get("themes", []):
            qs = []
            if th.get("invalid"):
                qs.append({"q": "무효 신호 점검: " + th["invalid"], "kw": kw(th["invalid"])})
            for c in th.get("companies", [])[:6]:
                if c.get("check"):
                    qs.append({"q": f"{c['name']}: {c['check']}", "kw": kw(c["check"] + " " + c["name"])})
            for cp in (th.get("catalysts") or [])[:3]:
                qs.append({"q": f"촉매 {cp.get('date')}: {cp.get('event')}", "kw": kw(cp.get("event", ""))})
            out["themes"].append({"id": th["id"], "name": th["name"], "questions": qs[:6]})
        for cp in (L.get("checkpoints") or [])[:6]:
            out.setdefault("general", []).append({"q": cp, "kw": kw(cp)})
    (DATA / "research").mkdir(parents=True, exist_ok=True)
    (DATA / "research" / "questions.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    return out


def kw(text):
    stop = {"여부", "확인", "필요", "이후", "대비", "기준", "수준", "관련", "또는", "있는", "없는", "하는", "이번", "오늘", "내년", "가장", "공통의", "지점", "되는지", "맞는지", "하면", "까지", "보도와", "발표", "숫자", "시점", "전제", "띔의", "띔은", "본다", "보류한다"}
    w = [re.sub(r"(의|이|가|을|를|은|는|에서|으로|로)$", "", x) for x in re.findall(r"[가-힣A-Za-z]{2,}", text)]
    w = [x for x in w if len(x) >= 2 and x not in stop]
    return "|".join(dict.fromkeys(w[:8]))


def excerpt(cat, nid, q, window=600, max_hits=6):
    txt = fetch_text(cat, nid)
    pat = re.compile(q, re.I)
    hits, last = [], -10 ** 9
    for m in pat.finditer(txt):
        if m.start() - last < window:
            continue
        last = m.start()
        s, e = max(0, m.start() - window // 2), min(len(txt), m.end() + window // 2)
        hits.append({"at": m.start(), "match": m.group(0), "text": re.sub(r"\n{2,}", "\n", txt[s:e])})
        if len(hits) >= max_hits:
            break
    return {"cat": cat, "nid": nid, "chars": len(txt), "q": q, "hits": hits, "note": "없으면 본문에 그 질문의 답이 없는 것 — '없음'으로 적는다"}


# ---------- Tier 3 ----------
def weekly(days=7):
    cards = [c for c in all_cards(days).values()]
    by = defaultdict(list)
    for c in cards:
        by[c["sector"]].append(c)
    rows = []
    for sec, cs in by.items():
        st = Counter((c.get("stance") or c.get("stance_hint")) for c in cs)
        theses = [c.get("thesis") for c in cs if c.get("thesis")]
        # 반복 주장: 논지 3-gram 겹침으로 묶기
        groups = []
        for t in theses:
            g = grams(t, 2)
            for grp in groups:
                if jaccard(g, grp["g"]) > 0.25:
                    grp["n"] += 1; break
            else:
                groups.append({"t": t, "g": g, "n": 1})
        rep = sorted(groups, key=lambda x: -x["n"])[:3]
        new = [c.get("new_claim") for c in cs if c.get("new_claim")][:5]
        nums = []
        for c in cs:
            nums += (c.get("numbers3") or [])[:2]
        rows.append({"sector": sec, "n": len(cs), "n_cards": sum(1 for c in cs if c["status"] in ("card", "deep")), "n_deep": sum(1 for c in cs if c["status"] == "deep"),
                     "stance": dict(st), "brokers": len({c["broker"] for c in cs}), "novelty_avg": round(sum(c.get("novelty") or 0 for c in cs) / len(cs), 2),
                     "contrarian": sum(1 for c in cs if c.get("contrarian")), "repeated": [{"claim": r["t"][:120], "n": r["n"]} for r in rep],
                     "new_claims": [x[:140] for x in new], "numbers": nums[:8], "titles": [f"{c['date'][5:]} {c['broker']} {c['title'][:40]}" for c in sorted(cs, key=lambda c: -(c.get('novelty') or 0))[:5]]})
    rows.sort(key=lambda r: -r["n"])
    out = {"made_at": datetime.now(KST).strftime("%Y-%m-%d %H:%M"), "days": days, "n": len(cards), "sectors": rows}
    CARDS.mkdir(parents=True, exist_ok=True)
    (CARDS / "weekly_latest.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    return out


def weekly_md(o):
    L = [f"## 네이버 산업·전략 리포트 카드 집계 ({o['days']}일, {o['n']}건, {o['made_at']})"]
    for r in o["sectors"]:
        L.append(f"- **{r['sector']}** {r['n']}건(카드 {r['n_cards']}·깊이 {r['n_deep']}, 증권사 {r['brokers']}) 입장 {r['stance']} 신규성 {r['novelty_avg']} 반대 {r['contrarian']}")
        for x in r["repeated"]:
            L.append(f"  · 반복 주장(×{x['n']}): {x['claim']}")
        for x in r["new_claims"][:3]:
            L.append(f"  · 새 주장: {x}")
        if r["numbers"]:
            L.append("  · 숫자: " + " / ".join(r["numbers"][:5]))
    return "\n".join(L)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("build"); s.add_argument("--days", type=int, default=2); s.add_argument("--force", action="store_true")
    s = sub.add_parser("queue"); s.add_argument("--top", type=int, default=15); s.add_argument("--date")
    s = sub.add_parser("save"); s.add_argument("--cat", required=True); s.add_argument("--nid", required=True); s.add_argument("--file"); s.add_argument("--json")
    s = sub.add_parser("pick-deep"); s.add_argument("--top", type=int, default=3)
    sub.add_parser("questions")
    s = sub.add_parser("answers"); s.add_argument("--days", type=int, default=7)
    s = sub.add_parser("mark-deep"); s.add_argument("--cat", required=True); s.add_argument("--nid", required=True); s.add_argument("--file-id")
    s = sub.add_parser("excerpt"); s.add_argument("--cat", required=True); s.add_argument("--nid", required=True); s.add_argument("--q", required=True); s.add_argument("--window", type=int, default=600)
    s = sub.add_parser("weekly"); s.add_argument("--days", type=int, default=7); s.add_argument("--json", action="store_true")
    a = ap.parse_args()
    if a.cmd == "build":
        print(json.dumps(build(a.days, a.force), ensure_ascii=False))
    elif a.cmd == "queue":
        print(queue(a.top, a.date))
    elif a.cmd == "save":
        fields = json.loads(Path(a.file).read_text(encoding="utf-8")) if a.file else json.loads(a.json or "{}")
        print(json.dumps(save_card(a.cat, a.nid, fields), ensure_ascii=False))
    elif a.cmd == "pick-deep":
        print(json.dumps(pick_deep(a.top), ensure_ascii=False, indent=1))
    elif a.cmd == "mark-deep":
        print(json.dumps(mark_deep(a.cat, a.nid, a.file_id), ensure_ascii=False))
    elif a.cmd == "questions":
        q = questions(); print(json.dumps({"themes": len(q["themes"]), "questions": sum(len(t["questions"]) for t in q["themes"]) + len(q.get("general", []))}, ensure_ascii=False))
    elif a.cmd == "answers":
        print(json.dumps(answers(a.days), ensure_ascii=False, indent=1))
    elif a.cmd == "excerpt":
        print(json.dumps(excerpt(a.cat, a.nid, a.q, a.window), ensure_ascii=False, indent=1))
    elif a.cmd == "weekly":
        o = weekly(a.days); print(json.dumps(o, ensure_ascii=False) if a.json else weekly_md(o))


if __name__ == "__main__":
    main()
