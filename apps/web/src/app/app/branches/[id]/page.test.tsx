import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("next/navigation", () => ({
  useParams: () => ({ id: "branch-1" }),
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

import BranchDetailPage from "@/app/app/branches/[id]/page";
import { apiClient } from "@/lib/api/client";
import { ApiError } from "@/lib/api/errors";
import type { Branch } from "@/lib/branch/types";
import type { LegalEntity } from "@/lib/legal-entity/types";

const mockedGet = vi.mocked(apiClient.get);
const mockedPatch = vi.mocked(apiClient.patch);
const mockedDelete = vi.mocked(apiClient.delete);

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

function mockLoad(branch: Branch, entities: LegalEntity[] = [sampleEntity]) {
  mockedGet.mockImplementation((path: string) => {
    if (path === "/branches/branch-1") return Promise.resolve(branch);
    if (path === "/legal-entities") return Promise.resolve(entities);
    return Promise.reject(new Error(`Unexpected path ${path}`));
  });
}

describe("BranchDetailPage", () => {
  afterEach(() => {
    mockedGet.mockReset();
    mockedPatch.mockReset();
    mockedDelete.mockReset();
    toastMock.mockReset();
  });

  it("loads and renders the branch", async () => {
    mockLoad(sampleBranch);
    render(<BranchDetailPage />);

    expect(await screen.findByRole("heading", { name: "HQ Branch" })).toBeInTheDocument();
    expect(screen.getByText("Active")).toBeInTheDocument();
    expect(screen.getByText("Acme Technologies Pvt Ltd")).toBeInTheDocument();
  });

  it("shows an error state when not found", async () => {
    mockedGet.mockRejectedValueOnce(new ApiError({ status: 404, code: "NOT_FOUND", message: "Not found" }));
    render(<BranchDetailPage />);

    expect(await screen.findByText(/could not be found/i)).toBeInTheDocument();
  });

  it("enters edit mode and restores values on cancel", async () => {
    mockLoad(sampleBranch);
    const user = userEvent.setup();
    render(<BranchDetailPage />);

    await user.click(await screen.findByRole("button", { name: /^edit$/i }));
    const cityInput = screen.getByLabelText(/^city$/i);
    await user.type(cityInput, "Bengaluru");
    await user.click(screen.getByRole("button", { name: /cancel/i }));

    expect(screen.queryByLabelText(/^city$/i)).not.toBeInTheDocument();
  });

  it("saves changes with the current If-Match version", async () => {
    mockLoad(sampleBranch);
    mockedPatch.mockResolvedValueOnce({ ...sampleBranch, city: "Bengaluru", version: 2 });
    const user = userEvent.setup();
    render(<BranchDetailPage />);

    await user.click(await screen.findByRole("button", { name: /^edit$/i }));
    await user.type(screen.getByLabelText(/^city$/i), "Bengaluru");
    await user.click(screen.getByRole("button", { name: /save changes/i }));

    await waitFor(() => expect(mockedPatch).toHaveBeenCalledTimes(1));
    expect(mockedPatch).toHaveBeenCalledWith("/branches/branch-1", { city: "Bengaluru" }, { ifMatch: "1" });
    expect(toastMock).toHaveBeenCalledWith(expect.objectContaining({ variant: "success" }));
  });

  it("shows stale-resource actions on 409 STALE_RESOURCE", async () => {
    mockLoad(sampleBranch);
    mockedPatch.mockRejectedValueOnce(new ApiError({ status: 409, code: "STALE_RESOURCE", message: "Stale" }));
    const user = userEvent.setup();
    render(<BranchDetailPage />);

    await user.click(await screen.findByRole("button", { name: /^edit$/i }));
    await user.type(screen.getByLabelText(/^city$/i), "Bengaluru");
    await user.click(screen.getByRole("button", { name: /save changes/i }));

    expect(await screen.findByText(/changed by someone else/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /reload latest/i })).toBeInTheDocument();
  });

  it("deactivates the branch after confirmation", async () => {
    mockLoad(sampleBranch);
    mockedDelete.mockResolvedValueOnce({ ...sampleBranch, is_active: false, version: 2 });
    const user = userEvent.setup();
    render(<BranchDetailPage />);

    await user.click(await screen.findByRole("button", { name: /deactivate/i }));
    const dialog = screen.getByRole("dialog");
    await user.click(within(dialog).getByRole("button", { name: /deactivate/i }));

    await waitFor(() => expect(mockedDelete).toHaveBeenCalledTimes(1));
    expect(mockedDelete).toHaveBeenCalledWith("/branches/branch-1", { ifMatch: "1" });
    expect(toastMock).toHaveBeenCalledWith(expect.objectContaining({ variant: "success" }));
  });

  it("shows a blocked message when deactivation is blocked by active departments", async () => {
    mockLoad(sampleBranch);
    mockedDelete.mockRejectedValueOnce(
      new ApiError({ status: 409, code: "BRANCH_HAS_ACTIVE_DEPARTMENTS", message: "Blocked" }),
    );
    const user = userEvent.setup();
    render(<BranchDetailPage />);

    await user.click(await screen.findByRole("button", { name: /deactivate/i }));
    const dialog = screen.getByRole("dialog");
    await user.click(within(dialog).getByRole("button", { name: /deactivate/i }));

    await waitFor(() =>
      expect(toastMock).toHaveBeenCalledWith(
        expect.objectContaining({ title: "Can't deactivate this branch", variant: "danger" }),
      ),
    );
  });
});
