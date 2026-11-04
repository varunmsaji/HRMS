import { useEffect, useState } from "react";

import { apiClient } from "@/lib/api/client";
import type { LeaveType } from "@/lib/leave-type/types";

/** The company's leave types, or an empty list until they load (or when the user may not read
 * them). Pass `enabled: false` to skip the request. */
export function useLeaveTypes(enabled = true): LeaveType[] {
  const [types, setTypes] = useState<LeaveType[]>([]);
  useEffect(() => {
    if (!enabled) return;
    let current = true;
    apiClient
      .get<LeaveType[]>("/leave-types")
      .then((list) => {
        if (current) setTypes(list);
      })
      .catch(() => {
        if (current) setTypes([]);
      });
    return () => {
      current = false;
    };
  }, [enabled]);
  return types;
}
