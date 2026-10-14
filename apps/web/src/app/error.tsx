"use client";

import { RouteError, type RouteErrorProps } from "@/components/common/route-error";

/** Error boundary for the public pages (login, registration, invite and onboarding links). */
export default function PublicError(props: RouteErrorProps) {
  return <RouteError {...props} />;
}
