import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { describe, expect, it } from "vitest";

import { Collapse } from "@/components/common/collapse";
import { KpiGrid } from "@/components/attendance/dashboard/kpi-grid";
import { DEFAULT_FILTERS, computeKpis } from "@/lib/attendance/dashboard";
import { makeDay } from "@/lib/attendance/__fixtures__/day";

function Demo() {
  const [open, setOpen] = useState(false);
  return (
    <>
      <button type="button" onClick={() => setOpen((o) => !o)}>
        toggle
      </button>
      <Collapse open={open}>
        <button type="button">inside</button>
      </Collapse>
    </>
  );
}

describe("Collapse", () => {
  it("keeps closed content out of the accessibility tree and brings it back when opened", async () => {
    render(<Demo />);
    expect(screen.queryByRole("button", { name: "inside" })).not.toBeInTheDocument();
    await userEvent.setup().click(screen.getByRole("button", { name: "toggle" }));
    expect(screen.getByRole("button", { name: "inside" })).toBeInTheDocument();
  });

  it("marks itself hidden and collapses its row while closed", () => {
    const { container } = render(
      <Collapse open={false}>
        <p>content</p>
      </Collapse>,
    );
    const root = container.firstElementChild as HTMLElement;
    expect(root).toHaveAttribute("aria-hidden", "true");
    expect(root.className).toMatch(/grid-rows-\[0fr\]/);
    expect(root.className).toMatch(/invisible/);
  });
});

describe("KpiGrid more statuses", () => {
  it("expands and collapses the rarer statuses", async () => {
    render(<KpiGrid kpi={computeKpis([makeDay()])} filters={DEFAULT_FILTERS} focusLabel="today" onDrill={() => {}} />);
    expect(screen.queryByRole("button", { name: /^Half day:/ })).not.toBeInTheDocument();
    const toggle = screen.getByRole("button", { name: /more statuses/i });
    expect(toggle).toHaveAttribute("aria-expanded", "false");
    await userEvent.setup().click(toggle);
    expect(screen.getByRole("button", { name: /^Half day:/ })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /fewer statuses/i })).toHaveAttribute("aria-expanded", "true");
  });
});
