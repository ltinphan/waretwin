// E2E-only vite config: extends the repo config, retargets the /api proxy to
// the e2e backend on 8001 (host port 8000 is taken by an unrelated docker
// container and vite.config.ts hardcodes 127.0.0.1:8000 — we must not edit it).
import { defineConfig, mergeConfig } from "vite";
import base from "../vite.config";

export default mergeConfig(
  typeof base === "function" ? base({ command: "serve", mode: "test" }) : base,
  defineConfig({
    server: {
      port: 5173,
      strictPort: true,
      proxy: {
        "/api": "http://127.0.0.1:8001",
        "/ws": { target: "ws://127.0.0.1:8001", ws: true },
      },
    },
  })
);
