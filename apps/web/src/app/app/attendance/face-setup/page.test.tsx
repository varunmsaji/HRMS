import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@/lib/api/client", () => ({ apiClient: { get: vi.fn() } }));

import FaceSetupPage from "@/app/app/attendance/face-setup/page";
import { apiClient } from "@/lib/api/client";

const get = vi.mocked(apiClient.get);
beforeEach(() => vi.clearAllMocks());

describe("Face setup page", () => {
  it("reads the canonical status from the server", async () => {
    get.mockResolvedValue({
      profile: null,
      open_window: null,
      enrollment_state: "ENROLLMENT_AVAILABLE",
    });
    render(<FaceSetupPage />);
    expect(await screen.findByText(/Status: Enrollment open/)).toBeInTheDocument();
    expect(get).toHaveBeenCalledWith("/attendance/face-enrollment/me");
  });

  it("shows an error state", async () => {
    get.mockRejectedValue(new Error("x"));
    render(<FaceSetupPage />);
    expect(await screen.findByText(/Couldn’t load your enrollment status/)).toBeInTheDocument();
  });
});
