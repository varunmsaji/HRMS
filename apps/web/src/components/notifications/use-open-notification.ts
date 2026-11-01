"use client";

import { useRouter } from "next/navigation";
import { useCallback } from "react";

import { useNotifications } from "@/components/notifications/notifications-provider";
import { markNotificationRead } from "@/lib/notifications/api";
import { safeActionPath } from "@/lib/notifications/format";
import type { AppNotification } from "@/lib/notifications/types";

/** Click behaviour shared by the bell and the notification centre: persist "read" on the server,
 * then follow the (app-relative) action link. Navigation never waits on, or fails because of,
 * the read call. */
export function useOpenNotification(onRead?: (updated: AppNotification) => void) {
  const router = useRouter();
  const { refreshUnread, setUnreadCount, unreadCount } = useNotifications();

  return useCallback(
    async (notification: AppNotification) => {
      const path = safeActionPath(notification.action_url);
      const read = notification.is_read
        ? Promise.resolve()
        : markNotificationRead(notification.id)
            .then((updated) => {
              onRead?.(updated);
              setUnreadCount(Math.max(0, unreadCount - 1));
            })
            .catch(() => {})
            .finally(() => void refreshUnread());
      if (path) router.push(path);
      await read;
    },
    [router, onRead, refreshUnread, setUnreadCount, unreadCount],
  );
}
