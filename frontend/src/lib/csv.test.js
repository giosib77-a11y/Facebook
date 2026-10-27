import { test, expect } from "vitest";
import { toCSV, fmtDate } from "./csv";

const BOM = "﻿";

test("toCSV: იწყება BOM-ით", () => {
  expect(toCSV(["a"], []).startsWith(BOM)).toBe(true);
});

test("toCSV: სტრიქონები \\r\\n-ით, უჯრები მძიმით", () => {
  expect(toCSV(["a", "b"], [["1", "2"], ["3", "4"]])).toBe(BOM + "a,b\r\n1,2\r\n3,4");
});

test("toCSV: მძიმე, ბრჭყალი და ახალი ხაზი ბრჭყალებში, ბრჭყალი ორმაგდება", () => {
  const out = toCSV(["h"], [["a,b"], ['say "hi"'], ["x\ny"]]);
  expect(out).toBe(BOM + 'h\r\n"a,b"\r\n"say ""hi"""\r\n"x\ny"');
});

test("toCSV: ფორმულის ინექცია — წინ ემატება აპოსტროფი", () => {
  const out = toCSV(["h"], [["=SUM(1)"], ["+x"], ["@x"], ["-x"]]);
  expect(out).toBe(BOM + "h\r\n'=SUM(1)\r\n'+x\r\n'@x\r\n'-x");
});

test("toCSV: რიცხვები უცვლელია", () => {
  const out = toCSV(["h"], [["-5"], ["3.5"], [-5], ["-2,5"]]);
  // "-2,5" მძიმის გამო ბრჭყალებში მოექცევა, მაგრამ აპოსტროფი არ ემატება
  expect(out).toBe(BOM + 'h\r\n-5\r\n3.5\r\n-5\r\n"-2,5"');
});

test("toCSV: null/undefined → ცარიელი უჯრა", () => {
  expect(toCSV(["a", "b", "c"], [[null, undefined, "x"]])).toBe(BOM + "a,b,c\r\n,,x");
});

test("fmtDate: ცარიელი/null → —", () => {
  expect(fmtDate("")).toBe("—");
  expect(fmtDate(null)).toBe("—");
  expect(fmtDate(undefined)).toBe("—");
});

test("fmtDate: ვალიდური ISO თარიღი → არა-ცარიელი, არა —", () => {
  const out = fmtDate("2026-03-15T10:00:00Z");
  expect(typeof out).toBe("string");
  expect(out).not.toBe("—");
  expect(out.length).toBeGreaterThan(0);
});
