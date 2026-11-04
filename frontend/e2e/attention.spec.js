import { test, expect } from "@playwright/test";
import { blockExternal, mockApi, loginAs } from "./helpers.js";

test("შეჩერებული საუბარი: „ბოტის ჩართვა“ resume request-ს აგზავნის", async ({ page }) => {
  const net = await blockExternal(page);
  await loginAs(page);
  const resumed = [];
  const paused = {
    psid: "psid-1", last_message: "გამარჯობა", at: new Date().toISOString(),
    needs_attention: false, paused_until: new Date(Date.now() + 3600e3).toISOString(),
  };
  await mockApi(page, {
    "GET /shops/me": [{ id: "shop-1", name: "ტესტ მაღაზია", bot_enabled: true }],
    "GET /admin/check": (route) => route.fulfill({ status: 403, json: { detail: "forbidden" } }),
    "GET /shops/shop-1/usage": {
      tier: "free", tier_label: "უფასო", monthly_customers: 1, customer_limit: 50,
      products: 0, product_limit: 10, prices: {},
    },
    "GET /shops/shop-1/analytics": {},
    "GET /products": [],
    "GET /orders": [],
    "GET /shops/shop-1/attention": { items: [paused], count: 1, attention_count: 0 },
    "POST /shops/shop-1/attention/psid-1/resume": (route, request) => {
      resumed.push(request.url());
      return route.fulfill({ json: { ok: true, paused_until: null } });
    },
  });
  await page.goto("");

  await expect(page.getByText(/ბოტი შეჩერებულია · /)).toBeVisible();
  await page.getByRole("button", { name: /ბოტის ჩართვა/ }).click();
  await expect.poll(() => resumed.length).toBe(1);
  expect(net.blocked).toEqual([]);
});
