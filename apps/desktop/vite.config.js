import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import { resolve } from "node:path";

const DEV_AGENT_PORT = 5175;
const DEV_AGENT_TOKEN = process.env.VITE_AGENT_TOKEN || process.env.AGENT_TOKEN || "";
const BASE = process.env.VITE_BASE || (process.env.NODE_ENV === 'production' ? './' : '/');

export default defineConfig({
  // Force SPA fallback so client routes do not 404
  appType: "spa",
  base: BASE,
  plugins: [react()],
  build: {
    outDir: 'dist',
    emptyOutDir: true,
  },
  server: {
    host: "127.0.0.1",
    port: 5173,
    strictPort: true,
    proxy: {
      "/api": {
        target: `http://127.0.0.1:${DEV_AGENT_PORT}`,
        changeOrigin: true,
        secure: false,
        rewrite: (p) => p.replace(/^\/api/, ""),
        configure: (proxy) => {
          proxy.on("proxyReq", (proxyReq, req) => {
            if (DEV_AGENT_TOKEN) {
              try {
                proxyReq.setHeader("Authorization", `Bearer ${DEV_AGENT_TOKEN}`);
                proxyReq.setHeader("X-Agent-Token", DEV_AGENT_TOKEN);
              } catch {}
            }
          });
        },
      },
    },
  },
  // Silence the “Could not auto-determine entry point” warning
  optimizeDeps: {
    entries: ["index.html"],
    esbuildOptions: { loader: { ".js": "jsx" } },
  },
});
