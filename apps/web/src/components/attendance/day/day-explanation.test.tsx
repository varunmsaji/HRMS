import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { DayExplanationCard } from "@/components/attendance/day/day-explanation";
import type { AttendanceDayExplanation } from "@/lib/attendance/types";

function make(over: Partial<AttendanceDayExplanation> = {}): AttendanceDayExplanation {
  return {
    verdict: { status: "PRESENT", label: "Present", tone: "success" },
    reason: "Worked 8 h 10 m of 8 h. On time.",
    facts: [{ key: "worked", label: "Worked", value: "8 h 10 m" }],
    rules_applied: [],
    pay: { paid: "1 day", unpaid: null, leave: null, label: "1 day paid" },
    overtime: null,
    action: null,
    provisional: false,
    ...over,
  };
}

describe("DayExplanationCard", () => {
  it("shows the reason, the facts and the pay as the API wrote them", () => {
    render(<DayExplanationCard explanation={make()} />);
    expect(screen.getByText("Worked 8 h 10 m of 8 h. On time.")).toBeInTheDocument();
    expect(screen.getByText("Worked")).toBeInTheDocument();
    expect(screen.getByText("1 day paid")).toBeInTheDocument();
    expect(screen.queryByRole("note")).toBeNull();
  });

  it("shows the deadline and what happens when a day still needs fixing", () => {
    render(
      <DayExplanationCard
        explanation={make({
          action: { kind: "REQUEST_CORRECTION", deadline: "2026-11-30", consequence: "Counts as absent (unpaid) if not fixed" },
        })}
      />,
    );
    expect(screen.getByRole("note")).toHaveTextContent("Fix by 2026-11-30. Counts as absent (unpaid) if not fixed.");
  });

  it("splits overtime into found, approved and waiting", () => {
    render(
      <DayExplanationCard
        explanation={make({ overtime: { found_min: 105, approved_min: 90, pending_min: 15, class_label: "WEEKDAY" } })}
      />,
    );
    expect(screen.getByText(/1h 45m found|1 h 45 m found|105/i)).toBeInTheDocument();
    expect(screen.getByText(/waiting for approval/)).toBeInTheDocument();
  });
});
