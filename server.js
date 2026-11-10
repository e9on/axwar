// AX 인재전쟁 앱 서버. 지금은 배포 테스트용 첫 화면만 내보낸다.
const http = require("http");

const PORT = Number(process.env.PORT) || 3000;

const page = `<!doctype html>
<html lang="ko">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>AX 인재전쟁</title>
</head>
<body>
<h1>AX 인재전쟁 배포 테스트</h1>
</body>
</html>`;

const server = http.createServer((req, res) => {
  if (req.method !== "GET" && req.method !== "HEAD") {
    res.writeHead(405, { Allow: "GET, HEAD" });
    return res.end();
  }
  if (req.url === "/healthz") {
    res.writeHead(200, { "Content-Type": "text/plain; charset=utf-8" });
    return res.end("ok");
  }
  res.writeHead(200, { "Content-Type": "text/html; charset=utf-8" });
  res.end(req.method === "HEAD" ? undefined : page);
});

server.listen(PORT, "0.0.0.0", () => {
  console.log(`listening on ${PORT}`);
});
