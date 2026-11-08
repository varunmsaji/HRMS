import '../../../core/auth/permissions.dart';
import '../../../core/forms/form_spec.dart';
import '../../../core/resource/resource_config.dart';

/// Leave policies — an identity per leave type plus versions (mirrors `LeavePolicyCreate`/
/// `LeavePolicyVersionCreate` in `apps/api/.../leave/schemas.py` and the web `leave-policies/[id]` page).

const _active = FieldSpec('is_active', 'Active', kind: FieldKind.toggle, editOnly: true);

const leavePolicyIdentitySpec = FormSpec(name: 'leave_policy', label: 'Leave policy', fields: [
  FieldSpec('leave_type_id', 'Leave type', kind: FieldKind.choice, choiceKey: 'leave_types', required: true, readOnlyOnEdit: true),
  FieldSpec('name', 'Name', required: true),
  _active,
]);

const leavePolicyVersionSpec = FormSpec(name: 'leave_policy_version', label: 'Leave policy version', fields: [
  FieldSpec('effective_from', 'Effective from', kind: FieldKind.date),
  FieldSpec('allow_employee_request', 'Employees can apply for themselves', kind: FieldKind.toggle),
  FieldSpec('allow_manager_request_on_behalf', 'Managers can apply for their reports', kind: FieldKind.toggle),
  FieldSpec('allow_hr_request_on_behalf', 'HR can apply for anyone', kind: FieldKind.toggle),
  FieldSpec('max_backdated_days', 'Furthest back an application can start (days)', kind: FieldKind.integer),
  FieldSpec('max_requests_per_month', 'Most applications per month', kind: FieldKind.integer),
  FieldSpec('reason_required', 'Employees must give a reason', kind: FieldKind.toggle),
  FieldSpec('attachment_required', 'Employees must attach a document', kind: FieldKind.toggle),
  FieldSpec('approval_chain', 'Who approves', kind: FieldKind.select, options: ['AUTO', 'MANAGER', 'MANAGER_THEN_HR', 'MANAGER_THEN_HOD_THEN_HR', 'HR']),
  FieldSpec('half_day_allowed', 'Half-day leave is allowed', kind: FieldKind.toggle),
  FieldSpec('accrual_frequency', 'Days are credited', kind: FieldKind.select, options: ['NONE', 'MONTHLY', 'YEARLY']),
  FieldSpec('accrual_rate_per_cycle', 'Days credited each time', kind: FieldKind.decimal),
  FieldSpec('max_carry_forward_days', 'Maximum carry-forward (days)', kind: FieldKind.decimal),
  FieldSpec('year_end_action', 'At the end of the leave year', kind: FieldKind.select, options: ['CARRY_FORWARD', 'LAPSE', 'ENCASH_EXCESS'], optionLabels: {
    'CARRY_FORWARD': 'Carry forward up to the cap, the rest lapses',
    'LAPSE': 'Lapse — the whole balance is forfeited',
    'ENCASH_EXCESS': 'Carry forward up to the cap, encash the rest',
  }),
  FieldSpec('allow_negative_balance', 'Balance can go below zero', kind: FieldKind.toggle),
  FieldSpec('negative_balance_floor', 'Days below zero allowed', kind: FieldKind.decimal, showWhen: 'allow_negative_balance'),
  FieldSpec('encashment_allowed', 'Unused days can be encashed', kind: FieldKind.toggle),
  FieldSpec('max_encashment_days', 'Most days that can be encashed', kind: FieldKind.decimal, showWhen: 'encashment_allowed'),
  FieldSpec('min_balance_after_encashment', 'Balance that must stay after encashing', kind: FieldKind.decimal, showWhen: 'encashment_allowed'),
  FieldSpec('encashment_frequency', 'How often (note only)', showWhen: 'encashment_allowed'),
  FieldSpec('encashment_calculation_basis', 'How it is paid (note only)', showWhen: 'encashment_allowed'),
  FieldSpec('sandwich_rule_enabled', 'Count weekly offs and holidays between two leave days', kind: FieldKind.toggle),
  FieldSpec('reserve_balance_on_submission', 'Hold the days as soon as someone applies', kind: FieldKind.toggle),
  FieldSpec('pre_delivery_days', 'Days before delivery (maternity, note only)', kind: FieldKind.integer),
  FieldSpec('post_delivery_days', 'Days after delivery (maternity, note only)', kind: FieldKind.integer),
  FieldSpec('allowed_during_probation', 'Employees on probation can apply', kind: FieldKind.toggle),
  FieldSpec('accrue_during_probation', 'Employees on probation earn days', kind: FieldKind.toggle),
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

// ---- leave types, combination rules, statutory minimums --------------------------------------

const statutoryLeaveCategories = ['EARNED', 'SICK', 'CASUAL', 'MATERNITY', 'PATERNITY'];

const leaveTypeSpec = FormSpec(name: 'leave_type', label: 'Leave type', defaults: {'is_paid_default': true, 'requires_balance': true}, fields: [
  FieldSpec('code', 'Code', kind: FieldKind.upper, required: true, readOnlyOnEdit: true),
  FieldSpec('name', 'Name', required: true),
  FieldSpec('is_paid_default', 'Paid by default', kind: FieldKind.toggle),
  FieldSpec('requires_balance', 'Needs a leave balance', kind: FieldKind.toggle),
  FieldSpec('is_comp_off', 'Compensatory off', kind: FieldKind.toggle),
  FieldSpec('statutory_category', 'Statutory category', kind: FieldKind.select, options: statutoryLeaveCategories, hint: 'Links this type to a statutory minimum'),
  _active,
]);

final leaveTypeResource = ResourceConfig(
  title: 'Leave Types',
  singular: 'Leave type',
  path: '/leave-types',
  spec: leaveTypeSpec,
  rowTitle: (r) => '${r['name']} (${r['code']})',
  rowSubtitle: (r) => [if (r['is_paid_default'] == true) 'Paid' else 'Unpaid', if (r['is_comp_off'] == true) 'Comp-off', if (r['statutory_category'] != null) prettyEnum('${r['statutory_category']}')].join(' · '),
  manage: leaveTypeManage,
);

const leaveCombinationRuleSpec = FormSpec(name: 'leave_combination_rule', label: 'Combination rule', defaults: {'allowed': true}, fields: [
  FieldSpec('leave_type_id_a', 'Leave type A', kind: FieldKind.choice, choiceKey: 'leave_types', required: true),
  FieldSpec('leave_type_id_b', 'Leave type B', kind: FieldKind.choice, choiceKey: 'leave_types', required: true),
  FieldSpec('allowed', 'Allowed together', kind: FieldKind.toggle),
  FieldSpec('reason', 'Reason', kind: FieldKind.multiline),
]);

final leaveCombinationRuleResource = ResourceConfig(
  title: 'Leave Combination Rules',
  singular: 'Combination rule',
  path: '/leave-combination-rules',
  spec: leaveCombinationRuleSpec,
  rowTitle: (r) => '${r['allowed'] == true ? 'Allowed' : 'Not allowed'} together',
  rowSubtitle: (r) => r['reason'] as String?,
  manage: 'LEAVE.COMBINATION_RULE_MANAGE',
  hasActive: false,
  editable: false,
  hardDelete: true,
);

const statutoryLeaveMinimumSpec = FormSpec(name: 'statutory_leave_minimum', label: 'Statutory minimum', fields: [
  FieldSpec('leave_category', 'Leave category', kind: FieldKind.select, required: true, options: statutoryLeaveCategories),
  FieldSpec('min_days_per_year', 'Minimum days per year', kind: FieldKind.decimal, required: true),
  FieldSpec('state_code', 'State code', hint: 'Leave blank to apply everywhere'),
  FieldSpec('establishment_type', 'Establishment type', hint: 'Optional'),
  FieldSpec('note', 'Note', kind: FieldKind.multiline),
]);

final statutoryLeaveMinimumResource = ResourceConfig(
  title: 'Statutory Minimums',
  singular: 'Statutory minimum',
  path: '/statutory-leave-minimums',
  spec: statutoryLeaveMinimumSpec,
  rowTitle: (r) => '${prettyEnum('${r['leave_category']}')} · ${r['min_days_per_year']} days a year',
  rowSubtitle: (r) => [r['state_code'] ?? 'All states', if (r['establishment_type'] != null) r['establishment_type']].join(' · '),
  manage: 'LEAVE.STATUTORY_MINIMUM_MANAGE',
  hasActive: false,
  editable: false,
  hardDelete: true,
);
