import { test, expect } from "@playwright/test";
import { blockExternal, mockApi, loginAs } from "./helpers.js";

test("ვადის გაფრთხილება, email badge და ბოტის ჯანმრთელობა ერთდროულად ჩანს", async ({ page }) => {
  const net = await blockExternal(page);
  await loginAs(page);
  await mockApi(page, {
    "GET /shops/me": [{
      id: "shop-1", name: "ტესტ მაღაზია", bot_enabled: true, facebook_page_id: "page-1",
      bot_status: "token_expired", bot_status_at: new Date().toISOString(),
    }],
    "GET /admin/check": (route) => route.fulfill({ status: 403, json: { detail: "forbidden" } }),
    "GET /shops/shop-1/usage": {
      tier: "starter", tier_label: "Starter", monthly_customers: 1, customer_limit: 100,
      products: 0, product_limit: 50, prices: { starter: 29 },
      paid_until: new Date(Date.now() + 2 * 86400e3).toISOString(),
      expires_soon: true, expired: false, email_notifications: false,
    },
    "GET /shops/shop-1/analytics": {},
    "GET /products": [],
    "GET /orders": [],
    "GET /shops/shop-1/attention": { items: [], count: 0, attention_count: 0 },
  });
  await page.goto("");

  await expect(page.getByText(/პაკეტის ვადა იწურება .+-ს/)).toBeVisible();
  await expect(page.getByText("📭 email შეტყობინებები გამორთულია")).toBeVisible();
  await expect(page.getByText("⚠️ ბოტი ვერ პასუხობს — ხელახლა დააკავშირე Facebook გვერდი")).toBeVisible();
  expect(net.blocked).toEqual([]);
});
