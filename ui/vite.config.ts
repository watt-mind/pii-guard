/// <reference types="vitest/config" />
import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// The UI never talks to model providers. It only reaches the pii-guard API,
// through this proxy, so the browser stays same-origin.
const API_TARGET = process.env.PII_GUARD_API_URL ?? "http://127.0.0.1:8787";

const proxy = {
  "/v1": { target: API_TARGET, changeOrigin: true },
  "/healthz": { target: API_TARGET, changeOrigin: true },
};

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: { port: 5173, strictPort: true, proxy },
  preview: { port: 4173, proxy },
  test: {
    environment: "jsdom",
    setupFiles: ["./src/test/setup.ts"],
    css: false,
  },
});
