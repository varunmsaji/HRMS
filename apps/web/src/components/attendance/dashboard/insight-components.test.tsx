import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { DeltaChip } from "@/components/attendance/dashboard/delta-chip";
import { PunctualityPanel, WeekdayPanel } from "@/components/attendance/dashboard/insight-panels";
import { KpiGrid } from "@/components/attendance/dashboard/kpi-grid";
import { PayrollReadiness } from "@/components/attendance/dashboard/payroll-readiness";
import { TodayPulse } from "@/components/attendance/dashboard/today-pulse";
import { DEFAULT_FILTERS, type AttentionItem } from "@/lib/attendance/dashboard";
import { makeKpis, makeSummary, makeSummaryDay, makeWeekdays } from "@/lib/attendance/__fixtures__/summary";
import { compareRates } from "@/lib/attendance/insights";
import { toDistribution, toKpiSet, toPunctuality, toRatePoints } from "@/lib/attendance/summary";
import type { AttendancePeriod } from "@/lib/attendance-period/types";

// 2026-10-12 is a Monday; 2026-10-05 the Monday before.
const TODAY = "2026-10-12";
const LAST_WEEK = "2026-10-05";

describe("DeltaChip", () => {
  it("is green when the change is good news, whichever way it points", () => {
    const { rerender } = render(<DeltaChip delta={3} good="up" versus="last Mon" />);
    expect(screen.getByText("+3 vs last Mon").className).toMatch(/text-success/);
    rerender(<DeltaChip delta={-2} good="down" versus="last Mon" />);
    expect(screen.getByText("−2 vs last Mon").className).toMatch(/text-success/);
  });

  it("is red when the change is bad news and neutral for leave-style metrics", () => {
    const { rerender } = render(<DeltaChip delta={4} good="down" versus="last Mon" />);
    expect(screen.getByText("+4 vs last Mon").className).toMatch(/text-danger/);
    rerender(<DeltaChip delta={4} good="neutral" versus="last Mon" />);
    expect(screen.getByText("+4 vs last Mon").className).not.toMatch(/text-(success|danger)/);
  });

  it("says so when nothing changed or there is nothing to compare with", () => {
    const { rerender } = render(<DeltaChip delta={0} good="up" versus="last Mon" />);
    expect(screen.getByText("No change vs last Mon")).toBeInTheDocument();
    rerender(<DeltaChip delta={null} good="up" versus="last Mon" />);
    expect(screen.getByText("No comparison yet")).toBeInTheDocument();
  });

  it("does not show a rounding artefact as a change", () => {
    render(<DeltaChip delta={0.04} good="up" unit=" pts" decimals={1} versus="last Mon" />);
    expect(screen.getByText("No change vs last Mon")).toBeInTheDocument();
  });
});

describe("TodayPulse", () => {
  // Last Monday one of two attended; today two of three, with one absent.
  const summary = makeSummary(LAST_WEEK, TODAY, {
    days: [
      makeSummaryDay(LAST_WEEK, { expected: 2, present: 1, absent: 1 }),
      makeSummaryDay(TODAY, { expected: 3, present: 2, absent: 1 }),
    ],
    distribution: [
      { bucket: "PRESENT", count: 2 },
      { bucket: "ABSENT", count: 1 },
    ],
  });
  const points = toRatePoints(summary.daily);

  function renderPulse(onDrill = vi.fn()) {
    render(
      <TodayPulse
        points={points}
        focusDate={TODAY}
        focusLabel="today"
        comparison={compareRates(points, TODAY, LAST_WEEK)}
        distribution={toDistribution(summary.distribution)}
        filters={DEFAULT_FILTERS}
        onDrill={onDrill}
      />,
    );
    return onDrill;
  }

  it("shows today's rate, who made it up, and the change on the same weekday last week", () => {
    renderPulse();
    const pulse = screen.getByRole("region", { name: "Attendance at a glance" });
    // The headline comes first; the same figure also appears as the Present chip's share.
    expect(within(pulse).getAllByText("66.7%")[0].className).toMatch(/text-4xl/);
    expect(within(pulse).getByText("2 of 3 expected employees attended.")).toBeInTheDocument();
    expect(within(pulse).getByText("+16.7 pts vs last Mon")).toBeInTheDocument();
  });

  it("drills into a status from the breakdown", async () => {
    const onDrill = renderPulse();
    await userEvent.setup().click(screen.getByRole("button", { name: "Show Absent employees (1)" }));
    expect(onDrill).toHaveBeenCalledWith("ABSENT");
  });

  it("shows a dash, not 0%, when nobody was expected", () => {
    render(
      <TodayPulse
        points={toRatePoints(makeSummary(LAST_WEEK, TODAY).daily)}
        focusDate={TODAY}
        focusLabel="today"
        comparison={{ delta: null, baselineDate: LAST_WEEK, baselineRate: null }}
        distribution={[]}
        filters={DEFAULT_FILTERS}
        onDrill={vi.fn()}
      />,
    );
    expect(screen.getByText("Nobody was expected to work on this day.")).toBeInTheDocument();
    expect(screen.queryByText("0.0%")).not.toBeInTheDocument();
  });
});

describe("KpiGrid comparison", () => {
  const now = toKpiSet(makeKpis({ total_employees: 3, present: 2, absent: 1, checked_in: 2, not_checked_in: 1 }));
  const before = toKpiSet(makeKpis({ total_employees: 3, present: 1, absent: 2, checked_in: 1, not_checked_in: 2 }));

  it("shows how present and absent moved, and says it in the accessible name", () => {
    render(<KpiGrid kpi={now} filters={DEFAULT_FILTERS} focusLabel="today" compare={{ kpi: before, label: "last Mon" }} onDrill={vi.fn()} />);
    const present = screen.getByRole("button", { name: /^Present: 2\./ });
    expect(present).toHaveAccessibleName(/Up 1 versus last Mon/);
    expect(within(present).getByText("+1 vs last Mon").className).toMatch(/text-success/);
    const absent = screen.getByRole("button", { name: /^Absent: 1\./ });
    expect(within(absent).getByText("−1 vs last Mon").className).toMatch(/text-success/);
  });

  it("shows no change chips when there is no comparison day", () => {
    render(<KpiGrid kpi={now} filters={DEFAULT_FILTERS} focusLabel="today" compare={null} onDrill={vi.fn()} />);
    expect(screen.queryByText(/vs last/)).not.toBeInTheDocument();
  });
});

describe("PunctualityPanel", () => {
  const employees = new Map([["a", { id: "a", first_name: "Asha", last_name: "Rao", employee_code: "E-1" }]]);
  // Asha late twice (10 and 40 minutes), one on-time day: 1 of 3 on time.
  const punctual = (checked: number, late: number, minutes: number) =>
    toPunctuality({
      ...makeSummary(TODAY, TODAY).punctuality,
      checked_in: checked,
      late,
      on_time: checked - late,
      late_rate: checked ? (late / checked) * 100 : null,
      on_time_rate: checked ? ((checked - late) / checked) * 100 : null,
      avg_late_minutes: late ? minutes / late : null,
    });

  it("reports the on-time rate, average lateness and repeat late-comers, and drills into late arrivals", async () => {
    const onViewLate = vi.fn();
    render(
      <PunctualityPanel
        summary={punctual(3, 2, 50)}
        frequent={[{ employeeId: "a", lateDays: 2, totalLateMinutes: 50 }]}
        employeesById={employees}
        onViewLate={onViewLate}
      />,
    );
    expect(screen.getByText("33.3%")).toBeInTheDocument(); // 1 of 3 on time
    expect(screen.getByText("25 min")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Asha Rao" })).toHaveAttribute("href", "/app/attendance/employee/a");
    expect(screen.getByText("2 days")).toBeInTheDocument();
    await userEvent.setup().click(screen.getByRole("button", { name: /view all late arrivals/i }));
    expect(onViewLate).toHaveBeenCalled();
  });

  it("says so when nobody checked in, and congratulates a fully punctual range", () => {
    const { rerender } = render(
      <PunctualityPanel summary={punctual(0, 0, 0)} frequent={[]} employeesById={employees} onViewLate={vi.fn()} />,
    );
    expect(screen.getByText(/nobody has checked in/i)).toBeInTheDocument();
    rerender(<PunctualityPanel summary={punctual(1, 0, 0)} frequent={[]} employeesById={employees} onViewLate={vi.fn()} />);
    expect(screen.getByText("Everyone who checked in was on time.")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /view all late/i })).not.toBeInTheDocument();
  });
});

describe("WeekdayPanel", () => {
  it("names the weekday with the highest absence", () => {
    render(<WeekdayPanel stats={makeWeekdays({ 0: [2, 1], 1: [1, 0] })} />);
    expect(screen.getByText(/Mons have the highest absence — 50.0% of expected days/)).toBeInTheDocument();
    expect(screen.getByRole("img", { name: "Absence rate by weekday" })).toBeInTheDocument();
  });

  it("does not invent a pattern when there are no absences, or no working days at all", () => {
    const { rerender } = render(<WeekdayPanel stats={makeWeekdays({ 0: [1, 0], 1: [1, 0] })} />);
    expect(screen.getByText(/no weekday stands out/i)).toBeInTheDocument();
    rerender(<WeekdayPanel stats={makeWeekdays()} />);
    expect(screen.getByText("No expected working days in this range.")).toBeInTheDocument();
  });
});

describe("PayrollReadiness", () => {
  const period = {
    id: "per-1",
    legal_entity_id: "le-1",
    period_start: "2026-10-01",
    period_end: "2026-10-31",
    label: "October 2026",
    status: "OPEN",
    last_validation_status: "BLOCKED",
    reopened_at: null,
  } as unknown as AttendancePeriod;
  const blocker = (key: string, label: string, count: number): AttentionItem => ({
    key,
    label,
    hint: "",
    count,
    unit: "records",
    employees: null,
    severity: "high",
  });

  it("shows progress, time left, the validation state and what is still in the way", () => {
    render(
      <PayrollReadiness
        period={period}
        companyName="ABC India"
        today="2026-10-28"
        blockers={[blocker("missing_punch", "Missing punches", 6), blocker("pending_regularization", "Regularization pending", 3)]}
        rangeLabel="28 Oct"
      />,
    );
    const card = screen.getByRole("region", { name: "Payroll readiness" });
    expect(within(card).getByText("3 days left")).toBeInTheDocument();
    expect(within(card).getByText("Day 28 of 31")).toBeInTheDocument();
    expect(within(card).getByRole("progressbar", { name: "Period progress" })).toHaveAttribute("aria-valuenow", "90");
    expect(within(card).getByText("Validation blocked")).toBeInTheDocument();
    expect(within(card).getByText("Missing punches")).toBeInTheDocument();
    expect(within(card).getByRole("link", { name: /open period/i })).toHaveAttribute("href", "/app/attendance-periods/per-1");
    expect(within(card).getByText(/counts cover 28 Oct, not the whole period/i)).toBeInTheDocument();
  });

  it("flags a period that has already ended and a clear queue", () => {
    render(<PayrollReadiness period={period} companyName="ABC India" today="2026-11-02" blockers={[]} rangeLabel="02 Nov" />);
    expect(screen.getByText("Ended 2 days ago")).toBeInTheDocument();
    expect(screen.getByText("Nothing urgent in 02 Nov.")).toBeInTheDocument();
  });
});
