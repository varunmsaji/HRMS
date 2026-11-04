"use client";

import { leavePolicyConfig } from "@/components/leave-policy/policy-config";
import { NewPolicyPage } from "@/components/policy/new-policy-page";

export default function Page() {
  return <NewPolicyPage config={leavePolicyConfig} />;
}
