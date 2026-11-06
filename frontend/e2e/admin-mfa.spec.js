import { test, expect } from "@playwright/test";
import { blockExternal, mockApi, loginAs } from "./helpers.js";

const MFA_TEXT = "ადმინ პანელისთვის საჭიროა ორფაქტორიანი შესვლა (MFA)";
const USER_ID = "00000000-0000-0000-0000-000000000001";
const AAL2 = "Bearer e2e-aal2-token";

const OVERVIEW = {
  mrr: 29, total_shops: 1, total_sellers: 1, connected_shops: 0, total_products: 0,
  total_orders: 0, orders_30d: 0, revenue: 0,
};

/** aal2 token -> მონაცემები; ნებისმიერი სხვა (aal1) -> 403 MFA */
const adminData = (body) => (route, request) =>
  request.headers()["authorization"] === AAL2
    ? route.fulfill({ json: body })
    : route.fulfill({ status: 403, json: { detail: MFA_TEXT } });

const ADMIN_API = (sellers = []) => ({
  "GET /admin/overview": adminData(OVERVIEW),
  "GET /admin/shops": adminData([]),
  "GET /admin/sellers": adminData(sellers),
  "GET /admin/orders": adminData([]),
  "GET /admin/upgrade-requests": adminData([]),
  "GET /admin/growth": adminData([]),
});

function userWith(factors) {
  return { id: USER_ID, email: "admin@example.com", aud: "authenticated", role: "authenticated", factors };
}

/** Supabase MFA path-ები; აბრუნებს verify-ის body-ების სიას */
async function mockMfa(page, { factors, verifyStatus = 200 }) {
  const verifyBodies = [];
  const now = Math.floor(Date.now() / 1000);
  await mockApi(page, {
    "GET /auth/v1/user": userWith(factors),
    "POST /auth/v1/factors": {
      id: "f1",
      type: "totp",
      totp: {
        qr_code: "data:image/svg+xml;utf-8,<svg xmlns='http://www.w3.org/2000/svg'/>",
        secret: "JBSWY3DPEHPK3PXP",
        uri: "otpauth://totp/x",
      },
    },
    "POST /auth/v1/factors/f1/challenge": { id: "c1", type: "totp", expires_at: now + 300 },
    "POST /auth/v1/factors/f1/verify": (route, request) => {
      verifyBodies.push(request.postDataJSON());
      if (verifyStatus !== 200) {
        return route.fulfill({
          status: verifyStatus,
          json: { code: "mfa_verification_failed", msg: "Invalid TOTP code entered" },
        });
      }
      return route.fulfill({
        json: {
          access_token: "e2e-aal2-token",
          refresh_token: "r2",
          token_type: "bearer",
          expires_in: 3600,
          expires_at: now + 3600,
          user: userWith(factors),
        },
      });
    },
  });
  return verifyBodies;
}

test("MFA: პირველი ჩართვა — QR და გასაღები, კოდის შემდეგ მონაცემები", async ({ page }) => {
  const net = await blockExternal(page);
  await loginAs(page, { email: "admin@example.com" });
  const verifyBodies = await mockMfa(page, { factors: [] });
  await mockApi(page, ADMIN_API());
  await page.goto("admin.html");

  await expect(page.getByRole("img", { name: "QR კოდი" })).toBeVisible();
  await expect(page.getByText("JBSWY3DPEHPK3PXP")).toBeVisible();
  await expect(page.getByText("წვდომა აკრძალულია")).toHaveCount(0);
  await page.getByLabel("6-ნიშნა კოდი").fill("123456");
  await page.getByRole("button", { name: "დადასტურება" }).click();

  await expect(page.getByText("📊 საერთო მაჩვენებლები")).toBeVisible();
  expect(verifyBodies).toHaveLength(1);
  expect(verifyBodies[0].code).toBe("123456");
  expect(net.blocked).toEqual([]);
});

test("MFA: არსებული ფაქტორი — QR არ ჩანს, კოდი ხსნის მონაცემებს", async ({ page }) => {
  const net = await blockExternal(page);
  await loginAs(page, { email: "admin@example.com" });
  await mockMfa(page, { factors: [{ id: "f1", factor_type: "totp", status: "verified" }] });
  await mockApi(page, ADMIN_API());
  await page.goto("admin.html");

  await expect(page.getByRole("heading", { name: /შეიყვანე ავთენტიფიკატორის კოდი/ })).toBeVisible();
  await expect(page.getByRole("img", { name: "QR კოდი" })).toHaveCount(0);
  await page.getByLabel("6-ნიშნა კოდი").fill("654321");
  await page.getByRole("button", { name: "დადასტურება" }).click();

  await expect(page.getByText("📊 საერთო მაჩვენებლები")).toBeVisible();
  await expect(page.getByText("🔐 ორფაქტორიანი შესვლა ჩართულია ✓")).toBeVisible();
  expect(net.blocked).toEqual([]);
});

test("MFA: არასწორი კოდი (422) — შეცდომის ტექსტი, მონაცემები არ იხსნება", async ({ page }) => {
  const net = await blockExternal(page);
  await loginAs(page, { email: "admin@example.com" });
  await mockMfa(page, {
    factors: [{ id: "f1", factor_type: "totp", status: "verified" }],
    verifyStatus: 422,
  });
  await mockApi(page, ADMIN_API());
  await page.goto("admin.html");

  await page.getByLabel("6-ნიშნა კოდი").fill("000000");
  await page.getByRole("button", { name: "დადასტურება" }).click();

  await expect(page.getByText("კოდი არასწორია ან ვადა გაუვიდა — სცადე ხელახლა.")).toBeVisible();
  await expect(page.getByText("📊 საერთო მაჩვენებლები")).toHaveCount(0);
  expect(net.blocked).toEqual([]);
});

test("პანელი: MFA-ს 403-ზე „ადმინი“ ღილაკი ჩანს", async ({ page }) => {
  const net = await blockExternal(page);
  await loginAs(page);
  await mockApi(page, {
    "GET /shops/me": [],
    "GET /admin/check": (route) => route.fulfill({ status: 403, json: { detail: MFA_TEXT } }),
  });
  await page.goto("");

  await expect(page.getByRole("button", { name: "+ ახალი მაღაზია" })).toBeVisible();
  await expect(page.getByText(/ადმინი/).first()).toBeVisible();
  expect(net.blocked).toEqual([]);
});

test("recovery: confirm -> ელფოსტით გაგზავნის შეტყობინება, prompt არ ჩნდება", async ({ page }) => {
  const net = await blockExternal(page);
  await loginAs(page, { email: "admin@example.com" });
  await mockMfa(page, { factors: [{ id: "f1", factor_type: "totp", status: "verified" }] });
  let recoveryBody = null;
  await mockApi(page, {
    ...ADMIN_API([{ email: "seller@example.com", confirmed: true, shops: 1, last_sign_in: null, created_at: null }]),
    "POST /admin/recovery": (route, request) => {
      recoveryBody = request.postDataJSON();
      return route.fulfill({ json: { ok: true } });
    },
  });
  const dialogs = [];
  page.on("dialog", async (d) => {
    dialogs.push(d.type());
    if (d.type() === "confirm") await d.accept();
    else await d.dismiss();
  });
  await page.goto("admin.html");

  await page.getByLabel("6-ნიშნა კოდი").fill("123456");
  await page.getByRole("button", { name: "დადასტურება" }).click();
  await page.getByRole("button", { name: /გამყიდვლები/ }).click();
  await page.getByRole("button", { name: /პაროლი/ }).click();

  await expect(page.getByText("აღდგენის ბმული გაეგზავნა გამყიდველს ელფოსტაზე")).toBeVisible();
  expect(recoveryBody).toEqual({ email: "seller@example.com" });
  expect(dialogs).toEqual(["confirm"]);
  expect(net.blocked).toEqual([]);
});
