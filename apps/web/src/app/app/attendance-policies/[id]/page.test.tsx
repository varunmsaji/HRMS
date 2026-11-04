import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("next/navigation", () => ({ useParams: () => ({ id: "p1" }) }));
vi.mock("@/lib/auth/use-permissions", () => ({ usePermissions: () => ({ can: () => true }) }));
vi.mock("@/lib/dates/use-company-date", () => ({ useCompanyDatePattern: () => "dd/MM/yyyy" }));
vi.mock("@/components/common/toast", () => ({ useToast: () => ({ toast: vi.fn() }) }));
vi.mock("@/lib/api/client", () => ({
  apiClient: { get: vi.fn(), post: vi.fn(), patch: vi.fn(), delete: vi.fn() },
}));

import AttendancePolicyDetailPage from "@/app/app/attendance-policies/[id]/page";
import { apiClient } from "@/lib/api/client";

const mockedGet = vi.mocked(apiClient.get);
const mockedPatch = vi.mocked(apiClient.patch);
const mockedPost = vi.mocked(apiClient.post);

const draft = {
  id: "v1",
  status: "DRAFT",
  version: 2,
  effective_from: "2027-01-01",
  effective_to: null,
  grace_in_minutes: 5,
  grace_out_minutes: 0,
  hour_bands: [],
  late_bands: [],
  early_departure_bands: [],
};

function serve() {
  mockedGet.mockImplementation(((path: string) =>
    Promise.resolve(
      path.endsWith("/versions")
        ? [draft]
        : { id: "p1", name: "Office", code: "AP1", is_active: true, version: 1 },
    )) as never);
}

async function openDraft() {
  const user = userEvent.setup();
  render(<AttendancePolicyDetailPage />);
  await user.click(await screen.findByRole("tab", { name: "Versions" }));
  await screen.findByRole("button", { name: "Publish…" });
  return user;
}

describe("publishing a draft with unsaved edits", () => {
  afterEach(() => {
    mockedGet.mockReset();
    mockedPatch.mockReset();
    mockedPost.mockReset();
  });

  it("saves the edits first, and the dialog then publishes the saved version", async () => {
    serve();
    mockedPatch.mockResolvedValue({ ...draft, version: 3, grace_in_minutes: 15 } as never);
    mockedPost.mockResolvedValue({} as never);
    const user = await openDraft();

    const grace = screen.getByLabelText(/Grace in/);
    await user.clear(grace);
    await user.type(grace, "15");
    await user.click(screen.getByRole("button", { name: "Publish…" }));

    await screen.findByRole("heading", { name: "Publish this version?" });
    expect(mockedPatch).toHaveBeenCalledTimes(1);
    expect(mockedPatch.mock.calls[0][1]).toMatchObject({ grace_in_minutes: 15 });

    await user.click(screen.getByRole("button", { name: "Publish" }));
    await waitFor(() =>
      expect(mockedPost).toHaveBeenCalledWith(
        "/attendance-policies/p1/versions/v1/publish",
        { publish_reason: null },
        { ifMatch: "3" },
      ),
    );
  });

  it("does not open the dialog when the save fails", async () => {
    serve();
    mockedPatch.mockRejectedValue(new Error("nope"));
    const user = await openDraft();

    const grace = screen.getByLabelText(/Grace in/);
    await user.clear(grace);
    await user.type(grace, "15");
    await user.click(screen.getByRole("button", { name: "Publish…" }));

    await waitFor(() => expect(mockedPatch).toHaveBeenCalled());
    expect(screen.queryByRole("heading", { name: "Publish this version?" })).toBeNull();
  });

  it("does not save again when nothing changed", async () => {
    serve();
    const user = await openDraft();
    await user.click(screen.getByRole("button", { name: "Publish…" }));
    await screen.findByRole("heading", { name: "Publish this version?" });
    expect(mockedPatch).not.toHaveBeenCalled();
  });
});
