"""HTML 파일을 PNG 그림으로 바꾼다 (텔레그램으로 표를 그림으로 보내기 위해).

크롬/크로미움의 화면 캡처 기능(--headless --screenshot)을 쓴다. 깃허브 Actions(ubuntu)에는 google-chrome이 기본으로 있다.
한글 글꼴이 없으면 글자가 네모로 나오므로 깃허브에서는 fonts-noto-cjk를 설치한다 (워크플로 참고).
"""
import glob
import shutil
import subprocess
from pathlib import Path

CANDIDATES = ["google-chrome", "google-chrome-stable", "chromium", "chromium-browser"]


def find_chrome():
    for c in CANDIDATES:
        if shutil.which(c):
            return shutil.which(c)
    found = sorted(glob.glob("/opt/pw-browsers/chromium-*/chrome-linux*/chrome"))
    return found[-1] if found else None


def html_to_png(html_path, png_path, width, height):
    """성공하면 True. 높이는 내용에 맞게 호출하는 쪽에서 넉넉히 정한다."""
    chrome = find_chrome()
    if not chrome:
        return False
    cmd = [chrome, "--headless=new", "--no-sandbox", "--disable-gpu", "--hide-scrollbars",
           "--force-device-scale-factor=2", f"--window-size={width},{height}",
           f"--screenshot={Path(png_path).resolve()}", Path(html_path).resolve().as_uri()]
    try:
        subprocess.run(cmd, check=True, capture_output=True, timeout=60)
    except (OSError, subprocess.SubprocessError):
        return False
    return Path(png_path).exists()
