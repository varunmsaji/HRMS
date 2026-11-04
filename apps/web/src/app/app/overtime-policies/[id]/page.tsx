"use client";

import { overtimePolicyConfig } from "@/components/overtime-policy/policy-config";
import { PolicyDetailPage } from "@/components/policy/policy-detail-page";

export default function Page() {
  return <PolicyDetailPage config={overtimePolicyConfig} />;
}
