import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
export default defineConfig({
  // vitest: keep Playwright specs (e2e/**) out of the unit-test glob
  test: { exclude: ['e2e/**', '**/node_modules/**', '**/dist/**'] },
  plugins: [react()], server: { port: 5173, proxy: {
  '/api': 'http://127.0.0.1:8000',
  '/ws': { target: 'ws://127.0.0.1:8000', ws: true },
} } });
