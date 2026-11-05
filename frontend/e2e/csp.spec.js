import { test, expect } from "@playwright/test";
import { blockExternal, mockApi, SUPABASE_ORIGIN } from "./helpers.js";

// ყველა გვერდი production-ის CSP-ით (A-044 / N-12). backend არ ეშვება: დოკუმენტს vite preview აბრუნებს,
// header-ს ტესტი თავად ამატებს, API-ები იმოკება. violation = `securitypolicyviolation` event.
// sync with backend main.build_csp
const SUPABASE_HOST = new URL(SUPABASE_ORIGIN).host;
const CSP = [
  "default-src 'self'",
  "script-src 'self'",
  "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com",
  "font-src 'self' https://fonts.gstatic.com",
  "img-src 'self' data: blob: https:",
  `connect-src 'self' ${SUPABASE_ORIGIN} wss://${SUPABASE_HOST}`,
  "frame-ancestors 'self'",
  "base-uri 'self'",
  "form-action 'self'",
  "object-src 'none'",
].join("; ");

const SHOP_ID = "11111111-1111-4111-8111-111111111111";

// [path, ხილული ელემენტი, API mock-ები]
const PAGES = [
  ["", "#root input"],
  ["admin.html", "#root input"],
  [`order.html?shop=${SHOP_ID}`, "#shop-name", { "GET /public-menu": { shop: { name: "ტესტ მაღაზია", currency: "GEL" }, products: [] } }],
  ["reset.html", "#root h1"],
  ["landing.html", "h1"],
  ["privacy.html", "main"],
  ["terms.html", "main"],
  ["contact.html", "main"],
  [
    "delete-data.html?code=x",
    "#confVerified",
    { "GET /facebook/data-deletion/status": { valid: true, status: "completed", requested_at: null } },
  ],
];

/** დოკუმენტს CSP header-ს უმატებს (Google Fonts-ის abort violation არ არის) და violation-ებს window.__csp-ში წერს */
async function withCsp(page) {
  const net = await blockExternal(page);
  await page.route(
    (url) => url.origin === "http://localhost:4173",
    async (route, request) => {
      if (request.resourceType() !== "document") return route.fallback();
      const response = await route.fetch();
      await route.fulfill({ response, headers: { ...response.headers(), "content-security-policy": CSP } });
    }
  );
  await page.addInitScript(() => {
    window.__csp = [];
    document.addEventListener("securitypolicyviolation", (e) => {
      window.__csp.push(`${e.violatedDirective} ${e.blockedURI}`);
    });
  });
  return net;
}

for (const [path, visible, mocks] of PAGES) {
  test(`CSP: ${path || "/panel/"} — violation-ის გარეშე იხსნება`, async ({ page }) => {
    await withCsp(page);
    if (mocks) await mockApi(page, mocks);
    await page.goto(path);

    await expect(page.locator(visible).first()).toBeVisible();
    expect(await page.evaluate(() => window.__csp)).toEqual([]);
  });
}

test("CSP: negative control — inline script violation-ს ჩაწერს", async ({ page }) => {
  await withCsp(page);
  await page.goto("privacy.html");
  await expect(page.locator("main")).toBeVisible();

  await page.evaluate(() => {
    const s = document.createElement("script");
    s.textContent = "window.__ran = true";
    document.head.appendChild(s);
  });
  const violations = await page.evaluate(() => window.__csp);
  expect(violations.length).toBeGreaterThan(0);
  expect(violations[0]).toContain("script-src");
  expect(await page.evaluate(() => window.__ran)).toBeUndefined();
});
