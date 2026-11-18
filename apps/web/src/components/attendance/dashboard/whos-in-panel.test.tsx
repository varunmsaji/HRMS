import { cleanup, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { WhosInPanel, type RowMismatch, type WhosInRow } from "@/components/attendance/dashboard/whos-in-panel";
import type { EmployeeLite } from "@/lib/attendance/dashboard";
import { makeAbsentDay, makeDay } from "@/lib/attendance/__fixtures__/day";

const DATE = "2026-11-18";

function person(id: string, first: string): EmployeeLite {
  return { id, first_name: first, last_name: "Test", employee_code: id.toUpperCase() };
}

const EMPLOYEES = new Map(
  [person("a", "Asha"), person("b", "Bela"), person("c", "Chitra"), person("d", "Dev"), person("e", "Esha")].map((e) => [e.id, e]),
);

// Alphabetically Asha, Bela, Chitra, Dev, Esha — but Esha has a missing punch and Chitra has no
// record, so they must come first.
const ROWS: WhosInRow[] = [
  { id: "r-a", employeeId: "a", day: makeDay({ id: "d-a", employee_id: "a", attendance_date: DATE }) },
  { id: "r-b", employeeId: "b", day: makeDay({ id: "d-b", employee_id: "b", attendance_date: DATE, is_late: true, late_minutes: 12 }) },
  { id: "r-c", employeeId: "c", day: null },
  { id: "r-d", employeeId: "d", day: makeAbsentDay({ id: "d-d", employee_id: "d", attendance_date: DATE }) },
  {
    id: "r-e",
    employeeId: "e",
    day: makeDay({ id: "d-e", employee_id: "e", attendance_date: DATE, attendance_status: "INCOMPLETE", missing_punch: true, actual_last_out: null }),
  },
];

function renderList(props: Partial<React.ComponentProps<typeof WhosInPanel>> = {}) {
  return render(
    <WhosInPanel rows={ROWS} employeesById={EMPLOYEES} shiftNames={new Map()} timezone="UTC" fallbackDate={DATE} {...props} />,
  );
}

function namesInOrder(): string[] {
  const table = screen.getAllByRole("table")[0];
  return within(table)
    .getAllByRole("link")
    .filter((a) => a.getAttribute("href")?.startsWith("/app/attendance/employee/"))
    .map((a) => a.textContent ?? "");
}

afterEach(cleanup);

describe("WhosInPanel", () => {
  it("lists what HR has to fix or chase first, then the people who are fine", () => {
    renderList();
    // Fix: Esha. Chase: Chitra (no record) and Dev (absent), alphabetically. Late: Bela. Fine: Asha.
    expect(namesInOrder()).toEqual(["Esha Test", "Chitra Test", "Dev Test", "Bela Test", "Asha Test"]);
  });

  it("lets HR sort by name instead, and back to needs-attention order from the Status header", async () => {
    const user = userEvent.setup();
    renderList();
    await user.click(screen.getByRole("button", { name: /^Employee/ }));
    expect(namesInOrder()).toEqual(["Asha Test", "Bela Test", "Chitra Test", "Dev Test", "Esha Test"]);
    await user.click(screen.getByRole("button", { name: /^Status/ }));
    expect(namesInOrder()[0]).toBe("Esha Test");
  });

  it("offers no tick boxes without permission, and no repeated per-row buttons either way", () => {
    renderList();
    expect(screen.queryByRole("checkbox")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /mark .* present/i })).not.toBeInTheDocument();
  });

  it("selects everyone with nothing punched in one click and marks them together", async () => {
    const onMarkMany = vi.fn();
    const user = userEvent.setup();
    renderList({ onMarkMany });
    // Only Chitra (no record) and Dev (absent, no punches) can be marked present.
    expect(screen.getByText("2 employees have nothing punched.")).toBeInTheDocument();
    // The table and the small-screen cards both render in jsdom; check the table.
    const table = within(screen.getAllByRole("table")[0]);
    expect(table.getAllByRole("checkbox", { name: /^Select (Chitra|Dev) Test$/ })).toHaveLength(2);
    expect(table.queryByRole("checkbox", { name: "Select Asha Test" })).not.toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Select all 2" }));
    expect(screen.getByText("selected")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Mark 2 present" }));
    expect(onMarkMany).toHaveBeenCalledWith({
      employees: [
        { id: "c", label: "Chitra Test" },
        { id: "d", label: "Dev Test" },
      ],
      date: DATE,
    });
  });

  it("marks just the ticked people, and can clear the selection", async () => {
    const onMarkMany = vi.fn();
    const user = userEvent.setup();
    renderList({ onMarkMany });
    await user.click(screen.getAllByRole("checkbox", { name: "Select Dev Test" })[0]);
    await user.click(screen.getByRole("button", { name: "Mark 1 present" }));
    expect(onMarkMany).toHaveBeenCalledWith({ employees: [{ id: "d", label: "Dev Test" }], date: DATE });
    await user.click(screen.getByRole("button", { name: "Clear" }));
    expect(screen.getByText("2 employees have nothing punched.")).toBeInTheDocument();
  });

  it("does not offer bulk marking on a list that can span several days", () => {
    renderList({ onMarkMany: vi.fn(), showDate: true });
    expect(screen.queryByRole("checkbox")).not.toBeInTheDocument();
    expect(screen.queryByText(/nothing punched/)).not.toBeInTheDocument();
  });

  describe("mismatches", () => {
    const FIX = vi.fn();
    const mismatchFor = (row: WhosInRow): RowMismatch | null =>
      row.employeeId === "e"
        ? {
            reason: "Checked in but never checked out.",
            fixes: [
              { key: "punch", label: "Add punch-out", ariaLabel: "Add punch-out for Esha Test", onClick: FIX, primary: true },
              { key: "open", label: "Open day", ariaLabel: "Open Esha Test's day", href: "/app/attendance/d-e" },
            ],
          }
        : null;

    it("says what is wrong on the row and offers the fix there", async () => {
      FIX.mockClear();
      const user = userEvent.setup();
      renderList({ mismatchFor });
      const table = within(screen.getAllByRole("table")[0]);
      expect(table.getByText("Checked in but never checked out.")).toBeInTheDocument();
      await user.click(table.getByRole("button", { name: "Add punch-out for Esha Test" }));
      expect(FIX).toHaveBeenCalledTimes(1);
      expect(table.getByRole("link", { name: "Open Esha Test's day" })).toHaveAttribute("href", "/app/attendance/d-e");
    });

    it("counts the days that need fixing and can narrow the list to just them", async () => {
      const user = userEvent.setup();
      renderList({ mismatchFor });
      expect(screen.getByText((_, el) => el?.tagName === "SPAN" && el.textContent === "1 day doesn't add up and need fixing.")).toBeInTheDocument();
      expect(namesInOrder()).toHaveLength(5);
      await user.click(screen.getByRole("button", { name: "Show only these" }));
      expect(namesInOrder()).toEqual(["Esha Test"]);
      await user.click(screen.getByRole("button", { name: "Show everyone" }));
      expect(namesInOrder()).toHaveLength(5);
    });

    it("shows nothing extra when no row has a mismatch", () => {
      renderList({ mismatchFor: () => null });
      expect(screen.queryByText(/need fixing/)).not.toBeInTheDocument();
    });
  });
});
