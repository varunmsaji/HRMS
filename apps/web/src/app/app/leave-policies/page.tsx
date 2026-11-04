"use client";

import { leavePolicyConfig } from "@/components/leave-policy/policy-config";
import { PolicyListPage } from "@/components/policy/policy-list-page";

export default function Page() {
  return <PolicyListPage config={leavePolicyConfig} />;
}
