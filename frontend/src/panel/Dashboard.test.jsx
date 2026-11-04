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

test("StatCard არ ითვლის მხოლოდ-შეჩერებულს; ძველი API (needs_attention გარეშე) ითვლება", () => {
  setData([paused, needs, { psid: "old", last_message: "x" }]);
  render(<Dashboard />);
  const label = screen.getByText("ყურადღება სჭირდება", { selector: ".sl" });
  expect(label.previousElementSibling).toHaveTextContent("2");
});
