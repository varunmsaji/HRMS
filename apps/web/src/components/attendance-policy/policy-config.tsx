"use client";

import { ClipboardList } from "lucide-react";

import { AttendancePolicySummary } from "@/components/attendance-policy/attendance-policy-summary";
import { AttendancePolicyVersionForm } from "@/components/attendance-policy/attendance-policy-version-form";
import { FaceEnrollmentPolicyCard } from "@/components/attendance/face-enrollment-policy-card";
import type { PolicyKindConfig } from "@/components/policy/policy-kind-config";
import { apiClient } from "@/lib/api/client";
import { ATTENDANCE_POLICY_TEMPLATES } from "@/lib/attendance-policy/templates";
import type { AttendancePolicy, AttendancePolicyVersion } from "@/lib/attendance-policy/types";
import {
  attendancePolicyVersionToFormValues,
  buildAttendancePolicyVersionPayload,
  EMPTY_ATTENDANCE_POLICY_VERSION_FORM_VALUES,
  mapAttendancePolicyVersionApiErrors,
  validateAttendancePolicyForPublish,
  validateAttendancePolicyVersionForm,
  type AttendancePolicyVersionFormErrors,
  type AttendancePolicyVersionFormValues,
} from "@/lib/attendance-policy/validate-attendance-policy";
import { usePermissions } from "@/lib/auth/use-permissions";

interface AttendanceFormContext {
  shift_types_in_use: string[];
}

function AttendanceRulesForm({
  values,
  errors,
  onChange,
  context,
}: {
  values: AttendancePolicyVersionFormValues;
  errors: AttendancePolicyVersionFormErrors;
  onChange: (values: AttendancePolicyVersionFormValues) => void;
  context: AttendanceFormContext | null;
}) {
  return (
    <AttendancePolicyVersionForm
      values={values}
      errors={errors}
      onChange={onChange}
      shiftTypesInUse={context?.shift_types_in_use ?? null}
    />
  );
}

function AttendanceListExtras() {
  const { can } = usePermissions();
  return can("ATTENDANCE.FACE_ENROLLMENT_MANAGE") ? <FaceEnrollmentPolicyCard /> : null;
}

export const attendancePolicyConfig: PolicyKindConfig<
  AttendancePolicy,
  AttendancePolicyVersion,
  AttendancePolicyVersionFormValues,
  AttendancePolicyVersionFormErrors,
  AttendanceFormContext
> = {
  kind: "ATTENDANCE_POLICY",
  path: "/attendance-policies",
  pluralLabel: "Attendance Policies",
  singularLabel: "attendance policy",
  listDescription:
    "The rules that turn punches into a day's result: hours worked, lateness, missing punches and location checks.",
  emptyListTitle: "No attendance policies have been configured yet.",
  icon: ClipboardList,
  ListExtras: AttendanceListExtras,
  templates: ATTENDANCE_POLICY_TEMPLATES,
  emptyValues: EMPTY_ATTENDANCE_POLICY_VERSION_FORM_VALUES,
  Form: AttendanceRulesForm,
  Summary: AttendancePolicySummary,
  loadContext: () => apiClient.get<AttendanceFormContext>("/attendance-policies/form-context"),
  versionToValues: attendancePolicyVersionToFormValues,
  toPayload: buildAttendancePolicyVersionPayload,
  validateDraft: validateAttendancePolicyVersionForm,
  validateForPublish: validateAttendancePolicyForPublish,
  mapApiErrors: mapAttendancePolicyVersionApiErrors,
  historySummary: (version) =>
    `Grace ${version.grace_in_minutes} / ${version.grace_out_minutes} minutes, ${version.hour_bands.length} hour bands`,
};
