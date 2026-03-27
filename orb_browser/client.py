"""
OrbBrowser — deploy browser agents on Orb Cloud.

Usage:
    from orb_browser import OrbBrowser

    orb = OrbBrowser(api_key="orb_...")
    cdp_url = orb.deploy()

    # Use with browser-use
    from browser_use import Browser
    browser = Browser(cdp_url=cdp_url)
    await browser.start()

    # Sleep ($0 while frozen)
    orb.sleep()

    # Wake (~500ms)
    cdp_url = orb.wake()
    browser = Browser(cdp_url=cdp_url)
    await browser.start()
"""

import json
import time
import urllib.request
import urllib.error

# The orb.toml config that runs on Orb Cloud
ORB_TOML = """[agent]
name = "orb-browser"
lang = "node"
entry = "server.js"

[source]
git = "https://github.com/nextbysam/orb-browser.git"
branch = "main"

[build]
steps = [
  "apt-get update && DEBIAN_FRONTEND=noninteractive apt-get install -y libnss3 libatk-bridge2.0-0t64 libcups2t64 libdrm2 libgbm1 libpango-1.0-0 libcairo2 libasound2t64 libxshmfence1 libxcomposite1 libxrandr2 libxdamage1 libxfixes3 libxext6 libx11-xcb1 libxcb1 libxkbcommon0 libdbus-1-3",
  "cd /agent/code && npm install",
  "PLAYWRIGHT_BROWSERS_PATH=/opt/browsers npx playwright install chromium"
]
working_dir = "/agent/code"

[agent.env]
PLAYWRIGHT_BROWSERS_PATH = "/opt/browsers"
PORT = "8000"
CDP_PORT = "9222"

[backend]
provider = "custom"

[ports]
expose = [8000, 9222]
"""


class OrbBrowser:
    """Deploy and manage a browser on Orb Cloud with sleep/wake support."""

    def __init__(self, api_key: str, api_url: str = "https://api.orbcloud.dev"):
        self.api_key = api_key
        self.api_url = api_url
        self.computer_id: str | None = None
        self.short_id: str | None = None
        self.agent_port: int | None = None
        self.cdp_url: str | None = None
        self._state = "init"

    def deploy(
        self,
        name: str | None = None,
        runtime_mb: int = 2048,
        disk_mb: int = 4096,
        wait: bool = True,
    ) -> str:
        """
        Deploy a browser on Orb Cloud. Returns the CDP WebSocket URL.

        Takes 1-3 minutes on first deploy (installs Chrome).
        """
        if name is None:
            name = f"orb-browser-{int(time.time())}"

        self._state = "deploying"
        print(f"[orb-browser] Creating VM...")

        # 1. Create computer
        res = self._orb("POST", "/v1/computers", {
            "name": name, "runtime_mb": runtime_mb, "disk_mb": disk_mb,
        })
        self.computer_id = res["id"]
        self.short_id = self.computer_id[:8]
        print(f"[orb-browser] VM: {self.short_id}")

        try:
            # 2. Upload config
            req = urllib.request.Request(
                f"{self.api_url}/v1/computers/{self.computer_id}/config",
                data=ORB_TOML.encode(),
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/toml",
                },
                method="POST",
            )
            urllib.request.urlopen(req)

            # 3. Build
            print(f"[orb-browser] Building (Chrome + Playwright)...")
            req = urllib.request.Request(
                f"{self.api_url}/v1/computers/{self.computer_id}/build",
                headers={"Authorization": f"Bearer {self.api_key}"},
                method="POST",
            )
            build_res = json.loads(urllib.request.urlopen(req, timeout=900).read())
            if not build_res.get("success"):
                failed = next(
                    (s for s in build_res.get("steps", []) if s["exit_code"] != 0),
                    None,
                )
                raise RuntimeError(f"Build failed: {failed}")
            print(f"[orb-browser] Build OK")

            # 4. Deploy agent
            deploy_res = self._orb(
                "POST", f"/v1/computers/{self.computer_id}/agents", {}
            )
            self.agent_port = deploy_res["agents"][0]["port"]

            # 5. Wait for health
            if wait:
                self._wait_for_health(timeout=60)

            # 6. Set hostname so CDP URLs are correct
            vm_url = f"https://{self.short_id}.orbcloud.dev"
            urllib.request.urlopen(
                f"{vm_url}/set-host?host={self.short_id}.orbcloud.dev"
            )

            # 7. Get CDP URL
            cdp_data = json.loads(
                urllib.request.urlopen(f"{vm_url}/cdp").read()
            )
            self.cdp_url = cdp_data["cdpUrl"]
            self._state = "running"

            print(f"[orb-browser] Ready! CDP: {self.cdp_url}")
            return self.cdp_url

        except Exception:
            self.destroy()
            raise

    def connect(self, computer_id: str, agent_port: int) -> str:
        """Connect to an existing Orb Browser VM. Returns CDP URL."""
        self.computer_id = computer_id
        self.short_id = computer_id[:8]
        self.agent_port = agent_port
        self._state = "running"

        vm_url = f"https://{self.short_id}.orbcloud.dev"
        urllib.request.urlopen(
            f"{vm_url}/set-host?host={self.short_id}.orbcloud.dev"
        )
        cdp_data = json.loads(urllib.request.urlopen(f"{vm_url}/cdp").read())
        self.cdp_url = cdp_data["cdpUrl"]
        return self.cdp_url

    def sleep(self) -> dict:
        """
        Checkpoint the browser to NVMe. Costs $0 while sleeping.
        WebSocket connections will drop — reconnect after wake().
        """
        if self._state != "running":
            raise RuntimeError(f"Cannot sleep in state: {self._state}")

        res = self._orb(
            "POST",
            f"/v1/computers/{self.computer_id}/agents/demote",
            {"port": self.agent_port},
        )
        if res.get("status") != "demoted":
            raise RuntimeError(f"Sleep failed: {res}")

        self._state = "sleeping"
        print(f"[orb-browser] Sleeping (frozen, $0)")
        return res

    def wake(self, wait: bool = True) -> str:
        """
        Restore the browser from NVMe. ~500ms.
        Returns the CDP URL (same as before sleep).
        Reconnect browser-use with the returned URL.
        """
        if self._state != "sleeping":
            raise RuntimeError(f"Cannot wake in state: {self._state}")

        res = self._orb(
            "POST",
            f"/v1/computers/{self.computer_id}/agents/promote",
            {"port": self.agent_port},
        )
        if res.get("status") != "promoted":
            raise RuntimeError(f"Wake failed: {res}")

        if res.get("port"):
            self.agent_port = res["port"]

        if wait:
            self._wait_for_health(timeout=30)

        # Refresh CDP URL
        vm_url = f"https://{self.short_id}.orbcloud.dev"
        cdp_data = json.loads(urllib.request.urlopen(f"{vm_url}/cdp").read())
        self.cdp_url = cdp_data["cdpUrl"]
        self._state = "running"

        print(f"[orb-browser] Awake! CDP: {self.cdp_url}")
        return self.cdp_url

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
        print(f"[orb-browser] Destroyed {self.short_id}")

    @property
    def vm_url(self) -> str | None:
        return f"https://{self.short_id}.orbcloud.dev" if self.short_id else None

    @property
    def state(self) -> str:
        return self._state

    # -- Internal --

    def _orb(self, method: str, path: str, body: dict | None = None) -> dict:
        data = json.dumps(body).encode() if body else None
        req = urllib.request.Request(
            f"{self.api_url}{path}",
            data=data,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            method=method,
        )
        try:
            return json.loads(urllib.request.urlopen(req).read())
        except urllib.error.HTTPError as e:
            body_text = e.read().decode() if e.fp else ""
            raise RuntimeError(
                f"Orb API {method} {path} failed ({e.code}): {body_text}"
            )

    def _wait_for_health(self, timeout: int = 60):
        vm_url = f"https://{self.short_id}.orbcloud.dev"
        start = time.time()
        while time.time() - start < timeout:
            try:
                res = urllib.request.urlopen(f"{vm_url}/health", timeout=5)
                data = json.loads(res.read())
                if data.get("status") == "ok" and data.get("browserReady"):
                    return
            except Exception:
                pass
            time.sleep(2)
        raise TimeoutError(f"Browser not ready after {timeout}s")
