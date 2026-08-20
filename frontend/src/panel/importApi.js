/* Excel/CSV იმპორტი — ორბიჯიანი ნაკადი (preview → mapping → ატვირთვა).
 * გადმოტანილია app.js-იდან; ქსელური ნაწილი გამოცალკევებულია UI-სგან.
 */
import { getToken } from "./supabase.js";

const cfg = window.APP_CONFIG;

export const IMPORT_FIELDS = [
  { key: "name", label: "სახელი", required: true },
  { key: "price", label: "ფასი" },
  { key: "quantity", label: "მარაგი" },
  { key: "description", label: "აღწერა" },
  { key: "sku", label: "SKU / კოდი" },
];

/** detail შეიძლება იყოს string ან object — ორივე შემთხვევაში წასაკითხი ტექსტი */
function detailText(data, status) {
  if (data && data.detail) {
    return typeof data.detail === "string" ? data.detail : JSON.stringify(data.detail);
  }
  return "შეცდომა (HTTP " + status + ")";
}

async function post(path, fd) {
  const token = await getToken();
  if (!token) throw new Error("სესია არ არის — თავიდან შედი");
  const res = await fetch(cfg.API_BASE + path, {
    method: "POST",
    headers: { Authorization: "Bearer " + token, "ngrok-skip-browser-warning": "1" },
    body: fd,
  });
  const data = await res.json().catch(() => null);
  return { res, data };
}

/** ბიჯი 1 — ფაილის სვეტების ნახვა. აბრუნებს {headers, detected, preview, total_rows} */
export async function previewImport(shopId, file) {
  const fd = new FormData();
  fd.append("shop_id", shopId);
  fd.append("file", file);
  const { res, data } = await post("/products/import/preview", fd);
  if (!res.ok) throw new Error(detailText(data, res.status));
  return data;
}

/**
 * ბიჯი 3 — არჩეული mapping-ით ატვირთვა.
 * 422 + detail.errors → აბრუნებს {rowErrors} (მწკრივების სია), რომ UI-მ ჩამონათვალი აჩვენოს.
 */
export async function confirmImport(shopId, file, mapping) {
  const fd = new FormData();
  fd.append("shop_id", shopId);
  fd.append("file", file);
  fd.append("mapping", JSON.stringify(mapping));
  const { res, data } = await post("/products/import", fd);

  if (res.ok) {
    return { ok: true, message: (data && data.message) || "დაემატა " + (data && data.imported) + " პროდუქტი" };
  }
  if (res.status === 422 && data && data.detail && data.detail.errors) {
    return { ok: false, message: data.detail.message, rowErrors: data.detail.errors };
  }
  throw new Error(detailText(data, res.status));
}

/** mapping-ის აწყობა: არჩეული ველები + დამატებითი სვეტები აღწერისთვის */
export function buildMapping(fieldCols, extraCols) {
  const mapping = {};
  Object.entries(fieldCols).forEach(([k, v]) => {
    if (v !== "" && v != null) mapping[k] = parseInt(v, 10);
  });
  // გამოვრიცხოთ ის სვეტები, რაც უკვე ველად შეირჩა
  const used = Object.values(mapping);
  const extra = extraCols.filter((i) => !used.includes(i));
  if (extra.length) mapping.extra = extra;
  return mapping;
}
