"""텔레그램 봇으로 메시지를 보낸다.

사용법:
    python3 tools/telegram_send.py "보낼 내용"
    python3 tools/telegram_send.py --file reports/2026-11-02/morning.md
    python3 tools/telegram_send.py --test        # 연결 테스트 메시지

필요한 환경 변수: TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID
"""
import argparse
import sys
import urllib.error

from common import http_post_json, require_env

LIMIT = 4000  # 텔레그램 한 메시지 최대 4096자, 여유를 둔다


def split_text(text, limit=LIMIT):
    """줄 단위로 끊어서 limit 이하 조각으로 나눈다."""
    chunks, cur = [], ""
    for line in text.splitlines(keepends=True):
        while len(line) > limit:
            if cur:
                chunks.append(cur)
                cur = ""
            chunks.append(line[:limit])
            line = line[limit:]
        if len(cur) + len(line) > limit:
            chunks.append(cur)
            cur = ""
        cur += line
    if cur.strip():
        chunks.append(cur)
    return chunks


def send(text):
    token, chat_id = require_env("TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID")
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    chunks = split_text(text)
    for i, chunk in enumerate(chunks, 1):
        if len(chunks) > 1:
            chunk = f"({i}/{len(chunks)})\n" + chunk
        try:
            res = http_post_json(url, {"chat_id": chat_id, "text": chunk, "disable_web_page_preview": True})
        except urllib.error.HTTPError as e:
            # 오류 메시지에 토큰이 섞이지 않도록 상태 코드와 텔레그램 설명만 출력
            sys.exit(f"전송 실패 (HTTP {e.code}): {e.read().decode('utf-8', 'replace')}")
        if not res.get("ok"):
            sys.exit(f"전송 실패: {res.get('description')}")
    print(f"전송 완료: {len(chunks)}개 메시지")


def main():
    p = argparse.ArgumentParser(description="텔레그램 메시지 보내기")
    p.add_argument("text", nargs="?", help="보낼 내용")
    p.add_argument("--file", help="내용을 읽을 파일")
    p.add_argument("--test", action="store_true", help="연결 테스트 메시지 보내기")
    a = p.parse_args()

    if a.test:
        text = "✅ stock_team 텔레그램 연결 테스트 메시지입니다."
    elif a.file:
        with open(a.file, encoding="utf-8") as f:
            text = f.read()
    elif a.text:
        text = a.text
    else:
        p.error("보낼 내용, --file, --test 중 하나가 필요합니다.")
    send(text)


if __name__ == "__main__":
    main()
