import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { StatementDownload } from "@/components/attendance/statement-download";

const download = vi.fn();
const toast = vi.fn();

vi.mock("@/lib/api/client", () => ({ apiClient: { download: (path: string) => download(path) } }));
vi.mock("@/components/common/toast", () => ({ useToast: () => ({ toast }) }));

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe("StatementDownload", () => {
  it("downloads the month the page is showing, as a PDF unless another format is chosen", async () => {
    URL.createObjectURL = vi.fn(() => "blob:x");
    URL.revokeObjectURL = vi.fn();
    download.mockResolvedValue({ blob: new Blob(["x"]), filename: "statement_E1_2026-10.pdf" });
    render(<StatementDownload employeeId="e1" maxMonth="2026-11" month="2026-10" />);
    const user = userEvent.setup();
    expect(screen.queryByLabelText("Statement month")).not.toBeInTheDocument(); // the page owns the month
    await user.click(screen.getByRole("button", { name: "Download statement" }));
    await waitFor(() => expect(download).toHaveBeenCalledWith("/attendance/employees/e1/statement?month=2026-10&format=pdf"));
    await user.selectOptions(screen.getByLabelText("Statement format"), "xlsx");
    await user.click(screen.getByRole("button", { name: "Download statement" }));
    await waitFor(() => expect(download).toHaveBeenLastCalledWith("/attendance/employees/e1/statement?month=2026-10&format=xlsx"));
  });

  it("offers its own month picker, never beyond the current month, when the page has none", async () => {
    download.mockResolvedValue({ blob: new Blob(["x"]), filename: null });
    URL.createObjectURL = vi.fn(() => "blob:x");
    URL.revokeObjectURL = vi.fn();
    render(<StatementDownload employeeId="e1" maxMonth="2026-11" />);
    const picker = screen.getByLabelText("Statement month");
    expect(picker).toHaveAttribute("max", "2026-11");
    expect(picker).toHaveValue("2026-11");
    await userEvent.setup().click(screen.getByRole("button", { name: "Download statement" }));
    await waitFor(() => expect(download).toHaveBeenCalledWith(expect.stringContaining("month=2026-11")));
  });

  it("says when the statement could not be made", async () => {
    download.mockRejectedValue(new Error("nope"));
    render(<StatementDownload employeeId="e1" maxMonth="2026-11" />);
    await userEvent.setup().click(screen.getByRole("button", { name: "Download statement" }));
    await waitFor(() =>
      expect(toast).toHaveBeenCalledWith(expect.objectContaining({ title: "Could not download the statement", variant: "danger" })),
    );
  });
});
