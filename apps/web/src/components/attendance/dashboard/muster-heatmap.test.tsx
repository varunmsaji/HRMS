import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { MusterHeatmap } from "@/components/attendance/dashboard/muster-heatmap";
import type { Muster } from "@/lib/attendance/dashboard";
import { makeDay } from "@/lib/attendance/__fixtures__/day";

const download = vi.fn();
const toast = vi.fn();

vi.mock("@/lib/api/client", () => ({ apiClient: { download: (path: string) => download(path) } }));
vi.mock("@/components/common/toast", () => ({ useToast: () => ({ toast }) }));
vi.mock("next/link", () => ({ default: ({ children, href }: { children: React.ReactNode; href: string }) => <a href={href}>{children}</a> }));

const MUSTER: Muster = {
  dates: ["2026-11-01"],
  rows: [{ employeeId: "e1", name: "Asha", code: "E1", cells: new Map([["2026-11-01", makeDay({ attendance_date: "2026-11-01" })]]) }],
};
const QUERY = { date_from: "2026-11-01", date_to: "2026-11-30", department_id: "d1" };

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe("MusterHeatmap export", () => {
  it("asks the server for the register with the dashboard's window and filters", async () => {
    URL.createObjectURL = vi.fn(() => "blob:x");
    URL.revokeObjectURL = vi.fn();
    download.mockResolvedValue({ blob: new Blob(["x"]), filename: "muster-register_a_b.csv" });
    render(<MusterHeatmap muster={MUSTER} exportQuery={QUERY} />);
    await userEvent.setup().click(screen.getByRole("button", { name: "Export muster register" }));
    await waitFor(() => expect(download).toHaveBeenCalledWith("/attendance/export/muster?date_from=2026-11-01&date_to=2026-11-30&department_id=d1"));
    expect(toast).not.toHaveBeenCalled();
  });

  it("tells the user when the download fails", async () => {
    download.mockRejectedValue(new Error("boom"));
    render(<MusterHeatmap muster={MUSTER} exportQuery={QUERY} />);
    await userEvent.setup().click(screen.getByRole("button", { name: "Export muster register" }));
    await waitFor(() => expect(toast).toHaveBeenCalledWith(expect.objectContaining({ title: "Could not export the register", variant: "danger" })));
  });
});
