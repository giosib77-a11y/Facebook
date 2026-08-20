/* API-კლიენტი — გადმოტანილია admin.js-იდან ხაზ-ხაზ.
 *
 * ⚠️ არ „გააუმჯობესო": retry-ლოგიკა განზრახაა —
 *   • ქსელის შეცდომა (Render-ის cold start) → 2წმ პაუზა → ერთი ხელახალი ცდა
 *   • 5xx → იგივე (რომ მთელი პანელი არ დაემხოს წამიერ ჩავარდნაზე)
 *   • 401 → პანელზე დაბრუნება (სესია გაქრა)
 *   • 403 → { forbidden: true } — ადმინ-გეითის ამოსაცნობად
 */
const cfg = window.APP_CONFIG;
export const API = cfg.API_BASE;

/** Supabase-ის token პირდაპირ localStorage-იდან (SDK-ის ინიციალიზაციას არ ველოდებით) */
export function readStoredToken() {
  for (let i = 0; i < localStorage.length; i++) {
    const k = localStorage.key(i);
    if (k && k.indexOf("sb-") === 0 && k.indexOf("auth-token") >= 0) {
      try {
        const s = JSON.parse(localStorage.getItem(k));
        return s.access_token || (s.currentSession && s.currentSession.access_token) || null;
      } catch {
        /* გატეხილი ჩანაწერი — შემდეგს ვცდით */
      }
    }
  }
  return null;
}

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

export async function req(method, path, body, _retry) {
  const token = readStoredToken();
  if (!token) {
    location.href = "index.html"; // ფარდობითი → /panel/index.html (URL-კონტრაქტი)
    throw new Error("no session");
  }
  const opts = {
    method,
    headers: { Authorization: "Bearer " + token, "ngrok-skip-browser-warning": "1" },
  };
  if (body !== undefined) {
    opts.headers["Content-Type"] = "application/json";
    opts.body = JSON.stringify(body);
  }

  let res;
  try {
    res = await fetch(API + path, opts);
  } catch (netErr) {
    if (!_retry) {
      await sleep(2000);
      return req(method, path, body, true);
    }
    throw netErr;
  }

  if (res.status === 401) {
    location.href = "index.html";
    throw new Error("401");
  }
  if (res.status === 403) throw { forbidden: true };
  if (res.status >= 500 && !_retry) {
    await sleep(2000);
    return req(method, path, body, true);
  }
  if (res.status === 204) return null;

  const data = await res.json().catch(() => null);
  if (!res.ok) throw new Error((data && data.detail) || "HTTP " + res.status);
  return data;
}

export const api = (p) => req("GET", p);
