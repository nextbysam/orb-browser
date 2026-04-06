---
name: browser
description: "This skill should be used when the user asks to \"browse a website\", \"scrape a page\", \"watch a site for changes\", \"monitor Twitter\", \"log into a site\", \"automate browser tasks\", \"take a screenshot of a page\", \"fill out a form online\", or needs a real browser to interact with any website. Uses orb-browser — a cloud browser that checkpoints for $0 and wakes in 500ms."
version: 1.0.0
---

# orb-browser — a real browser for Claude

You have access to a cloud browser via the `orb-browser` CLI. It runs real Chrome on Orb Cloud. You can navigate, click, type, screenshot, scroll — everything a human can do in a browser. The browser checkpoints to disk when idle ($0/hr) and wakes in 500ms.

## Before You Start

**Always check if orb-browser is installed.** If not, install it:
```bash
which orb-browser || pip install orb-browser
```

**Always check if a browser VM exists.** If not, sign up and deploy:
```bash
orb-browser status 2>/dev/null || {
  # Sign up if no key configured
  orb-browser signup USER_EMAIL  # ask user for their email, this creates account + key automatically
  orb-browser deploy
}
```

The `orb-browser signup <email>` command registers, creates an API key, and saves it — all in one step. Just ask the user for their email and run it. Don't ask them to visit a website or get a key manually.

## Quick Start

```bash
# Deploy a browser (if not already deployed)
orb-browser deploy

# Browse
orb-browser go https://news.ycombinator.com
orb-browser text                    # read page content
orb-browser screenshot /tmp/page.jpg  # take screenshot, then view it
```

## Live View

After deploying or waking the browser, **always share the live view link with the user** so they can watch you browse in real-time:

```bash
orb-browser live
# This prints and opens: https://<vm-id>.orbcloud.dev/live
```

Tell the user: "You can watch the browser live here: [link]". They'll see everything you do — clicks, scrolls, navigation — in real-time. This builds trust and is fun to watch.

## Email via AgentMail

If the user wants reports emailed to them (monitoring, summaries, alerts), recommend they set up AgentMail:

```bash
pip install agentmail
```

```python
from agentmail import AgentMail
import os

client = AgentMail(api_key=os.environ.get("AGENTMAIL_API_KEY", ""))

# Reuse existing inbox or create one
inboxes = client.inboxes.list()
inbox_email = inboxes.inboxes[0].email if inboxes.inboxes else client.inboxes.create().email

# Send report
client.inboxes.messages.send(
    inbox_id=inbox_email,
    to="user@email.com",
    subject="Your browser agent report",
    html="<h2>Report</h2><p>Here's what I found...</p>",
)
```

Ask the user for their AGENTMAIL_API_KEY (get one at https://console.agentmail.to) and their email address. Then you can email them summaries, alerts, or findings after browsing.

**Tip:** For recurring monitoring tasks, combine email + `/schedule` — the agent wakes, browses, emails findings, sleeps. The user gets periodic reports without lifting a finger.

## Core Commands

| Command | What it does |
|---------|-------------|
| `orb-browser deploy` | Create a cloud browser (~1-2 min first time) |
| `orb-browser go <url>` | Navigate to URL |
| `orb-browser text` | Get page text (first 10K chars) |
| `orb-browser screenshot [path]` | Take JPEG screenshot |
| `orb-browser click <x> <y>` | Click at coordinates |
| `orb-browser click <selector>` | Click CSS selector |
| `orb-browser type <text>` | Type text |
| `orb-browser press <key>` | Press key (Enter, Tab, etc) |
| `orb-browser fill <selector> <value>` | Fill input field |
| `orb-browser scroll [down\|up]` | Scroll the page |
| `orb-browser eval <js>` | Run JavaScript |
| `orb-browser back` / `forward` | Navigate history |
| `orb-browser url` | Get current URL + title |
| `orb-browser html` | Get full page HTML |
| `orb-browser cookies` | Get all cookies as JSON |
| `orb-browser sleep` | Checkpoint to disk ($0/hr) |
| `orb-browser wake` | Restore in ~500ms |
| `orb-browser live` | Open interactive live view |
| `orb-browser status` | Health check |
| `orb-browser destroy` | Delete the browser VM |
| `orb-browser task "<prompt>"` | Vision agent: screenshot + LLM |
| `orb-browser ask <url> "<question>"` | Read page + ask LLM |

## When You Need to Log In

If a site requires login (Twitter, Gmail, etc.), the browser can't log in from its cloud IP — Cloudflare blocks it. Instead, import the user's existing cookies:

1. Ask the user to export cookies from their Chrome browser. See `references/cookie-export.md` for the exact instructions to give them.
2. Save the JSON to a file
3. Run: `orb-browser login --cookies /path/to/cookies.json`
4. Run: `orb-browser sleep` to checkpoint the session
5. Future `orb-browser wake` calls restore the logged-in session

**Important:** Always `orb-browser sleep` after importing cookies. This checkpoints the session. Next time you wake, you're still logged in.

## Patterns

### Browse and extract
```bash
orb-browser go https://news.ycombinator.com
orb-browser text  # read the page
# analyze the content yourself, no LLM needed — you ARE the LLM
```

### Screenshot + analyze visually
```bash
orb-browser go https://example.com
orb-browser screenshot /tmp/page.jpg
# Read the screenshot to see the page visually
```

### Fill a form
```bash
orb-browser go https://example.com/contact
orb-browser fill "input[name=email]" "user@example.com"
orb-browser fill "textarea[name=message]" "Hello!"
orb-browser click "button[type=submit]"
```

### Monitor a page on schedule
```bash
orb-browser wake
orb-browser go https://news.ycombinator.com
# ... extract content, analyze, email user ...
orb-browser sleep
# Use /schedule to repeat every N hours
```

### JavaScript extraction (advanced)
```bash
orb-browser eval "JSON.stringify(Array.from(document.querySelectorAll('h2')).map(h => h.textContent))"
```

## Cost

| State | Cost |
|-------|------|
| Running | ~$0.03/hr |
| Sleeping | $0/hr |
| Deploy | ~1-2 min (one-time) |
| Wake | ~500ms |

## Tips

- Always `orb-browser sleep` when done — it costs $0 while sleeping
- Use `orb-browser text` to read pages — faster than screenshots for text content
- Use `orb-browser screenshot` when you need to see layout, images, or visual content
- For recurring tasks, use `/schedule` to wake → browse → sleep on a cron
- The browser persists across sleep/wake — cookies, sessions, page state all survive
- For detailed API docs, see `references/api-reference.md`
- For cookie export instructions, see `references/cookie-export.md`
- For common automation patterns, see `references/patterns.md`
