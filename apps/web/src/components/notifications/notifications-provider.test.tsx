import { act, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@/lib/auth/auth-context", () => ({ useAuth: () => ({ user: { id: "u1" } }) }));

const api = vi.hoisted(() => ({
  listNotifications: vi.fn(),
  fetchUnreadCount: vi.fn(),
  markNotificationRead: vi.fn(),
  markAllNotificationsRead: vi.fn(),
}));
vi.mock("@/lib/notifications/api", () => api);

import { ToastProvider } from "@/components/common/toast";
import {
  NotificationsProvider,
  POLL_INTERVAL_MS,
  useNotifications,
} from "@/components/notifications/notifications-provider";

function Badge() {
  const { unreadCount } = useNotifications();
  return <span data-testid="badge">{unreadCount}</span>;
}

function renderProvider() {
  return render(
    <ToastProvider>
      <NotificationsProvider>
        <Badge />
      </NotificationsProvider>
    </ToastProvider>,
  );
}

async function flush() {
  await act(async () => {
    await Promise.resolve();
    await Promise.resolve();
  });
}

describe("NotificationsProvider polling", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    vi.clearAllMocks();
    api.listNotifications.mockResolvedValue({
      data: [{ id: "n2", title: "Leave request awaiting your approval", body: "Priya: 1 day" }],
    });
  });
  afterEach(() => {
    vi.useRealTimers();
  });

  it("re-reads the count while visible and toasts only when it goes up", async () => {
    api.fetchUnreadCount.mockResolvedValueOnce(1).mockResolvedValueOnce(1).mockResolvedValueOnce(2);
    renderProvider();
    await flush();
    expect(screen.getByTestId("badge").textContent).toBe("1");
    expect(api.listNotifications).not.toHaveBeenCalled(); // the first load never toasts

    await act(async () => {
      vi.advanceTimersByTime(POLL_INTERVAL_MS);
    });
    await flush();
    expect(api.fetchUnreadCount).toHaveBeenCalledTimes(2);
    expect(api.listNotifications).not.toHaveBeenCalled(); // unchanged count

    await act(async () => {
      vi.advanceTimersByTime(POLL_INTERVAL_MS);
    });
    await flush();
    await flush();
    expect(screen.getByTestId("badge").textContent).toBe("2");
    expect(api.listNotifications).toHaveBeenCalledWith({ per_page: 1, unread_only: true });
    expect(screen.getByText("Leave request awaiting your approval")).toBeTruthy();
  });

  it("does not poll a hidden tab", async () => {
    api.fetchUnreadCount.mockResolvedValue(0);
    const visibility = vi.spyOn(document, "visibilityState", "get").mockReturnValue("hidden");
    renderProvider();
    await flush();
    await act(async () => {
      vi.advanceTimersByTime(POLL_INTERVAL_MS * 3);
    });
    expect(api.fetchUnreadCount).toHaveBeenCalledTimes(1); // only the mount read
    visibility.mockRestore();
  });
});
