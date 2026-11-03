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
