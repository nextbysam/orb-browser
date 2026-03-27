const http = require("http");
const net = require("net");

const BROWSERS_PATH = process.env.PLAYWRIGHT_BROWSERS_PATH || "/opt/browsers";
const PORT = parseInt(process.env.PORT || "8000");
const CDP_PORT = parseInt(process.env.CDP_PORT || "9222");
const CHROME_INTERNAL_PORT = 9223; // Chrome binds to 127.0.0.1 only
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

// Launch Chromium on internal port (127.0.0.1 only)
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
    `--remote-debugging-port=${CHROME_INTERNAL_PORT}`,
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

// TCP proxy: 0.0.0.0:CDP_PORT → 127.0.0.1:CHROME_INTERNAL_PORT
// This makes Chrome's CDP accessible from outside the container
function startTcpProxy() {
  const proxy = net.createServer((client) => {
    const target = net.createConnection({ host: "127.0.0.1", port: CHROME_INTERNAL_PORT });
    client.pipe(target);
    target.pipe(client);
    client.on("error", () => target.destroy());
    target.on("error", () => client.destroy());
  });
  proxy.listen(CDP_PORT, "0.0.0.0", () => {
    console.log(`TCP proxy: 0.0.0.0:${CDP_PORT} → 127.0.0.1:${CHROME_INTERNAL_PORT}`);
  });
  proxy.on("error", (e) => console.error("TCP proxy error:", e.message));
}

// CDP URL helper
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
      res.end(JSON.stringify({ status: "ok", browserReady: !!wsEndpoint, error: initError }));

    } else if (url.pathname === "/cdp") {
      const cdpUrl = getCdpUrl();
      if (!cdpUrl) {
        res.statusCode = 503;
        res.end(JSON.stringify({ error: "browser not ready or hostname not set" }));
        return;
      }
      res.end(JSON.stringify({ cdpUrl }));

    } else if (url.pathname === "/json/version") {
      const cdpRes = await fetch(`http://127.0.0.1:${CHROME_INTERNAL_PORT}/json/version`);
      const data = await cdpRes.json();
      if (data.webSocketDebuggerUrl && PUBLIC_HOST) {
        const browserId = data.webSocketDebuggerUrl.split("/").pop();
        data.webSocketDebuggerUrl = `wss://${PUBLIC_HOST}/_port/${CDP_PORT}/devtools/browser/${browserId}`;
      }
      res.end(JSON.stringify(data));

    } else if (url.pathname === "/json" || url.pathname === "/json/list") {
      const cdpRes = await fetch(`http://127.0.0.1:${CHROME_INTERNAL_PORT}/json`);
      res.end(JSON.stringify(await cdpRes.json()));

    } else if (url.pathname === "/status") {
      res.end(JSON.stringify({
        status: "ok", browserReady: !!wsEndpoint, cdpUrl: getCdpUrl(),
        pid: browserProcess?.pid || null, publicHost: PUBLIC_HOST, error: initError,
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

server.listen(PORT, "0.0.0.0", () => {
  console.log(`Server on :${PORT}`);
  launchChromium();
  // Start TCP proxy after a brief delay for Chrome to start
  setTimeout(startTcpProxy, 3000);
});
