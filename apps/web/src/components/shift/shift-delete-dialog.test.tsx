import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("@/lib/api/client", () => ({
  apiClient: { get: vi.fn(), post: vi.fn() },
}));

import { ShiftDeleteDialog } from "@/components/shift/shift-delete-dialog";
import { apiClient } from "@/lib/api/client";
import type { Shift, ShiftDeletionCheck } from "@/lib/shift/types";

const mockedGet = vi.mocked(apiClient.get);
const mockedPost = vi.mocked(apiClient.post);

const shift = {
  id: "shift-1",
  name: "Night Crew",
  version: 4,
  is_active: false,
} as Shift;

function renderDialog() {
  const onDeleted = vi.fn();
  const onStale = vi.fn();
  render(
    <ShiftDeleteDialog
      open
      onOpenChange={vi.fn()}
      shift={shift}
      onDeleted={onDeleted}
      onStale={onStale}
    />,
  );
  return { onDeleted, onStale };
}

const allowed: ShiftDeletionCheck = {
  can_delete: true,
  blockers: [],
  published_version_count: 1,
  draft_version_count: 0,
};

describe("ShiftDeleteDialog", () => {
  afterEach(() => {
    mockedGet.mockReset();
    mockedPost.mockReset();
  });

  it("lists every blocker and offers no way to delete while any exist", async () => {
    mockedGet.mockResolvedValue({
      ...allowed,
      can_delete: false,
      blockers: [
        {
          code: "SHIFT_STILL_ACTIVE",
          message: "the shift is still active; deactivate it first",
          count: 1,
        },
        {
          code: "SHIFT_HAS_ROSTER_ENTRIES",
          message: "3 roster entr(ies) use it",
          count: 3,
        },
      ],
    });
    renderDialog();

    expect(
      await screen.findByText(/still active; deactivate it first/i),
    ).toBeInTheDocument();
    expect(screen.getByText(/3 roster entr/i)).toBeInTheDocument();
    expect(screen.queryByLabelText(/to confirm/i)).not.toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: /delete permanently/i }),
    ).toBeDisabled();
  });

  it("requires name, reason and acknowledgement before the delete is enabled", async () => {
    mockedGet.mockResolvedValue(allowed);
    mockedPost.mockResolvedValue(undefined);
    const user = userEvent.setup();
    const { onDeleted } = renderDialog();

    const button = await screen.findByRole("button", {
      name: /delete permanently/i,
    });
    expect(button).toBeDisabled();

    await user.type(screen.getByLabelText(/to confirm/i), "night crew");
    await user.type(
      screen.getByLabelText(/reason for deletion/i),
      "Created by mistake",
    );
    await user.click(screen.getByRole("checkbox"));
    expect(button).toBeDisabled(); // wrong-case name

    await user.clear(screen.getByLabelText(/to confirm/i));
    await user.type(screen.getByLabelText(/to confirm/i), "Night Crew");
    expect(button).toBeEnabled();

    await user.click(button);
    await waitFor(() => expect(onDeleted).toHaveBeenCalled());
    expect(mockedPost).toHaveBeenCalledWith(
      "/shifts/shift-1/delete",
      {
        confirm_name: "Night Crew",
        reason: "Created by mistake",
        acknowledge_irreversible: true,
      },
      { ifMatch: "4" },
    );
  });
});
