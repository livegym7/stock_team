"""텔레그램 봇으로 메시지를 보낸다.

사용법:
    python3 tools/telegram_send.py "보낼 내용"
    python3 tools/telegram_send.py --file reports/2026-11-02/morning.md
    python3 tools/telegram_send.py --test        # 연결 테스트 메시지
    python3 tools/telegram_send.py --photo 그림.png --caption "설명"   # 그림 보내기

필요한 환경 변수: TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID
"""
import argparse
import json
import sys
import urllib.error
import urllib.request
import uuid
from pathlib import Path

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


_NAME_RE = None


def bold_html(text):
    """종목명을 굵게 (텔레그램 HTML 모드). 종목 목록을 못 읽으면 글자만 안전하게 바꿔 돌려준다."""
    global _NAME_RE
    import html
    import re
    if _NAME_RE is None:
        try:
            from universe import bold_names
            names = bold_names()
            _NAME_RE = re.compile("|".join(re.escape(html.escape(n)) for n in names)) if names else False
        except Exception:
            _NAME_RE = False
    out = html.escape(text, quote=False)
    return _NAME_RE.sub(lambda m: f"<b>{m.group(0)}</b>", out) if _NAME_RE else out


def send(text, bold=True):
    """bold=True면 종목명을 굵게 보낸다 (HTML 모드). 형식 오류가 나면 그 조각은 그냥 글자로 다시 보낸다."""
    token, chat_id = require_env("TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID")
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    chunks = split_text(text, 3500 if bold else LIMIT)   # 굵게 표시 태그가 붙으므로 여유를 더 둔다
    for i, chunk in enumerate(chunks, 1):
        if len(chunks) > 1:
            chunk = f"({i}/{len(chunks)})\n" + chunk
        body = {"chat_id": chat_id, "text": chunk, "disable_web_page_preview": True}
        if bold:
            body.update(text=bold_html(chunk), parse_mode="HTML")
        try:
            try:
                res = http_post_json(url, body)
            except urllib.error.HTTPError as e:
                if not bold or e.code != 400:
                    raise
                res = http_post_json(url, {"chat_id": chat_id, "text": chunk, "disable_web_page_preview": True})
        except urllib.error.HTTPError as e:
            # 오류 메시지에 토큰이 섞이지 않도록 상태 코드와 텔레그램 설명만 출력
            sys.exit(f"전송 실패 (HTTP {e.code}): {e.read().decode('utf-8', 'replace')}")
        if not res.get("ok"):
            sys.exit(f"전송 실패: {res.get('description')}")
    print(f"전송 완료: {len(chunks)}개 메시지")


def send_photo(path, caption=""):
    """그림 1장을 보낸다 (설명은 1,024자까지). 표준 라이브러리로 multipart 요청을 직접 만든다."""
    token, chat_id = require_env("TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID")
    boundary = uuid.uuid4().hex
    parts = []
    for k, v in (("chat_id", chat_id), ("caption", caption[:1024])):
        parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n'.encode())
    parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="photo"; filename="{Path(path).name}"\r\n'
                 f"Content-Type: image/png\r\n\r\n".encode() + Path(path).read_bytes() + b"\r\n")
    parts.append(f"--{boundary}--\r\n".encode())
    req = urllib.request.Request(f"https://api.telegram.org/bot{token}/sendPhoto", data=b"".join(parts),
                                 headers={"Content-Type": f"multipart/form-data; boundary={boundary}"})
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            res = json.loads(resp.read())
    except urllib.error.HTTPError as e:
        sys.exit(f"그림 전송 실패 (HTTP {e.code}): {e.read().decode('utf-8', 'replace')}")
    if not res.get("ok"):
        sys.exit(f"그림 전송 실패: {res.get('description')}")
    print("그림 전송 완료")


def allowed(kind, name="", text=""):
    """Balance Lab 2.0 (2026-11-12): 텔레그램은 체크포인트 3회·즉시 알림·주간 요약·실패 알림만. config/features.toml [telegram]."""
    try:
        from common import load_toml
        t = (load_toml("features.toml") or {}).get("telegram") or {}
    except Exception:
        return True
    if t.get("mode") != "v2":
        return True
    if kind in ("test", "alert"):
        return True
    if kind == "file":
        return any(Path(name).name.startswith(x) for x in t.get("allow_files", []))
    # 짧은 글(실패·오류 알림)은 통과, 그 밖의 브리핑 글은 웹에만
    return len(text) <= 300 and any(w in text for w in ("실패", "오류", "건너뜀", "확인 필요"))


def main():
    p = argparse.ArgumentParser(description="텔레그램 메시지 보내기")
    p.add_argument("text", nargs="?", help="보낼 내용")
    p.add_argument("--file", help="내용을 읽을 파일")
    p.add_argument("--test", action="store_true", help="연결 테스트 메시지 보내기")
    p.add_argument("--photo", help="보낼 그림 파일 (PNG)")
    p.add_argument("--caption", default="", help="그림 설명")
    a = p.parse_args()

    if a.photo:
        if not allowed("photo", a.photo):
            print(f"보내지 않음 (Balance Lab 2.0: 텔레그램은 체크포인트·즉시 알림만, 이 그림은 웹에서 보기): {a.photo}"); return
        send_photo(a.photo, a.caption)
        return
    if a.test:
        text = "✅ stock_team 텔레그램 연결 테스트 메시지입니다."
    elif a.file:
        with open(a.file, encoding="utf-8") as f:
            text = f.read()
    elif a.text:
        text = a.text
    else:
        p.error("보낼 내용, --file, --test 중 하나가 필요합니다.")
    kind = "test" if a.test else "file" if a.file else "text"
    if not allowed(kind, a.file or "", text):
        print(f"보내지 않음 (Balance Lab 2.0: 텔레그램은 체크포인트 3회·즉시 알림·주간 요약·실패 알림만, 이 글은 웹 '시장 › 타임라인'에서 보기): {a.file or text[:40]}")
        return
    send(text)


if __name__ == "__main__":
    main()
