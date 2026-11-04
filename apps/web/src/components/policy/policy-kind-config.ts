import type { LucideIcon } from "lucide-react";
import type { ComponentType } from "react";

import type { ErrorDetail } from "@/lib/api/types";
import type { PolicyKind } from "@/lib/policy-assignment/types";

export interface PolicyBase {
  id: string;
  name: string;
  code: string | null;
  is_active: boolean;
  version: number;
  /** Only leave policies: the leave type they cover. */
  leave_type_id?: string;
  /** Filled by the list endpoint. */
  live_from?: string | null;
  has_draft?: boolean;
  assigned_company_wide?: boolean;
  assigned_group_count?: number;
}

export interface PolicyVersionBase {
  id: string;
  status: "DRAFT" | "PUBLISHED";
  version: number;
  effective_from: string | null;
  effective_to: string | null;
}

export interface PolicyTemplate<F> {
  key: string;
  label: string;
  description: string;
  defaultName: string;
  values: F;
}

/** Everything that differs between attendance, overtime and regularization policies. The list,
 * new-policy and detail pages are shared and read this. `F` is the rules form's values, `E` its
 * errors and `C` an optional context the form needs (for example which shift types exist). */
export interface PolicyKindConfig<
  P extends PolicyBase,
  V extends PolicyVersionBase,
  F extends { effectiveFrom: string },
  E extends object,
  C = null,
> {
  kind: PolicyKind;
  /** API and page path, for example "/attendance-policies". */
  path: string;
  pluralLabel: string;
  /** Lower case, for sentences: "attendance policy". */
  singularLabel: string;
  listDescription: string;
  emptyListTitle: string;
  icon: LucideIcon;
  /** Each policy covers one leave type, chosen when it is created and never changed. */
  leaveTyped?: boolean;
  /** Permission needed to change policies. Defaults to the attendance one. */
  managePermission?: string;
  /** Shown above the list, for related settings. */
  ListExtras?: ComponentType;

  templates: PolicyTemplate<F>[];
  emptyValues: F;
  Form: ComponentType<{
    values: F;
    errors: E;
    onChange: (values: F) => void;
    context: C | null;
  }>;
  Summary: ComponentType<{ version: V }>;
  loadContext?: () => Promise<C>;

  versionToValues: (version: V) => F;
  toPayload: (values: F) => Record<string, unknown>;
  validateDraft: (values: F) => E;
  validateForPublish: (values: F) => E;
  mapApiErrors: (details: ErrorDetail[]) => E;
  historySummary: (version: V) => string;
}
