import { redirect } from "next/navigation";

/** Old address of the roster day view; it now lives under Schedule. */
export default function LegacyBoardRedirect() {
  redirect("/app/rosters/schedule/day");
}
