"""
Browser agent running on Orb Cloud.

browser-use + Chrome run together — CDP stays local, no WebSocket over internet.
Send tasks via HTTP, get results back as JSON.
"""

import asyncio
import os

os.environ["PLAYWRIGHT_BROWSERS_PATH"] = os.environ.get(
    "PLAYWRIGHT_BROWSERS_PATH", "/home/awlsen/.cache/ms-playwright"
)

from fastapi import FastAPI
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel
from typing import Optional

app = FastAPI()

# Global browser
browser = None
init_error = None


class NavigateRequest(BaseModel):
    url: str = "https://example.com"


class TaskRequest(BaseModel):
    task: str


@app.on_event("startup")
async def startup():
    global browser, init_error
    try:
        from browser_use import Browser
        # Find the Playwright Chromium binary
        import glob
        browsers_path = os.environ.get("PLAYWRIGHT_BROWSERS_PATH", "/home/awlsen/.cache/ms-playwright")
        chrome_paths = glob.glob(f"{browsers_path}/chromium-*/chrome-linux*/chrome")
        chrome_path = chrome_paths[0] if chrome_paths else None
        print(f"Chrome path: {chrome_path}")

        browser = Browser(
            headless=True,
            disable_security=True,
            enable_default_extensions=False,
            is_local=True,
            executable_path=chrome_path,
            args=["--no-sandbox", "--disable-gpu", "--disable-dev-shm-usage"],
        )
        await browser.start()
        print("Browser ready")
    except Exception as e:
        init_error = str(e)
        print(f"Browser init failed: {e}")


@app.get("/health")
async def health():
    return {"status": "ok", "browserReady": browser is not None and init_error is None, "error": init_error}


@app.post("/navigate")
async def navigate(req: NavigateRequest):
    if not browser:
        return JSONResponse({"error": "browser not ready"}, 503)
    try:
        await browser.navigate_to(req.url)
        title = await browser.get_current_page_title()
        cookies = await browser.cookies()
        return {"title": title, "url": req.url, "cookies": len(cookies)}
    except Exception as e:
        return JSONResponse({"error": str(e)}, 500)


@app.post("/screenshot")
async def screenshot():
    if not browser:
        return JSONResponse({"error": "browser not ready"}, 503)
    try:
        img = await browser.take_screenshot()
        return Response(content=img, media_type="image/png")
    except Exception as e:
        return JSONResponse({"error": str(e)}, 500)


@app.get("/cookies")
async def cookies():
    if not browser:
        return JSONResponse({"error": "browser not ready"}, 503)
    try:
        c = await browser.cookies()
        return {"cookies": [{"name": x.name, "domain": x.domain} for x in c]}
    except Exception as e:
        return JSONResponse({"error": str(e)}, 500)


@app.get("/text")
async def get_text():
    if not browser:
        return JSONResponse({"error": "browser not ready"}, 503)
    try:
        text = await browser.get_state_as_text()
        return {"text": text}
    except Exception as e:
        return JSONResponse({"error": str(e)}, 500)


@app.get("/url")
async def get_url():
    if not browser:
        return JSONResponse({"error": "browser not ready"}, 503)
    try:
        return {"url": await browser.get_current_page_url(), "title": await browser.get_current_page_title()}
    except Exception as e:
        return JSONResponse({"error": str(e)}, 500)


if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", "8000"))
    uvicorn.run(app, host="0.0.0.0", port=port)
