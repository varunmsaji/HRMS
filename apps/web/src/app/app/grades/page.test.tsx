import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
}));

vi.mock("@/lib/auth/auth-context", () => ({
  useAuth: () => ({ session: { companyId: "company-1", accessToken: "token" } }),
}));

const toastMock = vi.fn();
vi.mock("@/components/common/toast", () => ({
  useToast: () => ({ toast: toastMock }),
}));

vi.mock("@/lib/api/client", () => ({
  apiClient: { get: vi.fn(), post: vi.fn() },
}));

import GradesPage from "@/app/app/grades/page";
import { apiClient } from "@/lib/api/client";
import { ApiError } from "@/lib/api/errors";
import type { Grade } from "@/lib/grade/types";

const mockedGet = vi.mocked(apiClient.get);
const mockedPost = vi.mocked(apiClient.post);

const sampleGrade: Grade = {
  id: "grade-1",
  company_id: "company-1",
  code: "L5",
  name: "Senior Engineer",
  level: 5,
  min_ctc: null,
  max_ctc: null,
  notice_period_days: null,
  probation_days: null,
  approval_limit: null,
  is_active: true,
  version: 1,
  created_at: "2026-08-01T00:00:00Z",
  updated_at: "2026-08-01T00:00:00Z",
};

function mockLoad(grades: Grade[]) {
  mockedGet.mockImplementation((path: string) => {
    if (path === "/grades") return Promise.resolve(grades);
    return Promise.reject(new Error(`Unexpected path ${path}`));
  });
}

describe("GradesPage", () => {
  afterEach(() => {
    mockedGet.mockReset();
    mockedPost.mockReset();
    toastMock.mockReset();
  });

  it("shows a loading state before data resolves", () => {
    mockedGet.mockReturnValue(new Promise(() => {}));
    render(<GradesPage />);
    expect(screen.getByRole("status")).toBeInTheDocument();
  });

  it("shows the empty state with guidance when there are no grades", async () => {
    mockLoad([]);
    render(<GradesPage />);

    expect(await screen.findByText(/no grades have been configured yet/i)).toBeInTheDocument();
  });

  it("renders the list of grades", async () => {
    mockLoad([sampleGrade]);
    render(<GradesPage />);

    expect(await screen.findByText(/Senior Engineer/)).toBeInTheDocument();
    expect(screen.getByText("Active")).toBeInTheDocument();
    expect(screen.getByText("Level 5")).toBeInTheDocument();
  });

  it("shows an error state when loading fails with forbidden", async () => {
    mockedGet.mockRejectedValueOnce(
      new ApiError({ status: 403, code: "PERMISSION_DENIED", message: "Forbidden" }),
    );
    render(<GradesPage />);

    expect(await screen.findByText(/do not have permission to view grades/i)).toBeInTheDocument();
  });

  it("creates a grade from the empty state and refreshes the list", async () => {
    let grades: Grade[] = [];
    mockedGet.mockImplementation((path: string) => {
      if (path === "/grades") return Promise.resolve(grades);
      return Promise.reject(new Error(`Unexpected path ${path}`));
    });
    mockedPost.mockImplementationOnce(async () => {
      grades = [sampleGrade];
      return sampleGrade;
    });
    const user = userEvent.setup();
    render(<GradesPage />);

    await user.click(await screen.findByRole("button", { name: /add grade/i }));
    const dialog = await screen.findByRole("dialog");
    await user.type(within(dialog).getByLabelText(/grade name/i), "Senior Engineer");
    await user.click(within(dialog).getByRole("button", { name: /^add grade$/i }));

    await waitFor(() => expect(mockedPost).toHaveBeenCalledTimes(1));
    expect(mockedPost).toHaveBeenCalledWith(
      "/grades",
      expect.objectContaining({ name: "Senior Engineer" }),
    );
    expect(toastMock).toHaveBeenCalledWith(expect.objectContaining({ variant: "success" }));
  });

  it("shows a validation error when the name is missing", async () => {
    mockLoad([]);
    const user = userEvent.setup();
    render(<GradesPage />);

    await user.click(await screen.findByRole("button", { name: /add grade/i }));
    const dialog = await screen.findByRole("dialog");
    await user.click(within(dialog).getByRole("button", { name: /^add grade$/i }));

    expect(await within(dialog).findByText(/grade name is required/i)).toBeInTheDocument();
    expect(within(dialog).queryByLabelText(/grade code/i)).not.toBeInTheDocument();
    expect(mockedPost).not.toHaveBeenCalled();
  });

  it("shows a client-side error when max CTC is below min CTC", async () => {
    mockLoad([]);
    const user = userEvent.setup();
    render(<GradesPage />);

    await user.click(await screen.findByRole("button", { name: /add grade/i }));
    const dialog = await screen.findByRole("dialog");
    await user.type(within(dialog).getByLabelText(/grade name/i), "Senior Engineer");
    await user.type(within(dialog).getByLabelText(/min ctc/i), "20000");
    await user.type(within(dialog).getByLabelText(/max ctc/i), "10000");
    await user.click(within(dialog).getByRole("button", { name: /^add grade$/i }));

    expect(await within(dialog).findByText(/max ctc must not be less than min ctc/i)).toBeInTheDocument();
    expect(mockedPost).not.toHaveBeenCalled();
  });

  it("surfaces an API error toast when creation fails", async () => {
    mockLoad([]);
    mockedPost.mockRejectedValueOnce(
      new ApiError({ status: 500, code: "INTERNAL_ERROR", message: "Something broke" }),
    );
    const user = userEvent.setup();
    render(<GradesPage />);

    await user.click(await screen.findByRole("button", { name: /add grade/i }));
    const dialog = await screen.findByRole("dialog");
    await user.type(within(dialog).getByLabelText(/grade name/i), "Senior Engineer");
    await user.click(within(dialog).getByRole("button", { name: /^add grade$/i }));

    await waitFor(() =>
      expect(toastMock).toHaveBeenCalledWith(
        expect.objectContaining({ title: "Could not add grade", variant: "danger" }),
      ),
    );
  });
});
