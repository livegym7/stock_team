"""공개 텔레그램 채널(t.me/s/채널아이디)의 글을 모아 저장하고 보여준다.

사용법:
    python3 tools/tg_channel.py collect               # 모든 채널의 새 글 수집 (data/telegram/에 저장)
    python3 tools/tg_channel.py show --hours 24       # 최근 24시간 글을 JSON으로 출력
    python3 tools/tg_channel.py show --hours 24 --watchlist   # 관심종목 관련 글만
    python3 tools/tg_channel.py show --type research  # 리서치 요약 글만

로그인이나 API 키가 필요 없다. 공개 채널만 읽을 수 있다.
"""
import argparse
import html
import json
import re
import time
from datetime import datetime, timedelta, timezone

from common import DATA, channels, http_get, watchlist

KST = timezone(timedelta(hours=9))
STORE = DATA / "telegram"

BODY_RE = re.compile(r'<div class="tgme_widget_message_text[^"]*"[^>]*>(.*?)</div>', re.S)
TIME_RE = re.compile(r'<time[^>]*datetime="([^"]+)"')
# 예) 목표주가 180,000원 >> 160,000원 | 투자의견 매수-유지 | KB증권
TARGET_RE = re.compile(r"목표주가\s*([\d,]+)원\s*>>\s*([\d,]+)원\s*\|\s*투자의견\s*([^|]+?)\s*\|\s*(\S.*)")
# 예) [✨ 리서치 요약] 기아 목표주가 하향 리포트 요약
TITLE_RE = re.compile(r"\[✨ 리서치 요약\]\s*(.+?)\s+목표주가\s*(상향|하향|유지)")


def to_text(body):
    body = re.sub(r"<br\s*/?>", "\n", body or "")
    return html.unescape(re.sub(r"<[^>]+>", "", body)).strip()


def classify(text):
    m = re.match(r"\s*\[([^\]]+)\]", text)
    tag = m.group(1) if m else ""
    if tag == "✨ 리서치 요약":
        return "research"
    if tag.startswith("✨ 리서치"):
        return "research_ranking"
    if tag == "입법":
        return "legislation"
    if tag == "시황" or text.startswith("🎯"):
        return "market"
    if tag == "퀀트 시그널":
        return "quant"
    if tag == "한국은행":
        return "bok"
    if tag.startswith("종목 토론실"):
        return "discussion"
    if text.startswith("💬") and "현재가" in text.split("\n")[0]:
        return "price"
    return "other"


def parse_research(text):
    """리서치 요약 글에서 종목, 방향, 목표가, 투자의견, 증권사를 뽑는다."""
    info = {}
    t = TITLE_RE.search(text)
    if t:
        info["stock"], info["direction"] = t.group(1), t.group(2)
    m = TARGET_RE.search(text)
    if m:
        info["target_before"] = int(m.group(1).replace(",", ""))
        info["target_after"] = int(m.group(2).replace(",", ""))
        info["opinion"] = m.group(3).strip()
        info["broker"] = m.group(4).strip()
    return info


def fetch_page(channel, before=None):
    params = {"before": before} if before else None
    page = http_get(f"https://t.me/s/{channel}", params).decode("utf-8", "replace")
    posts = []
    # 글 하나하나를 data-post 기준으로 잘라서 처리 (다른 글의 내용이 섞이지 않게)
    for block in page.split('data-post="')[1:]:
        post_id = block.split('"', 1)[0]
        body, tm = BODY_RE.search(block), TIME_RE.search(block)
        text = to_text(body.group(1)) if body else ""
        if not text or not tm:  # 사진만 있는 글 등은 건너뜀
            continue
        post = {
            "channel": channel,
            "id": int(post_id.rsplit("/", 1)[1]),
            "url": f"https://t.me/{post_id}",
            "time": datetime.fromisoformat(tm.group(1)).astimezone(KST).isoformat(),
            "type": classify(text),
            "text": text,
        }
        if post["type"] == "research":
            post.update(parse_research(text))
        posts.append(post)
    return posts


def load_store(channel):
    path = STORE / f"{channel}.jsonl"
    if not path.exists():
        return {}
    with open(path, encoding="utf-8") as f:
        return {p["id"]: p for p in map(json.loads, f)}


def mark_duplicates(posts):
    """같은 종목·증권사·목표가 리포트가 3시간 안에 다시 올라오면 중복으로 표시한다."""
    seen = {}
    for p in sorted(posts, key=lambda x: x["id"]):
        if p["type"] != "research" or "broker" not in p:
            continue
        key = (p.get("stock"), p["broker"], p.get("target_after"))
        t = datetime.fromisoformat(p["time"])
        if key in seen and t - seen[key] < timedelta(hours=3):
            p["duplicate"] = True
        else:
            seen[key] = t


def collect(channel, max_pages=10):
    """저장된 마지막 글 이후의 새 글을 모은다. 처음에는 최대 max_pages 페이지(약 200개)까지."""
    store = load_store(channel)
    last = max(store) if store else 0
    new, before = [], None
    for _ in range(max_pages):
        page = fetch_page(channel, before)
        if not page:
            break
        new += [p for p in page if p["id"] > last and p["id"] not in store]
        oldest = min(p["id"] for p in page)
        if oldest <= last:
            break
        before = oldest
        time.sleep(1)  # 서버에 부담을 주지 않도록 천천히
    for p in new:
        store[p["id"]] = p
    for p in store.values():  # 분류 규칙이 바뀌어도 저장된 글에 반영되도록 다시 분류
        p["type"] = classify(p["text"])
    posts = sorted(store.values(), key=lambda x: x["id"])
    mark_duplicates(posts)
    STORE.mkdir(parents=True, exist_ok=True)
    with open(STORE / f"{channel}.jsonl", "w", encoding="utf-8") as f:
        for p in posts:
            f.write(json.dumps(p, ensure_ascii=False) + "\n")
    return len(new)


def show(hours, only_type=None, only_watchlist=False):
    since = datetime.now(KST) - timedelta(hours=hours)
    names = [s["name"] for s in watchlist()]
    out = []
    for ch in channels():
        for p in load_store(ch["id"]).values():
            if datetime.fromisoformat(p["time"]) < since or p.get("duplicate"):
                continue
            if only_type and p["type"] != only_type:
                continue
            if only_watchlist and not any(n.lower() in p["text"].lower() for n in names):
                continue
            out.append(p)
    out.sort(key=lambda x: x["time"])
    print(json.dumps(out, ensure_ascii=False, indent=1))


def main():
    p = argparse.ArgumentParser(description="공개 텔레그램 채널 글 수집/조회")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("collect")
    s = sub.add_parser("show")
    s.add_argument("--hours", type=int, default=24)
    s.add_argument("--type", choices=[
        "research", "research_ranking", "market", "quant", "bok", "discussion", "legislation", "price", "other",
    ])
    s.add_argument("--watchlist", action="store_true", help="관심종목이 언급된 글만")
    a = p.parse_args()

    if a.cmd == "collect":
        for ch in channels():
            print(f"{ch['id']}: 새 글 {collect(ch['id'])}개")
    else:
        show(a.hours, a.type, a.watchlist)


if __name__ == "__main__":
    main()
