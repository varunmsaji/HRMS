import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { DirectorySummaryCards } from "@/components/employee/directory-summary";

describe("DirectorySummaryCards", () => {
  it("shows skeletons, never zeros or dashes, until the summary has loaded", () => {
    render(<DirectorySummaryCards summary={null} />);
    expect(screen.getAllByLabelText("Loading")).toHaveLength(4);
    expect(screen.queryByText("0")).not.toBeInTheDocument();
  });

  it("shows the figures once loaded", () => {
    render(
      <DirectorySummaryCards
        summary={{ total: 1200, active: 1100, on_probation: 7, on_notice: 3, department_count: 2, department_names: ["HR", "Ops"] }}
      />,
    );
    expect(screen.queryByLabelText("Loading")).not.toBeInTheDocument();
    expect(screen.getByText("1,200")).toBeInTheDocument();
    expect(screen.getByText("1100 active")).toBeInTheDocument();
    expect(screen.getByText("HR, Ops")).toBeInTheDocument();
  });
});
