import { test, expect } from "@playwright/test";
import { blockExternal, mockApi, loginAs } from "./helpers.js";

const PAGES = [{ id: "1", name: "Page A" }, { id: "2", name: "Page B" }];
const chooseUrl = (pages = PAGES) =>
  `?fb=choose&selection=SEL&pages=${encodeURIComponent(JSON.stringify(pages))}`;

async function setup(page, extra = {}) {
  const net = await blockExternal(page);
  await loginAs(page);
  await mockApi(page, {
    "GET /shops/me": [{ id: "shop-1", name: "ტესტ მაღაზია", bot_enabled: true }],
    "GET /admin/check": (route) => route.fulfill({ status: 403, json: { detail: "forbidden" } }),
    "GET /shops/shop-1/usage": {
      tier: "free", tier_label: "უფასო", monthly_customers: 1, customer_limit: 50,
      products: 0, product_limit: 10, prices: {},
    },
    "GET /shops/shop-1/analytics": {},
    "GET /shops/shop-1/attention": { items: [], count: 0, attention_count: 0 },
    "GET /products": [],
    "GET /orders": [],
    ...extra,
  });
  return net;
}

test("choose: გვერდის არჩევა → select request → წარმატების toast, სია ქრება", async ({ page }) => {
  const bodies = [];
  const net = await setup(page, {
    "POST /facebook/connect/select": (route, request) => {
      bodies.push(request.postDataJSON());
      return route.fulfill({ json: { fb: "connected", page: "Page B" } });
    },
  });
  await page.goto(chooseUrl());

  await expect(page.getByText("🔗 რომელი გვერდი დავაკავშირო?")).toBeVisible();
  await page.getByRole("button", { name: "Page B" }).click();
  await expect(page.locator("#toast")).toHaveText("Facebook გვერდი დაკავშირდა: Page B");
  expect(bodies).toEqual([{ selection: "SEL", page_id: "2" }]);
  await expect(page.getByText("🔗 რომელი გვერდი დავაკავშირო?")).toHaveCount(0);
  expect(net.blocked).toEqual([]);
});

test("choose: 400 (ვადა გაუვიდა) → backend-ის ტექსტი toast-ში", async ({ page }) => {
  const msg = "არჩევანს ვადა გაუვიდა (10 წუთი) — დააჭირე „დაკავშირებას“ ხელახლა.";
  const net = await setup(page, {
    "POST /facebook/connect/select": (route) => route.fulfill({ status: 400, json: { detail: msg } }),
  });
  await page.goto(chooseUrl());

  await page.getByRole("button", { name: "Page A" }).click();
  await expect(page.locator("#toast")).toHaveText(msg);
  await expect(page.getByText("🔗 რომელი გვერდი დავაკავშირო?")).toHaveCount(0);
  expect(net.blocked).toEqual([]);
});

test("choose: „გაუქმება“ → select არ იძახება", async ({ page }) => {
  const calls = [];
  const net = await setup(page, {
    "POST /facebook/connect/select": (route, request) => {
      calls.push(request.url());
      return route.fulfill({ json: { fb: "connected", page: "x" } });
    },
  });
  await page.goto(chooseUrl());

  await page.getByRole("button", { name: "გაუქმება" }).click();
  await expect(page.getByText("🔗 რომელი გვერდი დავაკავშირო?")).toHaveCount(0);
  expect(calls).toEqual([]);
  expect(net.blocked).toEqual([]);
});

test("choose: ცარიელი pages → შეცდომის toast, სია არ ჩანს", async ({ page }) => {
  const net = await setup(page);
  await page.goto(chooseUrl([]));

  await expect(page.locator("#toast")).toHaveText("დაკავშირება ვერ მოხერხდა. სცადეთ თავიდან.");
  await expect(page.getByText("🔗 რომელი გვერდი დავაკავშირო?")).toHaveCount(0);
  expect(net.blocked).toEqual([]);
});
