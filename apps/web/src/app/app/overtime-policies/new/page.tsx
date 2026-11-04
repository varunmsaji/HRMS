"use client";

import { overtimePolicyConfig } from "@/components/overtime-policy/policy-config";
import { NewPolicyPage } from "@/components/policy/new-policy-page";

export default function Page() {
  return <NewPolicyPage config={overtimePolicyConfig} />;
}
