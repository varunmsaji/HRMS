import { render, screen, waitFor } from "@testing-library/react";
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

import LegalEntitiesPage from "@/app/app/legal-entities/page";
import { apiClient } from "@/lib/api/client";
import { ApiError } from "@/lib/api/errors";
import type { LegalEntity } from "@/lib/legal-entity/types";

const mockedGet = vi.mocked(apiClient.get);
const mockedPost = vi.mocked(apiClient.post);

const sampleEntity: LegalEntity = {
  id: "le-1",
  company_id: "company-1",
  name: "Acme Technologies Pvt Ltd",
  registered_address: null,
  pan: "ABCDE1234F",
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

describe("LegalEntitiesPage", () => {
  afterEach(() => {
    mockedGet.mockReset();
    mockedPost.mockReset();
    toastMock.mockReset();
  });

  it("shows a loading state before data resolves", () => {
    mockedGet.mockReturnValue(new Promise(() => {}));
    render(<LegalEntitiesPage />);
    expect(screen.getByRole("status")).toBeInTheDocument();
  });

  it("shows the empty state with guidance when there are no companies", async () => {
    mockedGet.mockResolvedValueOnce([]);
    render(<LegalEntitiesPage />);

    expect(
      await screen.findByText(/no companies have been configured yet/i),
    ).toBeInTheDocument();
    expect(screen.getByText(/add the registered company/i)).toBeInTheDocument();
  });

  it("renders the list of companies", async () => {
    mockedGet.mockResolvedValueOnce([sampleEntity]);
    render(<LegalEntitiesPage />);

    expect(await screen.findByText("Acme Technologies Pvt Ltd")).toBeInTheDocument();
    expect(screen.getByText("Active")).toBeInTheDocument();
    expect(screen.getByText(/PAN ABCDE1234F/)).toBeInTheDocument();
  });

  it("shows an error state when loading fails with forbidden", async () => {
    mockedGet.mockRejectedValueOnce(
      new ApiError({ status: 403, code: "PERMISSION_DENIED", message: "Forbidden" }),
    );
    render(<LegalEntitiesPage />);

    expect(
      await screen.findByText(/do not have permission to view companies/i),
    ).toBeInTheDocument();
  });

  it("shows a generic error state on network failure with retry", async () => {
    mockedGet.mockRejectedValueOnce(new ApiError({ status: 0, code: "NETWORK_ERROR", message: "Could not reach the server." }));
    mockedGet.mockResolvedValueOnce([sampleEntity]);
    const user = userEvent.setup();
    render(<LegalEntitiesPage />);

    await screen.findByText("Could not reach the server.");
    await user.click(screen.getByRole("button", { name: /try again/i }));
    expect(await screen.findByText("Acme Technologies Pvt Ltd")).toBeInTheDocument();
  });

  it("creates a company from the empty state and refreshes the list", async () => {
    mockedGet.mockResolvedValueOnce([]);
    mockedGet.mockResolvedValueOnce([sampleEntity]);
    mockedPost.mockResolvedValueOnce(sampleEntity);
    const user = userEvent.setup();
    render(<LegalEntitiesPage />);

    await user.click(await screen.findByRole("button", { name: /add company/i }));
    await user.type(screen.getByLabelText(/company name/i), "Acme Technologies Pvt Ltd");
    await user.click(screen.getByRole("button", { name: /^add company$/i }));

    await waitFor(() => expect(mockedPost).toHaveBeenCalledTimes(1));
    expect(mockedPost).toHaveBeenCalledWith(
      "/legal-entities",
      expect.objectContaining({ name: "Acme Technologies Pvt Ltd" }),
    );
    expect(toastMock).toHaveBeenCalledWith(expect.objectContaining({ variant: "success" }));
    expect(await screen.findByText("Acme Technologies Pvt Ltd")).toBeInTheDocument();
  });

  it("shows a validation error when the name is missing", async () => {
    mockedGet.mockResolvedValueOnce([]);
    const user = userEvent.setup();
    render(<LegalEntitiesPage />);

    await user.click(await screen.findByRole("button", { name: /add company/i }));
    await user.click(screen.getByRole("button", { name: /^add company$/i }));

    expect(await screen.findByText(/company name is required/i)).toBeInTheDocument();
    expect(mockedPost).not.toHaveBeenCalled();
  });

  it("surfaces an API error toast when creation fails", async () => {
    mockedGet.mockResolvedValueOnce([]);
    mockedPost.mockRejectedValueOnce(
      new ApiError({ status: 500, code: "INTERNAL_ERROR", message: "Something broke" }),
    );
    const user = userEvent.setup();
    render(<LegalEntitiesPage />);

    await user.click(await screen.findByRole("button", { name: /add company/i }));
    await user.type(screen.getByLabelText(/company name/i), "Acme Pvt Ltd");
    await user.click(screen.getByRole("button", { name: /^add company$/i }));

    await waitFor(() =>
      expect(toastMock).toHaveBeenCalledWith(
        expect.objectContaining({ title: "Could not add company", variant: "danger" }),
      ),
    );
  });
});
