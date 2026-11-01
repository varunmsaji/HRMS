import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { ShiftVersionForm } from "@/components/shift/shift-version-form";
import { EMPTY_SHIFT_VERSION_FORM_VALUES } from "@/lib/shift/validate-shift-version";

function renderForm(shiftType: "" | "FIXED" | "FLEXIBLE" | "SPLIT") {
  const onChange = vi.fn();
  render(
    <ShiftVersionForm
      values={{ ...EMPTY_SHIFT_VERSION_FORM_VALUES, shiftType }}
      errors={{}}
      onChange={onChange}
      weeklyOffPatterns={[]}
    />,
  );
  return onChange;
}

function typeOptions(): string[] {
  const select = screen.getByLabelText(/^Type/) as HTMLSelectElement;
  return Array.from(select.options).map((o) => o.value);
}

describe("ShiftVersionForm schedule types", () => {
  it("offers only Fixed and Flexible for a new schedule", () => {
    renderForm("");
    expect(typeOptions()).toEqual(["", "FIXED", "FLEXIBLE"]);
    expect(screen.queryByText(/temporarily unavailable/i)).toBeNull();
  });

  it("keeps Fixed and Flexible versions editable and without a SPLIT option", () => {
    renderForm("FLEXIBLE");
    expect(typeOptions()).not.toContain("SPLIT");
    expect((screen.getByLabelText(/^Type/) as HTMLSelectElement).matches(":disabled")).toBe(false);
  });

  it("shows an existing SPLIT version read-only with an explanation, not converted", () => {
    renderForm("SPLIT");
    const select = screen.getByLabelText(/^Type/) as HTMLSelectElement;
    expect(select.value).toBe("SPLIT");
    expect(select.matches(":disabled")).toBe(true);
    expect(screen.getByText(/temporarily unavailable for new configuration/i)).toBeTruthy();
  });
});
