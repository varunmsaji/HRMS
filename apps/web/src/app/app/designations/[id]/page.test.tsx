import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("next/navigation", () => ({
  useParams: () => ({ id: "desig-1" }),
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

import DesignationDetailPage from "@/app/app/designations/[id]/page";
import { apiClient } from "@/lib/api/client";
import { ApiError } from "@/lib/api/errors";
import type { Department } from "@/lib/department/types";
import type { Designation } from "@/lib/designation/types";
import type { Grade } from "@/lib/grade/types";

const mockedGet = vi.mocked(apiClient.get);
const mockedPatch = vi.mocked(apiClient.patch);
const mockedDelete = vi.mocked(apiClient.delete);

const sampleDepartment: Department = {
  id: "dept-1",
  company_id: "company-1",
  branch_id: null,
  parent_id: null,
  name: "Engineering",
  code: null,
  head_employee_id: null,
  is_active: true,
  version: 1,
  created_at: "2026-08-01T00:00:00Z",
  updated_at: "2026-08-01T00:00:00Z",
};

const sampleGrade: Grade = {
  id: "grade-1",
  company_id: "company-1",
  code: "L5",
  name: "Senior Engineer Grade",
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

const sampleDesignation: Designation = {
  id: "desig-1",
  company_id: "company-1",
  department_id: null,
  grade_id: null,
  title: "Software Engineer",
  code: null,
  is_active: true,
  version: 1,
  created_at: "2026-08-01T00:00:00Z",
  updated_at: "2026-08-01T00:00:00Z",
};

function mockLoad(
  designation: Designation,
  departments: Department[] = [sampleDepartment],
  grades: Grade[] = [sampleGrade],
) {
  mockedGet.mockImplementation((path: string) => {
    if (path === "/designations/desig-1") return Promise.resolve(designation);
    if (path === "/departments") return Promise.resolve(departments);
    if (path === "/grades") return Promise.resolve(grades);
    return Promise.reject(new Error(`Unexpected path ${path}`));
  });
}

describe("DesignationDetailPage", () => {
  afterEach(() => {
    mockedGet.mockReset();
    mockedPatch.mockReset();
    mockedDelete.mockReset();
    toastMock.mockReset();
  });

  it("loads and renders the designation", async () => {
    mockLoad(sampleDesignation);
    render(<DesignationDetailPage />);

    expect(await screen.findByRole("heading", { name: "Software Engineer" })).toBeInTheDocument();
    expect(screen.getByText("Active")).toBeInTheDocument();
  });

  it("shows an error state when not found", async () => {
    mockedGet.mockRejectedValueOnce(new ApiError({ status: 404, code: "NOT_FOUND", message: "Not found" }));
    render(<DesignationDetailPage />);

    expect(await screen.findByText(/could not be found/i)).toBeInTheDocument();
  });

  it("enters edit mode and restores values on cancel", async () => {
    mockLoad(sampleDesignation);
    const user = userEvent.setup();
    render(<DesignationDetailPage />);

    await user.click(await screen.findByRole("button", { name: /^edit$/i }));
    await user.type(screen.getByLabelText(/designation title/i), " II");
    await user.click(screen.getByRole("button", { name: /cancel/i }));

    expect(screen.queryByLabelText(/designation title/i)).not.toBeInTheDocument();
  });

  it("saves changes with the current If-Match version", async () => {
    mockLoad(sampleDesignation);
    mockedPatch.mockResolvedValueOnce({ ...sampleDesignation, title: "Software Engineer II", version: 2 });
    const user = userEvent.setup();
    render(<DesignationDetailPage />);

    await user.click(await screen.findByRole("button", { name: /^edit$/i }));
    await user.type(screen.getByLabelText(/designation title/i), " II");
    await user.click(screen.getByRole("button", { name: /save changes/i }));

    await waitFor(() => expect(mockedPatch).toHaveBeenCalledTimes(1));
    expect(mockedPatch).toHaveBeenCalledWith("/designations/desig-1", { title: "Software Engineer II" }, { ifMatch: "1" });
    expect(toastMock).toHaveBeenCalledWith(expect.objectContaining({ variant: "success" }));
  });

  it("shows stale-resource actions on 409 STALE_RESOURCE", async () => {
    mockLoad(sampleDesignation);
    mockedPatch.mockRejectedValueOnce(new ApiError({ status: 409, code: "STALE_RESOURCE", message: "Stale" }));
    const user = userEvent.setup();
    render(<DesignationDetailPage />);

    await user.click(await screen.findByRole("button", { name: /^edit$/i }));
    await user.type(screen.getByLabelText(/designation title/i), " II");
    await user.click(screen.getByRole("button", { name: /save changes/i }));

    expect(await screen.findByText(/changed by someone else/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /reload latest/i })).toBeInTheDocument();
  });

  it("deactivates the designation after confirmation", async () => {
    mockLoad(sampleDesignation);
    mockedDelete.mockResolvedValueOnce({ ...sampleDesignation, is_active: false, version: 2 });
    const user = userEvent.setup();
    render(<DesignationDetailPage />);

    await user.click(await screen.findByRole("button", { name: /deactivate/i }));
    const dialog = screen.getByRole("dialog");
    await user.click(within(dialog).getByRole("button", { name: /deactivate/i }));

    await waitFor(() => expect(mockedDelete).toHaveBeenCalledTimes(1));
    expect(mockedDelete).toHaveBeenCalledWith("/designations/desig-1", { ifMatch: "1" });
    expect(toastMock).toHaveBeenCalledWith(expect.objectContaining({ variant: "success" }));
  });

  it("reactivates a deactivated designation", async () => {
    const inactiveDesignation = { ...sampleDesignation, is_active: false, version: 2 };
    mockLoad(inactiveDesignation);
    mockedPatch.mockResolvedValueOnce({ ...inactiveDesignation, is_active: true, version: 3 });
    const user = userEvent.setup();
    render(<DesignationDetailPage />);

    await user.click(await screen.findByRole("button", { name: /reactivate/i }));
    const dialog = screen.getByRole("dialog");
    await user.click(within(dialog).getByRole("button", { name: /reactivate/i }));

    await waitFor(() => expect(mockedPatch).toHaveBeenCalledTimes(1));
    expect(mockedPatch).toHaveBeenCalledWith(
      "/designations/desig-1",
      { is_active: true },
      { ifMatch: "2" },
    );
    expect(toastMock).toHaveBeenCalledWith(expect.objectContaining({ variant: "success" }));
  });

  it("shows department context when the designation belongs to one", async () => {
    mockLoad({ ...sampleDesignation, department_id: "dept-1" });
    render(<DesignationDetailPage />);

    await screen.findByRole("heading", { name: "Software Engineer" });
    expect(screen.getByText("Engineering")).toBeInTheDocument();
  });

  it("shows grade context when the designation belongs to one", async () => {
    mockLoad({ ...sampleDesignation, grade_id: "grade-1" });
    render(<DesignationDetailPage />);

    await screen.findByRole("heading", { name: "Software Engineer" });
    expect(screen.getByText("Senior Engineer Grade")).toBeInTheDocument();
  });
});
