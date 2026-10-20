import net from "node:net";
import { reactRouter } from "@react-router/dev/vite";
import tailwindcss from "@tailwindcss/vite";
import { defineConfig, type Plugin } from "vite";

// Node resolves "localhost" to ::1, so the dev server listens on IPv6 only. Browsers that try 127.0.0.1 for some
// requests (Safari does) then get refused and pages half-load. This forwards 127.0.0.1 to the same server, on
// loopback only: nothing else on the network can reach it.
function ipv4Loopback(): Plugin {
  return {
    name: "ipv4-loopback",
    apply: "serve",
    configureServer(server) {
      const http = server.httpServer;
      http?.once("listening", () => {
        const address = http.address();
        if (!address || typeof address === "string" || address.address !== "::1") return;
        const forward = net.createServer((socket) => {
          const upstream = net.connect(address.port, "::1");
          socket.pipe(upstream).pipe(socket);
          socket.on("error", () => upstream.destroy());
          upstream.on("error", () => socket.destroy());
        });
        // Something else already has 127.0.0.1 on this port: leave it alone.
        forward.on("error", () => forward.close());
        forward.listen(address.port, "127.0.0.1");
        http.once("close", () => forward.close());
      });
    },
  };
}

export default defineConfig({
  plugins: [tailwindcss(), reactRouter(), ipv4Loopback()],
  resolve: {
    tsconfigPaths: true,
  },
  server: {
    // Cloudflare quick tunnels (cloudflared tunnel --url http://localhost:5173) get a random *.trycloudflare.com
    // name; the leading dot allows any of them, and nothing else.
    allowedHosts: [".trycloudflare.com"],
    // Forward API calls to the FastAPI dev server (uvicorn on port 8000).
    proxy: {
      "/api": "http://127.0.0.1:8000",
    },
  },
});
