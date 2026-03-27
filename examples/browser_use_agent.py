"""
Run a browser-use AI agent on Orb Cloud.

The browser sleeps for $0 when idle and wakes in 500ms.

Usage:
    pip install orb-browser browser-use
    ORB_API_KEY=orb_... OPENAI_API_KEY=sk-... python examples/browser_use_agent.py
"""

import asyncio
import os
from orb_browser import OrbBrowser

ORB_KEY = os.environ.get("ORB_API_KEY")
if not ORB_KEY:
    print("Set ORB_API_KEY. Get one at https://docs.orbcloud.dev")
    exit(1)


async def main():
    # 1. Deploy a browser on Orb Cloud
    orb = OrbBrowser(api_key=ORB_KEY)
    cdp_url = orb.deploy()

    # 2. Connect browser-use
    from browser_use import Browser

    browser = Browser(cdp_url=cdp_url)
    await browser.start()

    # 3. Use it
    await browser.navigate_to("https://news.ycombinator.com")
    title = await browser.get_current_page_title()
    print(f"Page: {title}")

    screenshot = await browser.take_screenshot()
    with open("screenshot.png", "wb") as f:
        f.write(screenshot)
    print(f"Screenshot saved ({len(screenshot)} bytes)")

    # 4. Disconnect before sleep
    await browser.stop()

    # 5. Sleep — browser frozen to NVMe, $0/hr
    orb.sleep()
    print("Browser sleeping... (costs $0)")

    import time
    time.sleep(5)

    # 6. Wake — ~500ms, everything restored
    cdp_url = orb.wake()

    # 7. Reconnect — same page, same cookies
    browser = Browser(cdp_url=cdp_url)
    await browser.start()
    title = await browser.get_current_page_title()
    print(f"After wake: {title}")

    await browser.stop()

    # 8. Clean up
    orb.destroy()


asyncio.run(main())
