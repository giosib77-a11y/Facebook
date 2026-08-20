/* პანელის Supabase კლიენტი + auth-ჰელპერები — გადმოტანილია app.js-იდან ხაზ-ხაზ.
 * ⚠️ არც ერთი პარამეტრი არ შეცვალო — თითოეული განზრახაა (იხ. კომენტარები).
 */
import { createClient } from "@supabase/supabase-js";

const cfg = window.APP_CONFIG;

export const sb = createClient(cfg.SUPABASE_URL, cfg.SUPABASE_ANON_KEY, {
  auth: {
    persistSession: true,
    autoRefreshToken: true,
    // detectSessionInUrl:false — Facebook-ის redirect-ის #_=_ რომ არ დაარღვიოს სესია.
    // Supabase-ის OAuth-ს არ ვიყენებთ, მხოლოდ email/პაროლს.
    detectSessionInUrl: false,
    // implicit — პაროლის აღდგენის ბმული hash-ით (მრავალ მოწყობილობაზე მუშაობს)
    flowType: "implicit",
    // ⚠️ no-op lock — navigator LockManager-ის ჩაკეტვის თავიდან ასაცილებლად.
    // getSession() რომ არ „გაიჭედოს" მრავალი tab-ის/popup-ის დროს.
    // პირდაპირ ეხება Facebook-ის popup-ნაკადს — არ მოხსნა.
    lock: async (_name, _timeout, fn) => await fn(),
  },
});

/** token პირდაპირ storage-იდან — sb.auth.getSession() ზოგჯერ იჭედება */
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

export async function getToken() {
  const t = readStoredToken();
  if (t) return t;
  try {
    const { data } = await sb.auth.getSession();
    return data.session ? data.session.access_token : null;
  } catch {
    return null;
  }
}

/* token-ის ავტო-განახლება — 8წმ timeout-ით დაცული, რომ არ გაიჭედოს.
 * ერთდროული გამოძახებები ერთსა და იმავე Promise-ს იზიარებენ. */
let _refreshPromise = null;
export function refreshToken() {
  if (!_refreshPromise) {
    _refreshPromise = (async () => {
      try {
        const timeout = new Promise((res) => setTimeout(() => res(null), 8000));
        const doRefresh = sb.auth
          .refreshSession()
          .then((r) => (r && r.data && r.data.session ? r.data.session.access_token : null))
          .catch(() => null);
        return await Promise.race([doRefresh, timeout]);
      } finally {
        _refreshPromise = null;
      }
    })();
  }
  return _refreshPromise;
}

export function translateAuthError(msg) {
  if (/invalid login/i.test(msg)) return "არასწორი ელ-ფოსტა ან პაროლი";
  if (/already registered|already exists/i.test(msg)) return "ეს ელ-ფოსტა უკვე რეგისტრირებულია";
  if (/email not confirmed/i.test(msg)) return "ელ-ფოსტა ჯერ არ დადასტურებულა";
  if (/password should be/i.test(msg)) return "პაროლი ძალიან მოკლეა (მინ. 6 სიმბოლო)";
  return msg;
}

/** reset.html იმავე საქაღალდეშია — ⚠️ URL-კონტრაქტი (Supabase Redirect URLs) */
export function resetRedirectUrl() {
  const dir = location.pathname.replace(/[^/]*$/, "");
  return location.origin + dir + "reset.html";
}
