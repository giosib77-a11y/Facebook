import { test, expect } from "@playwright/test";
import { blockExternal, mockApi, loginAs } from "./helpers.js";

test("session-ის გარეშე /panel/ ავტორიზაციის ფორმას აჩვენებს", async ({ page }) => {
  const net = await blockExternal(page);
  await page.goto("");

  await expect(page.getByPlaceholder("you@example.com").first()).toBeVisible();
  await expect(page.locator('input[type="password"]').first()).toBeVisible();
  await expect(page.locator("form").getByRole("button", { name: "შესვლა" })).toBeVisible();
  expect(net.blocked).toEqual([]);
});

test("session-ით Dashboard იხსნება (მაღაზიების გარეშე)", async ({ page }) => {
  const net = await blockExternal(page);
  await loginAs(page);
  await mockApi(page, {
    "GET /shops/me": [],
    "GET /admin/check": (route) => route.fulfill({ status: 403, json: { detail: "forbidden" } }),
  });
  await page.goto("");

  await expect(page.getByRole("button", { name: "+ ახალი მაღაზია" })).toBeVisible();
  await expect(page.getByRole("combobox", { name: /მაღაზია/ })).toBeVisible();
  await expect(page.getByText("tester@example.com")).toBeVisible();
  expect(net.blocked).toEqual([]);
});
