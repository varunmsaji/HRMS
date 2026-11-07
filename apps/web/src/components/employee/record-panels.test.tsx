import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

const toastMock = vi.fn();
let permissions: string[] = [];
vi.mock("@/components/common/toast", () => ({ useToast: () => ({ toast: toastMock }) }));
vi.mock("@/lib/auth/use-permissions", () => ({
  usePermissions: () => ({ can: (code: string) => permissions.includes(code) }),
}));
vi.mock("@/lib/api/client", () => ({
  apiClient: { get: vi.fn(), post: vi.fn(), patch: vi.fn(), delete: vi.fn() },
}));

import { IdentityPanel } from "@/components/employee/identity-panel";
import { RecordListPanel } from "@/components/employee/record-list-panel";
import { apiClient } from "@/lib/api/client";
import { ApiError } from "@/lib/api/errors";
import { DEPENDENTS_SECTION, EXPERIENCE_SECTION } from "@/lib/employee/record-sections";

const mockedGet = vi.mocked(apiClient.get);
const mockedPost = vi.mocked(apiClient.post);
const mockedPatch = vi.mocked(apiClient.patch);
const mockedDelete = vi.mocked(apiClient.delete);

const experience = {
  id: "x1",
  version: 2,
  company_name: "Acme Ltd",
  designation: "Analyst",
  from_date: "2019-01-01",
  to_date: "2021-06-30",
  last_ctc_minor: 90000000,
  had_prior_pf_membership: true,
};

beforeEach(() => {
  vi.clearAllMocks();
  permissions = ["EMPLOYEE.UPDATE_SENSITIVE"];
});

describe("RecordListPanel", () => {
  it("lists the rows with formatted values from a paged request", async () => {
    mockedGet.mockResolvedValue([experience]);
    render(<RecordListPanel employeeId="e1" section={EXPERIENCE_SECTION} />);
    expect(await screen.findByText("Acme Ltd")).toBeInTheDocument();
    expect(mockedGet).toHaveBeenCalledWith("/employees/e1/experience?per_page=100");
    expect(screen.getByText("900000.00")).toBeInTheDocument();
    expect(screen.getByText("Yes")).toBeInTheDocument();
  });

  it("without the update grant there is no Add or Delete", async () => {
    permissions = [];
    mockedGet.mockResolvedValue([experience]);
    render(<RecordListPanel employeeId="e1" section={EXPERIENCE_SECTION} />);
    await screen.findByText("Acme Ltd");
    expect(screen.queryByRole("button", { name: "Add experience" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Delete/ })).not.toBeInTheDocument();
  });

  it("a forbidden list says so", async () => {
    mockedGet.mockRejectedValue(new ApiError({ status: 403, code: "PERMISSION_DENIED", message: "no" }));
    render(<RecordListPanel employeeId="e1" section={DEPENDENTS_SECTION} />);
    expect(await screen.findByText("You do not have permission to view this employee's dependents.")).toBeInTheDocument();
  });

  it("adding checks required fields, then posts the body and reloads", async () => {
    const user = userEvent.setup();
    mockedGet.mockResolvedValue([]);
    mockedPost.mockResolvedValue({});
    render(<RecordListPanel employeeId="e1" section={DEPENDENTS_SECTION} />);
    await user.click(await screen.findByRole("button", { name: "Add dependent / nominee" }));
    const dialog = await screen.findByRole("dialog");
    await user.click(within(dialog).getByRole("button", { name: "Save" }));
    expect(within(dialog).getByText("Full name is required.")).toBeInTheDocument();
    expect(mockedPost).not.toHaveBeenCalled();

    await user.type(within(dialog).getByLabelText(/Full name/), "Ravi");
    await user.type(within(dialog).getByLabelText(/^Relationship/), "Son");
    await user.click(within(dialog).getByLabelText("Is a minor"));
    await user.type(within(dialog).getByLabelText(/^Guardian name/), "Meera");
    await user.click(within(dialog).getByRole("button", { name: "Save" }));
    await waitFor(() => expect(mockedPost).toHaveBeenCalledTimes(1));
    expect(mockedPost).toHaveBeenCalledWith("/employees/e1/dependents", {
      full_name: "Ravi",
      relationship: "Son",
      is_minor: true,
      guardian_name: "Meera",
      is_pf_nominee: false,
      is_gratuity_nominee: false,
      is_esi_dependent: false,
    });
    expect(toastMock).toHaveBeenCalledWith(expect.objectContaining({ title: "Dependent added" }));
    await waitFor(() => expect(mockedGet).toHaveBeenCalledTimes(2));
  });

  it("server field errors land on their fields", async () => {
    const user = userEvent.setup();
    mockedGet.mockResolvedValue([]);
    mockedPost.mockRejectedValue(
      new ApiError({ status: 422, code: "VALIDATION_ERROR", message: "bad", details: [{ field: "body.from_date", code: "x", message: "Must be before To." }] }),
    );
    render(<RecordListPanel employeeId="e1" section={EXPERIENCE_SECTION} />);
    await user.click(await screen.findByRole("button", { name: "Add experience" }));
    const dialog = await screen.findByRole("dialog");
    await user.type(within(dialog).getByLabelText(/Company name/), "Acme");
    await user.type(within(dialog).getByLabelText(/^From/), "2020-01-01");
    await user.click(within(dialog).getByRole("button", { name: "Save" }));
    expect(await within(dialog).findByText("Must be before To.")).toBeInTheDocument();
  });

  it("deleting asks first and sends the row's version", async () => {
    const user = userEvent.setup();
    mockedGet.mockResolvedValue([experience]);
    mockedDelete.mockResolvedValue({});
    render(<RecordListPanel employeeId="e1" section={EXPERIENCE_SECTION} />);
    await user.click(await screen.findByRole("button", { name: "Delete Acme Ltd" }));
    const dialog = await screen.findByRole("dialog");
    expect(within(dialog).getByText("Delete this experience entry?")).toBeInTheDocument();
    await user.click(within(dialog).getByRole("button", { name: "Delete" }));
    await waitFor(() => expect(mockedDelete).toHaveBeenCalledWith("/employees/e1/experience/x1", { ifMatch: "2" }));
  });
});

describe("IdentityPanel", () => {
  const identity = { employee_id: "e1", pan_number: "ABCDE1234F", aadhaar_number: null, uan_number: null, father_or_husband_name: "Raj", version: 5 };

  it("shows the identity documents", async () => {
    mockedGet.mockResolvedValue(identity);
    render(<IdentityPanel employeeId="e1" />);
    expect(await screen.findByText("ABCDE1234F")).toBeInTheDocument();
    expect(screen.getByText("Raj")).toBeInTheDocument();
  });

  it("saves only the changed fields with If-Match", async () => {
    const user = userEvent.setup();
    mockedGet.mockResolvedValue(identity);
    mockedPatch.mockResolvedValue({});
    render(<IdentityPanel employeeId="e1" />);
    await user.click(await screen.findByRole("button", { name: "Edit identity" }));
    const dialog = await screen.findByRole("dialog");
    await user.type(within(dialog).getByLabelText(/^Aadhaar/), "123456789012");
    await user.click(within(dialog).getByRole("button", { name: "Save" }));
    await waitFor(() => expect(mockedPatch).toHaveBeenCalledWith("/employees/e1/identity", { aadhaar_number: "123456789012" }, { ifMatch: "5" }));
  });

  it("a stale record shows the conflict banner instead of closing", async () => {
    const user = userEvent.setup();
    mockedGet.mockResolvedValue(identity);
    mockedPatch.mockRejectedValue(new ApiError({ status: 409, code: "STALE_RESOURCE", message: "stale" }));
    render(<IdentityPanel employeeId="e1" />);
    await user.click(await screen.findByRole("button", { name: "Edit identity" }));
    const dialog = await screen.findByRole("dialog");
    await user.type(within(dialog).getByLabelText(/^UAN/), "100200300400");
    await user.click(within(dialog).getByRole("button", { name: "Save" }));
    expect(await within(dialog).findByText("This identity record was changed by someone else since you opened this form.")).toBeInTheDocument();
  });
});
