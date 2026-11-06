import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import FbPagePicker from "./FbPagePicker.jsx";

const pages = [
  { id: "1", name: "Page A" },
  { id: "2", name: "Page B" },
];

describe("FbPagePicker", () => {
  it("shows every page name", () => {
    render(<FbPagePicker pages={pages} onPick={() => {}} onCancel={() => {}} />);
    expect(screen.getByRole("button", { name: "Page A" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "Page B" })).toBeTruthy();
  });

  it("click calls onPick with the page id", async () => {
    const onPick = vi.fn();
    render(<FbPagePicker pages={pages} onPick={onPick} onCancel={() => {}} />);
    await userEvent.click(screen.getByRole("button", { name: "Page B" }));
    expect(onPick).toHaveBeenCalledWith("2");
  });

  it("busyId disables the other pages", () => {
    render(<FbPagePicker pages={pages} onPick={() => {}} onCancel={() => {}} busyId="1" />);
    expect(screen.getByRole("button", { name: "Page A" }).className).toContain("is-loading");
    expect(screen.getByRole("button", { name: "Page B" }).disabled).toBe(true);
  });

  it("cancel calls onCancel", async () => {
    const onCancel = vi.fn();
    render(<FbPagePicker pages={pages} onPick={() => {}} onCancel={onCancel} />);
    await userEvent.click(screen.getByRole("button", { name: "გაუქმება" }));
    expect(onCancel).toHaveBeenCalled();
  });

  it("renders markup in a name as text, not HTML", () => {
    const { container } = render(
      <FbPagePicker pages={[{ id: "1", name: "<b>x</b>" }]} onPick={() => {}} onCancel={() => {}} />
    );
    expect(screen.getByRole("button", { name: "<b>x</b>" })).toBeTruthy();
    expect(container.querySelector("b")).toBeNull();
  });

  it("renders nothing for an empty list", () => {
    const { container } = render(<FbPagePicker pages={[]} onPick={() => {}} onCancel={() => {}} />);
    expect(container.firstChild).toBeNull();
  });
});
