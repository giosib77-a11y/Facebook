import { test, expect, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

const toast = vi.fn();
const loadAttention = vi.fn();
let shopData;

vi.mock("./ShopData.jsx", () => ({ useShopData: () => shopData }));
vi.mock("./api.js", () => ({ api: vi.fn() }));
vi.mock("./ui.jsx", () => ({ useToast: () => toast }));
vi.mock("./ProductsTab.jsx", () => ({ default: () => null }));
vi.mock("./OrdersTab.jsx", () => ({ default: () => null }));
vi.mock("./BotTab.jsx", () => ({ default: () => null }));

import { api } from "./api.js";
import Dashboard, { AttentionCard } from "./Dashboard.jsx";

const paused = { psid: "a b/1", last_message: "გამარჯობა", at: "2026-11-05T10:00:00Z", needs_attention: false, paused_until: "2026-11-05T22:00:00Z" };
const needs = { psid: "p2", last_message: "ოპერატორი", at: "2026-11-05T10:00:00Z", needs_attention: true, paused_until: null };

function setData(attention) {
  shopData = {
    shopId: "s1", attention, loadAttention,
    usage: null, orders: [], products: [], shops: [], currentShop: null,
    selectShop: vi.fn(), loadShops: vi.fn(), loadUsage: vi.fn(),
  };
}

beforeEach(() => {
  vi.clearAllMocks();
  window.confirm = vi.fn(() => true);
  api.mockResolvedValue({ ok: true });
});

test("შეჩერებული item: badge და „ბოტის ჩართვა“ ჩანს", () => {
  setData([paused]);
  render(<AttentionCard />);
  expect(screen.getByText(/ბოტი შეჩერებულია · .+-მდე/)).toBeInTheDocument();
  expect(screen.getByRole("button", { name: /ბოტის ჩართვა/ })).toBeInTheDocument();
});

test("ბოტის ჩართვა → resume POST, toast, loadAttention", async () => {
  setData([paused]);
  render(<AttentionCard />);
  await userEvent.click(screen.getByRole("button", { name: /ბოტის ჩართვა/ }));
  expect(api).toHaveBeenCalledWith("/shops/s1/attention/a%20b%2F1/resume", "POST");
  expect(toast).toHaveBeenCalledWith("ბოტი ჩაირთო ამ საუბარში");
  expect(loadAttention).toHaveBeenCalled();
});

test("წაშლა confirm=true → DELETE სწორი path-ით", async () => {
  setData([needs]);
  render(<AttentionCard />);
  await userEvent.click(screen.getByRole("button", { name: /კლიენტის მონაცემების წაშლა/ }));
  expect(window.confirm).toHaveBeenCalledWith("წავშალო ამ კლიენტის საუბარი და მრიცხველი? შეუქცევადია.");
  expect(api).toHaveBeenCalledWith("/shops/s1/customers/p2", "DELETE");
  expect(toast).toHaveBeenCalledWith("კლიენტის მონაცემები წაიშალა");
  expect(loadAttention).toHaveBeenCalled();
});

test("წაშლა confirm=false → api არ იძახება", async () => {
  window.confirm = vi.fn(() => false);
  setData([needs]);
  render(<AttentionCard />);
  await userEvent.click(screen.getByRole("button", { name: /კლიენტის მონაცემების წაშლა/ }));
  expect(api).not.toHaveBeenCalled();
});

test("შეცდომა → toast(err.message, true)", async () => {
  api.mockRejectedValue(new Error("სერვისი მიუწვდომელია"));
  setData([paused]);
  render(<AttentionCard />);
  await userEvent.click(screen.getByRole("button", { name: /ბოტის ჩართვა/ }));
  expect(toast).toHaveBeenCalledWith("სერვისი მიუწვდომელია", true);
  expect(loadAttention).not.toHaveBeenCalled();
});

test("შეუჩერებელ item-ზე „ბოტის ჩართვა“ არ არის, „მოგვარდა“ არის", () => {
  setData([needs]);
  render(<AttentionCard />);
  expect(screen.queryByRole("button", { name: /ბოტის ჩართვა/ })).toBeNull();
  expect(screen.getByRole("button", { name: /მოგვარდა/ })).toBeInTheDocument();
});

test("მხოლოდ-შეჩერებულ item-ზე „მოგვარდა“ არ ჩანს", () => {
  setData([paused]);
  render(<AttentionCard />);
  expect(screen.queryByRole("button", { name: /მოგვარდა/ })).toBeNull();
});

const baseUsage = {
  tier: "starter", tier_label: "Starter", monthly_customers: 1, customer_limit: 100,
  products: 1, product_limit: 50, prices: { starter: 29 }, pending_request: null,
  payment_iban: "GE00TEST", payment_contact: "pay@example.com",
};

function setUsage(usage, shopExtra = {}) {
  setData([]);
  shopData.usage = usage ? { ...baseUsage, ...usage } : null;
  shopData.currentShop = { id: "s1", name: "მაღაზია", facebook_page_id: "p1", bot_enabled: true, ...shopExtra };
  shopData.shops = [shopData.currentShop];
}

test("expires_soon → გაფრთხილება, „განახლება“ same-tier request-ს აგზავნის, რეკვიზიტები ჩანს", async () => {
  setUsage({ expires_soon: true, paid_until: "2026-11-07T12:00:00Z" });
  render(<Dashboard />);
  expect(screen.getByText(/პაკეტის ვადა იწურება .+-ს — გადაიხადე და გამოგზავნე ქვითარი/)).toBeInTheDocument();
  expect(screen.getByText("GE00TEST")).toBeInTheDocument();
  expect(screen.getByText(/მოქმედებს: .+-მდე/)).toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", { name: "განახლება" }));
  expect(api).toHaveBeenCalledWith("/shops/s1/upgrade-request", "POST", { tier: "starter" });
});

test("expired → შეცდომის ბანერი; expires_soon-ის ბანერი არა", () => {
  setUsage({ expired: true, expires_soon: false, paid_until: "2026-11-01T12:00:00Z" });
  render(<Dashboard />);
  expect(screen.getByText("⚠️ პაკეტის ვადა ამოიწურა — მალე უფასო პაკეტზე გადახვალ")).toBeInTheDocument();
  expect(screen.queryByText(/ვადა იწურება/)).toBeNull();
});

test("ვადის ველების გარეშე (ძველი API / ვადა კარგია) → ბანერები და „მოქმედებს“ არა", () => {
  setUsage({ expires_soon: false, expired: false });
  render(<Dashboard />);
  expect(screen.queryByText(/ვადა/)).toBeNull();
  expect(screen.queryByText(/მოქმედებს:/)).toBeNull();
});

test("email_notifications false → badge; true / undefined → არა", () => {
  setUsage({ email_notifications: false });
  const { unmount } = render(<Dashboard />);
  const b = screen.getByText("📭 email შეტყობინებები გამორთულია");
  expect(b).toHaveAttribute("title", "ახალ შეკვეთასა და ოპერატორის მოთხოვნაზე email ჯერ არ იგზავნება");
  unmount();
  setUsage({ email_notifications: true });
  const r2 = render(<Dashboard />);
  expect(screen.queryByText(/email შეტყობინებები გამორთულია/)).toBeNull();
  r2.unmount();
  setUsage({});
  render(<Dashboard />);
  expect(screen.queryByText(/email შეტყობინებები გამორთულია/)).toBeNull();
});

test.each([
  ["token_error", "⚠️ ბოტი ვერ პასუხობს — ხელახლა დააკავშირე Facebook გვერდი"],
  ["token_expired", "⚠️ ბოტი ვერ პასუხობს — ხელახლა დააკავშირე Facebook გვერდი"],
  ["send_failed", "⚠️ ბოლო პასუხი ვერ გაიგზავნა"],
  ["budget_exhausted", "⚠️ ბოტის თვიური ლიმიტი ამოიწურა — ახალი კლიენტები ოპერატორთან გადადიან"],
])("bot_status %s → გაფრთხილება", (status, text) => {
  setUsage(null, { bot_status: status });
  render(<Dashboard />);
  expect(screen.getByText(text)).toBeInTheDocument();
});

test.each([[null], ["ok"], [undefined]])("bot_status %s → ჩვეულებრივი ტექსტი", (status) => {
  setUsage(null, { bot_status: status });
  render(<Dashboard />);
  expect(screen.getByText("ბოტი აქტიურია")).toBeInTheDocument();
  expect(screen.getByText("პასუხობს კლიენტებს ქართულად, 24/7")).toBeInTheDocument();
  expect(screen.queryByText(/^⚠️/)).toBeNull();
});

test("StatCard არ ითვლის მხოლოდ-შეჩერებულს; ძველი API (needs_attention გარეშე) ითვლება", () => {
  setData([paused, needs, { psid: "old", last_message: "x" }]);
  render(<Dashboard />);
  const label = screen.getByText("ყურადღება სჭირდება", { selector: ".sl" });
  expect(label.previousElementSibling).toHaveTextContent("2");
});
