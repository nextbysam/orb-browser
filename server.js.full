const http = require("http");
const net = require("net");
const { execSync } = require("child_process");
const { spawn } = require("child_process");

const BROWSERS_PATH = process.env.PLAYWRIGHT_BROWSERS_PATH || "/opt/browsers";
const PORT = parseInt(process.env.PORT || "3000");
const CDP_PORT = 9222;
const CHROME_INTERNAL_PORT = 9223;
let PUBLIC_HOST = process.env.PUBLIC_HOST || null;

let wsEndpoint = null;
let initError = null;
let chromeProcess = null;

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

const server = http.createServer(async (req, res) => {
  const url = new URL(req.url, "http://localhost");
  res.setHeader("Content-Type", "application/json");

  if (!PUBLIC_HOST) {
    for (const h of [req.headers["x-forwarded-host"], req.headers.host]) {
      if (h && h.includes("orbcloud.dev")) { PUBLIC_HOST = h.split(":")[0]; break; }
    }
  }

  try {
    if (url.pathname === "/health") {
      res.end(JSON.stringify({ status: "ok", browserReady: !!wsEndpoint, error: initError }));

    } else if (url.pathname === "/cdp") {
      if (!wsEndpoint || !PUBLIC_HOST) {
        res.statusCode = 503;
        res.end(JSON.stringify({ error: "browser not ready or host not set" }));
        return;
      }
      const browserId = wsEndpoint.split("/").pop();
      res.end(JSON.stringify({
        cdpUrl: `wss://${PUBLIC_HOST}/_port/${CDP_PORT}/devtools/browser/${browserId}`,
      }));

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
        status: "ok", browserReady: !!wsEndpoint, publicHost: PUBLIC_HOST,
        pid: chromeProcess?.pid || null, error: initError,
      }));

    } else if (url.pathname === "/set-host") {
      const h = url.searchParams.get("host");
      if (h) {
        PUBLIC_HOST = h;
        const browserId = wsEndpoint ? wsEndpoint.split("/").pop() : null;
        const cdpUrl = browserId ? `wss://${h}/_port/${CDP_PORT}/devtools/browser/${browserId}` : null;
        res.end(JSON.stringify({ ok: true, host: h, cdpUrl }));
      } else {
        res.statusCode = 400;
        res.end(JSON.stringify({ error: "?host= required" }));
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

// Start HTTP server first (Orb health check)
server.listen(PORT, "0.0.0.0", () => {
  console.log(`Server on :${PORT}`);

  // Launch Chrome on internal port
  const chromePath = findChromium();
  if (!chromePath) {
    initError = "Chromium not found";
    console.error(initError);
    return;
  }

  console.log("Launching:", chromePath);
  chromeProcess = spawn(chromePath, [
    "--no-sandbox", "--disable-gpu", "--disable-dev-shm-usage", "--headless",
    `--remote-debugging-port=${CHROME_INTERNAL_PORT}`,
    "--no-first-run", "--disable-background-networking", "--disable-default-apps",
    "--disable-extensions", "--disable-sync", "--mute-audio", "--hide-scrollbars",
    "--password-store=basic",
  ], { stdio: ["ignore", "pipe", "pipe"] });

  chromeProcess.stderr.on("data", (data) => {
    const match = data.toString().match(/DevTools listening on (ws:\/\/.+)/);
    if (match) {
      wsEndpoint = match[1];
      console.log("Chrome ready:", wsEndpoint);

      // Now start TCP proxy: 0.0.0.0:CDP_PORT → 127.0.0.1:CHROME_INTERNAL_PORT
      const proxy = net.createServer((client) => {
        const target = net.createConnection({ host: "127.0.0.1", port: CHROME_INTERNAL_PORT });
        client.pipe(target);
        target.pipe(client);
        client.on("error", () => target.destroy());
        target.on("error", () => client.destroy());
      });
      proxy.listen(CDP_PORT, "0.0.0.0", () => {
        console.log(`CDP proxy: 0.0.0.0:${CDP_PORT} → 127.0.0.1:${CHROME_INTERNAL_PORT}`);
      });
      proxy.on("error", (e) => {
        console.log("CDP proxy error (non-fatal):", e.message);
      });
    }
  });

  chromeProcess.on("exit", (code) => {
    console.error("Chrome exited:", code);
    wsEndpoint = null;
  });
});
