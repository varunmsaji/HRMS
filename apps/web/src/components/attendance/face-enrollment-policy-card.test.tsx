import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

const toast = vi.fn();
vi.mock("@/components/common/toast", () => ({ useToast: () => ({ toast }) }));
vi.mock("@/lib/api/client", () => ({ apiClient: { get: vi.fn(), put: vi.fn() } }));

import { FaceEnrollmentPolicyCard } from "@/components/attendance/face-enrollment-policy-card";
import { apiClient } from "@/lib/api/client";

const mockedGet = vi.mocked(apiClient.get);
const mockedPut = vi.mocked(apiClient.put);
const PATH = "/attendance/face-enrollment-policy";

afterEach(() => vi.clearAllMocks());

describe("FaceEnrollmentPolicyCard", () => {
  it("shows the current policy and enables it with a PUT", async () => {
    mockedGet.mockResolvedValueOnce({ require_enrollment_on_onboarding: false });
    mockedPut.mockResolvedValueOnce({ require_enrollment_on_onboarding: true });
    render(<FaceEnrollmentPolicyCard />);
    const box = await screen.findByRole("checkbox", { name: /require face enrollment/i });
    await waitFor(() => expect(box).not.toBeDisabled());
    expect(box).not.toBeChecked();

    await userEvent.click(box);
    await waitFor(() => expect(box).toBeChecked());
    expect(mockedPut).toHaveBeenCalledWith(PATH, { require_enrollment_on_onboarding: true });
  });

  it("keeps the old value and reports an error when the save fails", async () => {
    mockedGet.mockResolvedValueOnce({ require_enrollment_on_onboarding: true });
    mockedPut.mockRejectedValueOnce(new Error("boom"));
    render(<FaceEnrollmentPolicyCard />);
    const box = await screen.findByRole("checkbox", { name: /require face enrollment/i });
    await waitFor(() => expect(box).not.toBeDisabled());
    await userEvent.click(box);
    await waitFor(() =>
      expect(toast).toHaveBeenCalledWith(expect.objectContaining({ variant: "danger" })),
    );
    expect(box).toBeChecked();
  });

  it("shows the server error and no toggle when the policy cannot be read (e.g. 403)", async () => {
    mockedGet.mockRejectedValueOnce(new Error("no access"));
    render(<FaceEnrollmentPolicyCard />);
    expect(await screen.findByRole("alert")).toBeInTheDocument();
    expect(screen.queryByRole("checkbox")).not.toBeInTheDocument();
  });
});
