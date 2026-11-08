import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { AdvancedSettings, countChanged } from "@/components/policy/advanced-settings";

const defaults = { grace: "0", mode: "PAIR_ALL", bands: [] as Array<{ min: number }>, name: "" };

describe("AdvancedSettings", () => {
  it("counts only the folded settings that differ from the defaults, lists included", () => {
    const values = { ...defaults, mode: "FIRST_LAST", bands: [{ min: 5 }], name: "changed" };
    expect(countChanged(values, defaults, ["grace", "mode", "bands"])).toBe(2);
  });

  it("says when everything inside is at its default, and stays closed", () => {
    render(
      <AdvancedSettings values={defaults} defaults={defaults} fields={["grace", "mode"]}>
        <p>inside</p>
      </AdvancedSettings>,
    );
    expect(screen.getByText("all at their defaults")).toBeInTheDocument();
    expect(screen.getByText("inside").closest("details")).not.toHaveAttribute("open");
  });

  it("says how many were changed, and opens when one has an error", () => {
    render(
      <AdvancedSettings
        values={{ ...defaults, grace: "5" }}
        defaults={defaults}
        fields={["grace", "mode"]}
        hasError
      >
        <p>inside</p>
      </AdvancedSettings>,
    );
    expect(screen.getByText("1 changed from the default")).toBeInTheDocument();
    expect(screen.getByText("inside").closest("details")).toHaveAttribute("open");
  });
});
