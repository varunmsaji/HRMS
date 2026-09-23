import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

const toastMock = vi.fn();
vi.mock("@/components/common/toast", () => ({
  useToast: () => ({ toast: toastMock }),
}));

vi.mock("@/lib/auth/auth-context", () => ({
  useAuth: () => ({ user: { company_timezone: "Asia/Kolkata" } }),
}));

vi.mock("@/lib/attendance/format", () => ({
  businessToday: () => "2026-09-23",
}));

vi.mock("@/lib/api/client", () => ({
  apiClient: { post: vi.fn() },
}));

import { CreatePeriodDialog } from "@/components/attendance-period/create-period-dialog";
import { apiClient } from "@/lib/api/client";
import { ApiError } from "@/lib/api/errors";
import type { LegalEntity } from "@/lib/legal-entity/types";

const mockedPost = vi.mocked(apiClient.post);

const entity = (id: string, name: string) => ({ id, name }) as LegalEntity;

function renderDialog(legalEntities: LegalEntity[]) {
  const onCreated = vi.fn();
  render(
    <CreatePeriodDialog
      open
      onOpenChange={vi.fn()}
      onCreated={onCreated}
      legalEntities={legalEntities}
    />,
  );
  return { onCreated };
}

describe("CreatePeriodDialog", () => {
  afterEach(() => {
    mockedPost.mockReset();
  });

  it("defaults to the current calendar month of the only legal entity", async () => {
    mockedPost.mockResolvedValueOnce({ id: "p-1" });
    const { onCreated } = renderDialog([entity("le-1", "Acme India")]);

    await userEvent.click(screen.getByRole("button", { name: /create period/i }));

    await waitFor(() => expect(onCreated).toHaveBeenCalled());
    expect(mockedPost).toHaveBeenCalledWith("/attendance-periods", {
      legal_entity_id: "le-1",
      month: "2026-09",
      label: undefined,
    });
  });

  it("requires choosing an entity when there are several", async () => {
    renderDialog([entity("le-1", "Acme India"), entity("le-2", "Acme Services")]);

    await userEvent.click(screen.getByRole("button", { name: /create period/i }));
    expect(await screen.findByText("Choose a legal entity.")).toBeInTheDocument();
    expect(mockedPost).not.toHaveBeenCalled();

    mockedPost.mockResolvedValueOnce({ id: "p-1" });
    await userEvent.selectOptions(screen.getByLabelText("Legal entity"), "le-2");
    await userEvent.selectOptions(screen.getByLabelText("Cycle"), "CUSTOM");
    await userEvent.click(screen.getByRole("button", { name: /create period/i }));

    await waitFor(() =>
      expect(mockedPost).toHaveBeenCalledWith("/attendance-periods", {
        legal_entity_id: "le-2",
        period_start: "2026-09-23",
        period_end: "2026-09-23",
        label: undefined,
      }),
    );
  });

  it("explains an overlap within the same legal entity", async () => {
    mockedPost.mockRejectedValueOnce(
      new ApiError({ status: 409, code: "ATTENDANCE_PERIOD_OVERLAP", message: "overlap" }),
    );
    renderDialog([entity("le-1", "Acme India")]);

    await userEvent.click(screen.getByRole("button", { name: /create period/i }));

    expect(
      await screen.findByText(/another period for this legal entity already covers/i),
    ).toBeInTheDocument();
  });
});
