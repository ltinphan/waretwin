// E2E config: desktop (1280x800) + mobile (375x667) projects; dual webServer
// (vite dev on 5173 using e2e/vite.e2e.config.ts, backend on 8001 — host port
// 8000 is occupied by an unrelated docker container, so the e2e vite config
// proxies /api to 8001 instead of the 8000 hardcoded in vite.config.ts).
import { defineConfig, devices } from "@playwright/test";
import { existsSync } from "node:fs";

const E2E_DIR = import.meta.dirname;        // frontend/e2e (specs + artifacts)
const FRONTEND_DIR = E2E_DIR + "/..";      // frontend (vite dev cwd)
const REPO_DIR = E2E_DIR + "/../..";       // repo root (backend cwd)

export default defineConfig({
  testDir: E2E_DIR,
  timeout: 60_000,
  expect: { timeout: 15_000 },
  outputDir: E2E_DIR + "/artifacts/test-results",
  use: {
    baseURL: "http://localhost:5173",
    trace: "retain-on-failure",
    screenshot: "off",
    actionTimeout: 15_000,
    navigationTimeout: 15_000,
  },
  webServer: [
    {
      command: "npm run dev -- --config e2e/vite.e2e.config.ts --port 5173",
      cwd: FRONTEND_DIR,
      url: "http://localhost:5173/",
      timeout: 120_000,
      reuseExistingServer: true,
    },
    {
      command:
        // fresh scratch DBs per e2e run — exact-count assertions need a pristine state
        "rm -f /tmp/e2e_l.db /tmp/e2e_t.db && " +
        "cd backend && TWIN_LAYOUT_DB=/tmp/e2e_l.db TWIN_DB=/tmp/e2e_t.db " +
        (existsSync(REPO_DIR + "/backend/.venv311/bin/python") ? ".venv311/bin/python" : "python3") +
        " -m uvicorn app.main:app --port 8001",
      cwd: REPO_DIR,
      url: "http://127.0.0.1:8001/api/health",
      timeout: 120_000,
      reuseExistingServer: true,
    },
  ],
  projects: [
    { name: "desktop", use: { ...devices["Desktop Chrome"], viewport: { width: 1280, height: 800 } } },
    { name: "mobile", use: { ...devices["Desktop Chrome"], viewport: { width: 375, height: 667 }, isMobile: false, hasTouch: true },
    // T1-T6 isolation is API-level (no viewport dependence) and NOT idempotent across
    // parallel workers (T4 forks once per worker) — desktop-only.
    testIgnore: /isolation\.spec\.ts/ },
  ],
});
