import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { ActivityList, GrowthChart } from "@/components/dashboard/dashboard-cards";

describe("GrowthChart", () => {
  const points = [
    { month: "2026-06", headcount: 60 },
    { month: "2026-07", headcount: 61 },
    { month: "2026-08", headcount: 64 },
  ];

  it("leads with the current headcount and the change over the period", () => {
    render(<GrowthChart points={points} />);
    expect(screen.getAllByText("64").length).toBeGreaterThan(0);
    expect(screen.getByText(/\+4 since Jun/)).toBeInTheDocument();
  });

  it("describes the whole trend for assistive tech, with real values", () => {
    render(<GrowthChart points={points} />);
    expect(
      screen.getByRole("img", { name: "Employee headcount by month, from 60 in Jun to 64 in Aug" }),
    ).toBeInTheDocument();
  });

  it("says 'No change' for a flat trend and shows a decline as a negative number", () => {
    const { rerender } = render(
      <GrowthChart points={[{ month: "2026-06", headcount: 10 }, { month: "2026-07", headcount: 10 }]} />,
    );
    expect(screen.getByText(/No change since Jun/)).toBeInTheDocument();

    rerender(<GrowthChart points={[{ month: "2026-06", headcount: 12 }, { month: "2026-07", headcount: 10 }]} />);
    expect(screen.getByText(/-2 since Jun/)).toBeInTheDocument();
  });

  it("copes with a single month and with no history", () => {
    const { rerender } = render(<GrowthChart points={[{ month: "2026-06", headcount: 5 }]} />);
    expect(screen.getByText(/No change since Jun/)).toBeInTheDocument();

    rerender(<GrowthChart points={[]} />);
    expect(screen.getByText("No headcount history yet.")).toBeInTheDocument();
  });
});

describe("ActivityList", () => {
  it("keeps the full title on its own line and puts the subject and time beneath it", () => {
    render(
      <ActivityList
        items={[
          {
            kind: "LEAVE_APPLICATION_APPROVED",
            title: "Leave request approved",
            subject: "Varun Saji",
            detail: null,
            occurred_at: new Date().toISOString(),
          },
        ]}
      />,
    );
    expect(screen.getByText("Leave request approved")).toBeInTheDocument();
    expect(screen.getByText(/Varun Saji · /)).toBeInTheDocument();
  });

  it("uses an icon, not initials, for payroll events whose subject is a period like 2026-09", () => {
    const { container } = render(
      <ActivityList
        items={[
          { kind: "PAYROLL_PAY_RUN_PAID", title: "Payroll paid", subject: "2026-09", detail: null, occurred_at: new Date().toISOString() },
        ]}
      />,
    );
    expect(container.querySelector("svg")).not.toBeNull();
    expect(screen.queryByText("2")).not.toBeInTheDocument();
  });
});
