import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("next/navigation", () => ({
  useParams: () => ({ id: "grade-1" }),
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
  apiClient: { get: vi.fn(), patch: vi.fn(), delete: vi.fn() },
}));

import GradeDetailPage from "@/app/app/grades/[id]/page";
import { apiClient } from "@/lib/api/client";
import { ApiError } from "@/lib/api/errors";
import type { Grade } from "@/lib/grade/types";

const mockedGet = vi.mocked(apiClient.get);
const mockedPatch = vi.mocked(apiClient.patch);
const mockedDelete = vi.mocked(apiClient.delete);

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

function mockLoad(grade: Grade) {
  mockedGet.mockImplementation((path: string) => {
    if (path === "/grades/grade-1") return Promise.resolve(grade);
    return Promise.reject(new Error(`Unexpected path ${path}`));
  });
}

describe("GradeDetailPage", () => {
  afterEach(() => {
    mockedGet.mockReset();
    mockedPatch.mockReset();
    mockedDelete.mockReset();
    toastMock.mockReset();
  });

  it("loads and renders the grade", async () => {
    mockLoad(sampleGrade);
    render(<GradeDetailPage />);

    expect(await screen.findByRole("heading", { name: "Senior Engineer" })).toBeInTheDocument();
    expect(screen.getByText("Active")).toBeInTheDocument();
  });

  it("shows an error state when not found", async () => {
    mockedGet.mockRejectedValueOnce(new ApiError({ status: 404, code: "NOT_FOUND", message: "Not found" }));
    render(<GradeDetailPage />);

    expect(await screen.findByText(/could not be found/i)).toBeInTheDocument();
  });

  it("displays a formatted compensation band", async () => {
    mockLoad({ ...sampleGrade, min_ctc: 100_000_000, max_ctc: 200_000_000 });
    render(<GradeDetailPage />);

    await screen.findByRole("heading", { name: "Senior Engineer" });
    expect(screen.getByText("₹10,00,000")).toBeInTheDocument();
    expect(screen.getByText("₹20,00,000")).toBeInTheDocument();
  });

  it("enters edit mode and restores values on cancel", async () => {
    mockLoad(sampleGrade);
    const user = userEvent.setup();
    render(<GradeDetailPage />);

    await user.click(await screen.findByRole("button", { name: /^edit$/i }));
    const levelInput = screen.getByLabelText(/^level$/i);
    await user.clear(levelInput);
    await user.type(levelInput, "6");
    await user.click(screen.getByRole("button", { name: /cancel/i }));

    expect(screen.queryByLabelText(/^level$/i)).not.toBeInTheDocument();
  });

  it("saves changes with the current If-Match version", async () => {
    mockLoad(sampleGrade);
    mockedPatch.mockResolvedValueOnce({ ...sampleGrade, level: 6, version: 2 });
    const user = userEvent.setup();
    render(<GradeDetailPage />);

    await user.click(await screen.findByRole("button", { name: /^edit$/i }));
    const levelInput = screen.getByLabelText(/^level$/i);
    await user.clear(levelInput);
    await user.type(levelInput, "6");
    await user.click(screen.getByRole("button", { name: /save changes/i }));

    await waitFor(() => expect(mockedPatch).toHaveBeenCalledTimes(1));
    expect(mockedPatch).toHaveBeenCalledWith("/grades/grade-1", { level: 6 }, { ifMatch: "1" });
    expect(toastMock).toHaveBeenCalledWith(expect.objectContaining({ variant: "success" }));
  });

  it("shows stale-resource actions on 409 STALE_RESOURCE", async () => {
    mockLoad(sampleGrade);
    mockedPatch.mockRejectedValueOnce(new ApiError({ status: 409, code: "STALE_RESOURCE", message: "Stale" }));
    const user = userEvent.setup();
    render(<GradeDetailPage />);

    await user.click(await screen.findByRole("button", { name: /^edit$/i }));
    const levelInput = screen.getByLabelText(/^level$/i);
    await user.clear(levelInput);
    await user.type(levelInput, "6");
    await user.click(screen.getByRole("button", { name: /save changes/i }));

    expect(await screen.findByText(/changed by someone else/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /reload latest/i })).toBeInTheDocument();
  });

  it("deactivates the grade after confirmation", async () => {
    mockLoad(sampleGrade);
    mockedDelete.mockResolvedValueOnce({ ...sampleGrade, is_active: false, version: 2 });
    const user = userEvent.setup();
    render(<GradeDetailPage />);

    await user.click(await screen.findByRole("button", { name: /deactivate/i }));
    const dialog = screen.getByRole("dialog");
    await user.click(within(dialog).getByRole("button", { name: /deactivate/i }));

    await waitFor(() => expect(mockedDelete).toHaveBeenCalledTimes(1));
    expect(mockedDelete).toHaveBeenCalledWith("/grades/grade-1", { ifMatch: "1" });
    expect(toastMock).toHaveBeenCalledWith(expect.objectContaining({ variant: "success" }));
  });

  it("reactivates a deactivated grade", async () => {
    const inactiveGrade = { ...sampleGrade, is_active: false, version: 2 };
    mockLoad(inactiveGrade);
    mockedPatch.mockResolvedValueOnce({ ...inactiveGrade, is_active: true, version: 3 });
    const user = userEvent.setup();
    render(<GradeDetailPage />);

    await user.click(await screen.findByRole("button", { name: /reactivate/i }));
    const dialog = screen.getByRole("dialog");
    await user.click(within(dialog).getByRole("button", { name: /reactivate/i }));

    await waitFor(() => expect(mockedPatch).toHaveBeenCalledTimes(1));
    expect(mockedPatch).toHaveBeenCalledWith("/grades/grade-1", { is_active: true }, { ifMatch: "2" });
    expect(toastMock).toHaveBeenCalledWith(expect.objectContaining({ variant: "success" }));
  });
});
