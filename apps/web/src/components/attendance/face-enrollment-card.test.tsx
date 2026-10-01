import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("@/components/common/toast", () => ({
  useToast: () => ({ toast: vi.fn() }),
}));

vi.mock("@/lib/api/client", () => ({
  apiClient: { get: vi.fn(), post: vi.fn(), delete: vi.fn() },
}));

vi.mock("@/lib/auth/auth-context", () => ({
  useAuth: () => ({ user: { company_timezone: "Asia/Kolkata" } }),
}));

import { FaceEnrollmentCard } from "@/components/attendance/face-enrollment-card";
import { apiClient } from "@/lib/api/client";
import { ApiError } from "@/lib/api/errors";
import type { FaceProfile } from "@/lib/attendance/types";

const mockedGet = vi.mocked(apiClient.get);
const mockedPost = vi.mocked(apiClient.post);
const mockedDelete = vi.mocked(apiClient.delete);

const ENROLLED: FaceProfile = {
  id: "fp-1",
  employee_id: "emp-1",
  provider: "LUXAND",
  status: "ENROLLED",
  reference_photo_count: 1,
  consent_recorded_at: "2026-10-01T02:11:00Z",
  enrolled_at: "2026-10-01T02:11:00Z",
  enrolled_by_user_id: "user-1",
  revoked_at: null,
  revoked_by_user_id: null,
};

function notFound() {
  return new ApiError({ status: 404, code: "FACE_PROFILE_NOT_FOUND", message: "none" });
}

function jpeg(name = "face.jpg") {
  return new File([new Uint8Array([0xff, 0xd8, 0xff, 0xe0])], name, { type: "image/jpeg" });
}

describe("FaceEnrollmentCard", () => {
  afterEach(() => {
    mockedGet.mockReset();
    mockedPost.mockReset();
    mockedDelete.mockReset();
  });

  it("enrolls only after a photo is chosen and consent is confirmed", async () => {
    mockedGet.mockRejectedValue(notFound());
    mockedPost.mockResolvedValue(ENROLLED);
    const user = userEvent.setup();
    render(<FaceEnrollmentCard employeeId="emp-1" employeeLabel="Priya Sharma" />);

    await user.click(await screen.findByRole("button", { name: "Enroll face" }));
    const submit = screen.getByRole("button", { name: "Enroll" });
    expect(submit).toBeDisabled();

    await user.upload(screen.getByLabelText("Face photo"), jpeg());
    expect(submit).toBeDisabled();

    await user.click(screen.getByRole("checkbox"));
    expect(submit).toBeEnabled();
    await user.click(submit);

    await waitFor(() => expect(mockedPost).toHaveBeenCalledTimes(1));
    const [path, body] = mockedPost.mock.calls[0];
    expect(path).toBe("/attendance/face-profiles/emp-1");
    const form = body as FormData;
    expect(form.get("consent_confirmed")).toBe("true");
    expect((form.get("photo") as File).name).toBe("face.jpg");
    expect(await screen.findByText(/1 of 5 reference photos/)).toBeInTheDocument();
  });

  it("rejects a non-image file before uploading", async () => {
    mockedGet.mockRejectedValue(notFound());
    const user = userEvent.setup({ applyAccept: false });
    render(<FaceEnrollmentCard employeeId="emp-1" employeeLabel="Priya Sharma" />);

    await user.click(await screen.findByRole("button", { name: "Enroll face" }));
    await user.upload(
      screen.getByLabelText("Face photo"),
      new File(["%PDF"], "doc.pdf", { type: "application/pdf" }),
    );

    expect(screen.getByRole("alert")).toHaveTextContent("JPEG or PNG");
    expect(mockedPost).not.toHaveBeenCalled();
  });

  it("shows the server's reason when no face is detected", async () => {
    mockedGet.mockRejectedValue(notFound());
    mockedPost.mockRejectedValue(
      new ApiError({ status: 422, code: "FACE_NOT_DETECTED", message: "No face was detected in the photo." }),
    );
    const user = userEvent.setup();
    render(<FaceEnrollmentCard employeeId="emp-1" employeeLabel="Priya Sharma" />);

    await user.click(await screen.findByRole("button", { name: "Enroll face" }));
    await user.upload(screen.getByLabelText("Face photo"), jpeg());
    await user.click(screen.getByRole("checkbox"));
    await user.click(screen.getByRole("button", { name: "Enroll" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("No face was detected");
  });

  it("adds a photo without asking for consent again, and disables it at the limit", async () => {
    mockedGet.mockResolvedValue(ENROLLED);
    mockedPost.mockResolvedValue({ ...ENROLLED, reference_photo_count: 5 });
    const user = userEvent.setup();
    render(<FaceEnrollmentCard employeeId="emp-1" employeeLabel="Priya Sharma" />);

    await user.click(await screen.findByRole("button", { name: "Add photo" }));
    expect(screen.queryByRole("checkbox")).not.toBeInTheDocument();
    await user.upload(screen.getByLabelText("Face photo"), jpeg());
    const dialogSubmit = screen.getAllByRole("button", { name: "Add photo" }).at(-1)!;
    await user.click(dialogSubmit);

    await waitFor(() =>
      expect(mockedPost).toHaveBeenCalledWith("/attendance/face-profiles/emp-1/photos", expect.any(FormData)),
    );
    expect(await screen.findByText(/5 of 5 reference photos/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Add photo" })).toBeDisabled();
  });

  it("revokes after confirmation", async () => {
    mockedGet.mockResolvedValue(ENROLLED);
    mockedDelete.mockResolvedValue({
      ...ENROLLED,
      status: "REVOKED",
      revoked_at: "2026-10-01T02:30:00Z",
    });
    const user = userEvent.setup();
    render(<FaceEnrollmentCard employeeId="emp-1" employeeLabel="Priya Sharma" />);

    await user.click(await screen.findByRole("button", { name: "Revoke" }));
    expect(mockedDelete).not.toHaveBeenCalled();
    const confirm = screen.getAllByRole("button", { name: "Revoke" }).at(-1)!;
    await user.click(confirm);

    await waitFor(() => expect(mockedDelete).toHaveBeenCalledWith("/attendance/face-profiles/emp-1"));
    expect(await screen.findByRole("button", { name: "Re-enroll" })).toBeInTheDocument();
  });
});
