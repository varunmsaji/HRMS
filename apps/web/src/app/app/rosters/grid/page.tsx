import { redirect } from "next/navigation";

/** Old address of the roster week view; it now lives under Schedule. */
export default function LegacyGridRedirect() {
  redirect("/app/rosters/schedule/week");
}
