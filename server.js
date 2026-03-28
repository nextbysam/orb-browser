const http = require("http");
const PORT = parseInt(process.env.PORT || "8000");
http.createServer((req, res) => {
  res.setHeader("Content-Type", "application/json");
  res.end(JSON.stringify({ status: "ok", port: PORT }));
}).listen(PORT, "0.0.0.0", () => console.log("OK on " + PORT));
