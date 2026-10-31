import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("next/navigation", () => ({ useRouter: () => ({ push: vi.fn() }) }));
vi.mock("next/link", () => ({
  default: ({ href, children }: { href: string; children: React.ReactNode }) => <a href={href}>{children}</a>,
}));
vi.mock("@/components/common/toast", () => ({ useToast: () => ({ toast: vi.fn() }) }));
vi.mock("@/lib/api/client", () => ({ apiClient: { get: vi.fn(), getList: vi.fn(), post: vi.fn() } }));
vi.mock("@/lib/auth/use-permissions", () => ({
  usePermissions: () => ({ can: () => true, canAny: () => true, permissions: new Set() }),
}));
vi.mock("@/lib/auth/auth-context", () => ({ useAuth: () => ({ user: { id: "u1" } }) }));

import OnboardingPage from "@/app/app/onboarding/page";
import { apiClient } from "@/lib/api/client";
import { ApiError } from "@/lib/api/errors";

const mockedGet = vi.mocked(apiClient.get);
const mockedGetList = vi.mocked(apiClient.getList);

const onboardingCase = (id: string, name: string) => ({
  id,
  company_id: "co",
  status: "DRAFT",
  candidate_first_name: name,
  candidate_last_name: null,
  personal_email: `${name.toLowerCase()}@example.com`,
  personal_mobile: null,
  designation_id: null,
  department_id: null,
  branch_id: null,
  legal_entity_id: null,
  proposed_joining_date: "2027-01-15",
  created_by_user_id: "u1",
  employee_id: null,
  version: 1,
  created_at: "",
  updated_at: "",
});
const listOf = (rows: unknown[], page: number, totalPages: number) =>
  ({ data: rows, pagination: { page, per_page: 1, total: totalPages, total_pages: totalPages }, meta: { request_id: "r" } }) as never;

function deferred<T>() {
  let resolve!: (v: T) => void;
  let reject!: (e: unknown) => void;
  const promise = new Promise<T>((a, b) => {
    resolve = a;
    reject = b;
  });
  return { promise, resolve, reject };
}

describe("OnboardingPage loading behaviour", () => {
  afterEach(() => {
    mockedGet.mockReset();
    mockedGetList.mockReset();
  });
  const refs = () => mockedGet.mockResolvedValue([] as never);

  it("shows a skeleton first, then the rows", async () => {
    refs();
    const first = deferred<unknown>();
    mockedGetList.mockReturnValueOnce(first.promise as never);
    render(<OnboardingPage />);
    expect(screen.getByRole("status", { name: /loading onboarding cases/i })).toBeInTheDocument();
    await act(async () => first.resolve(listOf([onboardingCase("c1", "Asha")], 1, 2)));
    expect(await screen.findByText("Asha")).toBeInTheDocument();
  });

  it("keeps the rows and the toolbar on screen while the next page loads", async () => {
    refs();
    const second = deferred<unknown>();
    mockedGetList.mockResolvedValueOnce(listOf([onboardingCase("c1", "Asha")], 1, 2));
    mockedGetList.mockReturnValueOnce(second.promise as never);
    const user = userEvent.setup();
    render(<OnboardingPage />);
    await screen.findByText("Asha");

    await user.click(screen.getByRole("button", { name: /^next$/i }));
    expect(screen.getByText("Asha")).toBeInTheDocument();
    expect(screen.getByLabelText(/status/i)).toBeInTheDocument(); // search/filter controls stay mounted
    expect(screen.getByRole("button", { name: /^next$/i })).toBeDisabled();
    expect(document.querySelector('[aria-busy="true"]')).not.toBeNull();

    await act(async () => second.resolve(listOf([onboardingCase("c2", "Bala")], 2, 2)));
    expect(await screen.findByText("Bala")).toBeInTheDocument();
    expect(screen.queryByText("Asha")).not.toBeInTheDocument();
  });

  it("shows the error — not the previous page, and no success state — when a page load fails", async () => {
    refs();
    mockedGetList.mockResolvedValueOnce(listOf([onboardingCase("c1", "Asha")], 1, 2));
    mockedGetList.mockRejectedValueOnce(new ApiError({ status: 500, code: "INTERNAL_ERROR", message: "Page failed" }));
    const user = userEvent.setup();
    render(<OnboardingPage />);
    await screen.findByText("Asha");

    await user.click(screen.getByRole("button", { name: /^next$/i }));
    expect(await screen.findByText(/page failed/i)).toBeInTheDocument();
    expect(screen.queryByText("Asha")).not.toBeInTheDocument();
    expect(document.querySelector('[aria-busy="true"]')).toBeNull();
  });

  it("ignores a late response for a superseded status filter", async () => {
    refs();
    const staleAll = deferred<unknown>();
    mockedGetList.mockReturnValueOnce(staleAll.promise as never); // initial (no filter), slow
    mockedGetList.mockResolvedValueOnce(listOf([onboardingCase("c9", "FilteredOnly")], 1, 1));
    const user = userEvent.setup();
    render(<OnboardingPage />);

    // The status filter only exists once data is there, so let the first request settle with
    // its own rows, then change the filter and make the *older* answer arrive last.
    await act(async () => staleAll.resolve(listOf([onboardingCase("c1", "Asha")], 1, 1)));
    await screen.findByText("Asha");
    const late = deferred<unknown>();
    mockedGetList.mockReset();
    mockedGetList.mockReturnValueOnce(late.promise as never); // filter = A (slow)
    await user.selectOptions(screen.getByLabelText(/status/i), "DRAFT");
    mockedGetList.mockResolvedValueOnce(listOf([onboardingCase("c9", "FilteredOnly")], 1, 1));
    await user.selectOptions(screen.getByLabelText(/status/i), "SUBMITTED");
    expect(await screen.findByText("FilteredOnly")).toBeInTheDocument();

    await act(async () => late.resolve(listOf([onboardingCase("c7", "StaleRow")], 1, 1)));
    expect(screen.queryByText("StaleRow")).not.toBeInTheDocument();
    expect(screen.getByText("FilteredOnly")).toBeInTheDocument();
  });

  it("aborts the in-flight request on unmount", async () => {
    refs();
    mockedGetList.mockReturnValue(new Promise(() => {}) as never);
    const { unmount } = render(<OnboardingPage />);
    await waitFor(() => expect(mockedGetList).toHaveBeenCalled());
    const signal = (mockedGetList.mock.calls[0]?.[2] as { signal: AbortSignal }).signal;
    expect(signal.aborted).toBe(false);
    unmount();
    expect(signal.aborted).toBe(true);
  });
});
