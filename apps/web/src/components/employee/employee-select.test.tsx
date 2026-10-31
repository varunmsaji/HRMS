import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("@/lib/api/client", () => ({ apiClient: { getList: vi.fn() } }));

import { EmployeeSelect } from "@/components/employee/employee-select";
import { apiClient } from "@/lib/api/client";
import { useEmployeeDirectory } from "@/lib/employee/use-employee-directory";

const mockedGetList = vi.mocked(apiClient.getList);
const TOTAL = 230;
const ALL = Array.from({ length: TOTAL }, (_, i) => ({
  id: `emp-${i + 1}`,
  first_name: `Person${i + 1}`,
  last_name: null,
  employee_code: `E${i + 1}`,
}));

function Harness({ onChange }: { onChange?: (id: string) => void }) {
  const directory = useEmployeeDirectory();
  const [value, setValue] = useState("");
  return (
    <EmployeeSelect
      directory={directory}
      value={value}
      onChange={(id) => {
        setValue(id);
        onChange?.(id);
      }}
    />
  );
}

describe("EmployeeSelect", () => {
  afterEach(() => mockedGetList.mockReset());
  function serve() {
    mockedGetList.mockImplementation(((_p: string, q: { page: number; per_page: number }) =>
      Promise.resolve({
        data: ALL.slice((q.page - 1) * q.per_page, q.page * q.per_page),
        pagination: { page: q.page, per_page: q.per_page, total: TOTAL, total_pages: Math.ceil(TOTAL / q.per_page) },
        meta: { request_id: "r" },
      })) as never);
  }

  it("says the list is partial and lets the user reach an employee past the first 100", async () => {
    serve();
    const user = userEvent.setup();
    const onChange = vi.fn();
    render(<Harness onChange={onChange} />);

    expect(await screen.findByText(/showing 100 of 230 employees/i)).toBeInTheDocument();
    const select = screen.getByRole("combobox");
    expect(within(select).queryByRole("option", { name: /Person230/ })).toBeNull();

    await user.click(screen.getByRole("button", { name: /load more/i }));
    await user.click(await screen.findByRole("button", { name: /load more/i }).catch(() => screen.getByRole("button", { name: /load more/i })));
    await waitFor(() => expect(screen.queryByText(/showing/i)).not.toBeInTheDocument());

    await user.selectOptions(select, "emp-230");
    expect(onChange).toHaveBeenLastCalledWith("emp-230");
  });

  it("filters only what is loaded and states that it does", async () => {
    serve();
    const user = userEvent.setup();
    render(<Harness />);
    await screen.findByText(/showing 100 of 230/i);

    await user.type(screen.getByLabelText(/filter loaded employees/i), "Person7");
    expect(screen.getByText(/filter searches only these/i)).toBeInTheDocument();
    const options = within(screen.getByRole("combobox")).getAllByRole("option");
    // "Choose…" + Person7, Person70..Person79 (all within the loaded first 100)
    expect(options.length).toBe(12);
  });

  it("keeps the current selection as an option when more pages load", async () => {
    serve();
    const user = userEvent.setup();
    render(<Harness />);
    await screen.findByText(/showing 100 of 230/i);
    await user.selectOptions(screen.getByRole("combobox"), "emp-5");
    await user.click(screen.getByRole("button", { name: /load more/i }));
    await waitFor(() => expect(screen.getByText(/showing 200 of 230/i)).toBeInTheDocument());
    expect(screen.getByRole("combobox")).toHaveValue("emp-5");
  });

  it("shows an error with retry instead of an empty list when loading fails", async () => {
    mockedGetList.mockRejectedValue(new Error("down"));
    render(<Harness />);
    expect(await screen.findByRole("alert")).toHaveTextContent(/could not load employees/i);
    expect(screen.getByRole("button", { name: /retry/i })).toBeInTheDocument();
  });
});
