const http = require("node:http");
const fs = require("node:fs");
const path = require("node:path");
const preview = path.join(__dirname, "..", "preview.html");
http.createServer((request, response) => {
  if (request.url !== "/" && request.url !== "/preview.html") {
    response.writeHead(404); response.end("Not found"); return;
  }
  response.writeHead(200, { "Content-Type": "text/html; charset=utf-8", "Cache-Control": "no-store" });
  response.end(fs.readFileSync(preview));
}).listen(4319, "127.0.0.1", () => console.log("Preview: http://127.0.0.1:4319"));
