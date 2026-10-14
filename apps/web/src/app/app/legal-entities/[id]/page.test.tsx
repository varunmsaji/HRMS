import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("next/navigation", () => ({
  useParams: () => ({ id: "le-1" }),
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

import LegalEntityDetailPage from "@/app/app/legal-entities/[id]/page";
import { apiClient } from "@/lib/api/client";
import { ApiError } from "@/lib/api/errors";
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

describe("LegalEntityDetailPage", () => {
  afterEach(() => {
    mockedGet.mockReset();
    mockedPatch.mockReset();
    mockedDelete.mockReset();
    toastMock.mockReset();
  });

  it("loads and renders the company", async () => {
    mockedGet.mockResolvedValueOnce(sampleEntity);
    render(<LegalEntityDetailPage />);

    expect(
      await screen.findByRole("heading", { name: "Acme Technologies Pvt Ltd" }),
    ).toBeInTheDocument();
    expect(screen.getByText("Active")).toBeInTheDocument();
    expect(screen.getAllByText("Not configured").length).toBeGreaterThan(0);
  });

  it("shows an error state when not found", async () => {
    mockedGet.mockRejectedValueOnce(
      new ApiError({ status: 404, code: "NOT_FOUND", message: "Not found" }),
    );
    render(<LegalEntityDetailPage />);

    expect(await screen.findByText(/could not be found/i)).toBeInTheDocument();
  });

  it("shows a forbidden error state", async () => {
    mockedGet.mockRejectedValueOnce(
      new ApiError({ status: 403, code: "PERMISSION_DENIED", message: "Forbidden" }),
    );
    render(<LegalEntityDetailPage />);

    expect(
      await screen.findByText(/do not have permission to view this company/i),
    ).toBeInTheDocument();
  });

  it("enters edit mode and restores values on cancel", async () => {
    mockedGet.mockResolvedValueOnce(sampleEntity);
    const user = userEvent.setup();
    render(<LegalEntityDetailPage />);

    await user.click(await screen.findByRole("button", { name: /^edit$/i }));
    const panInput = screen.getByLabelText(/^pan$/i);
    await user.type(panInput, "ABCDE1234F");
    await user.click(screen.getByRole("button", { name: /cancel/i }));

    expect(screen.queryByLabelText(/^pan$/i)).not.toBeInTheDocument();
  });

  it("saves changes with the current If-Match version", async () => {
    mockedGet.mockResolvedValueOnce(sampleEntity);
    mockedPatch.mockResolvedValueOnce({ ...sampleEntity, pan: "ABCDE1234F", version: 2 });
    const user = userEvent.setup();
    render(<LegalEntityDetailPage />);

    await user.click(await screen.findByRole("button", { name: /^edit$/i }));
    await user.type(screen.getByLabelText(/^pan$/i), "ABCDE1234F");
    await user.click(screen.getByRole("button", { name: /save changes/i }));

    await waitFor(() => expect(mockedPatch).toHaveBeenCalledTimes(1));
    expect(mockedPatch).toHaveBeenCalledWith(
      "/legal-entities/le-1",
      { pan: "ABCDE1234F" },
      { ifMatch: "1" },
    );
    expect(toastMock).toHaveBeenCalledWith(expect.objectContaining({ variant: "success" }));
  });

  it("shows a validation error for an invalid PAN", async () => {
    mockedGet.mockResolvedValueOnce(sampleEntity);
    const user = userEvent.setup();
    render(<LegalEntityDetailPage />);

    await user.click(await screen.findByRole("button", { name: /^edit$/i }));
    await user.type(screen.getByLabelText(/^pan$/i), "not-a-pan");
    await user.click(screen.getByRole("button", { name: /save changes/i }));

    expect(await screen.findByText(/enter a valid pan/i)).toBeInTheDocument();
    expect(mockedPatch).not.toHaveBeenCalled();
  });

  it("shows stale-resource actions on 409 STALE_RESOURCE", async () => {
    mockedGet.mockResolvedValueOnce(sampleEntity);
    mockedPatch.mockRejectedValueOnce(
      new ApiError({ status: 409, code: "STALE_RESOURCE", message: "Stale" }),
    );
    const user = userEvent.setup();
    render(<LegalEntityDetailPage />);

    await user.click(await screen.findByRole("button", { name: /^edit$/i }));
    await user.type(screen.getByLabelText(/^pan$/i), "ABCDE1234F");
    await user.click(screen.getByRole("button", { name: /save changes/i }));

    expect(
      await screen.findByText(/changed by someone else/i),
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /reload latest/i })).toBeInTheDocument();
  });

  it("deactivates the company after confirmation", async () => {
    mockedGet.mockResolvedValueOnce(sampleEntity);
    mockedDelete.mockResolvedValueOnce({ ...sampleEntity, is_active: false, version: 2 });
    const user = userEvent.setup();
    render(<LegalEntityDetailPage />);

    await user.click(await screen.findByRole("button", { name: /deactivate/i }));
    const dialog = screen.getByRole("dialog");
    await user.click(within(dialog).getByRole("button", { name: /deactivate/i }));

    await waitFor(() => expect(mockedDelete).toHaveBeenCalledTimes(1));
    expect(mockedDelete).toHaveBeenCalledWith("/legal-entities/le-1", { ifMatch: "1" });
    expect(toastMock).toHaveBeenCalledWith(expect.objectContaining({ variant: "success" }));
  });

  it("shows a blocked message when deactivation is blocked by active branches", async () => {
    mockedGet.mockResolvedValueOnce(sampleEntity);
    mockedDelete.mockRejectedValueOnce(
      new ApiError({
        status: 409,
        code: "LEGAL_ENTITY_HAS_ACTIVE_BRANCHES",
        message: "Blocked",
      }),
    );
    const user = userEvent.setup();
    render(<LegalEntityDetailPage />);

    await user.click(await screen.findByRole("button", { name: /deactivate/i }));
    const dialog = screen.getByRole("dialog");
    await user.click(within(dialog).getByRole("button", { name: /deactivate/i }));

    await waitFor(() =>
      expect(toastMock).toHaveBeenCalledWith(
        expect.objectContaining({ title: "Can't deactivate this company", variant: "danger" }),
      ),
    );
  });
});
