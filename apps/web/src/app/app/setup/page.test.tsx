import { render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("@/lib/api/client", () => ({
  apiClient: { get: vi.fn() },
}));

import CompanySetupPage from "@/app/app/setup/page";
import { apiClient } from "@/lib/api/client";
import { ApiError } from "@/lib/api/errors";
import type { SetupChecklist } from "@/lib/company/setup-checklist";

const mockedGet = vi.mocked(apiClient.get);

const item = (code: string, label: string, required: boolean, done: boolean) => ({
  code,
  label,
  description: `${label} description`,
  required,
  is_complete: done,
  path: `/app/${code.toLowerCase()}`,
});

const partial: SetupChecklist = {
  items: [
    item("SHIFT", "Create a shift", true, true),
    item("EMPLOYEES", "Add your people", true, false),
    item("BRANCH", "Add your offices", false, false),
  ],
  required_total: 2,
  required_complete: 1,
  next_code: "EMPLOYEES",
};

describe("CompanySetupPage", () => {
  afterEach(() => {
    mockedGet.mockReset();
  });

  it("shows a loading state before the response resolves", () => {
    mockedGet.mockImplementation(() => new Promise(() => {}));
    render(<CompanySetupPage />);
    expect(screen.getByRole("status")).toBeInTheDocument();
  });

  it("lists essentials and optional steps from the one live checklist", async () => {
    mockedGet.mockResolvedValue(partial);
    render(<CompanySetupPage />);

    expect(await screen.findByText("Add your people")).toBeInTheDocument();
    expect(screen.getAllByText("1 of 2 essentials done").length).toBeGreaterThan(0);
    expect(screen.getByText("Add your offices")).toBeInTheDocument();
    expect(screen.getByText("Done")).toBeInTheDocument();
    // Only the checklist is asked for: there is no second, disagreeing "registration" count.
    expect(mockedGet).toHaveBeenCalledTimes(1);
    expect(mockedGet).toHaveBeenCalledWith("/companies/current/setup-checklist");
  });

  it("says so when every essential is done", async () => {
    mockedGet.mockResolvedValue({ ...partial, required_complete: 2, next_code: "BRANCH" });
    render(<CompanySetupPage />);
    expect(await screen.findByText("Essentials done")).toBeInTheDocument();
  });

  it("explains itself when the checklist cannot be loaded, instead of rendering nothing", async () => {
    mockedGet.mockRejectedValue(
      new ApiError({ status: 403, code: "PERMISSION_DENIED", message: "Forbidden" }),
    );
    render(<CompanySetupPage />);
    expect(await screen.findByText(/could not load your setup list/i)).toBeInTheDocument();
  });
});
