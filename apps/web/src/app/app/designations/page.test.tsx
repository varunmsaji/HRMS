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

import DesignationsPage from "@/app/app/designations/page";
import { apiClient } from "@/lib/api/client";
import { ApiError } from "@/lib/api/errors";
import type { Department } from "@/lib/department/types";
import type { Designation } from "@/lib/designation/types";
import type { Grade } from "@/lib/grade/types";

const mockedGet = vi.mocked(apiClient.get);
const mockedPost = vi.mocked(apiClient.post);

const sampleDepartment: Department = {
  id: "dept-1",
  company_id: "company-1",
  branch_id: null,
  parent_id: null,
  name: "Engineering",
  code: null,
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
  department_id: "dept-1",
  grade_id: "grade-1",
  title: "Software Engineer",
  code: null,
  is_active: true,
  version: 1,
  created_at: "2026-08-01T00:00:00Z",
  updated_at: "2026-08-01T00:00:00Z",
};

function mockLoad(
  designations: Designation[],
  departments: Department[] = [sampleDepartment],
  grades: Grade[] = [sampleGrade],
) {
  mockedGet.mockImplementation((path: string) => {
    if (path === "/designations") return Promise.resolve(designations);
    if (path === "/departments") return Promise.resolve(departments);
    if (path === "/grades") return Promise.resolve(grades);
    return Promise.reject(new Error(`Unexpected path ${path}`));
  });
}

describe("DesignationsPage", () => {
  afterEach(() => {
    mockedGet.mockReset();
    mockedPost.mockReset();
    toastMock.mockReset();
  });

  it("shows a loading state before data resolves", () => {
    mockedGet.mockReturnValue(new Promise(() => {}));
    render(<DesignationsPage />);
    expect(screen.getByRole("status")).toBeInTheDocument();
  });

  it("shows the empty state with guidance when there are no designations", async () => {
    mockLoad([]);
    render(<DesignationsPage />);

    expect(await screen.findByText(/no designations have been configured yet/i)).toBeInTheDocument();
  });

  it("renders the list of designations with department and grade context", async () => {
    mockLoad([sampleDesignation]);
    render(<DesignationsPage />);

    expect(await screen.findByText("Software Engineer")).toBeInTheDocument();
    expect(screen.getByText("Active")).toBeInTheDocument();
    expect(screen.getByText(/Engineering/)).toBeInTheDocument();
    expect(screen.getByText(/Senior Engineer Grade/)).toBeInTheDocument();
  });

  it("shows an error state when loading fails with forbidden", async () => {
    mockedGet.mockRejectedValueOnce(
      new ApiError({ status: 403, code: "PERMISSION_DENIED", message: "Forbidden" }),
    );
    render(<DesignationsPage />);

    expect(await screen.findByText(/do not have permission to view designations/i)).toBeInTheDocument();
  });

  it("creates a designation from the empty state and refreshes the list", async () => {
    let designations: Designation[] = [];
    mockedGet.mockImplementation((path: string) => {
      if (path === "/designations") return Promise.resolve(designations);
      if (path === "/departments") return Promise.resolve([sampleDepartment]);
      if (path === "/grades") return Promise.resolve([sampleGrade]);
      return Promise.reject(new Error(`Unexpected path ${path}`));
    });
    mockedPost.mockImplementationOnce(async () => {
      designations = [sampleDesignation];
      return sampleDesignation;
    });
    const user = userEvent.setup();
    render(<DesignationsPage />);

    await user.click(await screen.findByRole("button", { name: /add designation/i }));
    const dialog = await screen.findByRole("dialog");
    await user.type(within(dialog).getByLabelText(/designation title/i), "Software Engineer");
    await user.click(within(dialog).getByRole("button", { name: /^add designation$/i }));

    await waitFor(() => expect(mockedPost).toHaveBeenCalledTimes(1));
    expect(mockedPost).toHaveBeenCalledWith(
      "/designations",
      expect.objectContaining({ title: "Software Engineer" }),
    );
    expect(toastMock).toHaveBeenCalledWith(expect.objectContaining({ variant: "success" }));
  });

  it("shows a validation error when the title is missing", async () => {
    mockLoad([]);
    const user = userEvent.setup();
    render(<DesignationsPage />);

    await user.click(await screen.findByRole("button", { name: /add designation/i }));
    const dialog = await screen.findByRole("dialog");
    await user.click(within(dialog).getByRole("button", { name: /^add designation$/i }));

    expect(await within(dialog).findByText(/designation title is required/i)).toBeInTheDocument();
    expect(mockedPost).not.toHaveBeenCalled();
  });

  it("surfaces an API error toast when creation fails", async () => {
    mockLoad([]);
    mockedPost.mockRejectedValueOnce(
      new ApiError({ status: 500, code: "INTERNAL_ERROR", message: "Something broke" }),
    );
    const user = userEvent.setup();
    render(<DesignationsPage />);

    await user.click(await screen.findByRole("button", { name: /add designation/i }));
    const dialog = await screen.findByRole("dialog");
    await user.type(within(dialog).getByLabelText(/designation title/i), "Software Engineer");
    await user.click(within(dialog).getByRole("button", { name: /^add designation$/i }));

    await waitFor(() =>
      expect(toastMock).toHaveBeenCalledWith(
        expect.objectContaining({ title: "Could not add designation", variant: "danger" }),
      ),
    );
  });

  it("selects a grade when creating a designation", async () => {
    let designations: Designation[] = [];
    let lastPayload: unknown;
    mockedGet.mockImplementation((path: string) => {
      if (path === "/designations") return Promise.resolve(designations);
      if (path === "/departments") return Promise.resolve([sampleDepartment]);
      if (path === "/grades") return Promise.resolve([sampleGrade]);
      return Promise.reject(new Error(`Unexpected path ${path}`));
    });
    mockedPost.mockImplementationOnce(async (_path: string, payload: unknown) => {
      lastPayload = payload;
      designations = [sampleDesignation];
      return sampleDesignation;
    });
    const user = userEvent.setup();
    render(<DesignationsPage />);

    await user.click(await screen.findByRole("button", { name: /add designation/i }));
    const dialog = await screen.findByRole("dialog");
    await user.type(within(dialog).getByLabelText(/designation title/i), "Software Engineer");
    await user.selectOptions(within(dialog).getByLabelText(/^grade$/i), "grade-1");
    await user.click(within(dialog).getByRole("button", { name: /^add designation$/i }));

    await waitFor(() => expect(mockedPost).toHaveBeenCalledTimes(1));
    expect(lastPayload).toEqual(expect.objectContaining({ grade_id: "grade-1" }));
  });
});
