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

import NotificationsPage from "@/app/app/notifications/page";
import { NotificationsProvider } from "@/components/notifications/notifications-provider";

const note = (over: object = {}) => ({
  id: "n1",
  type: "FACE_ENROLLMENT_REQUESTED",
  category: "ATTENDANCE",
  priority: "HIGH",
  title: "Face Enrollment Requested",
  body: "Please enroll.",
  entity_type: null,
  entity_id: null,
  action_url: "/app/attendance/face-setup",
  action_label: "Complete Face Enrollment",
  metadata: {},
  is_read: false,
  read_at: null,
  created_at: new Date().toISOString(),
  expires_at: null,
  ...over,
});

function renderPage() {
  return render(
    <NotificationsProvider>
      <NotificationsPage />
    </NotificationsProvider>,
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  api.fetchUnreadCount.mockResolvedValue(1);
  api.listNotifications.mockResolvedValue({
    data: [note(), note({ id: "n2", title: "Older one", is_read: true })],
    pagination: { page: 1, per_page: 20, total: 2, total_pages: 1, next_cursor: null },
    meta: {},
  });
  api.markNotificationRead.mockResolvedValue(note({ is_read: true }));
  api.markAllNotificationsRead.mockResolvedValue({ updated: 1, unread_count: 0 });
});

describe("Notifications page", () => {
  it("lists notifications and opens one", async () => {
    const user = userEvent.setup();
    renderPage();
    await user.click(await screen.findByText("Face Enrollment Requested"));
    await waitFor(() => expect(push).toHaveBeenCalledWith("/app/attendance/face-setup"));
    expect(api.markNotificationRead).toHaveBeenCalledWith("n1");
  });

  it("filters to unread and shows the empty state", async () => {
    const user = userEvent.setup();
    renderPage();
    await screen.findByText("Older one");
    api.listNotifications.mockResolvedValue({ data: [], pagination: null, meta: {} });
    await user.click(screen.getByRole("tab", { name: /Unread/ }));
    expect(await screen.findByText("No unread notifications")).toBeInTheDocument();
    expect(api.listNotifications).toHaveBeenLastCalledWith(
      expect.objectContaining({ unread_only: true, page: 1 }),
    );
  });

  it("marks all as read", async () => {
    const user = userEvent.setup();
    renderPage();
    await screen.findByText("Older one");
    await user.click(screen.getByRole("button", { name: "Mark all as read" }));
    await waitFor(() => expect(api.markAllNotificationsRead).toHaveBeenCalled());
  });

  it("shows an error state", async () => {
    api.listNotifications.mockRejectedValue(new Error("x"));
    renderPage();
    expect(await screen.findByText("Couldn’t load your notifications.")).toBeInTheDocument();
  });
});
