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

import { useAuth } from "@/lib/auth/auth-context";
import { fetchUnreadCount } from "@/lib/notifications/api";

interface NotificationsContextValue {
  unreadCount: number;
  /** Re-reads the unread count from the server (the count is never computed client-side). */
  refreshUnread: () => Promise<void>;
  /** Optimistic adjustment after a local mark-read; always followed by `refreshUnread`. */
  setUnreadCount: (count: number) => void;
}

const NotificationsContext = createContext<NotificationsContextValue | null>(null);

/** Minimum gap between focus-triggered refreshes: refresh when the user comes back, never poll. */
const FOCUS_REFRESH_MIN_MS = 30_000;

export function NotificationsProvider({ children }: { children: ReactNode }) {
  const { user } = useAuth();
  const signedIn = Boolean(user);
  const [unreadCount, setUnreadCount] = useState(0);
  const lastFetch = useRef(0);

  const refreshUnread = useCallback(async () => {
    lastFetch.current = Date.now();
    try {
      setUnreadCount(await fetchUnreadCount());
    } catch {
      // A failed badge read must never break the shell; keep the last known count.
    }
  }, []);

  useEffect(() => {
    if (!signedIn) return;
    // Fetch-on-mount: the loader sets its own loading/error state.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    void refreshUnread();
    const onWake = () => {
      if (document.visibilityState === "hidden") return;
      if (Date.now() - lastFetch.current < FOCUS_REFRESH_MIN_MS) return;
      void refreshUnread();
    };
    window.addEventListener("focus", onWake);
    document.addEventListener("visibilitychange", onWake);
    return () => {
      window.removeEventListener("focus", onWake);
      document.removeEventListener("visibilitychange", onWake);
    };
  }, [signedIn, refreshUnread]);

  const shown = signedIn ? unreadCount : 0; // signing out drops the badge without an effect
  const value = useMemo(
    () => ({ unreadCount: shown, refreshUnread, setUnreadCount }),
    [shown, refreshUnread],
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
