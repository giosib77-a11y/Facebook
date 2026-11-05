import { test, expect, vi, beforeAll, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";

vi.mock("../lib/api.js", () => ({
  api: vi.fn(),
  req: vi.fn(),
  readStoredToken: vi.fn(() => "tok"),
}));
vi.mock("@supabase/supabase-js", () => ({
  createClient: () => ({
    auth: {
      getUser: () => Promise.resolve({ data: { user: { email: "admin@example.com" } } }),
      signOut: () => Promise.resolve(),
    },
  }),
}));

let AdminPage;
let apiMod;

const DAY = 86400e3;
const shop = (over) => ({
  id: "s1", owner_id: "o1", name: "Shop One", owner_email: "a@x.ge", tier: "starter", tier_label: "Starter",
  monthly_customers: 1, customer_limit: 100, products: 0, orders: 0,
  fb_connected: false, bot_enabled: true, created_at: "2026-01-02T00:00:00Z",
  paid_until: new Date(Date.now() + 20 * DAY).toISOString(), ...over,
});
const OVERVIEW = {
  mrr: 0, total_shops: 1, total_sellers: 1, connected_shops: 0, total_products: 0,
  total_orders: 0, orders_30d: 0, revenue: 0,
};

let data;

beforeAll(async () => {
  window.APP_CONFIG = { API_BASE: "", SUPABASE_URL: "http://sb.test", SUPABASE_PUBLISHABLE_KEY: "k" };
  apiMod = await import("../lib/api.js");
  AdminPage = (await import("./AdminPage.jsx")).default;
});

beforeEach(() => {
  data = { "/admin/overview": OVERVIEW, "/admin/shops": [shop()] };
  apiMod.readStoredToken.mockReturnValue("tok");
  apiMod.api.mockImplementation(async (p) => (p in data ? data[p] : []));
  apiMod.req.mockResolvedValue({ owner_id: "o1", tier: "starter", paid_until: "2026-12-31T00:00:00Z" });
  window.confirm = vi.fn(() => true);
});

async function renderPage() {
  render(<AdminPage />);
  await screen.findByText("Shop One");
}

test("shows the paid-until column with the date, red when <=3 days or expired", async () => {
  data["/admin/shops"] = [
    shop({ id: "s1", name: "Shop One" }),
    shop({ id: "s2", name: "Shop Two", paid_until: new Date(Date.now() + 2 * DAY).toISOString() }),
    shop({ id: "s3", name: "Shop Three", paid_until: new Date(Date.now() - 5 * DAY).toISOString() }),
  ];
  await renderPage();
  expect(screen.getByRole("columnheader", { name: "ვადა" })).toBeInTheDocument();
  const fmt = (ms) => new Date(ms).toLocaleDateString("ka-GE");
  const far = screen.getByText(fmt(Date.now() + 20 * DAY));
  expect(far.style.color).toBe("");
  const soon = screen.getByText(fmt(Date.now() + 2 * DAY));
  expect(soon.style.color).toBe("var(--danger)");
  const gone = screen.getByText(fmt(Date.now() - 5 * DAY));
  expect(gone.style.color).toBe("var(--danger)");
});

test("+30 days calls extend with the right path/body and reloads", async () => {
  await renderPage();
  const before = apiMod.api.mock.calls.length;
  fireEvent.click(screen.getByRole("button", { name: "+30 დღე" }));
  await waitFor(() =>
    expect(apiMod.req).toHaveBeenCalledWith("POST", "/admin/subscriptions/o1/extend", { days: 30 })
  );
  expect(await screen.findByText(/ვადა გაგრძელდა:/)).toBeInTheDocument();
  await waitFor(() => expect(apiMod.api.mock.calls.length).toBeGreaterThan(before));
});

test("+30 days: double click with confirm sends exactly one request", async () => {
  await renderPage();
  const btn = screen.getByRole("button", { name: "+30 დღე" });
  fireEvent.click(btn);
  fireEvent.click(btn);
  await screen.findByText(/ვადა გაგრძელდა:/);
  expect(window.confirm).toHaveBeenCalledWith("გავაგრძელო ვადა 30 დღით?");
  expect(apiMod.req).toHaveBeenCalledTimes(1);
});

test("+30 days: declined confirm sends nothing", async () => {
  window.confirm = vi.fn(() => false);
  await renderPage();
  fireEvent.click(screen.getByRole("button", { name: "+30 დღე" }));
  expect(window.confirm).toHaveBeenCalledTimes(1);
  expect(apiMod.req).not.toHaveBeenCalled();
  expect(screen.getByRole("button", { name: "+30 დღე" })).toBeEnabled();
});

test("+30 days: button is disabled while in flight and re-enabled after", async () => {
  let resolve;
  apiMod.req.mockReturnValue(new Promise((r) => { resolve = r; }));
  await renderPage();
  fireEvent.click(screen.getByRole("button", { name: "+30 დღე" }));
  await waitFor(() => expect(screen.getByRole("button", { name: "+30 დღე" })).toBeDisabled());
  resolve({ owner_id: "o1", tier: "starter", paid_until: "2026-12-31T00:00:00Z" });
  await waitFor(() => expect(screen.getByRole("button", { name: "+30 დღე" })).toBeEnabled());
  expect(apiMod.req).toHaveBeenCalledTimes(1);
});

test("+30 days: button is re-enabled after an error", async () => {
  apiMod.req.mockRejectedValue(new Error("fail"));
  await renderPage();
  fireEvent.click(screen.getByRole("button", { name: "+30 დღე" }));
  await screen.findByText("fail");
  await waitFor(() => expect(screen.getByRole("button", { name: "+30 დღე" })).toBeEnabled());
});

test("extend error shows the backend detail in a toast", async () => {
  apiMod.req.mockRejectedValue(new Error("მფლობელი ვერ მოიძებნა"));
  await renderPage();
  fireEvent.click(screen.getByRole("button", { name: "+30 დღე" }));
  expect(await screen.findByText("მფლობელი ვერ მოიძებნა")).toBeInTheDocument();
});

test("+30 days is disabled on the free tier, and no date shows as a dash", async () => {
  data["/admin/shops"] = [shop({ tier: "free", tier_label: "Free", paid_until: null })];
  await renderPage();
  expect(screen.getByRole("button", { name: "+30 დღე" })).toBeDisabled();
});

test("llm.alert shows the spend banner in dollars and the monthly stat", async () => {
  data["/admin/overview"] = {
    ...OVERVIEW,
    llm: { today_usd: 0.85, month_usd: 12.34, daily_cap_usd: 1, kill_switch: false, alert: true },
  };
  await renderPage();
  expect(screen.getByText("⚠️ LLM ხარჯი: დღეს $0.85 / $1.00 (85%)")).toBeInTheDocument();
  expect(screen.getByText("LLM ხარჯი (თვე)")).toBeInTheDocument();
  expect(screen.getByText("$12.34")).toBeInTheDocument();
});

test("llm.alert with unknown today_usd shows dashes instead of NaN", async () => {
  data["/admin/overview"] = {
    ...OVERVIEW,
    llm: { today_usd: null, month_usd: null, daily_cap_usd: 1, kill_switch: false, alert: true },
  };
  await renderPage();
  expect(screen.getByText("⚠️ LLM ხარჯი: დღეს — / $1.00 (—)")).toBeInTheDocument();
});

test("llm.alert with zero cap shows a dash for the percent", async () => {
  data["/admin/overview"] = {
    ...OVERVIEW,
    llm: { today_usd: 0.5, month_usd: 1, daily_cap_usd: 0, kill_switch: false, alert: true },
  };
  await renderPage();
  expect(screen.getByText("⚠️ LLM ხარჯი: დღეს $0.50 / $0.00 (—)")).toBeInTheDocument();
});

test("kill_switch shows its banner", async () => {
  data["/admin/overview"] = {
    ...OVERVIEW,
    llm: { today_usd: 1, month_usd: 1, daily_cap_usd: 1, kill_switch: true, alert: true },
  };
  await renderPage();
  expect(screen.getByText("LLM_KILL_SWITCH ჩართულია — ბოტი ყველგან ოპერატორზეა")).toBeInTheDocument();
});

test("no overview.llm -> no banner and no LLM stat", async () => {
  await renderPage();
  expect(screen.queryByText(/LLM/)).not.toBeInTheDocument();
});
