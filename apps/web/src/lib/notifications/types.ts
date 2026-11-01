/** `GET /v1/notifications` rows. The server owns recipient, tenant and read state. */
export interface AppNotification {
  id: string;
  type: string;
  category: string;
  priority: "LOW" | "NORMAL" | "HIGH";
  title: string;
  body: string;
  entity_type: string | null;
  entity_id: string | null;
  action_url: string | null;
  action_label: string | null;
  metadata: Record<string, unknown>;
  is_read: boolean;
  read_at: string | null;
  created_at: string;
  expires_at: string | null;
}
