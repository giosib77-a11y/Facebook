// გაშვება: cd frontend && npm test
import { test, expect } from "vitest";
import { changedProductFields } from "./productDiff.js";

const product = {
  id: "p1", name: "პური", price: 2.5, quantity: 5, sku: "BR-1",
  description: "ახალი", is_active: true, image_url: "http://x/a.png",
};
const same = {
  name: "პური", price: 2.5, quantity: 5, sku: "BR-1",
  description: "ახალი", is_active: true, image_url: "http://x/a.png",
};

test("მხოლოდ ფასის შეცვლა quantity-ს არ შეიცავს", () => {
  const d = changedProductFields(product, { ...same, price: 3 });
  expect(d).toEqual({ price: 3 });
  expect("quantity" in d).toBe(false);
});

test("ხელით შეცვლილი მარაგი იგზავნება", () => {
  expect(changedProductFields(product, { ...same, quantity: 9 })).toEqual({ quantity: 9 });
});

test("ცვლილება არ არის → ცარიელი ობიექტი", () => {
  expect(changedProductFields(product, same)).toEqual({});
});

test("null/ცარიელი ველები ნორმალიზდება (ცვლილებად არ ითვლება)", () => {
  const bare = { id: "p2", name: "A", price: "1.00", quantity: 0, sku: null, description: null, is_active: false, image_url: null };
  const payload = { name: "A", price: 1, quantity: 0, sku: null, description: null, is_active: false, image_url: null };
  expect(changedProductFields(bare, payload)).toEqual({});
});

test("ველის გასუფთავება → null იგზავნება", () => {
  expect(changedProductFields(product, { ...same, sku: null, description: null })).toEqual({
    sku: null, description: null,
  });
});

test("ფოტოს წაშლა და ახალი ფოტო", () => {
  expect(changedProductFields(product, { ...same, image_url: null })).toEqual({ image_url: null });
  expect(changedProductFields(product, { ...same, image_url: "http://x/b.png" })).toEqual({
    image_url: "http://x/b.png",
  });
});

test("is_active და სახელი", () => {
  expect(changedProductFields(product, { ...same, is_active: false, name: "პური 2" })).toEqual({
    is_active: false, name: "პური 2",
  });
});
