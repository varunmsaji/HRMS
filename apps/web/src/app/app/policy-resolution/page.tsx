import { redirect } from "next/navigation";

export default function PolicyResolutionPage() {
  redirect("/app/policy-assignments?tab=check");
}
