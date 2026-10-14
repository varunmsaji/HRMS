import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { RouteError } from "@/components/common/route-error";
import { ApiError } from "@/lib/api/errors";

describe("RouteError", () => {
  it("never shows an unexpected error's own message", () => {
    render(<RouteError error={new TypeError("Cannot read properties of undefined (reading 'salary')")} />);
    expect(screen.getByRole("alert")).toHaveTextContent(/unexpected problem/);
    expect(screen.queryByText(/salary/)).toBeNull();
  });

  it("shows an API failure's safe message with its reference", () => {
    const error = new ApiError({ status: 500, code: "INTERNAL_ERROR", message: "An unexpected error occurred", requestId: "req-abc" });
    render(<RouteError error={error} />);
    expect(screen.getByRole("alert")).toHaveTextContent("An unexpected error occurred Reference: req-abc");
  });

  it("falls back to the server-error digest as the reference", () => {
    const error = Object.assign(new Error("hidden"), { digest: "d1g3st" });
    render(<RouteError error={error} />);
    expect(screen.getByRole("alert")).toHaveTextContent("Reference: d1g3st");
    expect(screen.queryByText(/hidden/)).toBeNull();
  });

  it("prefers retry over reset", () => {
    const retry = vi.fn();
    const reset = vi.fn();
    render(<RouteError error={new Error("x")} retry={retry} reset={reset} />);
    fireEvent.click(screen.getByRole("button", { name: "Try again" }));
    expect(retry).toHaveBeenCalledTimes(1);
    expect(reset).not.toHaveBeenCalled();
  });
});
