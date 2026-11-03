import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { ScopeTabs } from "@/components/common/scope-tabs";

type Scope = "MINE" | "TEAM" | "DECISIONS";

describe("ScopeTabs", () => {
  it("draws only the options that are shown and reports a choice", async () => {
    const onChange = vi.fn();
    const user = userEvent.setup();
    render(
      <ScopeTabs<Scope>
        label="Balance scope"
        value="TEAM"
        onChange={onChange}
        options={[
          { value: "MINE", label: "My balance" },
          { value: "TEAM", label: "Team balances" },
        ]}
      />,
    );
    expect(screen.getByRole("button", { name: "Team balances" })).toHaveAttribute("aria-pressed", "true");
    await user.click(screen.getByRole("button", { name: "My balance" }));
    expect(onChange).toHaveBeenCalledWith("MINE");
  });

  it("hides a 'My' option for an account with no employee record", () => {
    render(
      <ScopeTabs<Scope>
        label="Balance scope"
        value="TEAM"
        onChange={vi.fn()}
        options={[
          { value: "MINE", label: "My balance", show: false },
          { value: "DECISIONS", label: "Decision center" },
          { value: "TEAM", label: "Team balances" },
        ]}
      />,
    );
    expect(screen.queryByRole("button", { name: "My balance" })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Decision center" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Team balances" })).toBeInTheDocument();
  });

  it("draws nothing when there is only one scope to be in", () => {
    const { container } = render(
      <ScopeTabs<Scope>
        label="Balance scope"
        value="TEAM"
        onChange={vi.fn()}
        options={[
          { value: "MINE", label: "My balance", show: false },
          { value: "TEAM", label: "Team balances" },
        ]}
      />,
    );
    expect(container).toBeEmptyDOMElement();
  });
});
