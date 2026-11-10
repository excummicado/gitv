// The smoke tests' front door, standing in for nginx on the server: /api goes to the test API, every other address
// to the built site (react-router-serve). Run by playwright.config.ts; ports come from the environment.
import http from "node:http";

const port = Number(process.env.PORT);
const api = new URL(process.env.API_ORIGIN);
const site = new URL(process.env.SITE_ORIGIN);

http
  .createServer((req, res) => {
    const target = req.url.startsWith("/api/") ? api : site;
    const upstream = http.request(
      { host: target.hostname, port: target.port, method: req.method, path: req.url, headers: req.headers },
      (answer) => {
        res.writeHead(answer.statusCode ?? 502, answer.headers);
        answer.pipe(res);
      },
    );
    upstream.on("error", () => {
      res.writeHead(502).end();
    });
    req.pipe(upstream);
  })
  .listen(port, "127.0.0.1");
