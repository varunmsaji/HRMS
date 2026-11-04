"use client";

import { attendancePolicyConfig } from "@/components/attendance-policy/policy-config";
import { NewPolicyPage } from "@/components/policy/new-policy-page";

export default function Page() {
  return <NewPolicyPage config={attendancePolicyConfig} />;
}
