import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { makeAbsentDay, makeDay } from "@/lib/attendance/__fixtures__/day";
import { buildMuster, indexEmployees } from "@/lib/attendance/dashboard";

import { ColumnChart, LineChart, ProportionBar } from "./charts";
import { MusterHeatmap } from "./muster-heatmap";
import { TrendChart } from "./trend-chart";

describe("LineChart", () => {
  const points = [
    { key: "a", label: "01 Oct", value: 80 },
    { key: "b", label: "02 Oct", value: null },
    { key: "c", label: "03 Oct", value: 100 },
  ];

  it("is named, and mirrors every point (including gaps) in a hidden data table", () => {
    render(<LineChart points={points} ariaLabel="Present %, daily" format={(v) => `${v}%`} yMax={100} />);
    expect(screen.getByRole("img", { name: "Present %, daily" })).toBeInTheDocument();
    const table = screen.getByRole("table", { name: "Present %, daily" });
    expect(within(table).getByText("80%")).toBeInTheDocument();
    expect(within(table).getByText("No data")).toBeInTheDocument();
  });

  it("breaks the line at a missing value instead of interpolating across it", () => {
    const { container } = render(<LineChart points={points} ariaLabel="x" format={(v) => String(v)} yMax={100} />);
    // Two isolated points on either side of the gap → no connecting path, two dots.
    expect(container.querySelectorAll("circle")).toHaveLength(2);
    expect(container.querySelectorAll("path")).toHaveLength(2);
  });
});

describe("ColumnChart / ProportionBar", () => {
  it("exposes both series as a table for assistive tech", () => {
    render(
      <ColumnChart
        ariaLabel="Worked vs scheduled"
        valueLabel="Worked"
        referenceLabel="Scheduled"
        format={(m) => `${m / 60}h`}
        data={[{ key: "d1", label: "01 Oct", value: 480, reference: 540 }]}
      />,
    );
    const table = screen.getByRole("table", { name: "Worked vs scheduled" });
    expect(within(table).getByText("8h")).toBeInTheDocument();
    expect(within(table).getByText("9h")).toBeInTheDocument();
  });

  it("renders only non-zero segments in proportion", () => {
    const { container } = render(
      <ProportionBar
        ariaLabel="dist"
        segments={[
          { key: "p", label: "Present", count: 3, barClass: "bg-success" },
          { key: "a", label: "Absent", count: 1, barClass: "bg-danger" },
          { key: "l", label: "Leave", count: 0, barClass: "bg-on-leave" },
        ]}
      />,
    );
    const segs = container.querySelectorAll<HTMLElement>("[role='img'] > div");
    expect(segs).toHaveLength(2);
    expect(segs[0].style.width).toBe("75%");
  });
});

describe("TrendChart", () => {
  const range = { from: "2026-10-01", to: "2026-10-14" };
  const rows = [
    makeDay({ employee_id: "e1", attendance_date: "2026-10-01" }),
    makeAbsentDay({ employee_id: "e2", attendance_date: "2026-10-01" }),
  ];

  it("maps rows to the chosen metric and switches with the selector", async () => {
    const user = userEvent.setup();
    render(<TrendChart rows={rows} range={range} />);
    const table = () => screen.getByRole("table", { name: /present %, daily/i });
    expect(within(table()).getAllByText("50.0%").length).toBeGreaterThan(0);

    await user.selectOptions(screen.getByLabelText("Trend metric"), "absent_pct");
    expect(screen.getByRole("img", { name: /absent %, daily/i })).toBeInTheDocument();

    await user.selectOptions(screen.getByLabelText("Trend metric"), "avg_hours");
    expect(within(screen.getByRole("table", { name: /average hours/i })).getByText("9.0h")).toBeInTheDocument();
  });

  it("offers weekly aggregation only when the range is long enough, and says when there's no data", async () => {
    const user = userEvent.setup();
    const { rerender } = render(<TrendChart rows={rows} range={{ from: "2026-10-01", to: "2026-10-05" }} />);
    expect(screen.queryByRole("group", { name: "Granularity" })).not.toBeInTheDocument();
    rerender(<TrendChart rows={rows} range={range} />);
    await user.click(screen.getByRole("button", { name: "weekly" }));
    expect(screen.getByRole("img", { name: /present %, weekly/i })).toBeInTheDocument();
    rerender(<TrendChart rows={[]} range={range} />);
    expect(screen.getByText(/no attendance recorded in this range to chart/i)).toBeInTheDocument();
  });
});

describe("MusterHeatmap", () => {
  const employees = indexEmployees([{ id: "e1", first_name: "Asha", last_name: "Rao", employee_code: "E-1" }]);
  const dates = ["2026-10-05", "2026-10-06", "2026-10-07"];
  const muster = buildMuster(
    [
      makeDay({ employee_id: "e1", attendance_date: "2026-10-05", id: "d1" }),
      makeAbsentDay({ employee_id: "e1", attendance_date: "2026-10-06", id: "d2" }),
    ],
    dates,
    employees,
  );

  it("never relies on colour alone: each cell has a glyph and a spoken status, and links to the day", () => {
    render(<MusterHeatmap muster={muster} />);
    const grid = screen.getByRole("table", { name: /attendance status by employee and day/i });
    expect(within(grid).getByText("05 Oct: Present")).toBeInTheDocument();
    expect(within(grid).getByText("06 Oct: Absent")).toBeInTheDocument();
    expect(within(grid).getByText("07 Oct: no record")).toBeInTheDocument();
    expect(within(grid).getByRole("link", { name: /06 oct: absent/i })).toHaveAttribute("href", "/app/attendance/d2");
    expect(within(grid).getByRole("link", { name: "Asha Rao" })).toHaveAttribute("href", "/app/attendance/employee/e1");
    expect(screen.getByRole("list", { name: "Legend" })).toBeInTheDocument();
  });
});
