import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("next/navigation", () => ({
  useParams: () => ({ id: "dept-1" }),
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

import DepartmentDetailPage from "@/app/app/departments/[id]/page";
import { apiClient } from "@/lib/api/client";
import { ApiError } from "@/lib/api/errors";
import type { Branch } from "@/lib/branch/types";
import type { Department } from "@/lib/department/types";

const mockedGet = vi.mocked(apiClient.get);
const mockedPatch = vi.mocked(apiClient.patch);
const mockedDelete = vi.mocked(apiClient.delete);

const sampleBranch: Branch = {
  id: "branch-1",
  company_id: "company-1",
  legal_entity_id: "le-1",
  name: "HQ Branch",
  code: null,
  address_line1: null,
  address_line2: null,
  city: null,
  state_code: null,
  pincode: null,
  timezone: null,
  latitude: null,
  longitude: null,
  geofence_radius_m: null,
  is_active: true,
  version: 1,
  created_at: "2026-08-01T00:00:00Z",
  updated_at: "2026-08-01T00:00:00Z",
};

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

function mockLoad(
  department: Department,
  branches: Branch[] = [sampleBranch],
  departments: Department[] = [sampleDepartment],
) {
  mockedGet.mockImplementation((path: string) => {
    if (path === "/departments/dept-1") return Promise.resolve(department);
    if (path === "/branches") return Promise.resolve(branches);
    if (path === "/departments") return Promise.resolve(departments);
    if (path === "/employees") return Promise.resolve([]);
    return Promise.reject(new Error(`Unexpected path ${path}`));
  });
}

describe("DepartmentDetailPage", () => {
  afterEach(() => {
    mockedGet.mockReset();
    mockedPatch.mockReset();
    mockedDelete.mockReset();
    toastMock.mockReset();
  });

  it("loads and renders the department", async () => {
    mockLoad(sampleDepartment);
    render(<DepartmentDetailPage />);

    expect(await screen.findByRole("heading", { name: "Engineering" })).toBeInTheDocument();
    expect(screen.getByText("Active")).toBeInTheDocument();
  });

  it("shows an error state when not found", async () => {
    mockedGet.mockRejectedValueOnce(new ApiError({ status: 404, code: "NOT_FOUND", message: "Not found" }));
    render(<DepartmentDetailPage />);

    expect(await screen.findByText(/could not be found/i)).toBeInTheDocument();
  });

  it("enters edit mode and restores values on cancel", async () => {
    mockLoad(sampleDepartment);
    const user = userEvent.setup();
    render(<DepartmentDetailPage />);

    await user.click(await screen.findByRole("button", { name: /^edit$/i }));
    const codeInput = screen.getByLabelText(/department code/i);
    await user.type(codeInput, "ENG");
    await user.click(screen.getByRole("button", { name: /cancel/i }));

    expect(screen.queryByLabelText(/department code/i)).not.toBeInTheDocument();
  });

  it("saves changes with the current If-Match version", async () => {
    mockLoad(sampleDepartment);
    mockedPatch.mockResolvedValueOnce({ ...sampleDepartment, code: "ENG", version: 2 });
    const user = userEvent.setup();
    render(<DepartmentDetailPage />);

    await user.click(await screen.findByRole("button", { name: /^edit$/i }));
    await user.type(screen.getByLabelText(/department code/i), "ENG");
    await user.click(screen.getByRole("button", { name: /save changes/i }));

    await waitFor(() => expect(mockedPatch).toHaveBeenCalledTimes(1));
    expect(mockedPatch).toHaveBeenCalledWith("/departments/dept-1", { code: "ENG" }, { ifMatch: "1" });
    expect(toastMock).toHaveBeenCalledWith(expect.objectContaining({ variant: "success" }));
  });

  it("shows stale-resource actions on 409 STALE_RESOURCE", async () => {
    mockLoad(sampleDepartment);
    mockedPatch.mockRejectedValueOnce(new ApiError({ status: 409, code: "STALE_RESOURCE", message: "Stale" }));
    const user = userEvent.setup();
    render(<DepartmentDetailPage />);

    await user.click(await screen.findByRole("button", { name: /^edit$/i }));
    await user.type(screen.getByLabelText(/department code/i), "ENG");
    await user.click(screen.getByRole("button", { name: /save changes/i }));

    expect(await screen.findByText(/changed by someone else/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /reload latest/i })).toBeInTheDocument();
  });

  it("shows a cycle-detection error on the parent field", async () => {
    mockLoad(sampleDepartment);
    mockedPatch.mockRejectedValueOnce(
      new ApiError({ status: 409, code: "DEPARTMENT_CYCLE_DETECTED", message: "Cycle" }),
    );
    const user = userEvent.setup();
    render(<DepartmentDetailPage />);

    await user.click(await screen.findByRole("button", { name: /^edit$/i }));
    await user.type(screen.getByLabelText(/department code/i), "ENG");
    await user.click(screen.getByRole("button", { name: /save changes/i }));

    expect(await screen.findByText(/would create a cycle/i)).toBeInTheDocument();
  });

  it("deactivates the department after confirmation", async () => {
    mockLoad(sampleDepartment);
    mockedDelete.mockResolvedValueOnce({ ...sampleDepartment, is_active: false, version: 2 });
    const user = userEvent.setup();
    render(<DepartmentDetailPage />);

    await user.click(await screen.findByRole("button", { name: /deactivate/i }));
    const dialog = screen.getByRole("dialog");
    await user.click(within(dialog).getByRole("button", { name: /deactivate/i }));

    await waitFor(() => expect(mockedDelete).toHaveBeenCalledTimes(1));
    expect(mockedDelete).toHaveBeenCalledWith("/departments/dept-1", { ifMatch: "1" });
    expect(toastMock).toHaveBeenCalledWith(expect.objectContaining({ variant: "success" }));
  });

  it("reactivates a deactivated department", async () => {
    const inactiveDepartment = { ...sampleDepartment, is_active: false, version: 2 };
    mockLoad(inactiveDepartment);
    mockedPatch.mockResolvedValueOnce({ ...inactiveDepartment, is_active: true, version: 3 });
    const user = userEvent.setup();
    render(<DepartmentDetailPage />);

    await user.click(await screen.findByRole("button", { name: /reactivate/i }));
    const dialog = screen.getByRole("dialog");
    await user.click(within(dialog).getByRole("button", { name: /reactivate/i }));

    await waitFor(() => expect(mockedPatch).toHaveBeenCalledTimes(1));
    expect(mockedPatch).toHaveBeenCalledWith(
      "/departments/dept-1",
      { is_active: true },
      { ifMatch: "2" },
    );
    expect(toastMock).toHaveBeenCalledWith(expect.objectContaining({ variant: "success" }));
  });
});
