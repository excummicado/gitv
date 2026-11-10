import { existsSync } from "node:fs";
import { defineConfig } from "@playwright/test";

// Smoke tests of the built site (npm run smoke builds it first) against a local API on a small database
// (api/tests/smoke_server.py). The proxy stands in for nginx: /api to the API, the rest to the site.
const API_PORT = 8181;
const SITE_PORT = 5181;
const PORT = 5180;
const python = process.env.SMOKE_PYTHON ?? (existsSync("../api/venv/bin/python") ? "venv/bin/python" : "python");

export default defineConfig({
  testDir: "e2e",
  retries: process.env.CI ? 1 : 0,
  reporter: process.env.CI ? "github" : "list",
  use: { baseURL: `http://127.0.0.1:${PORT}`, locale: "ru-RU" },
  projects: [
    { name: "desktop", use: { viewport: { width: 1280, height: 800 } } },
    { name: "phone", use: { viewport: { width: 375, height: 812 } } },
  ],
  webServer: [
    {
      command: `${python} -m tests.smoke_server ${API_PORT}`,
      cwd: "../api",
      url: `http://127.0.0.1:${API_PORT}/api/v1/health`,
      reuseExistingServer: !process.env.CI,
    },
    {
      command: "react-router-serve ./build/server/index.js",
      env: { PORT: String(SITE_PORT), HOST: "127.0.0.1", API_URL: `http://127.0.0.1:${API_PORT}` },
      url: `http://127.0.0.1:${SITE_PORT}`,
      reuseExistingServer: !process.env.CI,
    },
    {
      command: "node e2e/proxy.mjs",
      env: { PORT: String(PORT), API_ORIGIN: `http://127.0.0.1:${API_PORT}`, SITE_ORIGIN: `http://127.0.0.1:${SITE_PORT}` },
      url: `http://127.0.0.1:${PORT}`,
      reuseExistingServer: !process.env.CI,
    },
  ],
});
