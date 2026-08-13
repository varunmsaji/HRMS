import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { LoadingState } from "@/components/common/loading-state";

describe("LoadingState", () => {
  it("renders an accessible status region with the given label", () => {
    render(<LoadingState label="Loading setup progress…" />);

    const status = screen.getByRole("status");
    expect(status).toHaveTextContent("Loading setup progress…");
  });

  it("defaults to a generic label when none is given", () => {
    render(<LoadingState />);
    expect(screen.getByRole("status")).toHaveTextContent("Loading…");
  });
});
