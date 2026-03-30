"""
Browser agent that runs on Orb Cloud.

browser-use + Chrome run together in the same VM.
Accepts tasks via HTTP, executes them locally — no remote CDP.
"""

import asyncio
import json
import os
from http.server import HTTPServer, BaseHTTPRequestHandler
from threading import Thread

os.environ["PLAYWRIGHT_BROWSERS_PATH"] = os.environ.get("PLAYWRIGHT_BROWSERS_PATH", "/opt/browsers")

# Global browser instance
browser = None
browser_ready = False
init_error = None


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/health":
            self.respond({"status": "ok", "browserReady": browser_ready, "error": init_error})
        elif self.path == "/status":
            self.respond({
                "status": "ok",
                "browserReady": browser_ready,
                "error": init_error,
                "currentUrl": None,  # TODO: track current URL
            })
        else:
            self.respond({"error": "not found"}, 404)

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(length)) if length else {}

        if self.path == "/navigate":
            url = body.get("url", "https://example.com")
            result = run_async(navigate(url))
            self.respond(result)

        elif self.path == "/screenshot":
            result = run_async(screenshot())
            if isinstance(result, bytes):
                self.send_response(200)
                self.send_header("Content-Type", "image/png")
                self.end_headers()
                self.wfile.write(result)
            else:
                self.respond(result)

        elif self.path == "/task":
            task = body.get("task", "")
            if not task:
                self.respond({"error": "task field required"}, 400)
                return
            result = run_async(run_task(task))
            self.respond(result)

        elif self.path == "/cookies":
            result = run_async(get_cookies())
            self.respond(result)

        else:
            self.respond({"error": "not found"}, 404)

    def respond(self, data, code=200):
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(data).encode())

    def log_message(self, format, *args):
        pass  # Suppress request logging


# Async helpers
loop = asyncio.new_event_loop()


def run_async(coro):
    return asyncio.run_coroutine_threadsafe(coro, loop).result(timeout=120)


async def init_browser():
    global browser, browser_ready, init_error
    try:
        from browser_use import Browser
        browser = Browser(
            headless=True,
            disable_security=True,
            args=["--no-sandbox", "--disable-gpu", "--disable-dev-shm-usage"],
        )
        await browser.start()
        browser_ready = True
        print("Browser ready")
    except Exception as e:
        init_error = str(e)
        print(f"Browser init failed: {e}")


async def navigate(url):
    if not browser_ready:
        return {"error": "browser not ready"}
    try:
        await browser.navigate_to(url)
        title = await browser.get_current_page_title()
        cookies = await browser.cookies()
        return {"title": title, "url": url, "cookies": len(cookies)}
    except Exception as e:
        return {"error": str(e)}


async def screenshot():
    if not browser_ready:
        return {"error": "browser not ready"}
    try:
        return await browser.take_screenshot()
    except Exception as e:
        return {"error": str(e)}


async def get_cookies():
    if not browser_ready:
        return {"error": "browser not ready"}
    try:
        cookies = await browser.cookies()
        return {"cookies": [{"name": c.name, "domain": c.domain, "value": c.value} for c in cookies]}
    except Exception as e:
        return {"error": str(e)}


async def run_task(task_description):
    """Run a browser-use agent task."""
    if not browser_ready:
        return {"error": "browser not ready"}
    try:
        # For now, just navigate — full Agent integration needs an LLM key
        # which we'll add later
        await browser.navigate_to("https://example.com")
        title = await browser.get_current_page_title()
        return {"result": f"Navigated to example.com: {title}", "task": task_description}
    except Exception as e:
        return {"error": str(e)}


def run_loop():
    asyncio.set_event_loop(loop)
    loop.run_until_complete(init_browser())
    loop.run_forever()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8000"))

    # Start async loop in background thread
    thread = Thread(target=run_loop, daemon=True)
    thread.start()

    # Start HTTP server
    server = HTTPServer(("0.0.0.0", port), Handler)
    print(f"Agent listening on :{port}")
    server.serve_forever()
