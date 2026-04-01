"""
orb-browser agent — runs on Orb Cloud.

Playwright + Chrome in the same VM. Control via HTTP.
Includes /live endpoint for manual browser interaction (login, etc).
"""

import asyncio
import base64
import os
import uuid
import traceback

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
tasks: dict[str, dict] = {}  # task_id -> {status, result, error, steps}


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


@app.get("/debug/env")
async def debug_env():
    """Show LLM-related env vars for debugging proxy setup."""
    keys = ["ANTHROPIC_BASE_URL", "OPENAI_BASE_URL", "LLM_API_KEY", "LLM_PROVIDER",
            "LLM_BASE_URL", "API_BASE_URL", "ORB_PROXY_PORT", "PORT"]
    result = {}
    for k in keys:
        v = os.environ.get(k, "")
        if "KEY" in k and v:
            result[k] = v[:8] + "..."
        else:
            result[k] = v or "(unset)"
    return result


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
    start_url: Optional[str] = None  # navigate here before starting
    provider: Optional[str] = None   # "openai", "anthropic", or any openai-compatible
    llm_key: Optional[str] = None    # overrides env LLM_API_KEY
    model: Optional[str] = None      # e.g. "gpt-4o", "claude-sonnet-4-20250514"
    base_url: Optional[str] = None   # for openai-compatible APIs (GLM, Groq, Together, etc)
    max_steps: int = 50


async def _call_llm(base_url: str, api_key: str, model: str, messages: list[dict]) -> str:
    """Call LLM via OpenAI-compatible API. Retries on connection errors (Orb checkpoint/restore)."""
    import httpx
    url = f"{base_url}/chat/completions"
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    body = {"model": model, "messages": messages, "max_tokens": 256}

    last_err = None
    for attempt in range(3):
        try:
            async with httpx.AsyncClient(timeout=120) as client:
                resp = await client.post(url, headers=headers, json=body)
            if resp.status_code >= 400:
                raise RuntimeError(f"LLM API {resp.status_code}: {resp.text[:500]}")
            data = resp.json()
            if "error" in data:
                raise RuntimeError(f"LLM API error: {data['error']}")
            return data["choices"][0]["message"]["content"]
        except (httpx.ConnectError, httpx.ReadError, httpx.WriteError, httpx.PoolTimeout, ConnectionError, OSError) as e:
            last_err = e
            _log(f"[llm] Attempt {attempt+1} connection error (checkpoint/restore?): {e}")
            await asyncio.sleep(2)
    raise RuntimeError(f"LLM call failed after 3 attempts: {last_err}")


def _log(msg: str):
    import sys
    print(msg, flush=True)
    sys.stdout.flush()


async def _run_task_loop(task_id: str, req: TaskRequest):
    """Background coroutine that runs the vision agent loop."""
    task_state = tasks[task_id]
    api_key = req.llm_key or os.environ.get("LLM_API_KEY", "")
    base_url_val = req.base_url or os.environ.get("LLM_BASE_URL", "") or "https://openrouter.ai/api/v1"
    model = req.model or "google/gemini-2.0-flash-001"
    _log(f"[task {task_id}] LLM base_url={base_url_val} model={model}")

    task_page = None
    try:
        _log(f"[task {task_id}] Creating page...")
        task_page = await context.new_page()
        _log(f"[task {task_id}] Page created")

        if req.start_url:
            _log(f"[task {task_id}] Navigating to {req.start_url}")
            await task_page.goto(req.start_url, wait_until="domcontentloaded", timeout=30000)
            _log(f"[task {task_id}] At {task_page.url}")

        system_prompt = f"You are a browser automation agent. You see a screenshot of the browser at each step. Respond with EXACTLY one action per step:\n- GOTO <url> — navigate to a URL\n- CLICK <x> <y> — click at pixel coordinates\n- TYPE <text> — type text\n- SCROLL down/up — scroll the page\n- DONE <result> — task complete, report the result\n\nRespond with only the action, nothing else.\n\nTask: {req.task}"

        messages = [{"role": "system", "content": system_prompt}]

        for step in range(req.max_steps):
            task_state["steps"] = step + 1
            _log(f"[task {task_id}] Step {step+1}: taking screenshot...")
            screenshot_bytes = await task_page.screenshot(type="jpeg", quality=30)
            _log(f"[task {task_id}] Step {step+1}: screenshot {len(screenshot_bytes)} bytes")
            b64 = base64.b64encode(screenshot_bytes).decode()
            _log(f"[task {task_id}] Step {step+1}: b64 encoded ({len(b64)} chars)")

            # Keep only last 3 image messages to avoid payload bloat
            img_msgs = [i for i, m in enumerate(messages) if m["role"] == "user" and isinstance(m.get("content"), list)]
            while len(img_msgs) >= 3:
                messages.pop(img_msgs[0])
                img_msgs = [i for i, m in enumerate(messages) if m["role"] == "user" and isinstance(m.get("content"), list)]

            messages.append({
                "role": "user",
                "content": [
                    {"type": "text", "text": f"Step {step+1}. Current URL: {task_page.url}. What action should I take?"},
                    {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}},
                ],
            })

            _log(f"[task {task_id}] Step {step+1}: calling LLM...")
            try:
                action = await asyncio.wait_for(
                    _call_llm(base_url_val, api_key, model, messages),
                    timeout=300,
                )
            except asyncio.TimeoutError:
                _log(f"[task {task_id}] Step {step+1}: LLM timed out")
                task_state["status"] = "error"
                task_state["error"] = f"LLM call timed out at step {step+1}"
                return

            action = action.strip()
            _log(f"[task {task_id}] Step {step+1}: LLM responded: {action[:80]}")
            messages.append({"role": "assistant", "content": action})
            task_state["last_action"] = action

            if action.startswith("GOTO "):
                await task_page.goto(action[5:].strip(), wait_until="domcontentloaded", timeout=30000)
            elif action.startswith("CLICK "):
                parts = action[6:].strip().split()
                if len(parts) >= 2:
                    await task_page.mouse.click(int(parts[0]), int(parts[1]))
            elif action.startswith("TYPE "):
                await task_page.keyboard.type(action[5:].strip())
            elif action.startswith("SCROLL "):
                delta = 500 if "down" in action else -500
                await task_page.mouse.wheel(0, delta)
            elif action.startswith("DONE"):
                task_state["status"] = "done"
                task_state["result"] = action[4:].strip()
                _log(f"[task {task_id}] Done: {task_state['result'][:80]}")
                return

            await asyncio.sleep(1)

        task_state["status"] = "done"
        task_state["result"] = "Max steps reached"

    except Exception as e:
        _log(f"[task {task_id}] Error: {e}")
        task_state["status"] = "error"
        task_state["error"] = str(e)
        task_state["traceback"] = traceback.format_exc()
    finally:
        if task_page:
            try:
                await task_page.close()
            except Exception:
                pass


class TestRequest(BaseModel):
    llm_key: str
    base_url: str = "https://openrouter.ai/api/v1"
    model: str = "anthropic/claude-3.5-haiku"


@app.post("/task/test")
async def test_task(req: TestRequest):
    """Diagnostic: test each step of the task pipeline individually."""
    results = {}
    import time

    # Test 1: Create page
    t0 = time.time()
    try:
        tp = await context.new_page()
        results["new_page"] = f"OK ({time.time()-t0:.2f}s)"
    except Exception as e:
        results["new_page"] = f"FAIL: {e}"
        return results

    # Test 2: Screenshot
    t0 = time.time()
    try:
        ss = await tp.screenshot(type="jpeg", quality=30)
        results["screenshot"] = f"OK {len(ss)} bytes ({time.time()-t0:.2f}s)"
    except Exception as e:
        results["screenshot"] = f"FAIL: {e}"

    # Test 3: Base64
    t0 = time.time()
    b64 = base64.b64encode(ss).decode()
    results["base64"] = f"OK {len(b64)} chars ({time.time()-t0:.2f}s)"

    # Test 4: LLM text call
    base = req.base_url or os.environ.get("LLM_BASE_URL", "https://openrouter.ai/api/v1")
    results["llm_base_url"] = base
    t0 = time.time()
    try:
        answer = await asyncio.wait_for(
            _call_llm(base, req.llm_key, req.model,
                      [{"role": "user", "content": "Say hello in one word"}]),
            timeout=60,
        )
        results["llm_text"] = f"OK: {answer[:50]} ({time.time()-t0:.2f}s)"
    except Exception as e:
        results["llm_text"] = f"FAIL: {e}"

    # Test 5: LLM vision call
    t0 = time.time()
    try:
        answer = await asyncio.wait_for(
            _call_llm(base, req.llm_key, req.model,
                      [{"role": "user", "content": [
                          {"type": "text", "text": "What color is this page? One word."},
                          {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}},
                      ]}]),
            timeout=60,
        )
        results["llm_vision"] = f"OK: {answer[:50]} ({time.time()-t0:.2f}s)"
    except Exception as e:
        results["llm_vision"] = f"FAIL: {e}"

    await tp.close()
    results["cleanup"] = "OK"
    return results


@app.post("/task")
async def run_task(req: TaskRequest):
    """Start a task in the background. Returns task_id to poll with GET /task/{id}."""
    if not browser:
        return JSONResponse({"error": "browser not ready"}, 503)

    api_key = req.llm_key or os.environ.get("LLM_API_KEY", "")
    if not api_key:
        return JSONResponse({"error": "No LLM key. Pass llm_key or set LLM_API_KEY env var."}, 400)

    task_id = uuid.uuid4().hex[:8]
    tasks[task_id] = {
        "status": "running",
        "task": req.task,
        "model": req.model or "gpt-4o",
        "provider": req.provider or os.environ.get("LLM_PROVIDER", "openai"),
        "result": None,
        "error": None,
        "steps": 0,
        "last_action": None,
    }

    asyncio.create_task(_run_task_loop(task_id, req))
    print(f"[task {task_id}] Started: {req.task[:80]}")

    return {"task_id": task_id, "status": "running"}


@app.get("/task/{task_id}")
async def get_task(task_id: str):
    """Poll task status."""
    if task_id not in tasks:
        return JSONResponse({"error": "task not found"}, 404)
    return tasks[task_id]


# ── Ask (simple: navigate + read text + LLM summarize) ────

class AskRequest(BaseModel):
    url: str
    question: str
    llm_key: Optional[str] = None
    model: Optional[str] = None
    base_url: Optional[str] = None

@app.post("/ask")
async def ask(req: AskRequest):
    """Navigate to a URL, read the text, ask the LLM a question about it."""
    if not page:
        return JSONResponse({"error": "browser not ready"}, 503)

    api_key = req.llm_key or os.environ.get("LLM_API_KEY", "")
    base_url = req.base_url or os.environ.get("LLM_BASE_URL", "") or "https://openrouter.ai/api/v1"
    model = req.model or "google/gemini-2.0-flash-001"

    try:
        # Navigate and get text
        await page.goto(req.url, wait_until="domcontentloaded", timeout=30000)
        text = await page.inner_text("body")
        text = text[:8000]

        # Ask LLM via Orb proxy
        answer = await _call_llm(base_url, api_key, model,
                                 [{"role": "user", "content": f"Here is the content of {req.url}:\n\n{text}\n\nQuestion: {req.question}"}])

        return {"url": req.url, "question": req.question, "answer": answer}

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
