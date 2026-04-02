# orb-browser

A browser in the cloud that sleeps for $0 and wakes in 500ms.

Deploy Chrome on [Orb Cloud](https://orbcloud.dev). Browse, log in, interact. When you're done, put it to sleep — the entire browser is checkpointed to NVMe. Wake it later in ~500ms with everything intact: cookies, login sessions, page state. You're still logged in.

## Install

```bash
pip install orb-browser
```

## Get an API Key

```bash
curl -X POST https://api.orbcloud.dev/api/v1/auth/register \
  -H 'Content-Type: application/json' -d '{"email":"you@example.com"}'

curl -X POST https://api.orbcloud.dev/v1/keys \
  -H "Authorization: Bearer YOUR_KEY" \
  -H 'Content-Type: application/json' -d '{"name":"my-key"}'
```

## Quick Start

```python
from orb_browser import OrbBrowser

orb = OrbBrowser(api_key="orb_...")

# Deploy a browser (~1-2 min first time)
orb.deploy()

# Browse
orb.navigate("https://example.com")
orb.screenshot("page.jpg")
print(orb.text())

# Sleep — $0/hr while frozen
orb.sleep()

# Wake — ~500ms, everything restored
orb.wake()
print(orb.url())  # still on example.com

# Done
orb.destroy()
```

## Vision Agent

Give the browser a task in natural language. It screenshots the page, sends it to a vision LLM, and executes actions until done.

```python
# No LLM key needed — uses the built-in key
result = orb.task("Go to news.ycombinator.com and tell me the top story")
print(result)

# With a specific start URL
result = orb.task(
    "Describe any images on this page",
    start_url="https://home.cern/news",
    model="google/gemini-2.0-flash-001",
)

# Ask a question about a page (text-only, faster)
answer = orb.ask("https://example.com", "What does this page say?")
```

**CLI:**

```bash
orb-browser task "Go to example.com and read the page"
orb-browser ask https://example.com "What is this page about?"
```

## Manual Login

Need to log into Twitter, Gmail, or any site with OAuth/2FA? Use the live browser view:

```python
from orb_browser import OrbBrowser

orb = OrbBrowser(api_key="orb_...")
orb.deploy()

# Navigate to login page
orb.navigate("https://x.com/login")

# Open the live view in your browser
print(orb.live_url)
# → https://abc12345.orbcloud.dev/live

# Click, type, do 2FA in the live view...
# When done, checkpoint the session:

orb.sleep()
print(f"Saved! ID: {orb.computer_id}")

# Later — wake and you're still logged in:
orb.connect("COMPUTER_ID", AGENT_PORT)
orb.wake()
```

## API

```python
orb = OrbBrowser(api_key="orb_...")
```

### Lifecycle

| Method | Description |
|--------|-------------|
| `orb.deploy()` | Deploy browser VM (~1-2 min) |
| `orb.sleep()` | Checkpoint to NVMe ($0) |
| `orb.wake()` | Restore (~500ms) |
| `orb.destroy()` | Delete the VM |
| `orb.connect(id, port)` | Connect to existing VM |

### Browse

| Method | Description |
|--------|-------------|
| `orb.navigate(url)` | Go to URL |
| `orb.back()` | Go back |
| `orb.forward()` | Go forward |
| `orb.click(selector)` | Click element |
| `orb.click(x=100, y=200)` | Click coordinates |
| `orb.fill(selector, value)` | Fill input field |
| `orb.type(text)` | Type text |
| `orb.press(key)` | Press key (Enter, Tab, etc) |
| `orb.scroll(direction, amount)` | Scroll up/down |
| `orb.evaluate(js)` | Run JavaScript |

### Agent

| Method | Description |
|--------|-------------|
| `orb.task(prompt)` | Vision agent: screenshot + LLM + actions |
| `orb.ask(url, question)` | Navigate + read text + LLM answer |

### Read

| Method | Description |
|--------|-------------|
| `orb.screenshot(path)` | JPEG screenshot |
| `orb.url()` | Current URL + title |
| `orb.text()` | Page text content |
| `orb.html()` | Page HTML |
| `orb.cookies()` | All cookies |

### Properties

| Property | Description |
|----------|-------------|
| `orb.vm_url` | VM HTTPS URL |
| `orb.live_url` | Live browser view URL |
| `orb.computer_id` | VM ID (save for reconnecting) |
| `orb.state` | init, deploying, running, sleeping, destroyed |

## Live View

Open `orb.live_url` in your browser to see and control the remote Chrome:

- **Click** anywhere on the screen to click
- **Type** on your keyboard to type in the browser
- **URL bar** to navigate
- **Back/Forward** buttons

This is how you log into sites that need OAuth, 2FA, or CAPTCHA.

## How It Works

1. `deploy()` creates a VM on Orb Cloud with Python + Playwright + Chrome
2. Chrome runs locally in the VM — no remote WebSocket, no CDP over internet
3. You send HTTP requests, the agent executes them against local Chrome
4. `sleep()` uses CRIU to checkpoint the entire process tree to NVMe
5. `wake()` restores everything in ~500ms — Chrome doesn't know it was frozen

## Cost

| State | Cost |
|-------|------|
| Running | ~$0.03/hr |
| Sleeping | $0/hr |
| 1,000 browsers, 90% sleeping | ~$50/month |

## License

MIT
