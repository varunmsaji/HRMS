import { describe, expect, it } from "vitest";

import {
  balanceTone,
  collectLeaveTypes,
  filterEmployees,
  formatDays,
  hasAmount,
  pageSlice,
} from "@/lib/leave-ledger/matrix";
import type { LeaveBalance } from "@/lib/leave-ledger/types";

const bal = (type: string, code: string, name = code): LeaveBalance => ({
  employee_id: "e",
  leave_type_id: type,
  leave_type_code: code,
  leave_type_name: name,
  balance: "1",
  reserved_balance: "0",
});

describe("collectLeaveTypes", () => {
  it("returns each leave type once, ordered by code", () => {
    const cols = collectLeaveTypes([
      [bal("t-sl", "SL"), bal("t-cl", "CL")],
      [bal("t-cl", "CL"), bal("t-el", "EL")],
    ]);
    expect(cols.map((c) => c.code)).toEqual(["CL", "EL", "SL"]);
  });

  it("is empty when nobody has balances yet", () => {
    expect(collectLeaveTypes([])).toEqual([]);
    expect(collectLeaveTypes([[]])).toEqual([]);
  });
});

describe("formatDays", () => {
  it.each([
    ["5.00", "5"],
    ["4.50", "4.5"],
    ["-1.250", "-1.25"],
    ["0", "0"],
    ["12.345", "12.35"],
  ])("formats %s as %s", (input, output) => {
    expect(formatDays(input)).toBe(output);
  });

  it("leaves non-numeric values untouched instead of hiding them", () => {
    expect(formatDays("n/a")).toBe("n/a");
    expect(formatDays("")).toBe("");
  });
});

describe("balanceTone / hasAmount", () => {
  it("classifies balances", () => {
    expect(balanceTone("4.5")).toBe("positive");
    expect(balanceTone("-1")).toBe("negative");
    expect(balanceTone("0.00")).toBe("zero");
    expect(balanceTone("junk")).toBe("zero");
  });

  it("detects a non-zero amount", () => {
    expect(hasAmount("0.0")).toBe(false);
    expect(hasAmount("2")).toBe(true);
    expect(hasAmount("x")).toBe(false);
  });
});

describe("filterEmployees", () => {
  const people = [
    { id: "1", first_name: "Asha", last_name: "Rao", employee_code: "EMP-0001" },
    { id: "2", first_name: "Bala", last_name: "Iyer", employee_code: "EMP-0002" },
  ];

  it("matches name or code, case-insensitively", () => {
    expect(filterEmployees(people, "asha").map((p) => p.id)).toEqual(["1"]);
    expect(filterEmployees(people, "0002").map((p) => p.id)).toEqual(["2"]);
  });

  it("returns everyone for a blank query, without mutating the input", () => {
    const result = filterEmployees(people, "   ");
    expect(result).toHaveLength(2);
    expect(result).not.toBe(people);
  });
});

describe("pageSlice", () => {
  const items = Array.from({ length: 45 }, (_, i) => i + 1);

  it("returns the requested 1-based page", () => {
    const p = pageSlice(items, 2, 20);
    expect(p.rows[0]).toBe(21);
    expect(p.rows).toHaveLength(20);
    expect(p).toMatchObject({ page: 2, totalPages: 3, total: 45 });
  });

  it("clamps an out-of-range page", () => {
    expect(pageSlice(items, 99, 20).page).toBe(3);
    expect(pageSlice(items, 0, 20).page).toBe(1);
  });

  it("handles an empty list as a single empty page", () => {
    expect(pageSlice([], 1, 20)).toMatchObject({ rows: [], page: 1, totalPages: 1, total: 0 });
  });
});
