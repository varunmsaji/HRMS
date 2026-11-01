import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

const push = vi.hoisted(() => vi.fn());
vi.mock("next/navigation", () => ({ useRouter: () => ({ push }) }));
vi.mock("@/lib/auth/auth-context", () => ({ useAuth: () => ({ user: { id: "u1" } }) }));

const api = vi.hoisted(() => ({
  listNotifications: vi.fn(),
  fetchUnreadCount: vi.fn(),
  markNotificationRead: vi.fn(),
  markAllNotificationsRead: vi.fn(),
}));
vi.mock("@/lib/notifications/api", () => api);

import { NotificationBell } from "@/components/notifications/notification-bell";
import { NotificationsProvider } from "@/components/notifications/notifications-provider";
import type { AppNotification } from "@/lib/notifications/types";

const FACE: AppNotification = {
  id: "n1",
  type: "FACE_ENROLLMENT_REQUESTED",
  category: "ATTENDANCE",
  priority: "HIGH",
  title: "Face Enrollment Requested",
  body: "Your HR team has requested you to complete face enrollment for attendance.",
  entity_type: "face_enrollment_window",
  entity_id: "w1",
  action_url: "/app/attendance/face-setup",
  action_label: "Complete Face Enrollment",
  metadata: {},
  is_read: false,
  read_at: null,
  created_at: new Date().toISOString(),
  expires_at: null,
};

function renderBell() {
  return render(
    <NotificationsProvider>
      <NotificationBell />
    </NotificationsProvider>,
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  api.fetchUnreadCount.mockResolvedValue(1);
  api.listNotifications.mockResolvedValue({ data: [FACE], pagination: null, meta: {} });
  api.markNotificationRead.mockResolvedValue({ ...FACE, is_read: true });
  api.markAllNotificationsRead.mockResolvedValue({ updated: 1, unread_count: 0 });
});

describe("NotificationBell", () => {
  it("shows the unread badge and hides it at zero", async () => {
    api.fetchUnreadCount.mockResolvedValue(0);
    renderBell();
    await waitFor(() => expect(api.fetchUnreadCount).toHaveBeenCalled());
    expect(screen.queryByTestId("notification-badge")).toBeNull();
  });

  it("renders the badge count", async () => {
    api.fetchUnreadCount.mockResolvedValue(120);
    renderBell();
    expect(await screen.findByText("99+")).toBeInTheDocument();
  });

  it("lists the face-enrollment notification and navigates + marks read on click", async () => {
    const user = userEvent.setup();
    renderBell();
    await screen.findByTestId("notification-badge");
    await user.click(screen.getByRole("button", { name: /Notifications, 1 unread/ }));
    const item = await screen.findByText("Face Enrollment Requested");
    expect(screen.getByText(/Complete Face Enrollment/)).toBeInTheDocument();
    await user.click(item);
    await waitFor(() => expect(push).toHaveBeenCalledWith("/app/attendance/face-setup"));
    await waitFor(() => expect(api.markNotificationRead).toHaveBeenCalledWith("n1"));
  });

  it("shows loading, empty and error states", async () => {
    const user = userEvent.setup();
    api.listNotifications.mockResolvedValueOnce({ data: [], pagination: null, meta: {} });
    renderBell();
    await user.click(screen.getByRole("button", { name: /Notifications/ }));
    expect(await screen.findByText("You’re all caught up.")).toBeInTheDocument();
  });

  it("shows an error state with retry", async () => {
    const user = userEvent.setup();
    api.listNotifications.mockRejectedValueOnce(new Error("boom"));
    renderBell();
    await user.click(screen.getByRole("button", { name: /Notifications/ }));
    expect(await screen.findByText("Couldn’t load notifications.")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Try again" }));
    expect(await screen.findByText("Face Enrollment Requested")).toBeInTheDocument();
  });

  it("marks all as read", async () => {
    const user = userEvent.setup();
    renderBell();
    await screen.findByTestId("notification-badge");
    await user.click(screen.getByRole("button", { name: /Notifications/ }));
    await screen.findByText("Face Enrollment Requested");
    api.fetchUnreadCount.mockResolvedValue(0);
    await user.click(screen.getByRole("button", { name: "Mark all as read" }));
    await waitFor(() => expect(api.markAllNotificationsRead).toHaveBeenCalled());
    await waitFor(() => expect(screen.queryByTestId("notification-badge")).toBeNull());
  });

  it("does not follow an unsafe action link", async () => {
    const user = userEvent.setup();
    api.listNotifications.mockResolvedValue({
      data: [{ ...FACE, action_url: "https://evil.example" }],
      pagination: null,
      meta: {},
    });
    renderBell();
    await user.click(screen.getByRole("button", { name: /Notifications/ }));
    await user.click(await screen.findByText("Face Enrollment Requested"));
    await waitFor(() => expect(api.markNotificationRead).toHaveBeenCalled());
    expect(push).not.toHaveBeenCalled();
  });
});
