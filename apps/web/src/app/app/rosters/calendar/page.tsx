import { redirect } from "next/navigation";

/** Old address of the roster month view; it now lives under Schedule. */
export default function LegacyCalendarRedirect() {
  redirect("/app/rosters/schedule/month");
}
