// გაშვება: node --test frontend/src/panel/productDiff.test.js
import test from "node:test";
import assert from "node:assert/strict";
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
  assert.deepEqual(d, { price: 3 });
  assert.equal("quantity" in d, false);
});

test("ხელით შეცვლილი მარაგი იგზავნება", () => {
  assert.deepEqual(changedProductFields(product, { ...same, quantity: 9 }), { quantity: 9 });
});

test("ცვლილება არ არის → ცარიელი ობიექტი", () => {
  assert.deepEqual(changedProductFields(product, same), {});
});

test("null/ცარიელი ველები ნორმალიზდება (ცვლილებად არ ითვლება)", () => {
  const bare = { id: "p2", name: "A", price: "1.00", quantity: 0, sku: null, description: null, is_active: false, image_url: null };
  const payload = { name: "A", price: 1, quantity: 0, sku: null, description: null, is_active: false, image_url: null };
  assert.deepEqual(changedProductFields(bare, payload), {});
});

test("ველის გასუფთავება → null იგზავნება", () => {
  assert.deepEqual(changedProductFields(product, { ...same, sku: null, description: null }), {
    sku: null, description: null,
  });
});

test("ფოტოს წაშლა და ახალი ფოტო", () => {
  assert.deepEqual(changedProductFields(product, { ...same, image_url: null }), { image_url: null });
  assert.deepEqual(changedProductFields(product, { ...same, image_url: "http://x/b.png" }), {
    image_url: "http://x/b.png",
  });
});

test("is_active და სახელი", () => {
  assert.deepEqual(changedProductFields(product, { ...same, is_active: false, name: "პური 2" }), {
    is_active: false, name: "პური 2",
  });
});
