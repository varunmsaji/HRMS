"use client";

import { RouteError, type RouteErrorProps } from "@/components/common/route-error";

/** Error boundary for every authenticated page. It sits inside `app/app/layout.tsx`, so the
 * navigation shell stays usable while one page shows the fallback. */
export default function AppSectionError(props: RouteErrorProps) {
  return <RouteError {...props} />;
}
