"use client";

import { regularizationPolicyConfig } from "@/components/regularization-policy/policy-config";
import { PolicyListPage } from "@/components/policy/policy-list-page";

export default function Page() {
  return <PolicyListPage config={regularizationPolicyConfig} />;
}
