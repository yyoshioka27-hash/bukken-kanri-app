"""Read-only smoke check of the deployed app. Never log property data."""

import re
import time

from playwright.sync_api import sync_playwright


APP_URL = "https://bukken-kanri-app-bgm7sywfwtxevuojvhaeks.streamlit.app/"
LOADED = re.compile(r"^Supabase読込:")
WAKE = re.compile(r"Yes, get this app back up!?", re.I)


def check_once(browser):
    # A new session must read Supabase again; an old caption is not sufficient.
    context = browser.new_context()
    try:
        page = context.new_page()
        page.goto(APP_URL, wait_until="domcontentloaded", timeout=60000)
        deadline = time.monotonic() + 180
        wake_requested = False
        while time.monotonic() < deadline:
            for frame in page.frames:
                loaded = frame.get_by_text(LOADED)
                if loaded.count() and loaded.first.is_visible():
                    print("PASS: deployed app successfully loaded data from Supabase.")
                    return True
                # Only the hosting provider's wake button may be clicked.
                # Never click app controls, restore, save, or download buttons.
                wake = frame.get_by_role("button", name=WAKE)
                if not wake_requested and wake.count() and wake.first.is_visible():
                    wake.first.click(timeout=10000)
                    wake_requested = True
            page.wait_for_timeout(2000)
        return False
    finally:
        context.close()


def main():
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        try:
            for attempt in range(1, 4):
                try:
                    if check_once(browser):
                        return 0
                except Exception:
                    # Browser errors can contain page text. Do not expose it in
                    # this public repository's logs, traces, or screenshots.
                    pass
                print(f"Attempt {attempt}/3: Supabase load could not be confirmed.")
                if attempt < 3:
                    time.sleep(10)
        finally:
            browser.close()
    print("FAIL: check Streamlit and the Supabase project status; no data was edited.")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
