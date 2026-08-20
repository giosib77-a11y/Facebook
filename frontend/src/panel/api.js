/* FastAPI backend-ის გამოძახება Bearer token-ით — გადმოტანილია app.js-იდან ხაზ-ხაზ.
 * ⚠️ 401-ზე token-ის ავტო-განახლება + ერთხელ retry. არ „გააუმჯობესო".
 * (ადმინს ცალკე, სხვა retry-ლოგიკა აქვს — განზრახ არ გავაერთიანე.)
 */
import { getToken, refreshToken } from "./supabase.js";

const cfg = window.APP_CONFIG;

export async function api(path, method, body, _retried) {
  const token = await getToken();
  if (!token) throw new Error("სესია არ არის — გთხოვ თავიდან შედი");

  const opts = {
    method: method || "GET",
    headers: { Authorization: "Bearer " + token, "ngrok-skip-browser-warning": "1" },
  };
  if (body !== undefined) {
    opts.headers["Content-Type"] = "application/json";
    opts.body = JSON.stringify(body);
  }

  const res = await fetch(cfg.API_BASE + path, opts);

  // ვადაგასული token → ერთხელ ვცდით განახლებას და თავიდან
  if (res.status === 401 && !_retried) {
    const fresh = await refreshToken();
    if (fresh) return api(path, method, body, true);
    throw new Error("სესია ამოიწურა — გთხოვ თავიდან შედი");
  }

  if (res.status === 204) return null;
  const data = await res.json().catch(() => null);
  if (!res.ok) {
    const detail = data && data.detail ? data.detail : "შეცდომა (HTTP " + res.status + ")";
    throw new Error(typeof detail === "string" ? detail : JSON.stringify(detail));
  }
  return data;
}
