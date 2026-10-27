import { test, expect } from "vitest";
import { STATUS, tierLabel } from "./constants";

test("tierLabel: standard → სტანდარტი", () => {
  expect(tierLabel("standard")).toBe("სტანდარტი");
});

test("tierLabel: free → უფასო", () => {
  expect(tierLabel("free")).toBe("უფასო");
});

test("tierLabel: უცნობი მნიშვნელობა უცვლელად ბრუნდება", () => {
  expect(tierLabel("enterprise")).toBe("enterprise");
});

test("STATUS.new → ახალი", () => {
  expect(STATUS.new).toBe("ახალი");
});
