import { apiClient } from "@/lib/api/client";

import type { AppNotification } from "./types";

export function listNotifications(query: { page?: number; per_page?: number; unread_only?: boolean }) {
  return apiClient.getList<AppNotification>("/notifications", {
    page: query.page,
    per_page: query.per_page,
    unread_only: query.unread_only ? "true" : undefined,
  });
}

export async function fetchUnreadCount(): Promise<number> {
  const data = await apiClient.get<{ unread_count: number }>("/notifications/unread-count");
  return data.unread_count;
}

export function markNotificationRead(id: string) {
  return apiClient.patch<AppNotification>(`/notifications/${id}/read`);
}

export function markAllNotificationsRead() {
  return apiClient.post<{ updated: number; unread_count: number }>("/notifications/read-all");
}
