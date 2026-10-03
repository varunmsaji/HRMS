import '../../../core/auth/permissions.dart';
import '../../../core/forms/form_spec.dart';
import '../../../core/resource/resource_config.dart';

/// Leave policies — an identity per leave type plus versions (mirrors `LeavePolicyCreate`/
/// `LeavePolicyVersionCreate` in `apps/api/.../leave/schemas.py` and the web `leave-policies/[id]` page).

const _active = FieldSpec('is_active', 'Active', kind: FieldKind.toggle, editOnly: true);

const leavePolicyIdentitySpec = FormSpec(name: 'leave_policy', label: 'Leave policy', fields: [
  FieldSpec('leave_type_id', 'Leave type', kind: FieldKind.choice, choiceKey: 'leave_types', required: true, readOnlyOnEdit: true),
  FieldSpec('name', 'Name', required: true),
  FieldSpec('code', 'Code'),
  _active,
]);

const leavePolicyVersionSpec = FormSpec(name: 'leave_policy_version', label: 'Leave policy version', fields: [
  FieldSpec('effective_from', 'Effective from', kind: FieldKind.date),
  FieldSpec('allow_employee_request', 'Employees can apply', kind: FieldKind.toggle),
  FieldSpec('allow_manager_request_on_behalf', 'Managers can apply on behalf', kind: FieldKind.toggle),
  FieldSpec('allow_hr_request_on_behalf', 'HR can apply on behalf', kind: FieldKind.toggle),
  FieldSpec('max_backdated_days', 'Maximum backdated days', kind: FieldKind.integer),
  FieldSpec('max_requests_per_month', 'Maximum requests per month', kind: FieldKind.integer),
  FieldSpec('reason_required', 'Reason required', kind: FieldKind.toggle),
  FieldSpec('attachment_required', 'Attachment required', kind: FieldKind.toggle),
  FieldSpec('approval_chain', 'Approval chain', kind: FieldKind.select, options: ['AUTO', 'MANAGER', 'MANAGER_THEN_HR', 'MANAGER_THEN_HOD_THEN_HR', 'HR']),
  FieldSpec('half_day_allowed', 'Half days allowed', kind: FieldKind.toggle),
  FieldSpec('accrual_frequency', 'Accrual frequency', kind: FieldKind.select, options: ['NONE', 'MONTHLY', 'YEARLY']),
  FieldSpec('accrual_rate_per_cycle', 'Accrual per cycle (days)', kind: FieldKind.decimal),
  FieldSpec('max_carry_forward_days', 'Maximum carry-forward (days)', kind: FieldKind.decimal),
  FieldSpec('year_end_action', 'At year end', kind: FieldKind.select, options: ['CARRY_FORWARD', 'LAPSE', 'ENCASH_EXCESS'], optionLabels: {
    'CARRY_FORWARD': 'Carry forward up to the cap, the rest lapses',
    'LAPSE': 'Lapse — the whole balance is forfeited',
    'ENCASH_EXCESS': 'Carry forward up to the cap, encash the rest',
  }),
  FieldSpec('allow_negative_balance', 'Allow a negative balance', kind: FieldKind.toggle),
  FieldSpec('negative_balance_floor', 'Negative-balance floor (days)', kind: FieldKind.decimal, showWhen: 'allow_negative_balance'),
  FieldSpec('encashment_allowed', 'Encashment allowed', kind: FieldKind.toggle),
  FieldSpec('max_encashment_days', 'Maximum encashment (days)', kind: FieldKind.decimal, showWhen: 'encashment_allowed'),
  FieldSpec('min_balance_after_encashment', 'Minimum balance after encashment (days)', kind: FieldKind.decimal, showWhen: 'encashment_allowed'),
  FieldSpec('encashment_frequency', 'Encashment frequency', showWhen: 'encashment_allowed'),
  FieldSpec('encashment_calculation_basis', 'Encashment calculation basis', showWhen: 'encashment_allowed'),
  FieldSpec('sandwich_rule_enabled', 'Sandwich rule', kind: FieldKind.toggle),
  FieldSpec('reserve_balance_on_submission', 'Reserve balance on submission', kind: FieldKind.toggle),
  FieldSpec('pre_delivery_days', 'Pre-delivery days (maternity)', kind: FieldKind.integer),
  FieldSpec('post_delivery_days', 'Post-delivery days (maternity)', kind: FieldKind.integer),
  FieldSpec('allowed_during_probation', 'Allowed during probation', kind: FieldKind.toggle),
  FieldSpec('accrue_during_probation', 'Accrues during probation', kind: FieldKind.toggle),
]);

final leavePolicyResource = ResourceConfig(
  title: 'Leave Policies',
  singular: 'Leave policy',
  path: '/leave-policies',
  spec: leavePolicyIdentitySpec,
  rowTitle: (r) => r['name'] as String,
  rowSubtitle: (r) => r['code'] as String?,
  manage: leavePolicyManage,
  versions: VersionsConfig(
    spec: leavePolicyVersionSpec,
    noun: 'policy version',
    summary: (v) => 'Accrual ${prettyEnum('${v['accrual_frequency']}')} · ${prettyEnum('${v['approval_chain']}')}',
  ),
);
