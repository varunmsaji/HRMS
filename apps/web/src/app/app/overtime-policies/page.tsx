"use client";

import { overtimePolicyConfig } from "@/components/overtime-policy/policy-config";
import { PolicyListPage } from "@/components/policy/policy-list-page";

export default function Page() {
  return <PolicyListPage config={overtimePolicyConfig} />;
}
