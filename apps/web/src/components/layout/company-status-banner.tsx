"use client";

import { Lock } from "lucide-react";

import { useAuth } from "@/lib/auth/auth-context";

const MESSAGES: Record<string, { title: string; body: string }> = {
  PENDING_APPROVAL: {
    title: "Your company is awaiting approval",
    body: "You can look around, but changes are disabled until a platform administrator approves your company.",
  },
  SUSPENDED: {
    title: "Your company is suspended",
    body: "Your team can view data, but changes are disabled until the suspension is lifted. Contact support.",
  },
};

/** Read-only notice for companies the platform has not (yet) cleared for writes. Rendered from
 * the status shipped in `GET /auth/me`; the API enforces it regardless of what this shows. */
export function CompanyStatusBanner() {
  const { user } = useAuth();
  const message = user?.company_status ? MESSAGES[user.company_status] : undefined;
  if (!message) return null;
  return (
    <div
      role="status"
      className="mb-6 flex items-start gap-3 rounded-lg border border-warning bg-warning-subtle px-4 py-3 text-sm text-warning"
    >
      <Lock className="mt-0.5 h-4 w-4 shrink-0" aria-hidden="true" />
      <div>
        <p className="font-semibold">{message.title}</p>
        <p>{message.body}</p>
      </div>
    </div>
  );
}
