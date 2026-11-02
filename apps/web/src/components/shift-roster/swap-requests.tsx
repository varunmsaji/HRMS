"use client";

import { ArrowLeftRight, ArrowRight, Check, CheckCircle2, CircleAlert, Repeat } from "lucide-react";
import { useState } from "react";

import { Button } from "@/components/ui/button";
import { shortDate, timeRange, type SwapParty, type SwapRequest, type SwapResponse } from "@/lib/shift-roster/schedule";

function Party({ party }: { party: SwapParty }) {
  return (
    <div className="min-w-0 flex-1 rounded-lg border border-border p-3">
      <p className="truncate text-sm font-semibold text-foreground">{party.name}</p>
      <p className="mt-0.5 truncate text-xs text-foreground-muted">
        {party.code}
        {party.department ? ` · ${party.department}` : ""}
      </p>
      <span className="mt-2 inline-block rounded bg-primary-subtle px-1.5 py-0.5 text-[11px] font-medium text-primary">
        {party.shift_name} ({timeRange(party.shift_start, party.shift_end).replace(" – ", "–")})
      </span>
    </div>
  );
}

function SwapCard({
  swap,
  canDecide,
  meEmployeeId,
  onDecide,
  onRespond,
}: {
  swap: SwapRequest;
  canDecide: boolean;
  meEmployeeId: string | null;
  onDecide: (swap: SwapRequest, approve: boolean) => Promise<void>;
  onRespond: (swap: SwapRequest, response: SwapResponse) => Promise<void>;
}) {
  const [busy, setBusy] = useState<"approve" | "decline" | "consent" | "withdraw" | null>(null);
  async function run(approve: boolean) {
    setBusy(approve ? "approve" : "decline");
    try {
      await onDecide(swap, approve);
    } finally {
      setBusy(null);
    }
  }
  async function respond(response: SwapResponse) {
    setBusy(response);
    try {
      await onRespond(swap, response);
    } finally {
      setBusy(null);
    }
  }
  const isRequester = meEmployeeId !== null && swap.requester.employee_id === meEmployeeId;
  const isCounterpart = meEmployeeId !== null && swap.counterpart.employee_id === meEmployeeId;
  const needsMyAnswer = isCounterpart && !swap.counterpart_consented;
  return (
    <article className="flex flex-col rounded-xl border border-border bg-surface">
      <header className="flex items-center justify-between gap-2 border-b border-border px-4 py-2.5 text-xs">
        <span className="flex items-center gap-1.5 font-medium text-primary">
          <Repeat className="h-3.5 w-3.5" aria-hidden="true" />
          Swap Request #{swap.reference}
        </span>
        <span className="text-foreground-muted">{shortDate(swap.swap_date)}</span>
      </header>
      <div className="flex items-stretch gap-2 p-4">
        <Party party={swap.requester} />
        <div className="flex shrink-0 flex-col items-center justify-center text-primary">
          {swap.counterpart_consented ? (
            <ArrowLeftRight className="h-4 w-4" aria-hidden="true" />
          ) : (
            <ArrowRight className="h-4 w-4" aria-hidden="true" />
          )}
          <span className="mt-1 text-[10px] font-medium uppercase text-foreground-muted">{shortDate(swap.swap_date).slice(4)}</span>
        </div>
        <Party party={swap.counterpart} />
      </div>
      {swap.reason ? (
        <p className="mx-4 rounded-md bg-muted/50 px-3 py-2 text-xs text-foreground-secondary">
          <span className="font-semibold text-foreground">Reason:</span> “{swap.reason}”
        </p>
      ) : null}
      <p
        className={
          "mx-4 mt-3 flex items-center gap-1.5 text-xs " +
          (swap.counterpart_consented && swap.coverage_ok ? "text-success" : "text-warning")
        }
      >
        {swap.counterpart_consented && swap.coverage_ok ? (
          <CheckCircle2 className="h-3.5 w-3.5 shrink-0" aria-hidden="true" />
        ) : (
          <CircleAlert className="h-3.5 w-3.5 shrink-0" aria-hidden="true" />
        )}
        {swap.counterpart_consented
          ? "Mutual consent verified"
          : `Waiting for ${swap.counterpart.name.split(" ")[0]} to agree`}
        {" · "}
        {swap.coverage_ok ? "Shift coverage targets intact" : "A shift is already below its coverage target"}
      </p>
      {isRequester || isCounterpart ? (
        <footer className="mt-4 flex flex-wrap justify-end gap-2 border-t border-border px-4 py-3">
          {needsMyAnswer ? (
            <Button type="button" size="sm" disabled={busy !== null} onClick={() => void respond("consent")} loading={busy === "consent"}>
              <Check className="h-4 w-4" aria-hidden="true" />
              Agree to swap
            </Button>
          ) : null}
          <Button type="button" variant="outline" size="sm" disabled={busy !== null} onClick={() => void respond("withdraw")} loading={busy === "withdraw"}>
            {isRequester ? "Withdraw request" : "Turn down"}
          </Button>
        </footer>
      ) : null}
      {canDecide ? (
        <footer className="mt-4 flex justify-end gap-2 border-t border-border px-4 py-3">
          <Button type="button" variant="outline" size="sm" disabled={busy !== null} onClick={() => void run(false)} loading={busy === "decline"}>
            Decline
          </Button>
          <Button
            type="button"
            size="sm"
            disabled={busy !== null || !swap.counterpart_consented}
            title={swap.counterpart_consented ? undefined : "The colleague has not agreed yet"}
            onClick={() => void run(true)}
            loading={busy === "approve"}
          >
            <Check className="h-4 w-4" aria-hidden="true" />
            Approve Swap
          </Button>
        </footer>
      ) : isRequester || isCounterpart ? null : (
        <div className="h-4" />
      )}
    </article>
  );
}

export function SwapRequests({
  swaps,
  canDecide,
  meEmployeeId = null,
  onDecide,
  onRespond,
}: {
  swaps: SwapRequest[];
  canDecide: boolean;
  /** The signed-in employee, so their own requests get Agree / Withdraw actions. */
  meEmployeeId?: string | null;
  onDecide: (swap: SwapRequest, approve: boolean) => Promise<void>;
  onRespond: (swap: SwapRequest, response: SwapResponse) => Promise<void>;
}) {
  return (
    <section
      id="swap-requests"
      aria-label="Pending shift swap requests"
      className="rounded-2xl border border-border bg-surface p-5 shadow-elevation-1"
    >
      <div className="flex flex-wrap items-center gap-3">
        <span className="flex h-9 w-9 items-center justify-center rounded-lg bg-warning-subtle text-warning">
          <ArrowLeftRight className="h-4 w-4" aria-hidden="true" />
        </span>
        <div>
          <h2 className="flex items-center gap-2 text-base font-semibold text-foreground">
            Pending Shift Swap Requests
            {swaps.length > 0 ? (
              <span className="rounded-full bg-warning-subtle px-2 py-0.5 text-2xs font-semibold text-warning">
                {swaps.length} Pending Review
              </span>
            ) : null}
          </h2>
          <p className="text-xs text-foreground-secondary">Resolve employee rotation clashes and mutual swap exchanges</p>
        </div>
      </div>
      {swaps.length === 0 ? (
        <p className="py-8 text-center text-sm text-foreground-muted">No swap requests are waiting for a decision.</p>
      ) : (
        <div className="mt-5 grid grid-cols-1 gap-4 xl:grid-cols-2">
          {swaps.map((s) => (
            <SwapCard key={s.id} swap={s} canDecide={canDecide} meEmployeeId={meEmployeeId} onDecide={onDecide} onRespond={onRespond} />
          ))}
        </div>
      )}
    </section>
  );
}
