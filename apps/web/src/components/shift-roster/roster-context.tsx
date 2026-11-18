"use client";

import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";

import { apiClient } from "@/lib/api/client";
import { businessToday } from "@/lib/attendance/format";
import { useAuth } from "@/lib/auth/auth-context";

/** State shared by every Shift Rosters view (the layout stays mounted while you switch views):
 * the date you are looking at, and how many swap requests are waiting. Each view derives its own
 * span from `anchor` — the week for Week, the month for Month, the day for Day — so switching
 * views keeps your place instead of resetting to today. */

interface RosterShared {
  anchor: string;
  setAnchor: (iso: string) => void;
  pendingSwaps: number;
  refreshSwaps: () => void;
}

const RosterContext = createContext<RosterShared | null>(null);

const ISO_DATE = /^\d{4}-\d{2}-\d{2}$/;

/** `?date=` from the address bar, when it is a real calendar date. */
function dateFromUrl(): string | null {
  if (typeof window === "undefined") return null;
  const value = new URLSearchParams(window.location.search).get("date");
  if (!value || !ISO_DATE.test(value)) return null;
  return Number.isNaN(Date.parse(`${value}T00:00:00Z`)) ? null : value;
}

export function RosterProvider({ children }: { children: ReactNode }) {
  const { user } = useAuth();
  const today = businessToday(user?.company_timezone ?? "Asia/Kolkata");
  const [anchor, setAnchorState] = useState<string>(() => dateFromUrl() ?? today);
  const [pendingSwaps, setPendingSwaps] = useState(0);

  const setAnchor = useCallback((iso: string) => {
    if (!ISO_DATE.test(iso)) return;
    setAnchorState(iso);
    try {
      const url = new URL(window.location.href);
      url.searchParams.set("date", iso);
      window.history.replaceState(window.history.state, "", url);
    } catch {
      // The address bar is a convenience; the in-memory state is what the views read.
    }
  }, []);

  const refreshSwaps = useCallback(() => {
    void apiClient
      .get<unknown[]>("/rosters/swap-requests?status=PENDING")
      .then((rows) => setPendingSwaps(Array.isArray(rows) ? rows.length : 0))
      .catch(() => setPendingSwaps(0));
  }, []);

  useEffect(() => {
    refreshSwaps();
  }, [refreshSwaps]);

  const value = useMemo(
    () => ({ anchor, setAnchor, pendingSwaps, refreshSwaps }),
    [anchor, setAnchor, pendingSwaps, refreshSwaps],
  );
  return <RosterContext.Provider value={value}>{children}</RosterContext.Provider>;
}

/** The shared date for a roster view. Outside the layout (a view rendered on its own, as in unit
 * tests) it falls back to plain local state starting at `fallback`. */
export function useRosterAnchor(fallback: string): [string, (iso: string) => void] {
  const shared = useContext(RosterContext);
  const [local, setLocal] = useState(fallback);
  if (shared) return [shared.anchor, shared.setAnchor];
  return [local, setLocal];
}

const NO_REFRESH = () => {};

export function useRosterSwapBadge(): { pendingSwaps: number; refreshSwaps: () => void } {
  const shared = useContext(RosterContext);
  return { pendingSwaps: shared?.pendingSwaps ?? 0, refreshSwaps: shared?.refreshSwaps ?? NO_REFRESH };
}
