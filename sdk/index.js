/**
 * OrbBrowser — Client SDK for browser sessions that sleep for $0
 *
 * Usage:
 *   const { OrbBrowser } = require("orb-browser-sdk");
 *   const browser = new OrbBrowser({ apiKey: "orb_..." });
 *   await browser.deploy();
 *   await browser.navigate("https://example.com");
 *   await browser.sleep();   // frozen to NVMe, $0/hr
 *   await browser.wake();    // ~500ms, everything restored
 */

const fs = require("fs");
const path = require("path");

class OrbBrowser {
  constructor({ apiKey, orbApiUrl = "https://api.orbcloud.dev" }) {
    if (!apiKey) throw new Error("apiKey is required");
    this.apiKey = apiKey;
    this.orbApiUrl = orbApiUrl;
    this.computerId = null;
    this.shortId = null;
    this.agentPort = null;
    this.vmUrl = null;
    this._state = "init"; // init | deploying | running | sleeping | destroyed
  }

  /**
   * Deploy a new browser VM on Orb Cloud.
   * Takes 3-5 minutes (builds Chrome from scratch).
   */
  async deploy({ name = `orb-browser-${Date.now()}`, runtimeMb = 2048, diskMb = 4096 } = {}) {
    this._state = "deploying";

    // 1. Create computer
    const comp = await this._orbApi("POST", "/v1/computers", { name, runtime_mb: runtimeMb, disk_mb: diskMb });
    this.computerId = comp.id;
    this.shortId = comp.id.slice(0, 8);
    this.vmUrl = `https://${this.shortId}.orbcloud.dev`;

    try {
      // 2. Upload config
      const toml = fs.readFileSync(path.join(__dirname, "..", "orb.toml"), "utf8");
      await fetch(`${this.orbApiUrl}/v1/computers/${this.computerId}/config`, {
        method: "POST",
        headers: { Authorization: `Bearer ${this.apiKey}`, "Content-Type": "application/toml" },
        body: toml,
      });

      // 3. Build
      const buildRes = await fetch(`${this.orbApiUrl}/v1/computers/${this.computerId}/build`, {
        method: "POST",
        headers: { Authorization: `Bearer ${this.apiKey}` },
        signal: AbortSignal.timeout(900_000),
      });
      const buildData = await buildRes.json();
      if (!buildData.success) {
        const failed = (buildData.steps || []).find((s) => s.exit_code !== 0);
        throw new Error(`Build failed: ${failed?.step || "unknown"}`);
      }

      // 4. Deploy agent
      const deploy = await this._orbApi("POST", `/v1/computers/${this.computerId}/agents`, {});
      this.agentPort = deploy.agents[0].port;

      // 5. Wait for health
      await this._waitForHealth(60_000);
      this._state = "running";

      return { computerId: this.computerId, vmUrl: this.vmUrl, agentPort: this.agentPort };
    } catch (err) {
      await this.destroy().catch(() => {});
      throw err;
    }
  }

  /**
   * Connect to an existing Orb Browser VM (skip deploy).
   */
  connect({ computerId, agentPort }) {
    this.computerId = computerId;
    this.shortId = computerId.slice(0, 8);
    this.vmUrl = `https://${this.shortId}.orbcloud.dev`;
    this.agentPort = agentPort;
    this._state = "running";
  }

  /**
   * Sleep: checkpoint the browser to NVMe. Costs $0 while sleeping.
   * Returns checkpoint metadata.
   */
  async sleep() {
    if (this._state !== "running") throw new Error(`Cannot sleep in state: ${this._state}`);
    const res = await this._orbApi("POST", `/v1/computers/${this.computerId}/agents/demote`, { port: this.agentPort });
    if (res.status !== "demoted") throw new Error(`Sleep failed: ${JSON.stringify(res)}`);
    this._state = "sleeping";
    return res;
  }

  /**
   * Wake: restore the browser from NVMe checkpoint. ~500ms.
   * Returns restore metadata.
   */
  async wake() {
    if (this._state !== "sleeping") throw new Error(`Cannot wake in state: ${this._state}`);
    const res = await this._orbApi("POST", `/v1/computers/${this.computerId}/agents/promote`, { port: this.agentPort });
    if (res.status !== "promoted") throw new Error(`Wake failed: ${JSON.stringify(res)}`);
    if (res.port) this.agentPort = res.port;
    await this._waitForHealth(30_000);
    this._state = "running";
    return res;
  }

  /** Navigate to a URL. Returns { title, url, cookies }. */
  async navigate(url) {
    return this._vmApi(`/navigate?url=${encodeURIComponent(url)}`);
  }

  /** Take a screenshot. Returns a Buffer (JPEG). */
  async screenshot() {
    const res = await fetch(`${this.vmUrl}/screenshot`);
    if (!res.ok) throw new Error(`Screenshot failed: ${res.status}`);
    return Buffer.from(await res.arrayBuffer());
  }

  /** Get all cookies. Returns { cookies: [...] }. */
  async cookies() {
    return this._vmApi("/cookies");
  }

  /** Get browser status. Returns { status, browserReady, currentUrl, cookies, error }. */
  async status() {
    return this._vmApi("/status");
  }

  /** Health check. Returns { status, browserReady, error }. */
  async health() {
    return this._vmApi("/health");
  }

  /** Destroy the VM. */
  async destroy() {
    if (!this.computerId) return;
    await fetch(`${this.orbApiUrl}/v1/computers/${this.computerId}`, {
      method: "DELETE",
      headers: { Authorization: `Bearer ${this.apiKey}` },
    });
    this._state = "destroyed";
  }

  // -- Internal --

  async _orbApi(method, path, body) {
    const res = await fetch(`${this.orbApiUrl}${path}`, {
      method,
      headers: { Authorization: `Bearer ${this.apiKey}`, "Content-Type": "application/json" },
      body: body ? JSON.stringify(body) : undefined,
    });
    if (!res.ok) {
      const text = await res.text();
      throw new Error(`Orb API ${method} ${path} failed (${res.status}): ${text}`);
    }
    return res.json();
  }

  async _vmApi(path) {
    const res = await fetch(`${this.vmUrl}${path}`);
    if (!res.ok) throw new Error(`VM API ${path} failed: ${res.status}`);
    return res.json();
  }

  async _waitForHealth(timeoutMs) {
    const start = Date.now();
    while (Date.now() - start < timeoutMs) {
      try {
        const res = await fetch(`${this.vmUrl}/health`, { signal: AbortSignal.timeout(5000) });
        if (res.ok) return;
      } catch {}
      await new Promise((r) => setTimeout(r, 2000));
    }
    throw new Error(`Health check timed out after ${timeoutMs}ms`);
  }
}

module.exports = { OrbBrowser };
