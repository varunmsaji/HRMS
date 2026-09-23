import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

const toastMock = vi.fn();
vi.mock("@/components/common/toast", () => ({
  useToast: () => ({ toast: toastMock }),
}));

vi.mock("@/lib/api/client", () => ({
  apiClient: { post: vi.fn() },
}));

import { LeaveApplicationReviewDialog } from "@/components/leave-application/leave-application-review-dialog";
import { apiClient } from "@/lib/api/client";
import { ApiError } from "@/lib/api/errors";
import type { LeaveApplication } from "@/lib/leave-application/types";

const mockedPost = vi.mocked(apiClient.post);

const application = {
  id: "app-1",
  total_days: "2.00",
  lop_days: "0.00",
  version: 3,
} as LeaveApplication;

describe("LeaveApplicationReviewDialog", () => {
  it("offers approving the uncovered days as loss of pay after a balance shortfall", async () => {
    const onDone = vi.fn();
    mockedPost.mockRejectedValueOnce(
      new ApiError({
        status: 409,
        code: "LEAVE_APPLICATION_BALANCE_SHORTFALL",
        message: "short",
        details: [
          {
            field: "total_days",
            code: "LEAVE_APPLICATION_BALANCE_SHORTFALL",
            message: "short",
            context: { available: "1.00", shortfall: "1.00" },
          },
        ],
      }),
    );
    mockedPost.mockResolvedValueOnce({ ...application, status: "APPROVED", lop_days: "1.00" });

    render(
      <LeaveApplicationReviewDialog
        open
        onOpenChange={vi.fn()}
        application={application}
        action="approve"
        onDone={onDone}
      />,
    );

    await userEvent.click(screen.getByRole("button", { name: "Approve" }));
    expect(await screen.findByText("Not enough leave balance")).toBeInTheDocument();
    expect(screen.getByText(/covers 1\.00\s+of 2\.00 days — 1\.00 short/)).toBeInTheDocument();

    await userEvent.click(
      screen.getByRole("button", { name: "Approve, uncovered days as loss of pay" }),
    );
    await waitFor(() => expect(onDone).toHaveBeenCalled());
    expect(mockedPost).toHaveBeenLastCalledWith(
      "/leave-applications/app-1/approve",
      { reviewer_comment: undefined, excess_as_lop: true },
      { ifMatch: "3" },
    );
  });
});
