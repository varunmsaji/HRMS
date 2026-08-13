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

import DepartmentsPage from "@/app/app/departments/page";
import { apiClient } from "@/lib/api/client";
import { ApiError } from "@/lib/api/errors";
import type { Branch } from "@/lib/branch/types";
import type { Department } from "@/lib/department/types";

const mockedGet = vi.mocked(apiClient.get);
const mockedPost = vi.mocked(apiClient.post);

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
  branch_id: "branch-1",
  parent_id: null,
  name: "Engineering",
  code: null,
  is_active: true,
  version: 1,
  created_at: "2026-08-01T00:00:00Z",
  updated_at: "2026-08-01T00:00:00Z",
};

function mockLoad(departments: Department[], branches: Branch[] = [sampleBranch]) {
  mockedGet.mockImplementation((path: string) => {
    if (path === "/departments") return Promise.resolve(departments);
    if (path === "/branches") return Promise.resolve(branches);
    return Promise.reject(new Error(`Unexpected path ${path}`));
  });
}

describe("DepartmentsPage", () => {
  afterEach(() => {
    mockedGet.mockReset();
    mockedPost.mockReset();
    toastMock.mockReset();
  });

  it("shows a loading state before data resolves", () => {
    mockedGet.mockReturnValue(new Promise(() => {}));
    render(<DepartmentsPage />);
    expect(screen.getByRole("status")).toBeInTheDocument();
  });

  it("shows the empty state with guidance when there are no departments", async () => {
    mockLoad([]);
    render(<DepartmentsPage />);

    expect(await screen.findByText(/no departments have been configured yet/i)).toBeInTheDocument();
  });

  it("renders the list of departments with branch context", async () => {
    mockLoad([sampleDepartment]);
    render(<DepartmentsPage />);

    expect(await screen.findByText("Engineering")).toBeInTheDocument();
    expect(screen.getByText("Active")).toBeInTheDocument();
    expect(screen.getByText("HQ Branch")).toBeInTheDocument();
  });

  it("shows an error state when loading fails with forbidden", async () => {
    mockedGet.mockRejectedValueOnce(
      new ApiError({ status: 403, code: "PERMISSION_DENIED", message: "Forbidden" }),
    );
    render(<DepartmentsPage />);

    expect(await screen.findByText(/do not have permission to view departments/i)).toBeInTheDocument();
  });

  it("creates a department from the empty state and refreshes the list", async () => {
    let departments: Department[] = [];
    mockedGet.mockImplementation((path: string) => {
      if (path === "/departments") return Promise.resolve(departments);
      if (path === "/branches") return Promise.resolve([sampleBranch]);
      return Promise.reject(new Error(`Unexpected path ${path}`));
    });
    mockedPost.mockImplementationOnce(async () => {
      departments = [sampleDepartment];
      return sampleDepartment;
    });
    const user = userEvent.setup();
    render(<DepartmentsPage />);

    await user.click(await screen.findByRole("button", { name: /add department/i }));
    const dialog = await screen.findByRole("dialog");
    await user.type(within(dialog).getByLabelText(/department name/i), "Engineering");
    await user.click(within(dialog).getByRole("button", { name: /^add department$/i }));

    await waitFor(() => expect(mockedPost).toHaveBeenCalledTimes(1));
    expect(mockedPost).toHaveBeenCalledWith(
      "/departments",
      expect.objectContaining({ name: "Engineering" }),
    );
    expect(toastMock).toHaveBeenCalledWith(expect.objectContaining({ variant: "success" }));
  });

  it("shows a validation error when the name is missing", async () => {
    mockLoad([]);
    const user = userEvent.setup();
    render(<DepartmentsPage />);

    await user.click(await screen.findByRole("button", { name: /add department/i }));
    const dialog = await screen.findByRole("dialog");
    await user.click(within(dialog).getByRole("button", { name: /^add department$/i }));

    expect(await within(dialog).findByText(/department name is required/i)).toBeInTheDocument();
    expect(mockedPost).not.toHaveBeenCalled();
  });

  it("surfaces an API error toast when creation fails", async () => {
    mockLoad([]);
    mockedPost.mockRejectedValueOnce(
      new ApiError({ status: 500, code: "INTERNAL_ERROR", message: "Something broke" }),
    );
    const user = userEvent.setup();
    render(<DepartmentsPage />);

    await user.click(await screen.findByRole("button", { name: /add department/i }));
    const dialog = await screen.findByRole("dialog");
    await user.type(within(dialog).getByLabelText(/department name/i), "Engineering");
    await user.click(within(dialog).getByRole("button", { name: /^add department$/i }));

    await waitFor(() =>
      expect(toastMock).toHaveBeenCalledWith(
        expect.objectContaining({ title: "Could not add department", variant: "danger" }),
      ),
    );
  });
});
