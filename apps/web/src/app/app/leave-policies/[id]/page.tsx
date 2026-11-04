"use client";

import { leavePolicyConfig } from "@/components/leave-policy/policy-config";
import { PolicyDetailPage } from "@/components/policy/policy-detail-page";

export default function Page() {
  return <PolicyDetailPage config={leavePolicyConfig} />;
}
