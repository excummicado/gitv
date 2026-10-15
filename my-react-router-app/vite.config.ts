import { reactRouter } from "@react-router/dev/vite";
import tailwindcss from "@tailwindcss/vite";
import { defineConfig } from "vite";

export default defineConfig({
  plugins: [tailwindcss(), reactRouter()],
  resolve: {
    tsconfigPaths: true,
  },
  server: {
    // Forward API calls to the FastAPI dev server (uvicorn on port 8000).
    proxy: {
      "/api": "http://127.0.0.1:8000",
    },
  },
});
