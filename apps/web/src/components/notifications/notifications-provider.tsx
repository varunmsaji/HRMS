"use client";

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";

import { useOptionalToast } from "@/components/common/toast";
import { useAuth } from "@/lib/auth/auth-context";
import { fetchUnreadCount, listNotifications } from "@/lib/notifications/api";

interface NotificationsContextValue {
  unreadCount: number;
  /** Re-reads the unread count from the server (the count is never computed client-side). */
  refreshUnread: () => Promise<void>;
  /** Optimistic adjustment after a local mark-read; always followed by `refreshUnread`. */
  setUnreadCount: (count: number) => void;
}

const NotificationsContext = createContext<NotificationsContextValue | null>(null);

/** Minimum gap between focus-triggered refreshes. */
const FOCUS_REFRESH_MIN_MS = 30_000;
/** While the tab is visible the badge is re-read this often, so a new approval request or
 * decision shows up without a reload. A hidden tab is never polled. */
export const POLL_INTERVAL_MS = 60_000;

export function NotificationsProvider({ children }: { children: ReactNode }) {
  const { user } = useAuth();
  const signedIn = Boolean(user);
  const [unreadCount, setUnreadCountState] = useState(0);
  const lastFetch = useRef(0);
  /** Last count we know of; null until the first read, so the initial load never toasts. */
  const known = useRef<number | null>(null);
  const toaster = useOptionalToast();

  const setUnreadCount = useCallback((count: number) => {
    known.current = count;
    setUnreadCountState(count);
  }, []);

  const announceNewest = useCallback(async () => {
    if (!toaster) return;
    try {
      const page = await listNotifications({ per_page: 1, unread_only: true });
      const newest = page.data[0];
      if (newest) toaster.toast({ title: newest.title, description: newest.body, variant: "info" });
    } catch {
      // The badge already shows the new count; the toast is a nicety.
    }
  }, [toaster]);

  const refreshUnread = useCallback(async () => {
    lastFetch.current = Date.now();
    try {
      const count = await fetchUnreadCount();
      const previous = known.current;
      setUnreadCount(count);
      if (previous !== null && count > previous) void announceNewest();
    } catch {
      // A failed badge read must never break the shell; keep the last known count.
    }
  }, [announceNewest, setUnreadCount]);

  useEffect(() => {
    if (!signedIn) {
      known.current = null;
      return;
    }
    // Fetch-on-mount: the loader sets its own loading/error state.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    void refreshUnread();
    const onWake = () => {
      if (document.visibilityState === "hidden") return;
      if (Date.now() - lastFetch.current < FOCUS_REFRESH_MIN_MS) return;
      void refreshUnread();
    };
    const poll = window.setInterval(() => {
      if (document.visibilityState !== "hidden") void refreshUnread();
    }, POLL_INTERVAL_MS);
    window.addEventListener("focus", onWake);
    document.addEventListener("visibilitychange", onWake);
    return () => {
      window.clearInterval(poll);
      window.removeEventListener("focus", onWake);
      document.removeEventListener("visibilitychange", onWake);
    };
  }, [signedIn, refreshUnread]);

  const shown = signedIn ? unreadCount : 0; // signing out drops the badge without an effect
  const value = useMemo(
    () => ({ unreadCount: shown, refreshUnread, setUnreadCount }),
    [shown, refreshUnread, setUnreadCount],
  );
  return <NotificationsContext.Provider value={value}>{children}</NotificationsContext.Provider>;
}

const FALLBACK: NotificationsContextValue = {
  unreadCount: 0,
  refreshUnread: async () => {},
  setUnreadCount: () => {},
};

export function useNotifications(): NotificationsContextValue {
  return useContext(NotificationsContext) ?? FALLBACK;
}
