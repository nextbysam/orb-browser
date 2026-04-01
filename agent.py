"""
orb-browser agent — runs on Orb Cloud.

Playwright + Chrome in the same VM. Control via HTTP.
Includes /live endpoint for manual browser interaction (login, etc).
"""

import asyncio
import base64
import os

os.environ["PLAYWRIGHT_BROWSERS_PATH"] = os.environ.get(
    "PLAYWRIGHT_BROWSERS_PATH", "/opt/browsers"
)

from fastapi import FastAPI
from fastapi.responses import HTMLResponse, JSONResponse, Response
from pydantic import BaseModel
from typing import Optional

app = FastAPI(title="orb-browser", version="0.3.0")

browser = None
context = None
page = None
init_error = None


# ── Request Models ────────────────────────────────────────

class NavigateRequest(BaseModel):
    url: str = "https://example.com"

class ClickRequest(BaseModel):
    selector: Optional[str] = None
    x: Optional[int] = None
    y: Optional[int] = None

class FillRequest(BaseModel):
    selector: str
    value: str

class TypeRequest(BaseModel):
    text: str

class PressRequest(BaseModel):
    key: str  # "Enter", "Tab", "Escape", etc.

class ScrollRequest(BaseModel):
    direction: str = "down"  # "up" or "down"
    amount: int = 500

class EvalRequest(BaseModel):
    expression: str

class CookieRequest(BaseModel):
    cookies: list[dict]


# ── Startup ───────────────────────────────────────────────

@app.on_event("startup")
async def startup():
    global browser, context, page, init_error
    try:
        from playwright.async_api import async_playwright
        pw = await async_playwright().start()
        browser = await pw.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-gpu", "--disable-dev-shm-usage"],
        )
        context = await browser.new_context(
            viewport={"width": 1280, "height": 800},
            user_agent="Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/145.0.0.0 Safari/537.36",
        )
        page = await context.new_page()
        print("Browser ready")
    except Exception as e:
        init_error = str(e)
        print(f"Browser init failed: {e}")


# ── Health ────────────────────────────────────────────────

@app.get("/health")
async def health():
    return {"status": "ok", "browserReady": page is not None, "error": init_error}


# ── Navigation ────────────────────────────────────────────

@app.post("/navigate")
async def navigate(req: NavigateRequest):
    if not page: return JSONResponse({"error": "browser not ready"}, 503)
    try:
        await page.goto(req.url, wait_until="domcontentloaded", timeout=30000)
        return {"title": await page.title(), "url": page.url, "cookies": len(await context.cookies())}
    except Exception as e:
        return JSONResponse({"error": str(e)}, 500)


@app.post("/back")
async def back():
    if not page: return JSONResponse({"error": "browser not ready"}, 503)
    await page.go_back()
    return {"url": page.url, "title": await page.title()}


@app.post("/forward")
async def forward():
    if not page: return JSONResponse({"error": "browser not ready"}, 503)
    await page.go_forward()
    return {"url": page.url, "title": await page.title()}


# ── Interaction ───────────────────────────────────────────

@app.post("/click")
async def click(req: ClickRequest):
    if not page: return JSONResponse({"error": "browser not ready"}, 503)
    try:
        if req.selector:
            await page.click(req.selector, timeout=5000)
        elif req.x is not None and req.y is not None:
            await page.mouse.click(req.x, req.y)
        else:
            return JSONResponse({"error": "provide selector or x,y"}, 400)
        return {"ok": True, "url": page.url}
    except Exception as e:
        return JSONResponse({"error": str(e)}, 500)


@app.post("/fill")
async def fill(req: FillRequest):
    if not page: return JSONResponse({"error": "browser not ready"}, 503)
    try:
        await page.fill(req.selector, req.value, timeout=5000)
        return {"ok": True}
    except Exception as e:
        return JSONResponse({"error": str(e)}, 500)


@app.post("/type")
async def type_text(req: TypeRequest):
    if not page: return JSONResponse({"error": "browser not ready"}, 503)
    try:
        await page.keyboard.type(req.text)
        return {"ok": True}
    except Exception as e:
        return JSONResponse({"error": str(e)}, 500)


@app.post("/press")
async def press(req: PressRequest):
    if not page: return JSONResponse({"error": "browser not ready"}, 503)
    try:
        await page.keyboard.press(req.key)
        return {"ok": True}
    except Exception as e:
        return JSONResponse({"error": str(e)}, 500)


@app.post("/scroll")
async def scroll(req: ScrollRequest):
    if not page: return JSONResponse({"error": "browser not ready"}, 503)
    delta = req.amount if req.direction == "down" else -req.amount
    await page.mouse.wheel(0, delta)
    return {"ok": True}


@app.post("/eval")
async def evaluate(req: EvalRequest):
    if not page: return JSONResponse({"error": "browser not ready"}, 503)
    try:
        result = await page.evaluate(req.expression)
        return {"result": result}
    except Exception as e:
        return JSONResponse({"error": str(e)}, 500)


# ── Content ───────────────────────────────────────────────

@app.get("/url")
async def get_url():
    if not page: return JSONResponse({"error": "browser not ready"}, 503)
    return {"url": page.url, "title": await page.title()}

@app.get("/text")
async def get_text():
    if not page: return JSONResponse({"error": "browser not ready"}, 503)
    try:
        text = await page.inner_text("body")
        return {"text": text[:10000]}
    except Exception as e:
        return JSONResponse({"error": str(e)}, 500)

@app.get("/html")
async def get_html():
    if not page: return JSONResponse({"error": "browser not ready"}, 503)
    return {"html": await page.content()}

@app.post("/screenshot")
async def screenshot():
    if not page: return JSONResponse({"error": "browser not ready"}, 503)
    try:
        img = await page.screenshot(type="jpeg", quality=80)
        return Response(content=img, media_type="image/jpeg")
    except Exception as e:
        return JSONResponse({"error": str(e)}, 500)


# ── Cookies ───────────────────────────────────────────────

@app.get("/cookies")
async def get_cookies():
    if not page: return JSONResponse({"error": "browser not ready"}, 503)
    c = await context.cookies()
    return {"cookies": c}

@app.post("/cookies")
async def set_cookies(req: CookieRequest):
    if not page: return JSONResponse({"error": "browser not ready"}, 503)
    await context.add_cookies(req.cookies)
    return {"ok": True, "count": len(req.cookies)}

@app.delete("/cookies")
async def clear_cookies():
    if not page: return JSONResponse({"error": "browser not ready"}, 503)
    await context.clear_cookies()
    return {"ok": True}


# ── Task (natural language → browser-use Agent) ───────────

class TaskRequest(BaseModel):
    task: str
    provider: Optional[str] = None   # "openai", "anthropic", or any openai-compatible
    llm_key: Optional[str] = None    # overrides env LLM_API_KEY
    model: Optional[str] = None      # e.g. "gpt-4o", "claude-sonnet-4-20250514"
    base_url: Optional[str] = None   # for openai-compatible APIs (GLM, Groq, Together, etc)
    max_steps: int = 50

@app.post("/task")
async def run_task(req: TaskRequest):
    """Run a natural language task using browser-use Agent."""
    if not browser:
        return JSONResponse({"error": "browser not ready"}, 503)

    provider = req.provider or os.environ.get("LLM_PROVIDER", "openai")
    api_key = req.llm_key or os.environ.get("LLM_API_KEY", "")
    if not api_key:
        return JSONResponse({"error": "No LLM key. Pass llm_key or set LLM_API_KEY env var."}, 400)

    try:
        # Create LLM — use browser-use's native ChatVercel which handles everything
        base_url = req.base_url or os.environ.get("LLM_BASE_URL", "")
        model = req.model or "gpt-4o"

        from browser_use.llm.vercel import ChatVercel
        kwargs = {"model": model, "api_key": api_key}
        if base_url:
            kwargs["base_url"] = base_url
        llm = ChatVercel(**kwargs)

        # Simple agent loop — screenshot → LLM → act → repeat
        # No browser-use dependency, uses our existing Playwright browser
        from browser_use.llm.messages import UserMessage, AssistantMessage, ContentImage, ContentText
        import base64

        messages = [UserMessage(content=f"You are a browser automation agent. You can see a screenshot of the browser. Respond with EXACTLY one action in this format:\n- GOTO url\n- CLICK x y\n- TYPE text\n- SCROLL down/up\n- DONE result\n\nTask: {req.task}")]

        final = None
        for step in range(req.max_steps):
            # Take screenshot
            screenshot_bytes = await page.screenshot(type="jpeg", quality=60)
            b64 = base64.b64encode(screenshot_bytes).decode()

            # Add screenshot to messages
            messages.append(UserMessage(content=[
                ContentText(text=f"Step {step+1}. Current URL: {page.url}. What action should I take?"),
                ContentImage(image=f"data:image/jpeg;base64,{b64}"),
            ]))

            # Ask LLM
            response = await llm.ainvoke(messages)
            action = response.completion.strip()
            messages.append(AssistantMessage(content=action))

            # Parse and execute action
            if action.startswith("GOTO "):
                url = action[5:].strip()
                await page.goto(url, wait_until="domcontentloaded", timeout=30000)
            elif action.startswith("CLICK "):
                parts = action[6:].strip().split()
                if len(parts) >= 2:
                    await page.mouse.click(int(parts[0]), int(parts[1]))
            elif action.startswith("TYPE "):
                text = action[5:].strip()
                await page.keyboard.type(text)
            elif action.startswith("SCROLL "):
                direction = action[7:].strip()
                delta = 500 if direction == "down" else -500
                await page.mouse.wheel(0, delta)
            elif action.startswith("DONE"):
                final = action[4:].strip()
                break

            import asyncio as aio
            await aio.sleep(1)

        return {"task": req.task, "result": final, "model": model, "provider": provider}

    except Exception as e:
        return JSONResponse({"error": str(e)}, 500)


# ── Live Browser View ─────────────────────────────────────
# Opens in your browser. See the remote Chrome screen.
# Click anywhere to click. Type to type. Log in manually.

LIVE_HTML = """<!DOCTYPE html>
<html>
<head>
<title>orb-browser live</title>
<style>
  * { margin: 0; padding: 0; box-sizing: border-box; }
  body { background: #111; display: flex; flex-direction: column; align-items: center; font-family: system-ui; color: #eee; }
  h1 { padding: 10px; font-size: 14px; opacity: 0.5; }
  #screen { cursor: crosshair; border: 1px solid #333; }
  #bar { display: flex; gap: 8px; padding: 10px; width: 1280px; }
  #bar input { flex: 1; padding: 8px 12px; border-radius: 6px; border: 1px solid #444; background: #222; color: #eee; font-size: 14px; }
  #bar button { padding: 8px 16px; border-radius: 6px; border: none; background: #2563eb; color: white; cursor: pointer; font-size: 14px; }
  #bar button:hover { background: #1d4ed8; }
  #status { font-size: 12px; opacity: 0.5; padding: 4px; }
</style>
</head>
<body>
<h1>orb-browser live view — click to interact, type to type</h1>
<div id="bar">
  <button onclick="goBack()">←</button>
  <button onclick="goForward()">→</button>
  <input id="urlbar" placeholder="Enter URL..." onkeydown="if(event.key==='Enter')go()">
  <button onclick="go()">Go</button>
</div>
<canvas id="screen" width="1280" height="800"></canvas>
<div id="status">Loading...</div>

<script>
const canvas = document.getElementById('screen');
const ctx = canvas.getContext('2d');
const status = document.getElementById('status');
const urlbar = document.getElementById('urlbar');
const BASE = window.location.origin;

// Screenshot polling
async function refresh() {
  try {
    const res = await fetch(BASE + '/screenshot', {method:'POST'});
    const blob = await res.blob();
    const img = new Image();
    img.onload = () => { ctx.drawImage(img, 0, 0, 1280, 800); };
    img.src = URL.createObjectURL(blob);

    const urlRes = await fetch(BASE + '/url');
    const urlData = await urlRes.json();
    urlbar.value = urlData.url || '';
    status.textContent = urlData.title || '';
  } catch(e) {
    status.textContent = 'Error: ' + e.message;
  }
}

setInterval(refresh, 600);
refresh();

// Click
canvas.addEventListener('click', async (e) => {
  const rect = canvas.getBoundingClientRect();
  const x = Math.round((e.clientX - rect.left) * (1280 / rect.width));
  const y = Math.round((e.clientY - rect.top) * (800 / rect.height));
  status.textContent = `Clicking ${x}, ${y}...`;
  await fetch(BASE + '/click', {
    method: 'POST',
    headers: {'Content-Type':'application/json'},
    body: JSON.stringify({x, y})
  });
  setTimeout(refresh, 500);
});

// Keyboard
document.addEventListener('keydown', async (e) => {
  if (document.activeElement === urlbar) return;
  e.preventDefault();

  const special = {
    'Enter':'Enter', 'Tab':'Tab', 'Escape':'Escape',
    'Backspace':'Backspace', 'ArrowUp':'ArrowUp',
    'ArrowDown':'ArrowDown', 'ArrowLeft':'ArrowLeft',
    'ArrowRight':'ArrowRight', ' ':'Space',
  };

  if (special[e.key]) {
    await fetch(BASE + '/press', {
      method:'POST', headers:{'Content-Type':'application/json'},
      body: JSON.stringify({key: special[e.key]})
    });
  } else if (e.key.length === 1) {
    await fetch(BASE + '/type', {
      method:'POST', headers:{'Content-Type':'application/json'},
      body: JSON.stringify({text: e.key})
    });
  }
  setTimeout(refresh, 300);
});

// Navigation
async function go() {
  const url = urlbar.value;
  if (!url) return;
  status.textContent = 'Navigating...';
  await fetch(BASE + '/navigate', {
    method:'POST', headers:{'Content-Type':'application/json'},
    body: JSON.stringify({url: url.startsWith('http') ? url : 'https://' + url})
  });
  setTimeout(refresh, 1000);
}

async function goBack() {
  await fetch(BASE + '/back', {method:'POST'});
  setTimeout(refresh, 500);
}

async function goForward() {
  await fetch(BASE + '/forward', {method:'POST'});
  setTimeout(refresh, 500);
}
</script>
</body>
</html>"""


@app.get("/live")
async def live_view():
    """Open this in your browser to see and interact with the remote Chrome."""
    return HTMLResponse(LIVE_HTML)


# ── Main ──────────────────────────────────────────────────

if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", "8000"))
    uvicorn.run(app, host="0.0.0.0", port=port)
