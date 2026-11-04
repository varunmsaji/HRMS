import '../../../core/forms/form_spec.dart';

/// Assigning a policy (or work calendar / weekly-off pattern) to a scope — mirrors
/// `PolicyAssignmentCreate` and the web `policy-assignments` dialog. The policy list follows the
/// kind, the target list follows the scope, and a leave policy also names its leave type.
const policyKindLabels = {
  'WORK_CALENDAR': 'Work Calendar',
  'WEEKLY_OFF': 'Weekly-Off Pattern',
  'ATTENDANCE_POLICY': 'Attendance Policy',
  'OVERTIME_POLICY': 'Overtime Policy',
  'REGULARIZATION_POLICY': 'Regularization Policy',
  'LEAVE_POLICY': 'Leave Policy',
};

const scopeTypeLabels = {
  'COMPANY': 'Whole company',
  'LEGAL_ENTITY': 'Legal entity',
  'BRANCH': 'Branch',
  'DEPARTMENT': 'Department',
  'GRADE': 'Grade',
  'DESIGNATION': 'Designation',
  'SHIFT': 'Shift',
  'EMPLOYEE': 'Employee',
};

const policySources = {
  'WORK_CALENDAR': 'work_calendars',
  'WEEKLY_OFF': 'weekly_off_patterns',
  'ATTENDANCE_POLICY': 'attendance_policies',
  'OVERTIME_POLICY': 'overtime_policies',
  'REGULARIZATION_POLICY': 'regularization_policies',
  'LEAVE_POLICY': 'leave_policies',
};

/// What the form offers: calendars as they are, policies only when they can be assigned.
const assignablePolicySources = {
  'WORK_CALENDAR': 'work_calendars',
  'WEEKLY_OFF': 'weekly_off_patterns',
  'ATTENDANCE_POLICY': 'assignable_attendance_policies',
  'OVERTIME_POLICY': 'assignable_overtime_policies',
  'REGULARIZATION_POLICY': 'assignable_regularization_policies',
  'LEAVE_POLICY': 'assignable_leave_policies',
};

/// Calendars change who is rostered, so ending one is done with the impact preview on the web.
bool canEndAssignment(String policyKind, String scopeType, Object? effectiveTo) =>
    effectiveTo == null && scopeType != 'COMPANY' && policyKind != 'WORK_CALENDAR' && policyKind != 'WEEKLY_OFF';

const scopeSources = {
  'LEGAL_ENTITY': 'legal_entities',
  'BRANCH': 'branches',
  'DEPARTMENT': 'departments',
  'GRADE': 'grades',
  'DESIGNATION': 'designations',
  'SHIFT': 'shifts',
  'EMPLOYEE': 'employees',
};

const policyAssignmentSpec = FormSpec(name: 'policy_assignment', label: 'Policy assignment', defaults: {'policy_kind': 'ATTENDANCE_POLICY', 'scope_type': 'COMPANY'}, fields: [
  FieldSpec('policy_kind', 'Policy kind', kind: FieldKind.select, required: true, options: ['WORK_CALENDAR', 'WEEKLY_OFF', 'ATTENDANCE_POLICY', 'OVERTIME_POLICY', 'REGULARIZATION_POLICY', 'LEAVE_POLICY'], optionLabels: policyKindLabels),
  FieldSpec('leave_type_id', 'Leave type', kind: FieldKind.choice, choiceKey: 'leave_types', required: true, showWhen: 'policy_kind=LEAVE_POLICY'),
  FieldSpec('policy_id', 'Policy', kind: FieldKind.choice, required: true, dependsOn: 'policy_kind', choiceMap: assignablePolicySources),
  FieldSpec('scope_type', 'Scope', kind: FieldKind.select, required: true, options: ['COMPANY', 'LEGAL_ENTITY', 'BRANCH', 'DEPARTMENT', 'GRADE', 'DESIGNATION', 'SHIFT', 'EMPLOYEE'], optionLabels: scopeTypeLabels),
  FieldSpec('scope_id', 'Applies to', kind: FieldKind.choice, required: true, showWhen: 'scope_type!=COMPANY', dependsOn: 'scope_type', choiceMap: scopeSources),
  FieldSpec('effective_from', 'Effective from', kind: FieldKind.date, required: true),
  FieldSpec('reason', 'Reason', kind: FieldKind.multiline),
]);
