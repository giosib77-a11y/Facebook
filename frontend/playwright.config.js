import { defineConfig, devices } from "@playwright/test";

// ბრაუზერის (e2e) ტესტები: `npm run test:e2e`. backend არ ეშვება — API-ები page.route-ით იმოკება (e2e/helpers.js).
// ⚠️ `vite preview` უკვე აშენებულ `dist/`-ს ემსახურება → ჯერ `npm run build`.
export default defineConfig({
  testDir: "./e2e",
  testMatch: "**/*.spec.js", // Vitest-ის `src/**/*.test.*`-ს არ ერევა
  outputDir: "test-results",
  reporter: "list",
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
  use: {
    // base: "/panel/" (vite.config.js); ბოლოს "/" აუცილებელია, რომ page.goto("") სწორად გადაიყვანოს
    baseURL: "http://localhost:4173/panel/",
    trace: "retain-on-failure",
  },
  webServer: {
    command: "npm run preview -- --port 4173 --strictPort",
    url: "http://localhost:4173/panel/",
    reuseExistingServer: !process.env.CI,
    timeout: 60_000,
  },
});
