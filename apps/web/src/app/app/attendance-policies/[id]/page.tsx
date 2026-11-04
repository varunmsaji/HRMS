"use client";

import { attendancePolicyConfig } from "@/components/attendance-policy/policy-config";
import { PolicyDetailPage } from "@/components/policy/policy-detail-page";

export default function Page() {
  return <PolicyDetailPage config={attendancePolicyConfig} />;
}
