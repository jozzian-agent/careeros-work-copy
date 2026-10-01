"""Screenshot a self-contained HTML page to PNG via headless Chromium (Playwright sync API)."""

from __future__ import annotations

from functools import lru_cache
import glob
from pathlib import Path

from playwright.sync_api import Error, sync_playwright

#: Pinned headless_shell binary -- reuse the installed playwright browser, no download.
#: Globbed because the revision directory drifts when playwright is upgraded.
CHROMIUM_PATH = sorted(
    glob.glob(
        "/root/.cache/ms-playwright/chromium_headless_shell-*/"
        "chrome-headless-shell-linux64/chrome-headless-shell"
    )
)[-1]


@lru_cache(maxsize=1)
def chromium_available() -> bool:
    """Whether pinned Chromium can run, including in a restricted sandbox."""
    if not Path(CHROMIUM_PATH).exists():
        return False
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(executable_path=CHROMIUM_PATH)
            browser.close()
    except Error as exc:
        if "sandbox_host_linux.cc" in str(exc) and "Operation not permitted" in str(exc):
            return False
        raise
    return True


def render_page_png(html_path: str, png_path: str, viewport_width: int = 1200) -> None:
    """Screenshot a local HTML file to a PNG using the pinned headless Chromium binary."""
    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path=CHROMIUM_PATH)
        try:
            page = browser.new_page(
                viewport={"width": viewport_width, "height": 900},
                device_scale_factor=2,
            )
            page.goto(Path(html_path).resolve().as_uri(), wait_until="networkidle")
            page.screenshot(path=png_path, full_page=True)
        finally:
            browser.close()
