const http = require("http");
const { execSync } = require("child_process");

const BROWSERS_PATH = process.env.PLAYWRIGHT_BROWSERS_PATH || "/opt/browsers";
const PORT = parseInt(process.env.PORT || "8000");
const CDP_PORT = parseInt(process.env.CDP_PORT || "9222");
let PUBLIC_HOST = process.env.PUBLIC_HOST || null;

let browserProcess = null;
let wsEndpoint = null;
let initError = null;

// Find Playwright's Chromium binary
function findChromium() {
  const fs = require("fs");
  const path = require("path");
  try {
    const dirs = fs.readdirSync(BROWSERS_PATH).filter(d => d.startsWith("chromium-"));
    for (const dir of dirs) {
      for (const sub of ["chrome-linux64/chrome", "chrome-linux/chrome"]) {
        const p = path.join(BROWSERS_PATH, dir, sub);
        if (fs.existsSync(p)) return p;
      }
    }
  } catch {}
  return null;
}

// Launch Chromium with CDP debugging port
function launchChromium() {
  const { spawn } = require("child_process");
  const chromePath = findChromium();
  if (!chromePath) {
    initError = "Chromium binary not found";
    console.error(initError);
    return;
  }
  console.log("Launching:", chromePath);

  browserProcess = spawn(chromePath, [
    "--no-sandbox", "--disable-gpu", "--disable-dev-shm-usage", "--headless",
    `--remote-debugging-port=${CDP_PORT}`, "--remote-debugging-address=0.0.0.0",
    "--no-first-run", "--disable-background-networking", "--disable-default-apps",
    "--disable-extensions", "--disable-sync", "--disable-translate", "--mute-audio",
    "--hide-scrollbars", "--metrics-recording-only", "--no-default-browser-check",
    "--password-store=basic",
  ], { stdio: ["ignore", "pipe", "pipe"] });

  browserProcess.stderr.on("data", (data) => {
    const match = data.toString().match(/DevTools listening on (ws:\/\/.+)/);
    if (match) {
      wsEndpoint = match[1];
      console.log("CDP:", wsEndpoint);
    }
  });

  browserProcess.on("exit", (code) => {
    console.error("Chromium exited:", code);
    browserProcess = null;
    wsEndpoint = null;
  });
}

// Get the public-facing CDP WebSocket URL
// Orb proxies wss://{id}.orbcloud.dev/_port/9222/... → ws://container:9222/...
function getCdpUrl() {
  if (!wsEndpoint || !PUBLIC_HOST) return null;
  const browserId = wsEndpoint.split("/").pop();
  return `wss://${PUBLIC_HOST}/_port/${CDP_PORT}/devtools/browser/${browserId}`;
}

const server = http.createServer(async (req, res) => {
  const url = new URL(req.url, "http://localhost");
  res.setHeader("Content-Type", "application/json");

  // Auto-detect public hostname
  if (!PUBLIC_HOST) {
    for (const h of [req.headers["x-forwarded-host"], req.headers.host]) {
      if (h && h.includes("orbcloud.dev")) { PUBLIC_HOST = h.split(":")[0]; break; }
    }
  }

  try {
    if (url.pathname === "/health") {
      res.end(JSON.stringify({
        status: "ok",
        browserReady: !!wsEndpoint,
        error: initError,
      }));

    } else if (url.pathname === "/cdp") {
      // Return the CDP WebSocket URL for browser-use
      const cdpUrl = getCdpUrl();
      if (!cdpUrl) {
        res.statusCode = 503;
        res.end(JSON.stringify({ error: "browser not ready or hostname not set. Call /set-host?host=ID.orbcloud.dev first" }));
        return;
      }
      res.end(JSON.stringify({ cdpUrl }));

    } else if (url.pathname === "/json/version") {
      // Proxy and rewrite CDP discovery
      const cdpRes = await fetch(`http://127.0.0.1:${CDP_PORT}/json/version`);
      const data = await cdpRes.json();
      if (data.webSocketDebuggerUrl && PUBLIC_HOST) {
        const browserId = data.webSocketDebuggerUrl.split("/").pop();
        data.webSocketDebuggerUrl = `wss://${PUBLIC_HOST}/_port/${CDP_PORT}/devtools/browser/${browserId}`;
      }
      res.end(JSON.stringify(data));

    } else if (url.pathname === "/json" || url.pathname === "/json/list") {
      const cdpRes = await fetch(`http://127.0.0.1:${CDP_PORT}/json`);
      const data = await cdpRes.json();
      res.end(JSON.stringify(data));

    } else if (url.pathname === "/status") {
      res.end(JSON.stringify({
        status: "ok",
        browserReady: !!wsEndpoint,
        cdpUrl: getCdpUrl(),
        pid: browserProcess?.pid || null,
        publicHost: PUBLIC_HOST,
        error: initError,
      }));

    } else if (url.pathname === "/set-host") {
      const h = url.searchParams.get("host");
      if (h) {
        PUBLIC_HOST = h;
        res.end(JSON.stringify({ ok: true, host: h, cdpUrl: getCdpUrl() }));
      } else {
        res.statusCode = 400;
        res.end(JSON.stringify({ error: "?host=ID.orbcloud.dev required" }));
      }

    } else {
      res.statusCode = 404;
      res.end(JSON.stringify({ error: "not found" }));
    }
  } catch (e) {
    res.statusCode = 500;
    res.end(JSON.stringify({ error: e.message }));
  }
});

// No WebSocket proxy needed — Orb proxies wss://_port/9222 directly to Chrome
server.listen(PORT, "0.0.0.0", () => {
  console.log(`Server on :${PORT}`);
  launchChromium();
});
