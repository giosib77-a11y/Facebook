import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const API = "https://api.example";

let openSpy;
let popup;

async function load() {
  vi.resetModules();
  return import("./fbConnect.js");
}

function post(data, origin, source) {
  window.dispatchEvent(new MessageEvent("message", { data, origin, source }));
}

// startConnect-ის გარეშე popupRef null რჩება — "popup" ისე გავხსნათ, როგორც რეალურად
async function openPopup(mod) {
  await mod.startConnect("shop1", () => Promise.resolve({ login_url: "https://fb.example/login" }));
}

beforeEach(() => {
  window.APP_CONFIG = { API_BASE: API };
  popup = { close: vi.fn(), location: { href: "" } };
  openSpy = vi.spyOn(window, "open").mockReturnValue(popup);
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe("fbConnect message listener", () => {
  it("delivers a message from the API origin and the opened popup", async () => {
    const mod = await load();
    await openPopup(mod);
    const fn = vi.fn();
    mod.subscribeFbResult(fn);
    post({ fb: "connected" }, API, popup);
    expect(fn).toHaveBeenCalledWith({ fb: "connected" });
  });

  it("ignores a message from another origin", async () => {
    const mod = await load();
    await openPopup(mod);
    const fn = vi.fn();
    mod.subscribeFbResult(fn);
    post({ fb: "connected" }, "https://evil.example", popup);
    expect(fn).not.toHaveBeenCalled();
  });

  it("ignores a message from another source (right origin)", async () => {
    const mod = await load();
    await openPopup(mod);
    const fn = vi.fn();
    mod.subscribeFbResult(fn);
    post({ fb: "connected" }, API, { other: true });
    expect(fn).not.toHaveBeenCalled();
  });

  it("ignores a message when no popup was opened", async () => {
    const mod = await load();
    const fn = vi.fn();
    mod.subscribeFbResult(fn);
    post({ fb: "connected" }, API, popup);
    expect(fn).not.toHaveBeenCalled();
  });

  it("buffers a valid message received before subscribe", async () => {
    const mod = await load();
    await openPopup(mod);
    post({ fb: "connected", page: "P" }, API, popup);
    const fn = vi.fn();
    mod.subscribeFbResult(fn);
    expect(fn).toHaveBeenCalledWith({ fb: "connected", page: "P" });
  });

  it("does not buffer a message from a foreign origin", async () => {
    const mod = await load();
    await openPopup(mod);
    post({ fb: "connected" }, "https://evil.example", popup);
    const fn = vi.fn();
    mod.subscribeFbResult(fn);
    expect(fn).not.toHaveBeenCalled();
  });
});

describe("parsePages", () => {
  it("parses a valid JSON string", async () => {
    const { parsePages } = await load();
    expect(parsePages(JSON.stringify([{ id: "1", name: "A" }, { id: "2", name: "B" }]))).toEqual([
      { id: "1", name: "A" },
      { id: "2", name: "B" },
    ]);
  });

  it("accepts an array", async () => {
    const { parsePages } = await load();
    expect(parsePages([{ id: "7", name: "X" }])).toEqual([{ id: "7", name: "X" }]);
  });

  it("returns [] for non-JSON or non-array input", async () => {
    const { parsePages } = await load();
    expect(parsePages("not json{")).toEqual([]);
    expect(parsePages('{"id":"1"}')).toEqual([]);
    expect(parsePages(null)).toEqual([]);
    expect(parsePages(undefined)).toEqual([]);
  });

  it("drops entries with an invalid id or non-string name", async () => {
    const { parsePages } = await load();
    const raw = [
      { id: "abc", name: "bad" },
      { id: "", name: "empty" },
      { id: "1".repeat(33), name: "long" },
      { id: 5, name: "number" },
      { id: "3", name: 42 },
      null,
      { id: "4", name: "ok" },
    ];
    expect(parsePages(raw)).toEqual([{ id: "4", name: "ok" }]);
  });

  it("caps at 25 pages, trims name to 50 and falls back to id", async () => {
    const { parsePages } = await load();
    const many = Array.from({ length: 30 }, (_, i) => ({ id: String(i + 1), name: "n" }));
    expect(parsePages(many)).toHaveLength(25);
    expect(parsePages([{ id: "1", name: "x".repeat(80) }])[0].name).toHaveLength(50);
    expect(parsePages([{ id: "9", name: "" }])).toEqual([{ id: "9", name: "9" }]);
  });

  it("keeps markup in a name as plain text", async () => {
    const { parsePages } = await load();
    expect(parsePages([{ id: "1", name: "<img src=x onerror=alert(1)>" }])[0].name).toBe(
      "<img src=x onerror=alert(1)>"
    );
  });
});

describe("selectPage", () => {
  it("POSTs selection and page_id to /facebook/connect/select", async () => {
    const { selectPage } = await load();
    const api = vi.fn(() => Promise.resolve({ fb: "connected", page: "B" }));
    const res = await selectPage(api, "SEL", "2");
    expect(api).toHaveBeenCalledWith("/facebook/connect/select", "POST", { selection: "SEL", page_id: "2" });
    expect(res).toEqual({ fb: "connected", page: "B" });
  });
});

describe("choose redirect and reasons", () => {
  it("fbRedirectResult carries selection and pages from the query", async () => {
    const pages = JSON.stringify([{ id: "1", name: "A" }]);
    window.history.replaceState({}, "", "/?fb=choose&selection=S&pages=" + encodeURIComponent(pages));
    try {
      const { fbRedirectResult, parsePages } = await load();
      expect(fbRedirectResult.fb).toBe("choose");
      expect(fbRedirectResult.selection).toBe("S");
      expect(parsePages(fbRedirectResult.pages)).toEqual([{ id: "1", name: "A" }]);
      expect(window.location.search).toBe("");
    } finally {
      window.history.replaceState({}, "", "/");
    }
  });

  it("page_unavailable has its own text", async () => {
    const { fbResultMessage } = await load();
    const r = fbResultMessage({ fb: "error", reason: "page_unavailable" });
    expect(r.msg).toBe("ამ გვერდზე წვდომა აღარ არის — დააჭირე „დაკავშირებას“ ხელახლა.");
    expect(r.isErr).toBe(true);
  });
});

describe("startConnect", () => {
  it("calls window.open synchronously, before the api promise resolves", async () => {
    const mod = await load();
    let resolveApi;
    const api = vi.fn(() => new Promise((r) => (resolveApi = r)));
    const p = mod.startConnect("shop1", api);
    expect(openSpy).toHaveBeenCalledTimes(1);
    expect(openSpy.mock.invocationCallOrder[0]).toBeLessThan(api.mock.invocationCallOrder[0]);
    resolveApi({ login_url: "https://fb.example/login" });
    await p;
    expect(popup.location.href).toBe("https://fb.example/login");
  });

  it("falls back to location.href when the popup is blocked", async () => {
    openSpy.mockReturnValue(null);
    const mod = await load();
    const original = window.location;
    const fake = { href: "", search: original.search, pathname: original.pathname, origin: original.origin };
    Object.defineProperty(window, "location", { value: fake, configurable: true, writable: true });
    try {
      await mod.startConnect("shop1", () => Promise.resolve({ login_url: "https://fb.example/login" }));
      expect(fake.href).toBe("https://fb.example/login");
    } finally {
      Object.defineProperty(window, "location", { value: original, configurable: true, writable: true });
    }
  });

  it("closes the popup when the api call fails", async () => {
    const mod = await load();
    await expect(mod.startConnect("shop1", () => Promise.reject(new Error("boom")))).rejects.toThrow("boom");
    expect(popup.close).toHaveBeenCalled();
  });
});
