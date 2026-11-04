"use client";

import { regularizationPolicyConfig } from "@/components/regularization-policy/policy-config";
import { NewPolicyPage } from "@/components/policy/new-policy-page";

export default function Page() {
  return <NewPolicyPage config={regularizationPolicyConfig} />;
}
