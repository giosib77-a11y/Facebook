import { test, expect, vi, beforeAll, beforeEach, afterEach } from "vitest";

let req;

beforeAll(async () => {
  window.APP_CONFIG = { API_BASE: "http://api.test" };
  ({ req } = await import("./api.js"));
});

beforeEach(() => {
  localStorage.setItem("sb-x-auth-token", JSON.stringify({ access_token: "tok" }));
});

afterEach(() => {
  localStorage.clear();
  vi.unstubAllGlobals();
  vi.useRealTimers();
});

const jsonRes = (status, body) => ({
  status,
  ok: status >= 200 && status < 300,
  json: () => Promise.resolve(body),
});

test("403 with JSON detail rejects {forbidden, detail}", async () => {
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue(jsonRes(403, { detail: "X" })));
  await expect(req("GET", "/admin/overview")).rejects.toEqual({ forbidden: true, detail: "X" });
});

test("403 with a non-JSON body gives detail null", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn().mockResolvedValue({ status: 403, ok: false, json: () => Promise.reject(new SyntaxError("bad")) })
  );
  await expect(req("GET", "/admin/overview")).rejects.toEqual({ forbidden: true, detail: null });
});

test("5xx is retried once after a pause, then succeeds", async () => {
  vi.useFakeTimers();
  const fetchMock = vi
    .fn()
    .mockResolvedValueOnce(jsonRes(503, { detail: "down" }))
    .mockResolvedValueOnce(jsonRes(200, { ok: true }));
  vi.stubGlobal("fetch", fetchMock);
  const p = req("GET", "/x");
  await vi.advanceTimersByTimeAsync(2000);
  await expect(p).resolves.toEqual({ ok: true });
  expect(fetchMock).toHaveBeenCalledTimes(2);
});

test("second 5xx surfaces the backend detail as Error", async () => {
  vi.useFakeTimers();
  const fetchMock = vi.fn().mockResolvedValue(jsonRes(502, { detail: "ბმული შეიქმნა" }));
  vi.stubGlobal("fetch", fetchMock);
  const p = req("POST", "/admin/recovery", { email: "a@x.ge" });
  const assertion = expect(p).rejects.toThrow("ბმული შეიქმნა");
  await vi.advanceTimersByTimeAsync(2000);
  await assertion;
  expect(fetchMock).toHaveBeenCalledTimes(2);
});

test("401 redirects to index.html and rejects", async () => {
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue(jsonRes(401, {})));
  const hrefSet = vi.fn();
  const orig = window.location;
  Object.defineProperty(window, "location", {
    configurable: true,
    value: { set href(v) { hrefSet(v); } },
  });
  try {
    await expect(req("GET", "/x")).rejects.toThrow("401");
    expect(hrefSet).toHaveBeenCalledWith("index.html");
  } finally {
    Object.defineProperty(window, "location", { configurable: true, value: orig });
  }
});
