import { cleanup, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { EmployeePicker } from "@/components/attendance/dashboard/employee-picker";
import type { EmployeeLite } from "@/lib/attendance/dashboard";

const PEOPLE: EmployeeLite[] = [
  { id: "1", first_name: "Meera", last_name: "Pillai", employee_code: "DEMO-002" },
  { id: "2", first_name: "Arjun", last_name: "Nair", employee_code: "DEMO-001" },
  { id: "3", first_name: "Manoj", last_name: "Kumar", employee_code: "DEMO-016" },
];

afterEach(cleanup);

function setup(value = "") {
  const onChange = vi.fn();
  render(<EmployeePicker id="p" employees={PEOPLE} value={value} onChange={onChange} />);
  return onChange;
}

describe("EmployeePicker", () => {
  it("finds people by name or by employee code, alphabetically", async () => {
    const user = userEvent.setup();
    setup();
    const box = screen.getByRole("combobox", { name: "Employee" });
    await user.type(box, "a"); // in every name; the codes have no "a"
    expect(screen.getAllByRole("option").map((o) => o.textContent)).toEqual(["Arjun NairDEMO-001", "Manoj KumarDEMO-016", "Meera PillaiDEMO-002"]);
    await user.clear(box);
    await user.type(box, "demo-001");
    expect(screen.getAllByRole("option").map((o) => o.textContent)).toEqual(["Arjun NairDEMO-001"]);
  });

  it("chooses with the mouse or with the keyboard", async () => {
    const user = userEvent.setup();
    const onChange = setup();
    await user.type(screen.getByRole("combobox", { name: "Employee" }), "a");
    await user.click(screen.getByRole("option", { name: /Meera/ }));
    expect(onChange).toHaveBeenLastCalledWith("1");

    // Arjun is first, so one ArrowDown lands on Manoj.
    await user.type(screen.getByRole("combobox", { name: "Employee" }), "a{ArrowDown}{Enter}");
    expect(onChange).toHaveBeenLastCalledWith("3");
  });

  it("says so when nobody matches, and Escape closes the list", async () => {
    const user = userEvent.setup();
    setup();
    const box = screen.getByRole("combobox", { name: "Employee" });
    await user.type(box, "zzz");
    expect(screen.getByText(/No employee matches/)).toBeInTheDocument();
    await user.keyboard("{Escape}");
    expect(screen.queryByRole("listbox")).not.toBeInTheDocument();
  });

  it("shows the chosen person as a pill that clears", async () => {
    const user = userEvent.setup();
    const onChange = setup("2");
    expect(screen.getByText("Arjun Nair")).toBeInTheDocument();
    expect(screen.queryByRole("combobox")).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Clear employee Arjun Nair" }));
    expect(onChange).toHaveBeenCalledWith("");
  });

  it("only lists the first few matches so it stays short with a big company", async () => {
    const many = Array.from({ length: 40 }, (_, i) => ({ id: `x${i}`, first_name: `Person${String(i).padStart(2, "0")}`, last_name: "Test", employee_code: `C${i}` }));
    render(<EmployeePicker id="q" employees={many} value="" onChange={vi.fn()} />);
    await userEvent.setup().click(screen.getByRole("combobox", { name: "Employee" }));
    expect(screen.getAllByRole("option")).toHaveLength(8);
  });
});
