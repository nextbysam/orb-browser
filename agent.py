"""
Browser agent running on Orb Cloud.

Uses Playwright directly (not browser-use's Browser class which needs uvx).
Playwright + Chrome run together — CDP stays local.
"""

import asyncio
import os
import glob

os.environ["PLAYWRIGHT_BROWSERS_PATH"] = os.environ.get(
    "PLAYWRIGHT_BROWSERS_PATH", "/opt/browsers"
)

from fastapi import FastAPI
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel

app = FastAPI()

browser = None
page = None
init_error = None


class NavigateRequest(BaseModel):
    url: str = "https://example.com"


@app.on_event("startup")
async def startup():
    global browser, page, init_error
    try:
        from playwright.async_api import async_playwright
        pw = await async_playwright().start()
        browser = await pw.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-gpu", "--disable-dev-shm-usage"],
        )
        ctx = await browser.new_context()
        page = await ctx.new_page()
        print("Browser ready")
    except Exception as e:
        init_error = str(e)
        print(f"Browser init failed: {e}")


@app.get("/health")
async def health():
    return {"status": "ok", "browserReady": page is not None, "error": init_error}


@app.post("/navigate")
async def navigate(req: NavigateRequest):
    if not page:
        return JSONResponse({"error": "browser not ready"}, 503)
    try:
        await page.goto(req.url, wait_until="domcontentloaded", timeout=15000)
        title = await page.title()
        cookies = await page.context.cookies()
        return {"title": title, "url": req.url, "cookies": len(cookies)}
    except Exception as e:
        return JSONResponse({"error": str(e)}, 500)


@app.post("/screenshot")
async def screenshot():
    if not page:
        return JSONResponse({"error": "browser not ready"}, 503)
    try:
        img = await page.screenshot(type="jpeg", quality=80)
        return Response(content=img, media_type="image/jpeg")
    except Exception as e:
        return JSONResponse({"error": str(e)}, 500)


@app.get("/cookies")
async def cookies():
    if not page:
        return JSONResponse({"error": "browser not ready"}, 503)
    try:
        c = await page.context.cookies()
        return {"cookies": [{"name": x["name"], "domain": x["domain"]} for x in c]}
    except Exception as e:
        return JSONResponse({"error": str(e)}, 500)


@app.get("/text")
async def get_text():
    if not page:
        return JSONResponse({"error": "browser not ready"}, 503)
    try:
        text = await page.inner_text("body")
        return {"text": text[:5000]}
    except Exception as e:
        return JSONResponse({"error": str(e)}, 500)


@app.get("/url")
async def get_url():
    if not page:
        return JSONResponse({"error": "browser not ready"}, 503)
    return {"url": page.url, "title": await page.title()}


if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", "8000"))
    uvicorn.run(app, host="0.0.0.0", port=port)
