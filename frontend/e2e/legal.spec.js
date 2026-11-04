import { test, expect } from "@playwright/test";
import { blockExternal } from "./helpers.js";

test("delete-data.html: §1 (კლიენტი) არ ახსენებს Apps and Websites-ს, §2 (გამყიდველი) ახსენებს", async ({ page }) => {
  const net = await blockExternal(page);
  await page.goto("delete-data.html");

  const customer = page.locator("h2", { hasText: "1. კლიენტისთვის" });
  const seller = page.locator("h2", { hasText: "2. გამყიდველისთვის" });
  await expect(customer).toBeVisible();

  // სექციის ტექსტი = h2-დან შემდეგ h2-მდე
  const sectionText = (h) => h.evaluate((el) => {
    let t = "";
    for (let n = el.nextElementSibling; n && n.tagName !== "H2"; n = n.nextElementSibling) t += n.textContent + "\n";
    return t;
  });
  const s1 = await sectionText(customer);
  const s2 = await sectionText(seller);
  expect(s1).not.toContain("Apps and Websites");
  expect(s1).toContain("24 საათში");
  expect(s2).toContain("Apps and Websites");
  expect(s2).toContain("Facebook ID");
  expect(net.blocked).toEqual([]);
});

test("privacy.html: processor-ების სიაში SMTP provider და Telegram ჩანს", async ({ page }) => {
  const net = await blockExternal(page);
  await page.goto("privacy.html");

  await expect(page.getByText("SMTP provider").first()).toBeVisible();
  await expect(page.getByText("Telegram", { exact: false }).first()).toBeVisible();
  await expect(page.getByText("გამყიდველის ხელით გაგზავნილი პასუხიც იმავე ვადით ინახება")).toBeVisible();
  // §9 (საერთაშორისო გადაცემა) ახალ processor-ებსაც ასახელებს
  const s9 = await page.locator("h2", { hasText: "9. საერთაშორისო გადაცემა" }).evaluate((el) => el.nextElementSibling.textContent);
  expect(s9).toContain("SMTP provider");
  expect(s9).toContain("Telegram");
  expect(net.blocked).toEqual([]);
});
