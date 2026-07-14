"""
fb_login.py — one-time login for the FB BURNER account.

Opens a real browser window with a persistent profile (fb_profile/). Log in
manually there — that also handles any checkpoint FB throws. When you can see
the feed, close the browser window; the session stays saved in fb_profile/
and fb_feed.py reuses it. No password is ever written to disk.

BURNER ACCOUNT ONLY. Never log the main account in here.
"""
from playwright.sync_api import sync_playwright

import config

def main():
    with sync_playwright() as p:
        ctx = p.chromium.launch_persistent_context(
            config.FB_PROFILE_DIR,
            headless=False,
            viewport={"width": 1280, "height": 850},
            locale="en-US",
        )
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        page.goto("https://www.facebook.com/", timeout=60000)
        print("Log in to the BURNER account in the window (NEVER the main one).")
        print("Solve any checkpoint FB shows. When you can see the feed,")
        print("close the browser window to finish.")
        try:
            page.wait_for_event("close", timeout=0)
        except Exception:
            pass  # window/browser closed — that's the exit signal
        try:
            ctx.close()
        except Exception:
            pass
    print(f"Session saved to {config.FB_PROFILE_DIR}/ — fb_feed.py can run now.")

if __name__ == "__main__":
    main()
