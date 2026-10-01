import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("@/components/common/toast", () => ({
  useToast: () => ({ toast: vi.fn() }),
}));

vi.mock("@/lib/api/client", () => ({
  apiClient: { get: vi.fn(), post: vi.fn(), delete: vi.fn(), download: vi.fn() },
}));

vi.mock("@/lib/auth/auth-context", () => ({
  useAuth: () => ({ user: { company_timezone: "Asia/Kolkata" } }),
}));

import { FaceEnrollmentCard } from "@/components/attendance/face-enrollment-card";
import { apiClient } from "@/lib/api/client";
import type { FaceEnrollmentStatus, FaceProfile } from "@/lib/attendance/types";

const mockedGet = vi.mocked(apiClient.get);
const mockedPost = vi.mocked(apiClient.post);
const mockedDelete = vi.mocked(apiClient.delete);
const mockedDownload = vi.mocked(apiClient.download);

const BASE = "/attendance/face-profiles/emp-1";

const PROFILE: FaceProfile = {
  id: "fp-1",
  employee_id: "emp-1",
  provider: "LUXAND",
  status: "PENDING_APPROVAL",
  reference_photo_count: 5,
  consent_recorded_at: "2026-10-01T02:11:00Z",
  enrolled_at: "2026-10-01T02:11:00Z",
  enrolled_by_user_id: "user-emp",
  has_review_photo: true,
  reviewed_at: null,
  reviewed_by_user_id: null,
  review_note: null,
  revoked_at: null,
  revoked_by_user_id: null,
};

const WINDOW = {
  id: "w-1",
  employee_id: "emp-1",
  status: "OPEN" as const,
  opened_by_user_id: "user-hr",
  opened_at: "2026-10-01T02:00:00Z",
  expires_at: "2026-10-03T02:00:00Z",
};

function statusSequence(...states: FaceEnrollmentStatus[]) {
  for (const state of states) mockedGet.mockResolvedValueOnce(state);
}

function renderCard() {
  return render(<FaceEnrollmentCard employeeId="emp-1" employeeLabel="Priya Sharma" />);
}

describe("FaceEnrollmentCard", () => {
  afterEach(() => {
    vi.clearAllMocks();
  });

  it("opens a one-time enrollment window for an employee with no profile", async () => {
    statusSequence({ profile: null, open_window: null }, { profile: null, open_window: WINDOW });
    mockedPost.mockResolvedValue(WINDOW);
    const user = userEvent.setup();
    renderCard();

    await user.click(await screen.findByRole("button", { name: "Open face enrollment" }));

    expect(mockedPost).toHaveBeenCalledWith(`${BASE}/enrollment-window`);
    expect(await screen.findByText("Enrollment open")).toBeInTheDocument();
    expect(screen.getByText(/can set up face attendance in the mobile app until/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Cancel enrollment" })).toBeInTheDocument();
  });

  it("cancels an open window", async () => {
    statusSequence({ profile: null, open_window: WINDOW }, { profile: null, open_window: null });
    mockedDelete.mockResolvedValue(undefined);
    const user = userEvent.setup();
    renderCard();

    await user.click(await screen.findByRole("button", { name: "Cancel enrollment" }));

    expect(mockedDelete).toHaveBeenCalledWith(`${BASE}/enrollment-window`);
    expect(await screen.findByRole("button", { name: "Open face enrollment" })).toBeInTheDocument();
  });

  it("shows the submitted photo and approves it", async () => {
    statusSequence(
      { profile: PROFILE, open_window: null },
      { profile: { ...PROFILE, status: "ENROLLED", has_review_photo: false, reviewed_at: "2026-10-01T03:00:00Z" }, open_window: null },
    );
    mockedDownload.mockResolvedValue({ blob: new Blob([new Uint8Array([0xff, 0xd8])], { type: "image/jpeg" }), filename: null });
    mockedPost.mockResolvedValue({ ...PROFILE, status: "ENROLLED" });
    const user = userEvent.setup();
    renderCard();

    expect(await screen.findByText("Awaiting approval")).toBeInTheDocument();
    const photo = await screen.findByAltText("Face submitted for Priya Sharma");
    expect(photo.getAttribute("src")).toMatch(/^data:image\/jpeg;base64,/);
    expect(mockedDownload).toHaveBeenCalledWith(`${BASE}/review-photo`);

    await user.click(screen.getByRole("button", { name: "Approve" }));

    expect(mockedPost).toHaveBeenCalledWith(`${BASE}/approve`);
    expect(await screen.findByText("Enrolled")).toBeInTheDocument();
    expect(screen.queryByAltText("Face submitted for Priya Sharma")).not.toBeInTheDocument();
  });

  it("rejects with a reason", async () => {
    statusSequence(
      { profile: PROFILE, open_window: null },
      {
        profile: { ...PROFILE, status: "REJECTED", has_review_photo: false, reviewed_at: "2026-10-01T03:00:00Z", review_note: "Different person" },
        open_window: null,
      },
    );
    mockedDownload.mockResolvedValue({ blob: new Blob(["x"], { type: "image/jpeg" }), filename: null });
    mockedPost.mockResolvedValue({ ...PROFILE, status: "REJECTED" });
    const user = userEvent.setup();
    renderCard();

    await user.click(await screen.findByRole("button", { name: "Reject" }));
    await user.type(screen.getByLabelText(/Reason/), "Different person");
    const confirm = screen.getAllByRole("button", { name: "Reject" }).at(-1)!;
    await user.click(confirm);

    await waitFor(() => expect(mockedPost).toHaveBeenCalledWith(`${BASE}/reject`, { note: "Different person" }));
    expect(await screen.findByText("Rejected")).toBeInTheDocument();
    expect(screen.getByText(/Different person/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Open face enrollment" })).toBeInTheDocument();
  });

  it("revokes an enrolled profile after confirmation", async () => {
    const enrolled = { ...PROFILE, status: "ENROLLED" as const, has_review_photo: false, reviewed_at: "2026-10-01T03:00:00Z" };
    statusSequence(
      { profile: enrolled, open_window: null },
      { profile: { ...enrolled, status: "REVOKED", revoked_at: "2026-10-02T03:00:00Z" }, open_window: null },
    );
    mockedDelete.mockResolvedValue({ ...enrolled, status: "REVOKED" });
    const user = userEvent.setup();
    renderCard();

    await user.click(await screen.findByRole("button", { name: "Revoke" }));
    expect(mockedDelete).not.toHaveBeenCalled();
    await user.click(screen.getAllByRole("button", { name: "Revoke" }).at(-1)!);

    await waitFor(() => expect(mockedDelete).toHaveBeenCalledWith(BASE));
    expect(await screen.findByText("Revoked")).toBeInTheDocument();
  });
});
