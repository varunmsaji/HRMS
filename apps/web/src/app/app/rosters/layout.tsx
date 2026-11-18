"use client";

import type { ReactNode } from "react";

import { RosterProvider } from "@/components/shift-roster/roster-context";
import { RosterNav } from "@/components/shift-roster/roster-nav";

/** Wraps every Shift Rosters page. It stays mounted while you move between views, which is what
 * lets the date you picked carry over from one view to the next. */
export default function RostersLayout({ children }: { children: ReactNode }) {
  return (
    <RosterProvider>
      <div className="space-y-6">
        <RosterNav />
        {children}
      </div>
    </RosterProvider>
  );
}
