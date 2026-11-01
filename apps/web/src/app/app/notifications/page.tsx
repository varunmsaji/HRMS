"use client";

import { Bell } from "lucide-react";
import { useCallback, useEffect, useState } from "react";

import { EmptyState } from "@/components/common/empty-state";
import { ErrorState } from "@/components/common/error-state";
import { LoadingState } from "@/components/common/loading-state";
import { PaginationControls } from "@/components/common/pagination-controls";
import { PageHeader } from "@/components/common/page-header";
import { NotificationRow } from "@/components/notifications/notification-row";
import { useNotifications } from "@/components/notifications/notifications-provider";
import { useOpenNotification } from "@/components/notifications/use-open-notification";
import { Button } from "@/components/ui/button";
import type { PaginationMeta } from "@/lib/api/types";
import { listNotifications, markAllNotificationsRead } from "@/lib/notifications/api";
import type { AppNotification } from "@/lib/notifications/types";
import { cn } from "@/lib/utils";

const PER_PAGE = 20;

export default function NotificationsPage() {
  const { unreadCount, refreshUnread, setUnreadCount } = useNotifications();
  const [filter, setFilter] = useState<"all" | "unread">("all");
  const [page, setPage] = useState(1);
  const [items, setItems] = useState<AppNotification[]>([]);
  const [pagination, setPagination] = useState<PaginationMeta | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    setError(false);
    try {
      const result = await listNotifications({
        page,
        per_page: PER_PAGE,
        unread_only: filter === "unread",
      });
      setItems(result.data);
      setPagination(result.pagination);
    } catch {
      setError(true);
    } finally {
      setLoading(false);
    }
  }, [page, filter]);

  useEffect(() => {
    // Fetch-on-mount: the loader sets its own loading/error state.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    void load();
    void refreshUnread();
  }, [load, refreshUnread]);

  const open = useOpenNotification(
    useCallback(
      (updated: AppNotification) =>
        setItems((cur) => cur.map((n) => (n.id === updated.id ? updated : n))),
      [],
    ),
  );

  async function markAll() {
    try {
      const result = await markAllNotificationsRead();
      setUnreadCount(result.unread_count);
      await load();
    } catch {
      setError(true);
    }
  }

  return (
    <div className="space-y-6">
      <PageHeader
        title="Notifications"
        description="Updates and actions that need your attention."
        actions={
          <Button variant="outline" size="sm" onClick={markAll} disabled={unreadCount === 0}>
            Mark all as read
          </Button>
        }
      />
      <div role="tablist" aria-label="Filter notifications" className="flex gap-1">
        {(["all", "unread"] as const).map((key) => (
          <button
            key={key}
            role="tab"
            type="button"
            aria-selected={filter === key}
            onClick={() => {
              setFilter(key);
              setPage(1);
            }}
            className={cn(
              "rounded-md px-3 py-1.5 text-sm font-medium",
              filter === key
                ? "bg-primary-subtle text-primary"
                : "text-foreground-secondary hover:bg-muted",
            )}
          >
            {key === "all" ? "All" : `Unread${unreadCount > 0 ? ` (${unreadCount})` : ""}`}
          </button>
        ))}
      </div>
      {loading ? (
        <LoadingState />
      ) : error ? (
        <ErrorState message="Couldn’t load your notifications." onRetry={() => void load()} />
      ) : items.length === 0 ? (
        <EmptyState
          icon={Bell}
          title={filter === "unread" ? "No unread notifications" : "No notifications yet"}
          description="When something needs your attention, it will show up here."
        />
      ) : (
        <div className="overflow-hidden rounded-lg border border-border bg-surface">
          <ul className="divide-y divide-border">
            {items.map((n) => (
              <li key={n.id}>
                <button
                  type="button"
                  onClick={() => void open(n)}
                  className={cn(
                    "block w-full px-4 py-3 hover:bg-muted focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
                    n.is_read ? "" : "bg-primary-subtle/40",
                  )}
                >
                  <NotificationRow notification={n} />
                </button>
              </li>
            ))}
          </ul>
          {pagination ? (
            <PaginationControls pagination={pagination} onPageChange={setPage} />
          ) : null}
        </div>
      )}
    </div>
  );
}
