"""
OrbBrowser — deploy a browser on Orb Cloud.

    from orb_browser import OrbBrowser

    orb = OrbBrowser(api_key="orb_...")
    orb.deploy()

    # Control via HTTP
    orb.navigate("https://example.com")
    orb.screenshot("screenshot.jpg")

    # Manual login via live view
    print(orb.live_url)  # Open in your browser, log in manually

    # Sleep ($0 while frozen)
    orb.sleep()

    # Wake (~500ms, still logged in)
    orb.wake()
"""

import json
import time
import urllib.request
import urllib.error

def _make_orb_toml(provider="custom", llm_key="", llm_provider="openai"):
    """Generate orb.toml with the right LLM provider for Orb optimization."""
    return f"""[agent]
name = "orb-browser"
lang = "python"
entry = "agent.py"

[source]
git = "https://github.com/nextbysam/orb-browser.git"
branch = "main"

[build]
steps = [
  "pip install playwright fastapi uvicorn httpx",
  "PLAYWRIGHT_BROWSERS_PATH=/opt/browsers playwright install chromium",
]
working_dir = "/agent/code"

[agent.env]
PLAYWRIGHT_BROWSERS_PATH = "/opt/browsers"
LLM_API_KEY = "{llm_key}"
LLM_PROVIDER = "{llm_provider}"

[lifecycle]
idle_timeout = "300s"

[backend]
provider = "{provider}"

[ports]
expose = [8000]
"""


class OrbBrowser:
    """A browser on Orb Cloud. Deploy, control, sleep, wake."""

    def __init__(self, api_key: str, api_url: str = "https://api.orbcloud.dev",
                 agent_key: str | None = None):
        self.api_key = api_key
        self.api_url = api_url
        self.agent_key = agent_key  # optional API key for agent endpoints
        self.computer_id: str | None = None
        self.short_id: str | None = None
        self.agent_port: int | None = None
        self._state = "init"

    # ── Deploy ────────────────────────────────────────────

    def deploy(self, name: str | None = None, wait: bool = True,
               llm_key: str = "", llm_provider: str = "openai") -> str:
        """Deploy a browser on Orb Cloud. Returns the VM URL."""
        if name is None:
            name = f"orb-browser-{int(time.time())}"

        self._state = "deploying"
        print(f"[orb-browser] Creating VM...")

        res = self._orb("POST", "/v1/computers", {
            "name": name, "runtime_mb": 2048, "disk_mb": 4096,
        })
        self.computer_id = res["id"]
        self.short_id = self.computer_id[:8]
        print(f"[orb-browser] VM: {self.short_id}")

        try:
            # Upload config — provider tells Orb which LLM to optimize around
            orb_provider = {"openai": "openai", "anthropic": "anthropic"}.get(llm_provider, "custom")
            toml = _make_orb_toml(provider=orb_provider, llm_key=llm_key, llm_provider=llm_provider)
            req = urllib.request.Request(
                f"{self.api_url}/v1/computers/{self.computer_id}/config",
                data=toml.encode(),
                headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/toml"},
                method="POST",
            )
            urllib.request.urlopen(req)

            # Build
            print(f"[orb-browser] Building...")
            req = urllib.request.Request(
                f"{self.api_url}/v1/computers/{self.computer_id}/build",
                headers={"Authorization": f"Bearer {self.api_key}"},
                method="POST",
            )
            build_res = json.loads(urllib.request.urlopen(req, timeout=900).read())
            if not build_res.get("success"):
                raise RuntimeError(f"Build failed")
            print(f"[orb-browser] Build OK")

            # Deploy agent
            deploy_res = self._orb("POST", f"/v1/computers/{self.computer_id}/agents", {})
            self.agent_port = deploy_res["agents"][0]["port"]

            # Wait for health
            if wait:
                self._wait_for_health(timeout=60)

            self._state = "running"
            print(f"[orb-browser] Ready at {self.vm_url}")
            print(f"[orb-browser] Live view: {self.live_url}")
            return self.vm_url

        except Exception:
            self.destroy()
            raise

    # ── Connect to existing ───────────────────────────────

    def connect(self, computer_id: str, agent_port: int | None = None):
        """Connect to an existing browser VM."""
        self.computer_id = computer_id
        self.short_id = computer_id[:8]
        self.agent_port = agent_port
        self._state = "running"

    # ── Browser Control ───────────────────────────────────

    def navigate(self, url: str) -> dict:
        """Navigate to a URL."""
        return self._vm("POST", "/navigate", {"url": url})

    def click(self, selector: str | None = None, x: int | None = None, y: int | None = None) -> dict:
        """Click an element by selector or coordinates."""
        return self._vm("POST", "/click", {"selector": selector, "x": x, "y": y})

    def fill(self, selector: str, value: str) -> dict:
        """Fill an input field."""
        return self._vm("POST", "/fill", {"selector": selector, "value": value})

    def type(self, text: str) -> dict:
        """Type text."""
        return self._vm("POST", "/type", {"text": text})

    def press(self, key: str) -> dict:
        """Press a key (Enter, Tab, Escape, etc)."""
        return self._vm("POST", "/press", {"key": key})

    def scroll(self, direction: str = "down", amount: int = 500) -> dict:
        """Scroll the page."""
        return self._vm("POST", "/scroll", {"direction": direction, "amount": amount})

    def evaluate(self, expression: str) -> dict:
        """Execute JavaScript."""
        return self._vm("POST", "/eval", {"expression": expression})

    def screenshot(self, path: str | None = None) -> bytes:
        """Take a screenshot. Returns JPEG bytes. Optionally saves to path."""
        req = urllib.request.Request(f"{self.vm_url}/screenshot", data=b"", method="POST")
        if self.agent_key:
            req.add_header("X-Api-Key", self.agent_key)
        img = urllib.request.urlopen(req, timeout=30).read()
        if path:
            with open(path, "wb") as f:
                f.write(img)
        return img

    def task(self, prompt: str, llm_key: str | None = None,
             provider: str | None = None, model: str | None = None,
             base_url: str | None = None,
             max_steps: int = 50) -> str:
        """Run a natural language task. Synchronous — waits for completion."""
        body = {"task": prompt, "max_steps": max_steps}
        if llm_key:
            body["llm_key"] = llm_key
        if provider:
            body["provider"] = provider
        if model:
            body["model"] = model
        if base_url:
            body["base_url"] = base_url

        headers = {"Content-Type": "application/json"}
        if self.agent_key:
            headers["X-Api-Key"] = self.agent_key
        req = urllib.request.Request(
            f"{self.vm_url}/task",
            data=json.dumps(body).encode(),
            headers=headers,
            method="POST",
        )
        # Long timeout: Orb checkpoints/restores the VM during LLM calls
        result = json.loads(urllib.request.urlopen(req, timeout=max_steps * 300).read())
        return result.get("result", result)

    def url(self) -> dict:
        """Get current URL and title."""
        return self._vm("GET", "/url")

    def text(self) -> str:
        """Get page text content."""
        return self._vm("GET", "/text").get("text", "")

    def html(self) -> str:
        """Get page HTML."""
        return self._vm("GET", "/html").get("html", "")

    def cookies(self) -> list:
        """Get all cookies."""
        return self._vm("GET", "/cookies").get("cookies", [])

    def set_cookies(self, cookies: list[dict]):
        """Set cookies."""
        return self._vm("POST", "/cookies", {"cookies": cookies})

    def back(self) -> dict:
        """Go back."""
        return self._vm("POST", "/back")

    def forward(self) -> dict:
        """Go forward."""
        return self._vm("POST", "/forward")

    def ask(self, url: str, question: str, llm_key: str | None = None,
            model: str | None = None, base_url: str | None = None) -> str:
        """Navigate to URL, read text, ask LLM a question about it."""
        body = {"url": url, "question": question}
        if llm_key:
            body["llm_key"] = llm_key
        if model:
            body["model"] = model
        if base_url:
            body["base_url"] = base_url
        headers = {"Content-Type": "application/json"}
        if self.agent_key:
            headers["X-Api-Key"] = self.agent_key
        req = urllib.request.Request(
            f"{self.vm_url}/ask",
            data=json.dumps(body).encode(),
            headers=headers,
            method="POST",
        )
        result = json.loads(urllib.request.urlopen(req, timeout=120).read())
        return result.get("answer", result)

    def health(self) -> dict:
        """Health check."""
        return self._vm("GET", "/health")

    # ── Sleep / Wake ──────────────────────────────────────

    def sleep(self) -> dict:
        """Checkpoint the browser. $0 while sleeping."""
        res = self._orb("POST", f"/v1/computers/{self.computer_id}/agents/demote", {"port": self.agent_port})
        self._state = "sleeping"
        print(f"[orb-browser] Sleeping (frozen, $0)")
        return res

    def wake(self) -> str:
        """Restore the browser. ~500ms. Returns VM URL."""
        res = self._orb("POST", f"/v1/computers/{self.computer_id}/agents/promote", {"port": self.agent_port})
        if res.get("port"):
            self.agent_port = res["port"]
        self._wait_for_health(timeout=30)
        self._state = "running"
        print(f"[orb-browser] Awake!")
        return self.vm_url

    # ── Lifecycle ─────────────────────────────────────────

    def destroy(self):
        """Delete the VM."""
        if not self.computer_id:
            return
        try:
            req = urllib.request.Request(
                f"{self.api_url}/v1/computers/{self.computer_id}",
                headers={"Authorization": f"Bearer {self.api_key}"},
                method="DELETE",
            )
            urllib.request.urlopen(req)
        except urllib.error.HTTPError:
            pass
        self._state = "destroyed"
        print(f"[orb-browser] Destroyed")

    @property
    def vm_url(self) -> str | None:
        return f"https://{self.short_id}.orbcloud.dev" if self.short_id else None

    @property
    def live_url(self) -> str | None:
        return f"{self.vm_url}/live" if self.vm_url else None

    @property
    def state(self) -> str:
        return self._state

    # ── Internal ──────────────────────────────────────────

    def _orb(self, method: str, path: str, body: dict | None = None) -> dict:
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(
            f"{self.api_url}{path}", data=data,
            headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
            method=method,
        )
        try:
            return json.loads(urllib.request.urlopen(req).read())
        except urllib.error.HTTPError as e:
            raise RuntimeError(f"Orb API {method} {path} ({e.code}): {e.read().decode()}")

    def _vm(self, method: str, path: str, body: dict | None = None) -> dict:
        data = json.dumps(body).encode() if body is not None else None
        headers = {}
        if data:
            headers["Content-Type"] = "application/json"
        if self.agent_key:
            headers["X-Api-Key"] = self.agent_key
        req = urllib.request.Request(
            f"{self.vm_url}{path}", data=data, headers=headers, method=method,
        )
        return json.loads(urllib.request.urlopen(req, timeout=30).read())

    def _wait_for_health(self, timeout: int = 60):
        start = time.time()
        while time.time() - start < timeout:
            try:
                res = urllib.request.urlopen(f"{self.vm_url}/health", timeout=5)
                data = json.loads(res.read())
                if data.get("status") == "ok" and data.get("browserReady"):
                    return
            except Exception:
                pass
            time.sleep(2)
        raise TimeoutError(f"Browser not ready after {timeout}s")
