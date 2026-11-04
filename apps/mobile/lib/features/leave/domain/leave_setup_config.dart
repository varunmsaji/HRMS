import '../../../core/forms/form_spec.dart';
import '../../attendance/domain/policy_setup_config.dart';
import 'leave_resources.dart';

/// Leave policies on one page. Mirrors the web templates (`apps/web/src/lib/leave-policy/templates.ts`).

const _approvalLabels = {
  'AUTO': 'Approved automatically',
  'MANAGER': 'Manager approves',
  'MANAGER_THEN_HR': 'Manager approves, then HR',
  'MANAGER_THEN_HOD_THEN_HR': 'Manager, then department head, then HR',
  'HR': 'HR approves',
};

const _accrualLabels = {'NONE': 'No automatic credit', 'MONTHLY': 'Every month', 'YEARLY': 'Once a year'};

FieldSpec _labelled(String key, String label, Map<String, String> labels) {
  final f = leavePolicyVersionSpec.fields.firstWhere((f) => f.key == key);
  return FieldSpec(f.key, label, kind: f.kind, options: f.options, optionLabels: labels);
}

final leavePolicySetup = PolicySetupConfig(
  title: 'New leave policy',
  path: '/leave-policies',
  policyKind: 'LEAVE_POLICY',
  leaveTyped: true,
  rules: rulesWithout(leavePolicyVersionSpec, changes: {
    'approval_chain': _labelled('approval_chain', 'Who approves', _approvalLabels),
    'accrual_frequency': _labelled('accrual_frequency', 'Days are credited', _accrualLabels),
    'accrual_rate_per_cycle': adjusted(leavePolicyVersionSpec.fields.firstWhere((f) => f.key == 'accrual_rate_per_cycle'), showWhen: 'accrual_frequency!=NONE', required: true),
    'max_carry_forward_days': adjusted(leavePolicyVersionSpec.fields.firstWhere((f) => f.key == 'max_carry_forward_days'), showWhen: 'year_end_action!=LAPSE'),
  }),
  everydayKeys: const [
    'allow_employee_request',
    'allow_manager_request_on_behalf',
    'allow_hr_request_on_behalf',
    'approval_chain',
    'reason_required',
    'half_day_allowed',
    'sandwich_rule_enabled',
    'accrual_frequency',
    'accrual_rate_per_cycle',
    'year_end_action',
    'max_carry_forward_days',
  ],
  base: const {
    'allow_employee_request': true,
    'allow_manager_request_on_behalf': true,
    'allow_hr_request_on_behalf': true,
    'reason_required': true,
    'attachment_required': false,
    'approval_chain': 'MANAGER',
    'half_day_allowed': true,
    'accrual_frequency': 'NONE',
    'year_end_action': 'CARRY_FORWARD',
    'encashment_allowed': false,
    'allow_negative_balance': false,
    'sandwich_rule_enabled': true,
    'reserve_balance_on_submission': false,
    'allowed_during_probation': true,
    'accrue_during_probation': true,
  },
  templates: const [
    SetupTemplate(key: 'casual', label: 'Casual leave', description: '1 day a month. Unused days lapse at the end of the leave year.', defaultName: 'Casual leave', values: {'accrual_frequency': 'MONTHLY', 'accrual_rate_per_cycle': '1', 'year_end_action': 'LAPSE'}),
    SetupTemplate(key: 'earned', label: 'Earned leave', description: '1.5 days a month. Up to 30 unused days carry into the next year.', defaultName: 'Earned leave', values: {'accrual_frequency': 'MONTHLY', 'accrual_rate_per_cycle': '1.5', 'year_end_action': 'CARRY_FORWARD', 'max_carry_forward_days': '30'}),
    SetupTemplate(key: 'sick', label: 'Sick leave', description: '12 days credited once a year. Unused days lapse.', defaultName: 'Sick leave', values: {'accrual_frequency': 'YEARLY', 'accrual_rate_per_cycle': '12', 'year_end_action': 'LAPSE', 'sandwich_rule_enabled': false}),
    SetupTemplate(key: 'blank', label: 'Start from scratch', description: 'Set every rule yourself.', defaultName: ''),
  ],
);
