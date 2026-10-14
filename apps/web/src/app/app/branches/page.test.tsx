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

import BranchesPage from "@/app/app/branches/page";
import { apiClient } from "@/lib/api/client";
import { ApiError } from "@/lib/api/errors";
import type { Branch } from "@/lib/branch/types";
import type { LegalEntity } from "@/lib/legal-entity/types";

const mockedGet = vi.mocked(apiClient.get);
const mockedPost = vi.mocked(apiClient.post);

const sampleEntity: LegalEntity = {
  id: "le-1",
  company_id: "company-1",
  name: "Acme Technologies Pvt Ltd",
  registered_address: null,
  pan: null,
  tan: null,
  cin: null,
  gstin: null,
  pf_code: null,
  esi_code: null,
  lwf_reg: null,
  signatory_name: null,
  signatory_designation: null,
  signature_image_url: null,
  is_active: true,
  version: 1,
  created_at: "2026-08-01T00:00:00Z",
  updated_at: "2026-08-01T00:00:00Z",
};

const sampleBranch: Branch = {
  id: "branch-1",
  company_id: "company-1",
  legal_entity_id: "le-1",
  name: "HQ Branch",
  code: null,
  address_line1: null,
  address_line2: null,
  city: "Bengaluru",
  state_code: "KA",
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

function mockLoad(branches: Branch[], entities: LegalEntity[] = [sampleEntity]) {
  mockedGet.mockImplementation((path: string) => {
    if (path === "/branches") return Promise.resolve(branches);
    if (path === "/legal-entities") return Promise.resolve(entities);
    return Promise.reject(new Error(`Unexpected path ${path}`));
  });
}

describe("BranchesPage", () => {
  afterEach(() => {
    mockedGet.mockReset();
    mockedPost.mockReset();
    toastMock.mockReset();
  });

  it("shows a loading state before data resolves", () => {
    mockedGet.mockReturnValue(new Promise(() => {}));
    render(<BranchesPage />);
    expect(screen.getByRole("status")).toBeInTheDocument();
  });

  it("shows the empty state with guidance when there are no branches", async () => {
    mockLoad([]);
    render(<BranchesPage />);

    expect(await screen.findByText(/no branches have been configured yet/i)).toBeInTheDocument();
  });

  it("prompts to add a company first when none exist", async () => {
    mockLoad([], []);
    render(<BranchesPage />);

    expect(await screen.findByText(/let's set up your company/i)).toBeInTheDocument();
  });

  it("renders the list of branches", async () => {
    mockLoad([sampleBranch]);
    render(<BranchesPage />);

    expect(await screen.findByText("HQ Branch")).toBeInTheDocument();
    expect(screen.getByText("Active")).toBeInTheDocument();
    expect(screen.getByText(/Acme Technologies Pvt Ltd · Bengaluru/)).toBeInTheDocument();
  });

  it("shows an error state when loading fails with forbidden", async () => {
    mockedGet.mockImplementation((path: string) => {
      if (path === "/branches") {
        return Promise.reject(
          new ApiError({ status: 403, code: "PERMISSION_DENIED", message: "Forbidden" }),
        );
      }
      if (path === "/legal-entities") return Promise.resolve([]);
      if (path === "/companies/current") return Promise.resolve(null);
      return Promise.reject(new Error(`Unexpected path ${path}`));
    });
    render(<BranchesPage />);

    expect(await screen.findByText(/do not have permission to view branches/i)).toBeInTheDocument();
  });

  it("creates a branch from the empty state and refreshes the list", async () => {
    let branches: Branch[] = [];
    mockedGet.mockImplementation((path: string) => {
      if (path === "/branches") return Promise.resolve(branches);
      if (path === "/legal-entities") return Promise.resolve([sampleEntity]);
      return Promise.reject(new Error(`Unexpected path ${path}`));
    });
    mockedPost.mockImplementationOnce(async () => {
      branches = [sampleBranch];
      return sampleBranch;
    });
    const user = userEvent.setup();
    render(<BranchesPage />);

    await user.click(await screen.findByRole("button", { name: /add branch/i }));
    // Only one company exists, so the selector is hidden and pre-filled automatically.
    await user.type(screen.getByLabelText(/branch name/i), "HQ Branch");
    await user.click(screen.getByRole("button", { name: /^add branch$/i }));

    await waitFor(() => expect(mockedPost).toHaveBeenCalledTimes(1));
    expect(mockedPost).toHaveBeenCalledWith(
      "/branches",
      expect.objectContaining({ legal_entity_id: "le-1", name: "HQ Branch" }),
    );
    expect(toastMock).toHaveBeenCalledWith(expect.objectContaining({ variant: "success" }));
  });

  it("shows a validation error when required fields are missing", async () => {
    // Two companies so the selector isn't auto-hidden/pre-filled (see
    // `hideLegalEntitySelector` in BranchForm), letting the "select a company" error fire.
    mockLoad([], [sampleEntity, { ...sampleEntity, id: "le-2", name: "Second Entity" }]);
    const user = userEvent.setup();
    render(<BranchesPage />);

    await user.click(await screen.findByRole("button", { name: /add branch/i }));
    const dialog = await screen.findByRole("dialog");
    await user.click(within(dialog).getByRole("button", { name: /^add branch$/i }));

    expect(await within(dialog).findByText(/select a company\./i)).toBeInTheDocument();
    expect(mockedPost).not.toHaveBeenCalled();
  });
});
