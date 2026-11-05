import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("next/navigation", () => ({
  useParams: () => ({ id: "shift-1" }),
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
}));

vi.mock("@/lib/auth/auth-context", () => ({
  useAuth: () => ({
    session: { companyId: "company-1", accessToken: "token" },
    user: { permissions: ["ORG.SHIFT.MANAGE"] },
  }),
}));

const toastMock = vi.fn();
vi.mock("@/components/common/toast", () => ({
  useToast: () => ({ toast: toastMock }),
}));

vi.mock("@/lib/api/client", () => ({
  apiClient: { get: vi.fn(), getList: vi.fn(), post: vi.fn(), patch: vi.fn(), delete: vi.fn() },
}));

import ShiftDetailPage from "@/app/app/shifts/[id]/page";
import { apiClient } from "@/lib/api/client";
import { ApiError } from "@/lib/api/errors";
import type { Shift, ShiftVersion } from "@/lib/shift/types";

const mockedGet = vi.mocked(apiClient.get);
const mockedGetList = vi.mocked(apiClient.getList);
const mockedPost = vi.mocked(apiClient.post);
const mockedPatch = vi.mocked(apiClient.patch);
const mockedDelete = vi.mocked(apiClient.delete);

const sampleShift: Shift = {
  id: "shift-1",
  company_id: "company-1",
  name: "General Shift",
  code: "GEN",
  start_time: "00:00",
  end_time: "00:00",
  break_minutes_paid: 0,
  break_minutes_unpaid: 0,
  grace_in_minutes: 0,
  grace_out_minutes: 0,
  half_day_threshold_hours: null,
  min_hours_full_day: null,
  is_night_shift: false,
  is_cross_midnight: false,
  is_ot_eligible: false,
  is_active: true,
  version: 1,
  created_at: "2026-08-01T00:00:00Z",
  updated_at: "2026-08-01T00:00:00Z",
  current_version_id: null,
  draft_version_id: "version-1",
};

const draftVersion: ShiftVersion = {
  id: "version-1",
  company_id: "company-1",
  shift_id: "shift-1",
  status: "DRAFT",
  version: 1,
  effective_from: null,
  effective_to: null,
  shift_type: null,
  timezone: null,
  start_time: null,
  end_time: null,
  window_start: null,
  window_end: null,
  core_start: null,
  core_end: null,
  required_minutes: null,
  scheduled_minutes: null,
  min_scheduled_minutes: null,
  max_scheduled_minutes: null,
  is_night_shift: false,
  is_cross_midnight: false,
  is_ot_eligible: false,
  operates_on_holiday: false,
  operates_on_weekly_off: false,
  weekly_off_pattern_id: null,
  publish_reason: null,
  published_at: null,
  published_by: null,
  created_at: "2026-08-01T00:00:00Z",
  updated_at: "2026-08-01T00:00:00Z",
  breaks: [],
  duty_blocks: [],
};

function mockLoad(shift: Shift, versions: ShiftVersion[] = [draftVersion]) {
  mockedGet.mockImplementation((path: string) => {
    if (path === "/shifts/shift-1") return Promise.resolve(shift);
    if (path === "/weekly-off-patterns") return Promise.resolve([]);
    return Promise.reject(new Error(`Unexpected path ${path}`));
  });
  mockedGetList.mockImplementation((path: string) => {
    if (path === "/shifts/shift-1/versions") {
      return Promise.resolve({
        data: versions,
        pagination: {
          page: 1,
          per_page: 25,
          total: versions.length,
          total_pages: versions.length > 0 ? 1 : 0,
        },
        meta: { request_id: "r1" },
      });
    }
    return Promise.reject(new Error(`Unexpected path ${path}`));
  });
}

describe("ShiftDetailPage", () => {
  afterEach(() => {
    mockedGet.mockReset();
    mockedGetList.mockReset();
    mockedPost.mockReset();
    mockedPatch.mockReset();
    mockedDelete.mockReset();
    toastMock.mockReset();
  });

  it("loads and renders the shift identity", async () => {
    mockLoad(sampleShift);
    render(<ShiftDetailPage />);

    expect(await screen.findByRole("heading", { name: "General Shift" })).toBeInTheDocument();
    expect(screen.getByText("Active")).toBeInTheDocument();
    expect(screen.getByText(/draft in progress/i)).toBeInTheDocument();
  });

  it("shows an error state when not found", async () => {
    mockedGet.mockRejectedValueOnce(
      new ApiError({ status: 404, code: "NOT_FOUND", message: "Not found" }),
    );
    render(<ShiftDetailPage />);

    expect(await screen.findByText(/could not be found/i)).toBeInTheDocument();
  });

  it("enters edit mode and restores values on cancel", async () => {
    mockLoad(sampleShift);
    const user = userEvent.setup();
    render(<ShiftDetailPage />);

    await user.click(await screen.findByRole("button", { name: /^edit$/i }));
    const nameInput = screen.getByLabelText(/shift name/i);
    await user.clear(nameInput);
    await user.type(nameInput, "Renamed");
    await user.click(screen.getByRole("button", { name: /cancel/i }));

    expect(screen.queryByLabelText(/shift code/i)).not.toBeInTheDocument();
  });

  it("renames the shift without touching its draft when the schedule is left alone", async () => {
    mockLoad(sampleShift);
    mockedPatch.mockResolvedValueOnce({ ...sampleShift, name: "Renamed Shift", version: 2 });
    const user = userEvent.setup();
    render(<ShiftDetailPage />);

    await user.click(await screen.findByRole("button", { name: /^edit$/i }));
    const nameInput = await screen.findByLabelText(/shift name/i);
    await user.clear(nameInput);
    await user.type(nameInput, "Renamed Shift");
    await user.click(screen.getByRole("button", { name: /^save as draft$/i }));

    await waitFor(() => expect(mockedPatch).toHaveBeenCalledTimes(1));
    expect(mockedPatch).toHaveBeenCalledWith(
      "/shifts/shift-1",
      { name: "Renamed Shift" },
      { ifMatch: "1" },
    );
    expect(mockedPost).not.toHaveBeenCalled();
    expect(toastMock).toHaveBeenCalledWith(expect.objectContaining({ variant: "success" }));
  });

  it("saves the name and the schedule together into the open draft", async () => {
    mockLoad(sampleShift);
    mockedPatch
      .mockResolvedValueOnce({ ...sampleShift, name: "Renamed Shift", version: 2 })
      .mockResolvedValueOnce({ ...draftVersion, shift_type: "FIXED", version: 2 });
    const user = userEvent.setup();
    render(<ShiftDetailPage />);

    await user.click(await screen.findByRole("button", { name: /^edit$/i }));
    const nameInput = await screen.findByLabelText(/shift name/i);
    await user.clear(nameInput);
    await user.type(nameInput, "Renamed Shift");
    await user.selectOptions(screen.getByLabelText(/^type/i), "FIXED");
    await user.type(screen.getByLabelText(/start time/i), "09:00");
    await user.type(screen.getByLabelText(/end time/i), "18:00");
    await user.click(screen.getByRole("button", { name: /^save as draft$/i }));

    await waitFor(() => expect(mockedPatch).toHaveBeenCalledTimes(2));
    expect(mockedPatch).toHaveBeenNthCalledWith(
      1,
      "/shifts/shift-1",
      { name: "Renamed Shift" },
      { ifMatch: "1" },
    );
    expect(mockedPatch).toHaveBeenNthCalledWith(
      2,
      "/shifts/shift-1/versions/version-1",
      expect.objectContaining({ shift_type: "FIXED", start_time: "09:00", end_time: "18:00" }),
      { ifMatch: "1" },
    );
    expect(mockedPost).not.toHaveBeenCalled();
  });

  it("creates the draft automatically when none exists", async () => {
    mockLoad({ ...sampleShift, draft_version_id: null }, []);
    mockedPost.mockResolvedValueOnce({ ...draftVersion, id: "version-9" });
    mockedPatch.mockResolvedValueOnce({ ...draftVersion, id: "version-9", shift_type: "FIXED", version: 2 });
    const user = userEvent.setup();
    render(<ShiftDetailPage />);

    await user.click(await screen.findByRole("button", { name: /^edit$/i }));
    await user.selectOptions(await screen.findByLabelText(/^type/i), "FIXED");
    await user.type(screen.getByLabelText(/start time/i), "09:00");
    await user.type(screen.getByLabelText(/end time/i), "18:00");
    await user.click(screen.getByRole("button", { name: /^save as draft$/i }));

    await waitFor(() => expect(mockedPatch).toHaveBeenCalledTimes(1));
    expect(mockedPost).toHaveBeenCalledWith("/shifts/shift-1/versions", {});
    expect(mockedPatch).toHaveBeenCalledWith(
      "/shifts/shift-1/versions/version-9",
      expect.objectContaining({ shift_type: "FIXED" }),
      { ifMatch: "1" },
    );
  });

  it("saves the schedule and opens the publish step straight away", async () => {
    mockLoad({ ...sampleShift, draft_version_id: null }, []);
    mockedPost
      .mockResolvedValueOnce({ ...draftVersion, id: "version-9" })
      .mockResolvedValueOnce({ ...draftVersion, id: "version-9", status: "PUBLISHED" });
    mockedPatch.mockResolvedValueOnce({
      ...draftVersion,
      id: "version-9",
      shift_type: "FIXED",
      version: 2,
    });
    const user = userEvent.setup();
    render(<ShiftDetailPage />);

    await user.click(await screen.findByRole("button", { name: /^edit$/i }));
    await user.selectOptions(await screen.findByLabelText(/^type/i), "FIXED");
    await user.type(screen.getByLabelText(/start time/i), "09:00");
    await user.type(screen.getByLabelText(/end time/i), "18:00");
    await user.click(screen.getByRole("button", { name: /^save & publish…$/i }));

    const dialog = await screen.findByRole("dialog");
    await user.click(within(dialog).getByRole("button", { name: /^publish$/i }));
    await waitFor(() =>
      expect(mockedPost).toHaveBeenCalledWith(
        "/shifts/shift-1/versions/version-9/publish",
        expect.anything(),
        { ifMatch: "2" },
      ),
    );
  });

  it("deactivates the shift after confirmation", async () => {
    mockLoad(sampleShift);
    mockedDelete.mockResolvedValueOnce({ ...sampleShift, is_active: false, version: 2 });
    const user = userEvent.setup();
    render(<ShiftDetailPage />);

    await user.click(await screen.findByRole("button", { name: /deactivate/i }));
    const dialog = screen.getByRole("dialog");
    await user.click(within(dialog).getByRole("button", { name: /deactivate/i }));

    await waitFor(() => expect(mockedDelete).toHaveBeenCalledTimes(1));
    expect(mockedDelete).toHaveBeenCalledWith("/shifts/shift-1", { ifMatch: "1" });
    expect(toastMock).toHaveBeenCalledWith(expect.objectContaining({ variant: "success" }));
  });

  it("shows the open draft on the Versions tab and edits it", async () => {
    mockLoad(sampleShift);
    const user = userEvent.setup();
    render(<ShiftDetailPage />);

    await screen.findByRole("heading", { name: "General Shift" });
    await user.click(screen.getByRole("tab", { name: /versions/i }));

    expect(await screen.findByText(/no published schedule yet/i)).toBeInTheDocument();
    expect(screen.getByLabelText(/^type/i)).toBeInTheDocument();
  });

  it("saves a FIXED draft and shows the timing fields", async () => {
    mockLoad(sampleShift);
    mockedPatch.mockResolvedValueOnce({
      ...draftVersion,
      shift_type: "FIXED",
      effective_from: "2026-09-01",
      start_time: "09:00",
      end_time: "18:00",
      is_cross_midnight: false,
      version: 2,
    });
    const user = userEvent.setup();
    render(<ShiftDetailPage />);

    await screen.findByRole("heading", { name: "General Shift" });
    await user.click(screen.getByRole("tab", { name: /versions/i }));
    await screen.findByLabelText(/^type/i);

    await user.selectOptions(screen.getByLabelText(/^type/i), "FIXED");
    await user.type(screen.getByLabelText(/effective from/i), "2026-09-01");
    await user.type(screen.getByLabelText(/start time/i), "09:00");
    await user.type(screen.getByLabelText(/end time/i), "18:00");
    await user.click(screen.getByRole("button", { name: /save draft/i }));

    await waitFor(() => expect(mockedPatch).toHaveBeenCalledTimes(1));
    const [path, body, options] = mockedPatch.mock.calls[0];
    expect(path).toBe("/shifts/shift-1/versions/version-1");
    expect(body).toMatchObject({
      shift_type: "FIXED",
      effective_from: "2026-09-01",
      start_time: "09:00",
      end_time: "18:00",
    });
    expect(options).toEqual({ ifMatch: "1" });
    expect(toastMock).toHaveBeenCalledWith(expect.objectContaining({ variant: "success" }));
  });

  it("publishes a draft via the publish dialog", async () => {
    const configuredDraft: ShiftVersion = {
      ...draftVersion,
      shift_type: "FIXED",
      effective_from: "2026-09-01",
      start_time: "09:00",
      end_time: "18:00",
    };
    mockLoad(sampleShift, [configuredDraft]);
    mockedPost.mockResolvedValueOnce({ ...configuredDraft, status: "PUBLISHED", version: 2 });
    const user = userEvent.setup();
    render(<ShiftDetailPage />);

    await screen.findByRole("heading", { name: "General Shift" });
    await user.click(screen.getByRole("tab", { name: /versions/i }));
    await screen.findByLabelText(/^type/i);

    await user.click(screen.getByRole("button", { name: /^publish…$/i }));
    const dialog = await screen.findByRole("dialog");
    await user.click(within(dialog).getByRole("button", { name: /^publish$/i }));

    await waitFor(() => expect(mockedPost).toHaveBeenCalledTimes(1));
    expect(mockedPost).toHaveBeenCalledWith(
      "/shifts/shift-1/versions/version-1/publish",
      { publish_reason: null },
      { ifMatch: "1" },
    );
    expect(toastMock).toHaveBeenCalledWith(
      expect.objectContaining({ title: "Schedule published", variant: "success" }),
    );
  });

  it("includes expected_previous_version when a published version is already open", async () => {
    const publishedVersion: ShiftVersion = {
      ...draftVersion,
      id: "version-0",
      status: "PUBLISHED",
      version: 3,
      shift_type: "FIXED",
      effective_from: "2026-01-01",
      effective_to: null,
      start_time: "09:00",
      end_time: "18:00",
    };
    const configuredDraft: ShiftVersion = {
      ...draftVersion,
      shift_type: "FIXED",
      effective_from: "2026-09-01",
      start_time: "09:30",
      end_time: "18:30",
    };
    mockLoad(
      { ...sampleShift, current_version_id: "version-0" },
      [publishedVersion, configuredDraft],
    );
    mockedPost.mockResolvedValueOnce({ ...configuredDraft, status: "PUBLISHED", version: 2 });
    const user = userEvent.setup();
    render(<ShiftDetailPage />);

    await screen.findByRole("heading", { name: "General Shift" });
    await user.click(screen.getByRole("tab", { name: /versions/i }));
    await screen.findByLabelText(/^type/i);

    await user.click(screen.getByRole("button", { name: /^publish…$/i }));
    const dialog = await screen.findByRole("dialog");
    await user.click(within(dialog).getByRole("button", { name: /^publish$/i }));

    await waitFor(() => expect(mockedPost).toHaveBeenCalledTimes(1));
    expect(mockedPost).toHaveBeenCalledWith(
      "/shifts/shift-1/versions/version-1/publish",
      { publish_reason: null, expected_previous_version: 3 },
      { ifMatch: "1" },
    );
  });

  it("surfaces a stale-draft banner when publish returns 409 STALE_RESOURCE", async () => {
    mockLoad(sampleShift, [
      { ...draftVersion, shift_type: "FIXED", effective_from: "2026-09-01", start_time: "09:00", end_time: "18:00" },
    ]);
    mockedPost.mockRejectedValueOnce(
      new ApiError({ status: 409, code: "STALE_RESOURCE", message: "Stale" }),
    );
    const user = userEvent.setup();
    render(<ShiftDetailPage />);

    await screen.findByRole("heading", { name: "General Shift" });
    await user.click(screen.getByRole("tab", { name: /versions/i }));
    await screen.findByLabelText(/^type/i);

    await user.click(screen.getByRole("button", { name: /^publish…$/i }));
    const dialog = await screen.findByRole("dialog");
    await user.click(within(dialog).getByRole("button", { name: /^publish$/i }));

    expect(await screen.findByText(/changed by someone else/i)).toBeInTheDocument();
  });

  it("discards a draft after confirmation", async () => {
    mockLoad(sampleShift);
    mockedDelete.mockResolvedValueOnce({ ...draftVersion, version: 2 });
    const user = userEvent.setup();
    render(<ShiftDetailPage />);

    await screen.findByRole("heading", { name: "General Shift" });
    await user.click(screen.getByRole("tab", { name: /versions/i }));
    await screen.findByLabelText(/^type/i);

    await user.click(screen.getByRole("button", { name: /discard draft/i }));
    const dialog = await screen.findByRole("dialog");
    await user.click(within(dialog).getByRole("button", { name: /^discard draft$/i }));

    await waitFor(() => expect(mockedDelete).toHaveBeenCalledTimes(1));
    expect(mockedDelete).toHaveBeenCalledWith("/shifts/shift-1/versions/version-1", {
      ifMatch: "1",
    });
    expect(toastMock).toHaveBeenCalledWith(
      expect.objectContaining({ title: "Draft discarded", variant: "success" }),
    );
  });

  it("offers to create a new draft when none is open", async () => {
    mockLoad({ ...sampleShift, draft_version_id: null }, []);
    mockedPost.mockResolvedValueOnce(draftVersion);
    const user = userEvent.setup();
    render(<ShiftDetailPage />);

    await screen.findByRole("heading", { name: "General Shift" });
    await user.click(screen.getByRole("tab", { name: /versions/i }));

    await user.click(await screen.findByRole("button", { name: /new draft/i }));

    await waitFor(() => expect(mockedPost).toHaveBeenCalledTimes(1));
    expect(mockedPost).toHaveBeenCalledWith("/shifts/shift-1/versions", {});
  });
});
