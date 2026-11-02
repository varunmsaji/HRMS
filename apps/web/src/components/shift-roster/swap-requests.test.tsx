import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { SwapRequests } from "@/components/shift-roster/swap-requests";
import type { SwapParty, SwapRequest } from "@/lib/shift-roster/schedule";

function party(id: string, name: string, shift: string): SwapParty {
  return {
    employee_id: id,
    name,
    code: id.toUpperCase(),
    department: "Engineering",
    shift_id: `s-${shift}`,
    shift_name: shift,
    shift_start: "09:00:00",
    shift_end: "17:00:00",
  };
}

function swap(overrides: Partial<SwapRequest> = {}): SwapRequest {
  return {
    id: "w1",
    reference: "SW-201",
    swap_date: "2026-11-10",
    status: "PENDING",
    reason: null,
    counterpart_consented: false,
    coverage_ok: true,
    requester: party("asha", "Asha Rao", "Day"),
    counterpart: party("ben", "Ben Cole", "Night"),
    created_at: "2026-11-03T08:00:00Z",
    decided_at: null,
    decision_note: null,
    ...overrides,
  };
}

describe("SwapRequests", () => {
  it("lets the colleague agree, and the requester only withdraw", async () => {
    const onRespond = vi.fn().mockResolvedValue(undefined);
    const user = userEvent.setup();
    const { rerender } = render(
      <SwapRequests swaps={[swap()]} canDecide={false} meEmployeeId="ben" onDecide={vi.fn()} onRespond={onRespond} />,
    );
    expect(screen.getByText(/Waiting for Ben to agree/)).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: /Agree to swap/ }));
    expect(onRespond).toHaveBeenCalledWith(expect.objectContaining({ id: "w1" }), "consent");

    rerender(<SwapRequests swaps={[swap()]} canDecide={false} meEmployeeId="asha" onDecide={vi.fn()} onRespond={onRespond} />);
    expect(screen.queryByRole("button", { name: /Agree to swap/ })).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: /Withdraw request/ }));
    expect(onRespond).toHaveBeenLastCalledWith(expect.objectContaining({ id: "w1" }), "withdraw");
  });

  it("keeps Approve disabled for a manager until the colleague has agreed", () => {
    const { rerender } = render(
      <SwapRequests swaps={[swap()]} canDecide meEmployeeId={null} onDecide={vi.fn()} onRespond={vi.fn()} />,
    );
    expect(screen.getByRole("button", { name: /Approve Swap/ })).toBeDisabled();
    rerender(
      <SwapRequests
        swaps={[swap({ counterpart_consented: true })]}
        canDecide
        meEmployeeId={null}
        onDecide={vi.fn()}
        onRespond={vi.fn()}
      />,
    );
    expect(screen.getByRole("button", { name: /Approve Swap/ })).toBeEnabled();
  });
});
