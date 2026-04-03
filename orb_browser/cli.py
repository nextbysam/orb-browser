"""
orb-browser CLI — give any agent a browser.

Usage:
    orb-browser deploy              Deploy a browser on Orb Cloud
    orb-browser go <url>            Navigate to URL
    orb-browser screenshot [path]   Take screenshot (prints path or base64)
    orb-browser text                Get page text
    orb-browser html                Get page HTML
    orb-browser url                 Get current URL and title
    orb-browser click <x> <y>      Click at coordinates
    orb-browser click <selector>   Click element by CSS selector
    orb-browser type <text>        Type text
    orb-browser press <key>        Press key (Enter, Tab, Escape, etc)
    orb-browser scroll [down|up]   Scroll the page
    orb-browser eval <js>          Run JavaScript
    orb-browser cookies            Get cookies as JSON
    orb-browser sleep              Checkpoint browser ($0)
    orb-browser wake               Restore browser (~500ms)
    orb-browser live               Open live view in your browser
    orb-browser status             Show browser status
    orb-browser destroy            Delete the browser VM
    orb-browser back               Go back
    orb-browser forward            Go forward
    orb-browser fill <sel> <val>   Fill input by CSS selector
    orb-browser task <prompt>      Run a vision task (screenshot → LLM → action)
    orb-browser ask <url> <q>      Navigate to URL, ask LLM a question about it
    orb-browser setup              Set up API keys and provider
    orb-browser auth <key>         Save Orb API key
    orb-browser signup <email>     Create account and save key
"""

import json
import os
import sys
import webbrowser

CONFIG_DIR = os.path.expanduser("~/.orb-browser")
CONFIG_FILE = os.path.join(CONFIG_DIR, "config.json")


def load_config():
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE) as f:
            return json.load(f)
    return {}


def save_config(config):
    os.makedirs(CONFIG_DIR, exist_ok=True)
    with open(CONFIG_FILE, "w") as f:
        json.dump(config, f, indent=2)


def get_orb():
    from orb_browser.client import OrbBrowser
    config = load_config()
    api_key = config.get("api_key")
    if not api_key:
        print("No API key. Run: orb-browser auth <key> or orb-browser signup <email>")
        sys.exit(1)
    orb = OrbBrowser(api_key=api_key)
    comp_id = config.get("computer_id")
    port = config.get("agent_port")
    if comp_id:
        orb.computer_id = comp_id
        orb.short_id = comp_id[:8]
        orb.agent_port = port
        orb._state = config.get("state", "running")
    return orb


def save_state(orb):
    config = load_config()
    config["computer_id"] = orb.computer_id
    config["agent_port"] = orb.agent_port
    config["state"] = orb._state
    save_config(config)


def main():
    args = sys.argv[1:]
    if not args or args[0] in ("--help", "-h", "help"):
        print(__doc__)
        return

    cmd = args[0]

    # ── Setup ─────────────────────────────────────────
    if cmd == "setup":
        config = load_config()
        print("orb-browser setup")
        print("=" * 40)
        orb_key = input(f"Orb API key [{config.get('api_key', '')}]: ").strip()
        if orb_key:
            config["api_key"] = orb_key
        llm_key = input(f"LLM API key (OpenRouter) [{config.get('llm_key', '')}]: ").strip()
        if llm_key:
            config["llm_key"] = llm_key
        provider = input(f"LLM provider (openai/anthropic) [{config.get('provider', 'openai')}]: ").strip()
        if provider:
            config["provider"] = provider
        elif "provider" not in config:
            config["provider"] = "openai"
        base_url = input(f"LLM base URL (blank for default, or paste for GLM/Groq/etc) [{config.get('base_url', '')}]: ").strip()
        if base_url:
            config["base_url"] = base_url
        save_config(config)
        print(f"\nSaved to {CONFIG_FILE}")
        return

    # ── Task ──────────────────────────────────────────
    if cmd == "task":
        if len(args) < 2:
            print("Usage: orb-browser task \"<prompt>\"")
            return
        prompt = " ".join(args[1:])
        orb = get_orb()
        config = load_config()
        llm_key = config.get("llm_key", "")
        provider = config.get("provider", "openai")
        if not llm_key:
            print("No LLM key configured. Run: orb-browser setup")
            return
        import urllib.request
        import urllib.error
        task_body = {"task": prompt, "llm_key": llm_key, "provider": provider}
        if config.get("base_url"):
            task_body["base_url"] = config["base_url"]
        req = urllib.request.Request(
            f"{orb.vm_url}/task",
            data=json.dumps(task_body).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            print("Running task (VM may checkpoint during LLM calls)...")
            res = json.loads(urllib.request.urlopen(req, timeout=600).read())
            if "result" in res:
                print(f"Result: {res['result']}")
            else:
                print(json.dumps(res, indent=2))
        except urllib.error.HTTPError as e:
            print(f"Error: {e.read().decode()}")
        return

    # ── Auth ──────────────────────────────────────────
    if cmd == "auth":
        if len(args) < 2:
            print("Usage: orb-browser auth <api_key>")
            return
        config = load_config()
        config["api_key"] = args[1]
        save_config(config)
        print(f"API key saved to {CONFIG_FILE}")
        return

    if cmd == "signup":
        if len(args) < 2:
            print("Usage: orb-browser signup <email>")
            return
        import urllib.request
        email = args[1]
        # Register
        req = urllib.request.Request(
            "https://api.orbcloud.dev/api/v1/auth/register",
            data=json.dumps({"email": email}).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        res = json.loads(urllib.request.urlopen(req).read())
        initial_key = res["api_key"]
        # Create org key
        req = urllib.request.Request(
            "https://api.orbcloud.dev/v1/keys",
            data=json.dumps({"name": "orb-browser-cli"}).encode(),
            headers={"Authorization": f"Bearer {initial_key}", "Content-Type": "application/json"},
            method="POST",
        )
        res = json.loads(urllib.request.urlopen(req).read())
        api_key = res["api_key"]
        config = load_config()
        config["api_key"] = api_key
        save_config(config)
        print(f"Account created. API key saved to {CONFIG_FILE}")
        return

    # ── Deploy ────────────────────────────────────────
    if cmd == "deploy":
        orb = get_orb()
        config = load_config()
        orb.deploy(
            llm_key=config.get("llm_key", ""),
            llm_provider=config.get("provider", "openai"),
        )
        save_state(orb)
        print(orb.vm_url)
        return

    # ── Navigation ────────────────────────────────────
    if cmd == "go":
        if len(args) < 2:
            print("Usage: orb-browser go <url>")
            return
        orb = get_orb()
        result = orb.navigate(args[1])
        print(json.dumps(result))
        save_state(orb)
        return

    # ── Content ───────────────────────────────────────
    if cmd == "screenshot":
        orb = get_orb()
        path = args[1] if len(args) > 1 else None
        img = orb.screenshot(path)
        if path:
            print(path)
        else:
            import base64
            print(base64.b64encode(img).decode())
        return

    if cmd == "text":
        orb = get_orb()
        print(orb.text())
        return

    if cmd == "html":
        orb = get_orb()
        print(orb.html())
        return

    if cmd == "url":
        orb = get_orb()
        print(json.dumps(orb.url()))
        return

    # ── Interaction ───────────────────────────────────
    if cmd == "click":
        orb = get_orb()
        if len(args) == 3 and args[1].isdigit():
            result = orb.click(x=int(args[1]), y=int(args[2]))
        elif len(args) >= 2:
            result = orb.click(selector=args[1])
        else:
            print("Usage: orb-browser click <x> <y> or orb-browser click <selector>")
            return
        print(json.dumps(result))
        return

    if cmd == "type":
        if len(args) < 2:
            print("Usage: orb-browser type <text>")
            return
        orb = get_orb()
        result = orb.type(" ".join(args[1:]))
        print(json.dumps(result))
        return

    if cmd == "press":
        if len(args) < 2:
            print("Usage: orb-browser press <key>")
            return
        orb = get_orb()
        result = orb.press(args[1])
        print(json.dumps(result))
        return

    if cmd == "scroll":
        orb = get_orb()
        direction = args[1] if len(args) > 1 else "down"
        amount = int(args[2]) if len(args) > 2 else 500
        result = orb.scroll(direction, amount)
        print(json.dumps(result))
        return

    if cmd == "back":
        orb = get_orb()
        print(json.dumps(orb.back()))
        return

    if cmd == "forward":
        orb = get_orb()
        print(json.dumps(orb.forward()))
        return

    if cmd == "fill":
        if len(args) < 3:
            print("Usage: orb-browser fill <selector> <value>")
            return
        orb = get_orb()
        result = orb.fill(args[1], " ".join(args[2:]))
        print(json.dumps(result))
        return

    if cmd == "ask":
        if len(args) < 3:
            print('Usage: orb-browser ask <url> "<question>"')
            return
        orb = get_orb()
        config = load_config()
        url = args[1]
        question = " ".join(args[2:])
        llm_key = config.get("llm_key", "")
        answer = orb.ask(url, question, llm_key=llm_key)
        print(answer)
        return

    if cmd == "eval":
        if len(args) < 2:
            print("Usage: orb-browser eval <javascript>")
            return
        orb = get_orb()
        result = orb.evaluate(" ".join(args[1:]))
        print(json.dumps(result))
        return

    # ── Cookies ───────────────────────────────────────
    if cmd == "cookies":
        orb = get_orb()
        print(json.dumps(orb.cookies(), indent=2))
        return

    # ── Lifecycle ─────────────────────────────────────
    if cmd == "sleep":
        orb = get_orb()
        orb.sleep()
        save_state(orb)
        print("Sleeping. $0.")
        return

    if cmd == "wake":
        orb = get_orb()
        orb.wake()
        save_state(orb)
        print(orb.vm_url)
        return

    if cmd == "live":
        orb = get_orb()
        url = orb.live_url
        print(url)
        webbrowser.open(url)
        return

    if cmd == "status":
        orb = get_orb()
        try:
            h = orb.health()
            print(json.dumps(h))
        except Exception:
            config = load_config()
            print(json.dumps({"state": config.get("state", "unknown"), "computer_id": config.get("computer_id")}))
        return

    if cmd == "destroy":
        orb = get_orb()
        orb.destroy()
        config = load_config()
        config.pop("computer_id", None)
        config.pop("agent_port", None)
        config.pop("state", None)
        save_config(config)
        print("Destroyed.")
        return

    print(f"Unknown command: {cmd}")
    print("Run 'orb-browser' for usage.")


if __name__ == "__main__":
    main()
