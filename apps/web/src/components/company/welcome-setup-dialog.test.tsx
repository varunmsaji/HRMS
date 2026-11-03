import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const push = vi.fn();
vi.mock("next/navigation", () => ({ useRouter: () => ({ push }) }));

let mockUser: Record<string, unknown> | null;
vi.mock("@/lib/auth/auth-context", () => ({ useAuth: () => ({ user: mockUser }) }));
vi.mock("@/lib/api/client", () => ({ apiClient: { get: vi.fn() } }));

import { WelcomeSetupDialog } from "@/components/company/welcome-setup-dialog";
import { apiClient } from "@/lib/api/client";

const mockedGet = vi.mocked(apiClient.get);

function mockData(opts: { profileDone: boolean; legalEntities: number; branches: number }) {
  mockedGet.mockImplementation(async (path: string) => {
    if (path === "/companies/current/setup-progress") {
      return { status: "IN_PROGRESS", steps: [{ code: "COMPANY_PROFILE", label: "Company Profile", is_complete: opts.profileDone }] };
    }
    if (path === "/legal-entities") return Array.from({ length: opts.legalEntities });
    if (path === "/branches") return Array.from({ length: opts.branches });
    throw new Error(`unexpected ${path}`);
  });
}

const admin = {
  id: "user-1",
  company_status: "TRIAL",
  permissions: ["ORG.COMPANY.MANAGE", "ORG.BRANCH.MANAGE"],
};

describe("WelcomeSetupDialog", () => {
  beforeEach(() => {
    window.localStorage.clear();
    push.mockReset();
    mockedGet.mockReset();
    mockUser = admin;
  });
  afterEach(() => window.localStorage.clear());

  it("shows once on first login and sends the admin to the first unfinished step", async () => {
    mockData({ profileDone: false, legalEntities: 0, branches: 0 });
    render(<WelcomeSetupDialog companyName="Technobeala" />);
    expect(await screen.findByText("Welcome to Technobeala")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Start setup" }));
    expect(push).toHaveBeenCalledWith("/app/company");
  });

  it("points at branches when the profile and company already exist", async () => {
    mockData({ profileDone: true, legalEntities: 1, branches: 0 });
    render(<WelcomeSetupDialog companyName="Technobeala" />);
    await userEvent.click(await screen.findByRole("button", { name: "Start setup" }));
    expect(push).toHaveBeenCalledWith("/app/branches");
  });

  it("does not show again once it has been seen", async () => {
    mockData({ profileDone: false, legalEntities: 0, branches: 0 });
    const first = render(<WelcomeSetupDialog companyName="Technobeala" />);
    await screen.findByText("Welcome to Technobeala");
    first.unmount();
    render(<WelcomeSetupDialog companyName="Technobeala" />);
    await new Promise((resolve) => setTimeout(resolve, 20));
    expect(screen.queryByText("Welcome to Technobeala")).not.toBeInTheDocument();
  });

  it("stays away when setup is already finished", async () => {
    mockData({ profileDone: true, legalEntities: 1, branches: 2 });
    render(<WelcomeSetupDialog companyName="Technobeala" />);
    await waitFor(() => expect(mockedGet).toHaveBeenCalled());
    expect(screen.queryByText("Welcome to Technobeala")).not.toBeInTheDocument();
  });

  it("stays away for people who cannot manage the company, and while approval is pending", async () => {
    mockData({ profileDone: false, legalEntities: 0, branches: 0 });
    mockUser = { ...admin, permissions: ["EMPLOYEE.VIEW"] };
    const { unmount } = render(<WelcomeSetupDialog companyName="Technobeala" />);
    unmount();
    mockUser = { ...admin, company_status: "PENDING_APPROVAL" };
    render(<WelcomeSetupDialog companyName="Technobeala" />);
    await new Promise((resolve) => setTimeout(resolve, 20));
    expect(mockedGet).not.toHaveBeenCalled();
    expect(screen.queryByText("Welcome to Technobeala")).not.toBeInTheDocument();
  });
});
