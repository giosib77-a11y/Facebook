import { test, expect, vi } from "vitest";
import { render, screen, act, fireEvent } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { BusyButton, Skeleton, ToastProvider, useToast } from "./ui";

test("BusyButton: ნაგულისხმევი კლასი და children", () => {
  render(<BusyButton>შენახვა</BusyButton>);
  const btn = screen.getByRole("button", { name: "შენახვა" });
  expect(btn).toHaveClass("btn", "btn-primary");
  expect(btn).toBeEnabled();
  expect(btn).not.toHaveClass("is-loading");
});

test("BusyButton: busy → disabled და is-loading", () => {
  render(<BusyButton busy>შენახვა</BusyButton>);
  const btn = screen.getByRole("button");
  expect(btn).toBeDisabled();
  expect(btn).toHaveClass("is-loading");
});

test("BusyButton: დამატებითი props გადაეცემა, onClick ჩაირთვება", async () => {
  const onClick = vi.fn();
  render(<BusyButton type="submit" onClick={onClick}>OK</BusyButton>);
  const btn = screen.getByRole("button");
  expect(btn).toHaveAttribute("type", "submit");
  await userEvent.click(btn);
  expect(onClick).toHaveBeenCalledTimes(1);
});

test("BusyButton: busy-ზე onClick არ ირთვება", async () => {
  const onClick = vi.fn();
  render(<BusyButton busy onClick={onClick}>OK</BusyButton>);
  await userEvent.click(screen.getByRole("button"));
  expect(onClick).not.toHaveBeenCalled();
});

test("Skeleton: ნაგულისხმევად 3 ელემენტი", () => {
  const { container } = render(<Skeleton />);
  expect(container.querySelectorAll(".skel-item")).toHaveLength(3);
});

test("Skeleton: n={5} → 5 ელემენტი", () => {
  const { container } = render(<Skeleton n={5} />);
  expect(container.querySelectorAll(".skel-item")).toHaveLength(5);
});

function Trigger() {
  const toast = useToast();
  return (
    <>
      <button onClick={() => toast("შენახულია")}>ok</button>
      <button onClick={() => toast("შეცდომა", true)}>err</button>
    </>
  );
}

function renderToast() {
  const utils = render(
    <ToastProvider>
      <Trigger />
    </ToastProvider>,
  );
  return { ...utils, toastEl: () => utils.container.querySelector("#toast") };
}

test("Toast: თავდაპირველად hidden", () => {
  const { toastEl } = renderToast();
  expect(toastEl()).toHaveClass("hidden");
});

test("Toast: წარმატება → toast-ok და ტექსტი", () => {
  const { toastEl } = renderToast();
  fireEvent.click(screen.getByText("ok"));
  expect(toastEl()).toHaveClass("toast-ok");
  expect(toastEl()).toHaveTextContent("შენახულია");
  expect(toastEl()).not.toHaveClass("hidden");
});

test("Toast: შეცდომა → toast-err და ტექსტი", () => {
  const { toastEl } = renderToast();
  fireEvent.click(screen.getByText("err"));
  expect(toastEl()).toHaveClass("toast-err");
  expect(toastEl()).toHaveTextContent("შეცდომა");
});

test("Toast: 3500ms-ის შემდეგ ისევ hidden", () => {
  vi.useFakeTimers();
  try {
    const { toastEl } = renderToast();
    fireEvent.click(screen.getByText("ok"));
    expect(toastEl()).toHaveClass("toast-ok");
    act(() => {
      vi.advanceTimersByTime(3499);
    });
    expect(toastEl()).toHaveClass("toast-ok");
    act(() => {
      vi.advanceTimersByTime(1);
    });
    expect(toastEl()).toHaveClass("hidden");
  } finally {
    vi.useRealTimers();
  }
});
