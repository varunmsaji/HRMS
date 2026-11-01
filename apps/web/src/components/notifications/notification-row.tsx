import { Bell, ScanFace } from "lucide-react";

import { relativeTime } from "@/lib/notifications/format";
import type { AppNotification } from "@/lib/notifications/types";
import { cn } from "@/lib/utils";

function NotificationIcon({ type }: { type: string }) {
  const Icon = type === "FACE_ENROLLMENT_REQUESTED" ? ScanFace : Bell;
  return <Icon className="h-4 w-4" aria-hidden="true" />;
}

/** One notification: unread rows carry a dot, a stronger title and a tinted background. */
export function NotificationRow({
  notification,
  compact = false,
}: {
  notification: AppNotification;
  compact?: boolean;
}) {
  const unread = !notification.is_read;
  return (
    <div
      data-unread={unread}
      className={cn("flex w-full items-start gap-3 text-left", compact ? "py-0.5" : "")}
    >
      <span
        className={cn(
          "mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-full",
          unread ? "bg-primary-subtle text-primary" : "bg-muted text-foreground-muted",
        )}
      >
        <NotificationIcon type={notification.type} />
      </span>
      <span className="min-w-0 flex-1">
        <span className="flex items-start justify-between gap-2">
          <span
            className={cn(
              "break-words text-sm leading-snug",
              unread ? "font-semibold text-foreground" : "font-medium text-foreground-secondary",
            )}
          >
            {notification.title}
          </span>
          {unread ? (
            <span
              aria-label="Unread"
              className="mt-1.5 h-2 w-2 shrink-0 rounded-full bg-primary"
            />
          ) : null}
        </span>
        <span
          className={cn(
            "mt-0.5 block break-words text-xs text-foreground-secondary",
            compact ? "line-clamp-2" : "",
          )}
        >
          {notification.body}
        </span>
        <span className="mt-1 flex items-center gap-2 text-2xs text-foreground-muted">
          <time dateTime={notification.created_at}>{relativeTime(notification.created_at)}</time>
          {notification.action_label && unread ? (
            <span className="font-semibold text-primary">{notification.action_label} →</span>
          ) : null}
        </span>
      </span>
    </div>
  );
}
