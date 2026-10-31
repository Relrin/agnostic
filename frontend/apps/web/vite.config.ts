import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// The API runs on :8000 in development (`agnostic dev`); in production it serves this build on the same origin.
const API = process.env.AGNOSTIC_API_URL ?? "http://127.0.0.1:8000";

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    port: 5173,
    strictPort: true,
    proxy: {
      "/api": { target: API, changeOrigin: false },
      "/healthz": API,
      "/readyz": API,
    },
  },
  build: { sourcemap: true, target: "es2023" },
});
