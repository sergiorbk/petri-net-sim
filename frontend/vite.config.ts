import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";
import path from "node:path";

export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "./src"),
    },
  },
  server: {
    port: 6203,
    proxy: {
      // Override with VITE_PROXY_TARGET to point at a backend running
      // elsewhere (e.g. "http://backend:8000" inside Docker Compose dev).
      "/api": {
        target: process.env.VITE_PROXY_TARGET || "http://localhost:6201",
        changeOrigin: true,
      },
    },
  },
});
