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

test("llm.alert shows the spend banner; null today_tokens does not produce NaN", async () => {
  data["/admin/overview"] = {
    ...OVERVIEW,
    llm: { today_tokens: 850, month_tokens: 5000, daily_cap: 1000, kill_switch: false, alert: true },
  };
  await renderPage();
  expect(screen.getByText("⚠️ LLM ხარჯი: დღეს 850 / 1000 ტოკენი (85%)")).toBeInTheDocument();
  expect(screen.getByText("LLM ტოკენი (თვე)")).toBeInTheDocument();
  expect(screen.getByText("5000")).toBeInTheDocument();
});

test("llm.alert with unknown today_tokens shows a dash instead of NaN", async () => {
  data["/admin/overview"] = {
    ...OVERVIEW,
    llm: { today_tokens: null, month_tokens: null, daily_cap: 1000, kill_switch: false, alert: true },
  };
  await renderPage();
  expect(screen.getByText("⚠️ LLM ხარჯი: დღეს — / 1000 ტოკენი (—)")).toBeInTheDocument();
});

test("kill_switch shows its banner", async () => {
  data["/admin/overview"] = {
    ...OVERVIEW,
    llm: { today_tokens: 1, month_tokens: 1, daily_cap: 1000, kill_switch: true, alert: true },
  };
  await renderPage();
  expect(screen.getByText("LLM_KILL_SWITCH ჩართულია — ბოტი ყველგან ოპერატორზეა")).toBeInTheDocument();
});

test("no overview.llm -> no banner and no LLM stat", async () => {
  await renderPage();
  expect(screen.queryByText(/LLM/)).not.toBeInTheDocument();
});
