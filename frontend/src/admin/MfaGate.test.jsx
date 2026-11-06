import { test, expect, vi } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import MfaGate, { MfaStatus } from "./MfaGate.jsx";
import { isMfaRequired, ADMIN_MFA_REQUIRED } from "../lib/adminMfa.js";

const verifiedFactor = { id: "f1", factor_type: "totp", status: "verified" };
const staleFactor = { id: "old1", factor_type: "totp", status: "unverified" };

function makeMfa({ all = [], totp = [], over = {} } = {}) {
  return {
    listFactors: vi.fn().mockResolvedValue({ data: { all, totp, phone: [] }, error: null }),
    unenroll: vi.fn().mockResolvedValue({ data: { id: "x" }, error: null }),
    enroll: vi.fn().mockResolvedValue({
      data: { id: "new1", type: "totp", totp: { qr_code: "data:image/svg+xml;utf-8,<svg/>", secret: "SECRET123", uri: "otpauth://x" } },
      error: null,
    }),
    challenge: vi.fn().mockResolvedValue({ data: { id: "ch1" }, error: null }),
    verify: vi.fn().mockResolvedValue({ data: {}, error: null }),
    ...over,
  };
}

const codeInput = () => screen.getByLabelText("6-ნიშნა კოდი");
const submit = () => screen.getByRole("button", { name: "დადასტურება" });

test("challenge flow: verified factor -> challenge + verify -> onVerified", async () => {
  const mfa = makeMfa({ all: [verifiedFactor], totp: [verifiedFactor] });
  const onVerified = vi.fn();
  render(<MfaGate mfa={mfa} onVerified={onVerified} />);
  await screen.findByText("🔐 შეიყვანე ავთენტიფიკატორის კოდი");
  expect(screen.queryByAltText("QR კოდი")).toBeNull();
  expect(mfa.enroll).not.toHaveBeenCalled();
  fireEvent.change(codeInput(), { target: { value: "123456" } });
  fireEvent.click(submit());
  await waitFor(() => expect(onVerified).toHaveBeenCalledTimes(1));
  expect(mfa.challenge).toHaveBeenCalledWith({ factorId: "f1" });
  expect(mfa.verify).toHaveBeenCalledWith({ factorId: "f1", challengeId: "ch1", code: "123456" });
});

test("enroll flow: unenrolls unverified, shows QR and secret, verifies", async () => {
  const mfa = makeMfa({ all: [staleFactor], totp: [] });
  const onVerified = vi.fn();
  render(<MfaGate mfa={mfa} onVerified={onVerified} />);
  await screen.findByText("🔐 ჩართე ორფაქტორიანი შესვლა (MFA)");
  expect(mfa.unenroll).toHaveBeenCalledWith({ factorId: "old1" });
  expect(mfa.enroll).toHaveBeenCalledWith({ factorType: "totp" });
  expect(screen.getByAltText("QR კოდი").getAttribute("src")).toBe("data:image/svg+xml;utf-8,<svg/>");
  expect(screen.getByText("SECRET123")).toBeTruthy();
  fireEvent.change(codeInput(), { target: { value: "654321" } });
  fireEvent.click(submit());
  await waitFor(() => expect(onVerified).toHaveBeenCalledTimes(1));
  expect(mfa.challenge).toHaveBeenCalledWith({ factorId: "new1" });
  expect(mfa.verify).toHaveBeenCalledWith({ factorId: "new1", challengeId: "ch1", code: "654321" });
});

test("enroll continues when unenroll of a stale factor fails", async () => {
  const mfa = makeMfa({ all: [staleFactor], over: { unenroll: vi.fn().mockRejectedValue(new Error("boom")) } });
  render(<MfaGate mfa={mfa} onVerified={vi.fn()} />);
  await screen.findByAltText("QR კოდი");
  expect(mfa.enroll).toHaveBeenCalledTimes(1);
});

test("verify error shows message, clears input, no onVerified", async () => {
  const mfa = makeMfa({
    all: [verifiedFactor], totp: [verifiedFactor],
    over: { verify: vi.fn().mockResolvedValue({ data: null, error: { message: "invalid" } }) },
  });
  const onVerified = vi.fn();
  render(<MfaGate mfa={mfa} onVerified={onVerified} />);
  await screen.findByText("🔐 შეიყვანე ავთენტიფიკატორის კოდი");
  fireEvent.change(codeInput(), { target: { value: "111111" } });
  fireEvent.click(submit());
  await screen.findByText("კოდი არასწორია ან ვადა გაუვიდა — სცადე ხელახლა.");
  expect(onVerified).not.toHaveBeenCalled();
  expect(codeInput().value).toBe("");
});

test("listFactors error shows load error", async () => {
  const mfa = makeMfa({ over: { listFactors: vi.fn().mockResolvedValue({ data: null, error: { message: "x" } }) } });
  render(<MfaGate mfa={mfa} onVerified={vi.fn()} />);
  await screen.findByText("ორფაქტორიანი შესვლის ჩატვირთვა ვერ მოხერხდა — განაახლე გვერდი.");
  expect(mfa.enroll).not.toHaveBeenCalled();
});

test("enroll error shows load error", async () => {
  const mfa = makeMfa({ over: { enroll: vi.fn().mockResolvedValue({ data: null, error: { message: "x" } }) } });
  render(<MfaGate mfa={mfa} onVerified={vi.fn()} />);
  await screen.findByText("ორფაქტორიანი შესვლის ჩატვირთვა ვერ მოხერხდა — განაახლე გვერდი.");
});

test("input keeps digits only (max 6) and button disabled below 6 digits", async () => {
  const mfa = makeMfa({ all: [verifiedFactor], totp: [verifiedFactor] });
  render(<MfaGate mfa={mfa} onVerified={vi.fn()} />);
  await screen.findByLabelText("6-ნიშნა კოდი");
  fireEvent.change(codeInput(), { target: { value: "12a3-4" } });
  expect(codeInput().value).toBe("1234");
  expect(submit().disabled).toBe(true);
  fireEvent.change(codeInput(), { target: { value: "1234567" } });
  expect(codeInput().value).toBe("123456");
  expect(submit().disabled).toBe(false);
});

test("MfaStatus: verified state", async () => {
  const mfa = makeMfa({ all: [verifiedFactor], totp: [verifiedFactor] });
  render(<MfaStatus mfa={mfa} />);
  await screen.findByText("🔐 ორფაქტორიანი შესვლა ჩართულია ✓");
});

test("MfaStatus: not enabled -> enable opens enroll -> success shows enabled", async () => {
  const mfa = makeMfa();
  render(<MfaStatus mfa={mfa} />);
  await screen.findByText("🔐 ორფაქტორიანი შესვლა ჯერ არ არის ჩართული");
  fireEvent.click(screen.getByRole("button", { name: "ჩართვა" }));
  await screen.findByAltText("QR კოდი");
  fireEvent.change(codeInput(), { target: { value: "123456" } });
  fireEvent.click(submit());
  await screen.findByText(/ჩართულია ✓/);
  expect(screen.queryByAltText("QR კოდი")).toBeNull();
});

test("MfaStatus renders nothing on listFactors error", async () => {
  const mfa = makeMfa({ over: { listFactors: vi.fn().mockRejectedValue(new Error("x")) } });
  const { container } = render(<MfaStatus mfa={mfa} />);
  await waitFor(() => expect(mfa.listFactors).toHaveBeenCalled());
  await new Promise((r) => setTimeout(r, 0));
  expect(container.textContent).toBe("");
});

test("isMfaRequired recognises both error shapes", () => {
  expect(isMfaRequired({ forbidden: true, detail: ADMIN_MFA_REQUIRED })).toBe(true);
  expect(isMfaRequired(new Error(ADMIN_MFA_REQUIRED))).toBe(true);
  expect(isMfaRequired({ forbidden: true, detail: "სხვა" })).toBe(false);
  expect(isMfaRequired({ forbidden: true })).toBe(false);
  expect(isMfaRequired(null)).toBe(false);
  expect(isMfaRequired(undefined)).toBe(false);
});
