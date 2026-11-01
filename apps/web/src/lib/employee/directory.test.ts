import { describe, expect, it } from "vitest";

import { directoryRowsPath, employeesToCsv } from "./directory";

describe("directory helpers", () => {
  it("builds a repeated ids query", () => {
    expect(directoryRowsPath(["a", "b"])).toBe("/employees/directory/rows?ids=a&ids=b");
  });

  it("quotes csv cells that contain commas or quotes", () => {
    const csv = employeesToCsv([
      { code: "E1", name: 'Ann "A" Lee', email: null, mobile: null, status: "ACTIVE", designation: "Lead, QA", department: null, manager: null, shift: null },
    ]);
    expect(csv.split("\n")[1]).toBe('E1,"Ann ""A"" Lee",,,ACTIVE,"Lead, QA",,,');
  });
});
