"use client";

import { regularizationPolicyConfig } from "@/components/regularization-policy/policy-config";
import { PolicyDetailPage } from "@/components/policy/policy-detail-page";

export default function Page() {
  return <PolicyDetailPage config={regularizationPolicyConfig} />;
}
