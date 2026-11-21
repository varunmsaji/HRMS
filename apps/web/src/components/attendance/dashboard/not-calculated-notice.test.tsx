import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

const toast = vi.fn();
vi.mock("@/components/common/toast", () => ({ useToast: () => ({ toast }) }));
vi.mock("@/lib/api/client", () => ({ apiClient: { post: vi.fn() } }));

import { NotCalculatedNotice } from "@/components/attendance/dashboard/not-calculated-notice";
import { apiClient } from "@/lib/api/client";

const post = vi.mocked(apiClient.post);

beforeEach(() => {
  toast.mockClear();
  post.mockReset();
});

describe("NotCalculatedNotice", () => {
  it("says nothing when every employed person has a day", () => {
    const { container } = render(
      <NotCalculatedNotice date="2026-11-18" dateLabel="18 Nov" employeeIds={[]} canRecalculate />,
    );
    expect(container).toBeEmptyDOMElement();
  });

  it("names the count and the date, and queues only those people for that date", async () => {
    post.mockResolvedValue({} as never);
    render(<NotCalculatedNotice date="2026-11-18" dateLabel="18 Nov" employeeIds={["e1", "e2"]} canRecalculate />);
    expect(screen.getByRole("note")).toHaveTextContent("Not calculated: 2.");
    expect(screen.getByRole("note")).toHaveTextContent("no calculated day for 18 Nov");

    await userEvent.click(screen.getByRole("button", { name: "Recalculate" }));
    expect(post).toHaveBeenCalledWith("/attendance/days/calculate-range", {
      date_from: "2026-11-18",
      date_to: "2026-11-18",
      employee_ids: ["e1", "e2"],
    });
    await waitFor(() => expect(toast).toHaveBeenCalledWith(expect.objectContaining({ title: "Calculation queued" })));
  });

  it("tells the viewer without the permission but gives no button", () => {
    render(<NotCalculatedNotice date="2026-11-18" dateLabel="18 Nov" employeeIds={["e1"]} canRecalculate={false} />);
    expect(screen.getByRole("note")).toHaveTextContent("Not calculated: 1.");
    expect(screen.queryByRole("button")).toBeNull();
  });

  it("reports a failed request instead of pretending it was queued", async () => {
    post.mockRejectedValue(new Error("boom"));
    render(<NotCalculatedNotice date="2026-11-18" dateLabel="18 Nov" employeeIds={["e1"]} canRecalculate />);
    await userEvent.click(screen.getByRole("button", { name: "Recalculate" }));
    await waitFor(() => expect(toast).toHaveBeenCalledWith(expect.objectContaining({ title: "Could not queue the calculation" })));
  });
});
