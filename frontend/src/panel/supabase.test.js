import { beforeEach, describe, expect, it, vi } from "vitest";

const fakeClient = { auth: {} };
const createClient = vi.fn(() => fakeClient);
vi.mock("@supabase/supabase-js", () => ({ createClient }));

async function load() {
  vi.resetModules();
  return import("./supabase.js");
}

beforeEach(() => {
  createClient.mockClear();
  localStorage.clear();
  window.APP_CONFIG = { SUPABASE_URL: "https://x.supabase.co", SUPABASE_PUBLISHABLE_KEY: "pk" };
});

describe("supabase client options", () => {
  it("creates the client once, without a custom (no-op) lock", async () => {
    await load();
    expect(createClient).toHaveBeenCalledTimes(1);
    const [url, key, options] = createClient.mock.calls[0];
    expect(url).toBe("https://x.supabase.co");
    expect(key).toBe("pk");
    expect(Object.hasOwn(options.auth, "lock")).toBe(false);
  });

  it("keeps the other auth options unchanged", async () => {
    await load();
    expect(createClient.mock.calls[0][2].auth).toEqual({
      persistSession: true,
      autoRefreshToken: true,
      detectSessionInUrl: false,
      flowType: "implicit",
    });
  });
});

describe("readStoredToken", () => {
  it("returns the access_token from an sb-*-auth-token entry", async () => {
    localStorage.setItem("sb-x-auth-token", JSON.stringify({ access_token: "tok123" }));
    const { readStoredToken } = await load();
    expect(readStoredToken()).toBe("tok123");
  });

  it("returns null on broken JSON", async () => {
    localStorage.setItem("sb-x-auth-token", "{not json");
    const { readStoredToken } = await load();
    expect(readStoredToken()).toBeNull();
  });

  it("returns null when nothing is stored", async () => {
    const { readStoredToken } = await load();
    expect(readStoredToken()).toBeNull();
  });
});
