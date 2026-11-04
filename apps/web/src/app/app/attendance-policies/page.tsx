"use client";

import { attendancePolicyConfig } from "@/components/attendance-policy/policy-config";
import { PolicyListPage } from "@/components/policy/policy-list-page";

export default function Page() {
  return <PolicyListPage config={attendancePolicyConfig} />;
}
