import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

const permissions = vi.hoisted(() => ({ codes: [] as string[] }));

vi.mock("@/lib/auth/use-permissions", () => ({
  usePermissions: () => ({ can: (code: string) => permissions.codes.includes(code) }),
}));

vi.mock("@/lib/api/client", () => ({
  apiClient: { getList: vi.fn(), post: vi.fn(), delete: vi.fn() },
}));

import AttendanceGeofencesPage from "@/app/app/attendance-geofences/page";
import { apiClient } from "@/lib/api/client";
import { ApiError } from "@/lib/api/errors";

const mockedGetList = vi.mocked(apiClient.getList);
const mockedPost = vi.mocked(apiClient.post);

const hq = {
  branch_id: "b-1",
  name: "Kochi Office",
  code: null,
  is_active: true,
  latitude: 9.9312,
  longitude: 76.2673,
  radius_m: 100,
  configured: true,
  assigned_employee_count: 12,
  authorized_employee_count: 1,
};
const bare = { ...hq, branch_id: "b-2", name: "Unconfigured", assigned_employee_count: 0, authorized_employee_count: 0, latitude: null, longitude: null, radius_m: null, configured: false };

function envelope<T>(data: T[]) {
  return { data, pagination: null, meta: { request_id: "r" } } as never;
}

function route(attempts: unknown[] = []) {
  mockedGetList.mockImplementation(async (path: string) => {
    if (path === "/attendance/geofences") return envelope([hq, bare]);
    if (path === "/attendance/workplace-authorizations") return envelope([]);
    if (path === "/employees")
      return envelope([{ id: "e-1", first_name: "Asha", last_name: "N", employee_code: "E001" }]);
    if (path === "/attendance/geofence-attempts") return envelope(attempts);
    throw new Error(`unexpected ${path}`);
  });
}

afterEach(() => {
  vi.clearAllMocks();
  permissions.codes = [];
});

describe("AttendanceGeofencesPage", () => {
  it("lists workplaces with usage counts and flags an unconfigured branch", async () => {
    permissions.codes = ["ATTENDANCE.POLICY_MANAGE"];
    route();
    render(<AttendanceGeofencesPage />);

    expect(await screen.findByRole("cell", { name: "Kochi Office" })).toBeInTheDocument();
    expect(screen.getByText("12")).toBeInTheDocument();
    expect(screen.getByText("Active")).toBeInTheDocument();
    expect(screen.getByText("Not configured")).toBeInTheDocument();
    const link = screen.getByRole("link", { name: /9\.93120, 76\.26730/ });
    expect(link).toHaveAttribute("href", expect.stringContaining("openstreetmap.org"));
    expect(link).toHaveAttribute("rel", expect.stringContaining("noopener"));
    // Reviewing attempts needs a different permission.
    expect(screen.queryByText("Location attempts")).not.toBeInTheDocument();
  });

  it("only offers usable workplaces for authorisation and validates the form", async () => {
    permissions.codes = ["ATTENDANCE.POLICY_MANAGE"];
    route();
    const user = userEvent.setup();
    render(<AttendanceGeofencesPage />);
    await screen.findByRole("cell", { name: "Kochi Office" });

    const workplaceSelect = screen.getByLabelText("Workplace");
    expect(workplaceSelect).toHaveTextContent("Kochi Office");
    expect(workplaceSelect).not.toHaveTextContent("Unconfigured");

    await user.click(screen.getByRole("button", { name: "Authorise" }));
    expect(await screen.findByText("Choose an employee and a workplace.")).toBeInTheDocument();
    expect(mockedPost).not.toHaveBeenCalled();
  });

  it("authorises an employee and shows server refusals", async () => {
    permissions.codes = ["ATTENDANCE.POLICY_MANAGE"];
    route();
    mockedPost.mockRejectedValueOnce(
      new ApiError({ status: 409, code: "WORKPLACE_AUTHORIZATION_EXISTS", message: "Already authorised", details: [] } as never),
    );
    const user = userEvent.setup();
    render(<AttendanceGeofencesPage />);
    await screen.findByRole("cell", { name: "Kochi Office" });

    await user.selectOptions(screen.getByLabelText("Employee"), "e-1");
    await user.selectOptions(screen.getByLabelText("Workplace"), "b-1");
    await user.click(screen.getByRole("button", { name: "Authorise" }));

    await waitFor(() =>
      expect(mockedPost).toHaveBeenCalledWith("/attendance/workplace-authorizations", {
        employee_id: "e-1",
        branch_id: "b-1",
      }),
    );
    expect(await screen.findByText(/Already authorised/)).toBeInTheDocument();
  });

  it("shows rejected attempts in plain language without implying they became attendance", async () => {
    permissions.codes = ["ATTENDANCE.VIEW_ALL"];
    route([
      {
        id: "a-1",
        employee_id: "e-1",
        punch_id: null,
        direction: "IN",
        source: "WEB",
        mode: "REQUIRED",
        outcome: "OUTSIDE_GEOFENCE",
        accepted: false,
        branch_id: "b-1",
        distance_m: "850.25",
        radius_m: "100.00",
        accuracy_m: "12.00",
        latitude: "9.9390",
        longitude: "76.2673",
        captured_at: null,
        client_error: null,
        created_at: "2026-10-28T09:00:00Z",
      },
    ]);
    render(<AttendanceGeofencesPage />);

    expect(await screen.findByText("Outside the workplace")).toBeInTheDocument();
    expect(screen.getByText("Rejected")).toBeInTheDocument();
    expect(screen.getByText("850 m / 100 m")).toBeInTheDocument();
    expect(screen.getByText(/never becomes attendance by itself/)).toBeInTheDocument();
    expect(mockedGetList).toHaveBeenCalledWith(
      "/attendance/geofence-attempts",
      expect.objectContaining({ accepted: "false" }),
    );
    // No configuration section without the policy-manage permission.
    expect(screen.queryByText("Extra workplaces for individual employees")).not.toBeInTheDocument();
  });

  it("tells a user with neither permission that there is no access", async () => {
    render(<AttendanceGeofencesPage />);
    expect(await screen.findByText("No access")).toBeInTheDocument();
    expect(mockedGetList).not.toHaveBeenCalled();
  });
});
