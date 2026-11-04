import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const push = vi.fn();
vi.mock("next/navigation", () => ({ useRouter: () => ({ push }) }));
vi.mock("@/lib/auth/auth-context", () => ({
  useAuth: () => ({ user: { company_timezone: "Asia/Kolkata" } }),
}));
vi.mock("@/lib/dates/use-company-date", () => ({ useCompanyDatePattern: () => "dd/MM/yyyy" }));
vi.mock("@/components/common/toast", () => ({ useToast: () => ({ toast: vi.fn() }) }));
vi.mock("@/lib/api/client", () => ({
  apiClient: { get: vi.fn(), getList: vi.fn(), post: vi.fn() },
}));

import NewAttendancePolicyPage from "@/app/app/attendance-policies/new/page";
import { apiClient } from "@/lib/api/client";

const mockedGet = vi.mocked(apiClient.get);
const mockedGetList = vi.mocked(apiClient.getList);
const mockedPost = vi.mocked(apiClient.post);

describe("new attendance policy", () => {
  let companyOwn: unknown = null;

  beforeEach(() => {
    companyOwn = null;
    mockedGet.mockImplementation(((path: string) => {
      if (path === "/attendance-policies/form-context") {
        return Promise.resolve({ shift_types_in_use: ["FIXED"] });
      }
      if (path.startsWith("/policy-assignments/coverage")) {
        return Promise.resolve({
          scope_type: "COMPANY",
          scope_id: null,
          as_of: "2026-06-01",
          rows: [
            {
              policy_kind: "ATTENDANCE_POLICY",
              leave_type_id: null,
              leave_type_name: null,
              own: companyOwn,
              applied: null,
            },
          ],
        });
      }
      return Promise.resolve([]);
    }) as never);
    mockedGetList.mockResolvedValue({
      data: [],
      pagination: { page: 1, per_page: 100, total: 0, total_pages: 0, has_next: false, has_prev: false },
    } as never);
    mockedPost.mockResolvedValue({ policy: { id: "new-1" } } as never);
  });

  afterEach(() => {
    mockedGet.mockReset();
    mockedGetList.mockReset();
    mockedPost.mockReset();
    push.mockReset();
  });

  it("publishes a template in one call and assigns it company-wide by default", async () => {
    const user = userEvent.setup();
    render(<NewAttendancePolicyPage />);
    expect(screen.getByLabelText(/Policy name/)).toHaveValue("Standard office");

    await user.click(screen.getByRole("button", { name: /Save & publish/ }));
    const dialog = await screen.findByRole("dialog");
    await waitFor(() => expect(within(dialog).getByLabelText(/Who follows/)).toHaveValue("COMPANY"));
    await user.click(within(dialog).getByRole("button", { name: "Publish" }));

    await waitFor(() => expect(mockedPost).toHaveBeenCalledTimes(1));
    const [path, body] = mockedPost.mock.calls[0] as [string, Record<string, never>];
    expect(path).toBe("/attendance-policies/setup");
    expect(body).toMatchObject({
      name: "Standard office",
      publish: true,
      assign: { scope_type: "COMPANY", scope_id: null, expected_version: null },
    });
    expect(body.rules).toMatchObject({ grace_in_minutes: 10 });
    expect((body.rules as unknown as { hour_bands: unknown[] }).hour_bands).toHaveLength(3);
    expect(push).toHaveBeenCalledWith("/app/attendance-policies/new-1");
  });

  it("does not take over from an existing company policy without being asked", async () => {
    companyOwn = { assignment_id: "a1", policy_id: "old", policy_name: "Old", effective_from: "2026-01-01", version: 3 };
    const user = userEvent.setup();
    render(<NewAttendancePolicyPage />);
    await user.click(screen.getByRole("button", { name: /Save & publish/ }));
    const dialog = await screen.findByRole("dialog");
    await waitFor(() => expect(within(dialog).getByLabelText(/Who follows/)).toHaveValue("NOBODY"));
    await user.click(within(dialog).getByRole("button", { name: "Publish" }));
    await waitFor(() => expect(mockedPost).toHaveBeenCalledTimes(1));
    expect((mockedPost.mock.calls[0][1] as { assign: unknown }).assign).toBeNull();
  });

  it("switching template replaces the rules and the untouched name", async () => {
    const user = userEvent.setup();
    render(<NewAttendancePolicyPage />);
    await user.click(screen.getByRole("radio", { name: /Strict attendance/ }));
    expect(screen.getByLabelText(/Policy name/)).toHaveValue("Strict attendance");
    expect(screen.getByLabelText(/Late arrival grace/)).toHaveValue(0);
    expect(screen.getByLabelText(/Late days before a half-day/)).toHaveValue(3);
  });

  it("keeps a name the user typed when switching template", async () => {
    const user = userEvent.setup();
    render(<NewAttendancePolicyPage />);
    const name = screen.getByLabelText(/Policy name/);
    await user.clear(name);
    await user.type(name, "Factory");
    await user.click(screen.getByRole("radio", { name: /Flexible hours/ }));
    expect(screen.getByLabelText(/Policy name/)).toHaveValue("Factory");
  });

  it("asks for hour bands before publishing from scratch", async () => {
    const user = userEvent.setup();
    render(<NewAttendancePolicyPage />);
    await user.click(screen.getByRole("radio", { name: /Start from scratch/ }));
    const name = screen.getByLabelText(/Policy name/);
    await user.type(name, "Mine");
    await user.click(screen.getByRole("button", { name: /Save & publish/ }));
    expect(await screen.findByText(/Add at least one band to publish/)).toBeInTheDocument();
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("saves a draft without publishing or assigning", async () => {
    const user = userEvent.setup();
    render(<NewAttendancePolicyPage />);
    await user.click(screen.getByRole("button", { name: "Save as draft" }));
    await waitFor(() => expect(mockedPost).toHaveBeenCalledTimes(1));
    expect(mockedPost.mock.calls[0][1]).toMatchObject({ publish: false, assign: null });
  });

  it("says nothing was saved when publishing fails, and stays on the page", async () => {
    mockedPost.mockRejectedValue(new Error("Boom"));
    const user = userEvent.setup();
    render(<NewAttendancePolicyPage />);
    await user.click(screen.getByRole("button", { name: /Save & publish/ }));
    const dialog = await screen.findByRole("dialog");
    await user.click(within(dialog).getByRole("button", { name: "Publish" }));
    expect(await within(dialog).findByText("Nothing was saved. Boom")).toBeInTheDocument();
    expect(push).not.toHaveBeenCalled();
  });
});
