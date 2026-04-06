# orb-browser

Give your AI agent a browser.

A real Chrome browser in the cloud that your AI coding agent can control. It scrolls, clicks, types, screenshots — everything a human can do. When idle, it freezes to disk ($0). Wakes in 500ms, still logged in.

## Install the Claude Code Plugin

```bash
pip install orb-browser
```

In Claude Code:
```
/plugin marketplace add AWLSEN/orb-browser-marketplace
/plugin install orb-browser@orb-browser
```

Then just talk to your agent:

```
"Go to Hacker News and tell me the top 5 stories"
"Watch my Twitter for AI posts every 2 hours and email me a summary"
"Screenshot apple.com and describe the layout"
"Fill out the contact form on example.com"
```

Your agent handles the rest — deploys the browser, browses, reads, acts, sleeps.

## What Can It Do?

- **Browse any website** — navigate, scroll, click, type, fill forms
- **Read pages** — extract text, take screenshots, run JavaScript
- **Log into sites** — grabs cookies from your Chrome automatically
- **Monitor on schedule** — wake every N hours, browse, email you, sleep
- **Watch it live** — opens a real-time browser view so you see everything

## How It Works

1. Your AI agent (Claude Code, Codex) gets a cloud browser via the `orb-browser` CLI
2. The browser runs real Chrome on [Orb Cloud](https://orbcloud.dev)
3. Agent browses: `orb-browser go`, `orb-browser text`, `orb-browser click`
4. When done: `orb-browser sleep` — browser checkpoints to NVMe, $0/hr
5. Next run: `orb-browser wake` — 500ms, everything restored, still logged in

## Login Flow

For sites that need login (Twitter, Gmail, etc.), the agent grabs cookies from your local Chrome automatically:

```python
import browser_cookie3
cookies = browser_cookie3.chrome(domain_name='.x.com')
```

Injects them into the cloud browser. Checkpoints. Next wake = still logged in.

## CLI Reference

```bash
orb-browser deploy              # Create cloud browser
orb-browser go <url>            # Navigate
orb-browser text                # Read page text
orb-browser screenshot [path]   # Take screenshot
orb-browser click <x> <y>      # Click coordinates
orb-browser click <selector>    # Click CSS selector
orb-browser type <text>         # Type text
orb-browser fill <sel> <val>    # Fill input
orb-browser scroll [down|up]    # Scroll
orb-browser eval <js>           # Run JavaScript
orb-browser cookies             # Get/set cookies
orb-browser sleep               # Checkpoint ($0)
orb-browser wake                # Restore (500ms)
orb-browser live                # Open live view
orb-browser destroy             # Delete VM
```

## Python SDK

```python
from orb_browser import OrbBrowser

orb = OrbBrowser(api_key="orb_...")
orb.deploy()

orb.navigate("https://example.com")
print(orb.text())
orb.screenshot("page.jpg")

orb.sleep()   # $0
orb.wake()    # 500ms, still on example.com
orb.destroy()
```

## Cost

| State | Cost |
|-------|------|
| Running | ~$0.03/hr |
| Sleeping | $0/hr |
| 1,000 browsers, 90% sleeping | ~$50/month |

## License

MIT
