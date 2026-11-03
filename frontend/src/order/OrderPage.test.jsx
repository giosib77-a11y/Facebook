import { test, expect, vi, beforeAll, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";

// A-020: one idempotency_key per filled-in form — a retry after a lost response reuses it.
let OrderPage;
const SHOP = "22222222-2222-2222-2222-222222222222";
const MENU = {
  shop: { id: SHOP, name: "Test Shop", currency: "GEL" },
  products: [{ id: "p1", name: "Shirt", price: 5, quantity: 10, description: "" }],
};

beforeAll(async () => {
  // OrderPage reads APP_CONFIG and ?shop= at module load
  window.APP_CONFIG = { API_BASE: "" };
  window.history.replaceState({}, "", "/?shop=" + SHOP);
  window.scrollTo = () => {};
  OrderPage = (await import("./OrderPage")).default;
});

let orderResponses;
let orderBodies;

beforeEach(() => {
  orderBodies = [];
  orderResponses = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url, opts) => {
      if (String(url).includes("/public-menu")) {
        return { ok: true, status: 200, json: async () => MENU };
      }
      orderBodies.push(JSON.parse(opts.body));
      const next = orderResponses.shift();
      if (next instanceof Error) throw next;
      return next;
    })
  );
});

async function fillAndSubmit() {
  render(<OrderPage />);
  await screen.findByText("Shirt");
  fireEvent.change(screen.getByLabelText("რაოდენობა"), { target: { value: "2" } });
  fireEvent.change(screen.getByPlaceholderText("სახელი გვარი"), { target: { value: "Buyer" } });
  fireEvent.change(screen.getByPlaceholderText("5XX XX XX XX"), { target: { value: "555123456" } });
  fireEvent.change(screen.getByPlaceholderText("ქალაქი, ქუჩა, ბინა"), { target: { value: "Tbilisi" } });
  const submit = () => fireEvent.submit(document.getElementById("order-form"));
  submit();
  return submit;
}

const ok = { ok: true, status: 201, json: async () => ({ ok: true, order_id: "o1", total: 10 }) };
const badRequest = { ok: false, status: 400, json: async () => ({ detail: "მარაგი არ არის" }) };

test("network failure → retry sends the same idempotency_key", async () => {
  orderResponses.push(new TypeError("Failed to fetch"), ok);
  const submit = await fillAndSubmit();
  await waitFor(() => expect(orderBodies).toHaveLength(1));
  await waitFor(() => expect(screen.getByRole("button", { name: "შეკვეთის გაგზავნა" })).toBeEnabled());
  submit();
  await waitFor(() => expect(orderBodies).toHaveLength(2));
  const [first, second] = orderBodies;
  expect(first.idempotency_key).toMatch(/^[0-9a-f-]{36}$/);
  expect(second.idempotency_key).toBe(first.idempotency_key);
});

test("4xx (no order created) → next attempt gets a new key", async () => {
  orderResponses.push(badRequest, ok);
  const submit = await fillAndSubmit();
  await waitFor(() => expect(orderBodies).toHaveLength(1));
  await waitFor(() => expect(screen.getByRole("button", { name: "შეკვეთის გაგზავნა" })).toBeEnabled());
  submit();
  await waitFor(() => expect(orderBodies).toHaveLength(2));
  expect(orderBodies[0].idempotency_key).toMatch(/^[0-9a-f-]{36}$/);
  expect(orderBodies[1].idempotency_key).not.toBe(orderBodies[0].idempotency_key);
});
