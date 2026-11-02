"""여러 도구가 함께 쓰는 공통 기능: 설정 파일 읽기, 환경 변수 확인, HTTP 요청."""
import json
import os
import sys
import time
import tomllib
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CONFIG = ROOT / "config"
DATA = ROOT / "data"
CACHE = DATA / "cache"

USER_AGENT = "Mozilla/5.0 (stock_team personal research bot)"


def load_toml(name):
    with open(CONFIG / name, "rb") as f:
        return tomllib.load(f)


def watchlist(market=None):
    stocks = load_toml("watchlist.toml").get("stocks", [])
    if market:
        stocks = [s for s in stocks if s.get("market") == market]
    return stocks


def channels():
    return load_toml("channels.toml").get("channels", [])


def require_env(*names):
    """필요한 환경 변수가 없으면 무엇을 등록해야 하는지 알려주고 종료한다. 값은 출력하지 않는다."""
    missing = [n for n in names if not os.environ.get(n)]
    if missing:
        sys.exit(
            "환경 변수가 등록되지 않았습니다: " + ", ".join(missing)
            + "\n클라우드 환경 편집 > 환경 변수에 등록한 뒤 새 세션을 열어 주세요."
        )
    return [os.environ[n] for n in names]


def http_get(url, params=None, timeout=20, headers=None, retries=2):
    """연결이 잠깐 끊기면(서버 오류·네트워크 끊김) 2초, 4초 쉬고 다시 시도한다. 4xx 오류는 바로 넘긴다."""
    if params:
        url = url + "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, **(headers or {})})
    for attempt in range(retries + 1):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.read()
        except urllib.error.HTTPError as e:
            if e.code < 500 or attempt == retries:
                raise
        except (urllib.error.URLError, ConnectionError, TimeoutError):
            if attempt == retries:
                raise
        time.sleep(2 * (attempt + 1))


def http_post_json(url, payload, timeout=20, headers=None):
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url, data=data,
        headers={"Content-Type": "application/json", "User-Agent": USER_AGENT, **(headers or {})},
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read())
