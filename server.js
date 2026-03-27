const http = require("http");
const { execSync } = require("child_process");

const BROWSERS_PATH = process.env.PLAYWRIGHT_BROWSERS_PATH || "/opt/browsers";
const PORT = parseInt(process.env.PORT || "3000");
const CDP_PORT = parseInt(process.env.CDP_PORT || "9222");
let PUBLIC_HOST = process.env.PUBLIC_HOST || null; // auto-detected from first request

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

  // Auto-detect public hostname from Orb proxy headers
  if (!PUBLIC_HOST) {
    const fwdHost = req.headers["x-forwarded-host"];
    const origHost = req.headers["x-original-host"];
    const referer = req.headers.referer;
    // Check all possible header sources for the .orbcloud.dev hostname
    for (const h of [fwdHost, origHost, req.headers.host]) {
      if (h && h.includes("orbcloud.dev")) { PUBLIC_HOST = h.split(":")[0]; break; }
    }
  }

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
      const host = PUBLIC_HOST || req.headers["x-forwarded-host"] || req.headers.host || `localhost:${PORT}`;
      const proto = (PUBLIC_HOST || req.headers["x-forwarded-proto"] === "https" || host.includes("orbcloud.dev")) ? "wss" : "ws";
      res.end(JSON.stringify({
        wsEndpoint: `${proto}://${host}/devtools/browser/${browserId}`,
        httpEndpoint: `${proto === "wss" ? "https" : "http"}://${host}`,
      }));

    } else if (url.pathname === "/json/version") {
      // Proxy CDP /json/version, rewrite WebSocket URL to external
      const cdpRes = await fetch(`http://127.0.0.1:${CDP_PORT}/json/version`);
      const data = await cdpRes.json();
      const host = PUBLIC_HOST || req.headers["x-forwarded-host"] || req.headers.host || `localhost:${PORT}`;
      const proto = (PUBLIC_HOST || req.headers["x-forwarded-proto"] === "https" || host.includes("orbcloud.dev")) ? "wss" : "ws";
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

    } else if (url.pathname === "/set-host") {
      // Allow SDK to set the public hostname after deploy
      const h = url.searchParams.get("host");
      if (h) { PUBLIC_HOST = h; res.end(JSON.stringify({ ok: true, host: h })); }
      else { res.statusCode = 400; res.end(JSON.stringify({ error: "?host= required" })); }

    } else {
      res.statusCode = 404;
      res.end(JSON.stringify({
        error: "not found",
        endpoints: ["/health", "/cdp", "/json/version", "/json", "/status", "/set-host"],
      }));
    }
  } catch (e) {
    res.statusCode = 500;
    res.end(JSON.stringify({ error: e.message }));
  }
});

// WebSocket proxy: pipe CDP connections from :PORT to :CDP_PORT using raw TCP
const net = require("net");

server.on("upgrade", (req, clientSocket, head) => {
  const cdpPath = req.url || "/";
  const target = net.createConnection({ host: "127.0.0.1", port: CDP_PORT }, () => {
    // Reconstruct the HTTP upgrade request to send to Chrome
    const upgradeReq = [
      `GET ${cdpPath} HTTP/1.1`,
      `Host: 127.0.0.1:${CDP_PORT}`,
      "Upgrade: websocket",
      "Connection: Upgrade",
      `Sec-WebSocket-Key: ${req.headers["sec-websocket-key"]}`,
      `Sec-WebSocket-Version: ${req.headers["sec-websocket-version"]}`,
      "",
      "",
    ].join("\r\n");

    target.write(upgradeReq);
    if (head && head.length) target.write(head);

    // Once we get the response header from Chrome, pipe everything
    let headerDone = false;
    let buffer = Buffer.alloc(0);

    target.on("data", (chunk) => {
      if (headerDone) {
        clientSocket.write(chunk);
        return;
      }
      buffer = Buffer.concat([buffer, chunk]);
      const headerEnd = buffer.indexOf("\r\n\r\n");
      if (headerEnd !== -1) {
        headerDone = true;
        // Forward the 101 response to the client
        clientSocket.write(buffer.slice(0, headerEnd + 4));
        // Forward any remaining data
        if (headerEnd + 4 < buffer.length) {
          clientSocket.write(buffer.slice(headerEnd + 4));
        }
        // Now pipe bidirectionally
        clientSocket.pipe(target);
        // target already piping via on('data')
      }
    });
  });

  target.on("error", () => clientSocket.destroy());
  clientSocket.on("error", () => target.destroy());
  target.on("close", () => clientSocket.destroy());
  clientSocket.on("close", () => target.destroy());
});

// Start server FIRST (so health check passes), then launch Chrome
server.listen(PORT, "0.0.0.0", () => {
  console.log(`Server listening on :${PORT}`);
  launchChromium();
});
