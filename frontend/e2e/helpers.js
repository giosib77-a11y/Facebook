/**
 * e2e helper-ები: ქსელის იზოლაცია, API mock-ები, ყალბი სესია.
 *
 * ⚠️ Playwright-ში ბოლოს რეგისტრირებული route პირველი მოწმდება. ამიტომ
 * `blockExternal` ყოველთვის პირველი უნდა გამოიძახო (ის catch-all-ია), `mockApi` / `loginAs` — მის შემდეგ;
 * მათი route-ები catch-all-ს ასწრებენ, ხოლო შეუსაბამო მოთხოვნა `route.fallback()`-ით catch-all-ზე ჩავარდება.
 * backend არასდროს ეშვება; production Supabase / API-ს არც ერთი მოთხოვნა არ გადის.
 */

export const APP_ORIGIN = "http://localhost:4173";
export const PANEL_PREFIX = "/panel/";
// public/config.js-ის SUPABASE_URL (ref = ქვედომენი) — localStorage-ის გასაღებისთვის
export const SUPABASE_REF = "xtvuqanwqocxgwetpzze";
export const SUPABASE_ORIGIN = `https://${SUPABASE_REF}.supabase.co`;

const FONT_HOSTS = new Set(["fonts.googleapis.com", "fonts.gstatic.com"]);

/**
 * ყველაფერი, რაც არ არის `localhost:4173/panel/...` (სტატიკა) და არც mock-ითაა დამუშავებული, წყდება.
 * აბრუნებს `{ blocked }` — დაბლოკილი მოთხოვნების სიას (ტესტი ამოწმებს, რომ ცარიელია).
 */
export async function blockExternal(page) {
  const blocked = [];
  await page.route("**/*", (route) => {
    const url = new URL(route.request().url());
    const isPanelAsset = url.origin === APP_ORIGIN && url.pathname.startsWith(PANEL_PREFIX);
    if (isPanelAsset) return route.fallback();
    // Google Fonts — უვნებელი სტატიკა (გვერდი ფონტის გარეშეც მუშაობს); წყდება, მაგრამ არ ითვლება
    if (FONT_HOSTS.has(url.hostname)) return route.abort();
    blocked.push(`${route.request().method()} ${url.origin}${url.pathname}`);
    return route.abort();
  });
  return { blocked };
}

/**
 * handlers: { "GET /shops/me": [...], "POST /shops": (route, request) => ... }
 * მნიშვნელობა ფუნქციაა → თავად ამუშავებს route-ს; სხვა შემთხვევაში JSON-ად ბრუნდება (status 200).
 * შესატყვისი = method + pathname (host-ის მიუხედავად — API იმავე origin-ზეა, auth კი supabase-ზე).
 */
export async function mockApi(page, handlers) {
  for (const [key, value] of Object.entries(handlers)) {
    const [method, path] = key.split(" ");
    await page.route(
      (url) => url.pathname === path,
      (route, request) => {
        if (request.method() !== method) return route.fallback();
        if (typeof value === "function") return value(route, request);
        return route.fulfill({ json: value });
      }
    );
  }
}

/** ყალბი Supabase სესია localStorage-ში (readStoredToken-ის ფორმატი) + `/auth/v1/user` mock */
export async function loginAs(page, { email = "tester@example.com" } = {}) {
  const user = { id: "00000000-0000-0000-0000-000000000001", email, aud: "authenticated", role: "authenticated" };
  const session = {
    access_token: "e2e-fake-access-token",
    refresh_token: "e2e-fake-refresh-token",
    token_type: "bearer",
    expires_in: 3600,
    expires_at: Math.floor(Date.now() / 1000) + 3600,
    user,
  };
  await page.addInitScript(
    ([key, value]) => window.localStorage.setItem(key, value),
    [`sb-${SUPABASE_REF}-auth-token`, JSON.stringify(session)]
  );
  await mockApi(page, { "GET /auth/v1/user": user });
}
