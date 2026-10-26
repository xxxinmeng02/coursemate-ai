import { existsSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { defineConfig } from "@playwright/test";

const webRoot = path.dirname(fileURLToPath(import.meta.url));
const apiRoot = path.resolve(webRoot, "../../services/api");
const venvPython = path.join(apiRoot,
  process.platform === "win32" ? ".venv/Scripts/python.exe" : ".venv/bin/python");
const python = process.env.COURSEMATE_TEST_PYTHON
  ?? (existsSync(venvPython) ? venvPython : "python");

export default defineConfig({
  testDir: "./e2e",
  fullyParallel: false,
  workers: 1,
  retries: 0,
  timeout: 30_000,
  expect: { timeout: 10_000 },
  outputDir: "test-results",
  reporter: [
    ["list"],
    ["json", { outputFile: "test-results/results.json" }],
    ["html", { outputFolder: "playwright-report", open: "never" }],
  ],
  use: {
    baseURL: "http://localhost:3000",
    browserName: "chromium",
    headless: true,
    viewport: { width: 1280, height: 900 },
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
  },
  webServer: [
    {
      command: `"${python}" tests/retrieval_ui_server.py --port 8000`,
      cwd: apiRoot,
      url: "http://localhost:8000/health",
      reuseExistingServer: false,
      timeout: 30_000,
    },
    {
      command: "npm run start -- --hostname 127.0.0.1 --port 3000",
      cwd: webRoot,
      url: "http://localhost:3000",
      reuseExistingServer: false,
      timeout: 30_000,
    },
  ],
});
