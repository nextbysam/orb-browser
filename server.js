const http = require("http");
const { execSync } = require("child_process");

const BROWSERS_PATH = process.env.PLAYWRIGHT_BROWSERS_PATH || "/opt/browsers";
const PORT = parseInt(process.env.PORT || "3000");
const CDP_PORT = parseInt(process.env.CDP_PORT || "9222");

let browserProcess = null;
let wsEndpoint = null;
let initError = null;

// Find Playwright's Chromium binary
function findChromium() {
  const fs = require("fs");
  const path = require("path");
  // Look for chrome binary in Playwright's browser install
  try {
    const dirs = fs.readdirSync(BROWSERS_PATH).filter(d => d.startsWith("chromium-"));
    for (const dir of dirs) {
      for (const sub of ["chrome-linux64/chrome", "chrome-linux/chrome"]) {
        const p = path.join(BROWSERS_PATH, dir, sub);
        if (fs.existsSync(p)) return p;
      }
    }
  } catch {}
  // Fallback: ask Playwright
  try {
    return execSync("npx playwright install --dry-run chromium 2>/dev/null | grep chrome | head -1", { encoding: "utf8" }).trim();
  } catch {}
  return null;
}

// Launch Chromium with CDP debugging port exposed
function launchChromium() {
  const { spawn } = require("child_process");
  const chromePath = findChromium();
  if (!chromePath) {
    initError = "Chromium binary not found";
    console.error(initError);
    return;
  }
  console.log("Launching:", chromePath);

  const args = [
    "--no-sandbox",
    "--disable-gpu",
    "--disable-dev-shm-usage",
    "--headless",
    `--remote-debugging-port=${CDP_PORT}`,
    "--remote-debugging-address=0.0.0.0",
    "--no-first-run",
    "--disable-background-networking",
    "--disable-default-apps",
    "--disable-extensions",
    "--disable-sync",
    "--disable-translate",
    "--mute-audio",
    "--hide-scrollbars",
    "--metrics-recording-only",
    "--no-default-browser-check",
    "--password-store=basic",
  ];

  browserProcess = spawn(chromePath, args, { stdio: ["ignore", "pipe", "pipe"] });

  browserProcess.stderr.on("data", (data) => {
    const line = data.toString();
    // Capture the DevTools WebSocket URL
    const match = line.match(/DevTools listening on (ws:\/\/.+)/);
    if (match) {
      wsEndpoint = match[1];
      console.log("CDP WebSocket:", wsEndpoint);
    }
  });

  browserProcess.on("exit", (code) => {
    console.error("Chromium exited with code", code);
    browserProcess = null;
    wsEndpoint = null;
  });
}

// HTTP API server
const server = http.createServer(async (req, res) => {
  const url = new URL(req.url, "http://localhost");
  res.setHeader("Content-Type", "application/json");

  try {
    if (url.pathname === "/health") {
      res.end(JSON.stringify({
        status: "ok",
        browserReady: !!wsEndpoint,
        cdpPort: CDP_PORT,
        error: initError,
      }));

    } else if (url.pathname === "/cdp") {
      // Return CDP connection info for browser-use
      if (!wsEndpoint) {
        res.statusCode = 503;
        res.end(JSON.stringify({ error: "browser not ready" }));
        return;
      }
      // Extract the browser ID from the local wsEndpoint
      const browserId = wsEndpoint.split("/").pop();
      const host = req.headers["x-forwarded-host"] || req.headers.host || `localhost:${PORT}`;
      const proto = (req.headers["x-forwarded-proto"] === "https" || host.includes("orbcloud.dev")) ? "wss" : "ws";
      res.end(JSON.stringify({
        wsEndpoint: `${proto}://${host}/devtools/browser/${browserId}`,
        httpEndpoint: `${proto === "wss" ? "https" : "http"}://${host}`,
      }));

    } else if (url.pathname === "/json/version") {
      // Proxy CDP /json/version, rewrite WebSocket URL to external
      const cdpRes = await fetch(`http://127.0.0.1:${CDP_PORT}/json/version`);
      const data = await cdpRes.json();
      const host = req.headers["x-forwarded-host"] || req.headers.host || `localhost:${PORT}`;
      const proto = (req.headers["x-forwarded-proto"] === "https" || host.includes("orbcloud.dev")) ? "wss" : "ws";
      if (data.webSocketDebuggerUrl) {
        const browserId = data.webSocketDebuggerUrl.split("/").pop();
        data.webSocketDebuggerUrl = `${proto}://${host}/devtools/browser/${browserId}`;
      }
      res.end(JSON.stringify(data));

    } else if (url.pathname === "/json" || url.pathname === "/json/list") {
      // Proxy CDP /json for compatibility
      const cdpRes = await fetch(`http://127.0.0.1:${CDP_PORT}/json`);
      const data = await cdpRes.json();
      res.end(JSON.stringify(data));

    } else if (url.pathname === "/status") {
      res.end(JSON.stringify({
        status: "ok",
        browserReady: !!wsEndpoint,
        wsEndpoint,
        cdpPort: CDP_PORT,
        pid: browserProcess?.pid || null,
        error: initError,
      }));

    } else {
      res.statusCode = 404;
      res.end(JSON.stringify({
        error: "not found",
        endpoints: ["/health", "/cdp", "/json/version", "/json", "/status"],
      }));
    }
  } catch (e) {
    res.statusCode = 500;
    res.end(JSON.stringify({ error: e.message }));
  }
});

// WebSocket proxy: forward CDP connections from :3000 to :9222
const WebSocket = require("ws");
const wss = new WebSocket.Server({ noServer: true });

server.on("upgrade", (req, socket, head) => {
  // Proxy any WebSocket upgrade to Chrome's CDP
  const cdpPath = req.url || "/";
  const target = `ws://127.0.0.1:${CDP_PORT}${cdpPath}`;

  const cdpWs = new WebSocket(target);
  cdpWs.on("open", () => {
    wss.handleUpgrade(req, socket, head, (clientWs) => {
      // Bidirectional proxy
      clientWs.on("message", (data) => {
        if (cdpWs.readyState === WebSocket.OPEN) cdpWs.send(data);
      });
      cdpWs.on("message", (data) => {
        if (clientWs.readyState === WebSocket.OPEN) clientWs.send(data);
      });
      clientWs.on("close", () => cdpWs.close());
      cdpWs.on("close", () => clientWs.close());
      clientWs.on("error", () => cdpWs.close());
      cdpWs.on("error", () => clientWs.close());
    });
  });
  cdpWs.on("error", () => {
    socket.destroy();
  });
});

// Start server FIRST (so health check passes), then launch Chrome
server.listen(PORT, "0.0.0.0", () => {
  console.log(`Server listening on :${PORT}`);
  launchChromium();
});
