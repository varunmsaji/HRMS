"use client";

import { Bell } from "lucide-react";
import Link from "next/link";
import { useCallback, useState } from "react";

import { NotificationRow } from "@/components/notifications/notification-row";
import { useNotifications } from "@/components/notifications/notifications-provider";
import { useOpenNotification } from "@/components/notifications/use-open-notification";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { markAllNotificationsRead, listNotifications } from "@/lib/notifications/api";
import type { AppNotification } from "@/lib/notifications/types";

const RECENT = 8;

export function NotificationBell() {
  const { unreadCount, refreshUnread, setUnreadCount } = useNotifications();
  const [items, setItems] = useState<AppNotification[] | null>(null);
  const [error, setError] = useState(false);
  const [loading, setLoading] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    setError(false);
    try {
      const page = await listNotifications({ page: 1, per_page: RECENT });
      setItems(page.data);
    } catch {
      setError(true);
    } finally {
      setLoading(false);
    }
  }, []);

  const open = useOpenNotification(
    useCallback(
      (updated: AppNotification) =>
        setItems((cur) => cur?.map((n) => (n.id === updated.id ? updated : n)) ?? cur),
      [],
    ),
  );

  async function markAll() {
    try {
      const result = await markAllNotificationsRead();
      setUnreadCount(result.unread_count);
      setItems((cur) => cur?.map((n) => ({ ...n, is_read: true })) ?? cur);
    } catch {
      setError(true);
    } finally {
      void refreshUnread();
    }
  }

  const badge = unreadCount > 99 ? "99+" : String(unreadCount);

  return (
    <DropdownMenu
      onOpenChange={(isOpen) => {
        if (isOpen) {
          void load();
          void refreshUnread();
        }
      }}
    >
      <DropdownMenuTrigger asChild>
        <button
          type="button"
          aria-label={unreadCount > 0 ? `Notifications, ${unreadCount} unread` : "Notifications"}
          className="relative flex h-9 w-9 items-center justify-center rounded-full text-foreground-secondary hover:bg-muted focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
        >
          <Bell className="h-5 w-5" aria-hidden="true" />
          {unreadCount > 0 ? (
            <span
              data-testid="notification-badge"
              className="absolute -right-0.5 -top-0.5 flex h-4 min-w-4 items-center justify-center rounded-full bg-danger px-1 text-[10px] font-bold leading-none text-white"
            >
              {badge}
            </span>
          ) : null}
        </button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" className="w-[22rem] max-w-[calc(100vw-1.5rem)] p-0">
        <div className="flex items-center justify-between px-4 py-3">
          <h2 className="text-sm font-semibold text-foreground">Notifications</h2>
          <button
            type="button"
            onClick={markAll}
            disabled={unreadCount === 0}
            className="text-xs font-semibold text-primary hover:underline disabled:cursor-not-allowed disabled:text-foreground-muted disabled:no-underline"
          >
            Mark all as read
          </button>
        </div>
        <DropdownMenuSeparator className="m-0" />
        <div className="max-h-96 overflow-y-auto">
          {loading && items === null ? (
            <p role="status" className="px-4 py-8 text-center text-sm text-foreground-muted">
              Loading notifications…
            </p>
          ) : error && items === null ? (
            <div role="alert" className="px-4 py-6 text-center text-sm">
              <p className="text-foreground-secondary">Couldn’t load notifications.</p>
              <button
                type="button"
                onClick={() => void load()}
                className="mt-2 text-xs font-semibold text-primary hover:underline"
              >
                Try again
              </button>
            </div>
          ) : items !== null && items.length === 0 ? (
            <p className="px-4 py-8 text-center text-sm text-foreground-muted">
              You’re all caught up.
            </p>
          ) : (
            items?.map((n) => (
              <DropdownMenuItem
                key={n.id}
                onSelect={() => void open(n)}
                className={`cursor-pointer rounded-none px-4 py-3 ${n.is_read ? "" : "bg-primary-subtle/40"}`}
              >
                <NotificationRow notification={n} compact />
              </DropdownMenuItem>
            ))
          )}
        </div>
        <DropdownMenuSeparator className="m-0" />
        <DropdownMenuItem asChild className="justify-center rounded-none py-2.5">
          <Link href="/app/notifications" className="text-xs font-semibold text-primary">
            View all notifications
          </Link>
        </DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
