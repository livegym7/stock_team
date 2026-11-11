#!/usr/bin/env python3
"""Balance Lab 웹 배포용 폴더 만들기 (Cloudflare Pages, 2026-11-11).

web_build.py가 만든 web/index.html(Artifact용, 문서 머리 없음)을 일반 웹 페이지로 감싸
site/ 폴더에 넣는다: index.html · 앱 아이콘 · manifest(홈 화면 추가) · _headers(캐시 끔·검색 차단) · robots.txt.

  python3 tools/web_site.py                 # 실제 데이터로 site/ 만들기
  python3 tools/web_site.py --placeholder   # 데이터 없는 '잠금 확인 중' 페이지 (로그인 잠금 확인 전 첫 배포용)

로그인 잠금(Cloudflare Access)이 확인되기 전에는 깃허브 자동 배포가 --placeholder로만 올린다
(config/web.toml access_ready). 보유 종목·계좌가 공개 주소에 노출되지 않게 하기 위함. 주문 기능 없음, 키 없음.
"""
import argparse, json, shutil, sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WEB = ROOT / "web"
SITE = ROOT / "site"
KST = timezone(timedelta(hours=9))

HEAD = """<!doctype html>
<html lang="ko"><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<meta name="robots" content="noindex,nofollow">
<meta name="theme-color" content="#18181b">
<link rel="icon" href="/icon.svg" type="image/svg+xml">
<link rel="icon" href="/favicon.png" type="image/png" sizes="1024x1024">
<link rel="manifest" href="/manifest.webmanifest">
<link rel="apple-touch-icon" href="/icon-512.png">
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-title" content="Balance Lab">
<style>:root{color-scheme:light;box-sizing:border-box;padding-top:env(safe-area-inset-top,0px);padding-bottom:env(safe-area-inset-bottom,0px)}html{scroll-padding-top:env(safe-area-inset-top,0px)}body{margin:0;padding:0;font:14px -apple-system,BlinkMacSystemFont,sans-serif}img{max-width:100%}[hidden]:not([hidden=until-found i]){display:none!important}</style>
</head><body>
"""
TAIL = "\n</body></html>\n"

PLACEHOLDER = """<title>Balance Lab</title>
<style>body{font-family:'Noto Sans KR',system-ui,sans-serif;background:#fafafa;color:#18181b;display:grid;place-items:center;min-height:100vh;padding:0 16px}
@media (prefers-color-scheme:dark){body{background:#09090b;color:#fafafa}}main{max-width:420px;text-align:center}b{font-size:20px}p{color:#71717a;line-height:1.7}</style>
<main><img src="/icon-512.png" width="72" height="72" alt=""><p><b>Balance Lab</b></p>
<p>로그인 잠금을 확인하는 중입니다.<br>잠금이 확인되면 이 주소에 트레이딩룸이 올라옵니다.</p><p><small>{at}</small></p></main>"""


def build(placeholder=False):
    if SITE.exists():
        shutil.rmtree(SITE)
    SITE.mkdir()
    now = datetime.now(KST).strftime("%Y-%m-%d %H:%M")
    if placeholder:
        body = PLACEHOLDER.replace("{at}", f"배포 {now}")
    else:
        src = WEB / "index.html"
        if not src.exists():
            raise SystemExit("web/index.html 없음 — 먼저 python3 tools/web_build.py")
        body = src.read_text(encoding="utf-8")
    (SITE / "index.html").write_text(HEAD + body + TAIL, encoding="utf-8")
    shutil.copy(WEB / "brand" / "balance-lab-icon-1024.png", SITE / "icon-512.png")
    shutil.copy(WEB / "brand" / "balance-lab-icon.svg", SITE / "icon.svg")
    shutil.copy(WEB / "brand" / "balance-lab-icon-1024.png", SITE / "favicon.png")
    shutil.copy(WEB / "brand" / "balance-lab-icon-1024.png", SITE / "favicon.ico")   # 브라우저가 기본으로 찾는 주소 (PNG 내용, 대부분 브라우저가 읽음)
    (SITE / "manifest.webmanifest").write_text(json.dumps({
        "name": "Balance Lab", "short_name": "Balance Lab", "start_url": "/", "display": "standalone",
        "background_color": "#fafafa", "theme_color": "#18181b",
        "icons": [{"src": "/icon-512.png", "sizes": "1024x1024", "type": "image/png", "purpose": "any maskable"},
                  {"src": "/icon.svg", "sizes": "any", "type": "image/svg+xml"}]}, ensure_ascii=False), encoding="utf-8")
    (SITE / "_headers").write_text("/*\n  Cache-Control: no-store\n  X-Robots-Tag: noindex, nofollow\n  Referrer-Policy: no-referrer\n  X-Frame-Options: DENY\n", encoding="utf-8")
    (SITE / "robots.txt").write_text("User-agent: *\nDisallow: /\n", encoding="utf-8")
    kb = sum(f.stat().st_size for f in SITE.iterdir()) // 1024
    return {"site": "site/", "placeholder": placeholder, "kb": kb, "at": now}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--placeholder", action="store_true")
    a = ap.parse_args()
    print(json.dumps(build(a.placeholder), ensure_ascii=False))


if __name__ == "__main__":
    sys.exit(main())
