import { test, expect } from "@playwright/test";
import { blockExternal, mockApi, loginAs } from "./helpers.js";

test("ადმინ პანელი: LLM ხარჯის ბანერი და „ვადა“ სვეტი ჩანს", async ({ page }) => {
  const net = await blockExternal(page);
  await loginAs(page, { email: "admin@example.com" });
  await mockApi(page, {
    "GET /admin/overview": {
      mrr: 29, total_shops: 1, total_sellers: 1, connected_shops: 0, total_products: 0,
      total_orders: 0, orders_30d: 0, revenue: 0,
      llm: { today_usd: 0.9, month_usd: 12.34, daily_cap_usd: 1, kill_switch: false, alert: true },
    },
    "GET /admin/shops": [{
      id: "s1", owner_id: "o1", name: "ტესტ მაღაზია", owner_email: "a@example.com", tier: "starter",
      tier_label: "Starter", monthly_customers: 1, customer_limit: 100, products: 0, orders: 0,
      fb_connected: false, bot_enabled: true, created_at: "2026-01-02T00:00:00Z",
      paid_until: new Date(Date.now() + 2 * 86400e3).toISOString(),
    }],
    "GET /admin/sellers": [],
    "GET /admin/orders": [],
    "GET /admin/upgrade-requests": [],
    "GET /admin/growth": [],
  });
  await page.goto("admin.html");

  await expect(page.getByText("⚠️ LLM ხარჯი: დღეს $0.90 / $1.00 (90%)")).toBeVisible();
  await expect(page.getByRole("columnheader", { name: "ვადა" })).toBeVisible();
  await expect(page.getByRole("button", { name: "+30 დღე" })).toBeEnabled();
  expect(net.blocked).toEqual([]);
});
