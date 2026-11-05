import '../../../core/forms/form_spec.dart';
import 'policy_resources.dart';
import 'policy_setup_config.dart';

/// Attendance, overtime and regularization policies and shifts, created on one page. The templates
/// and defaults mirror the web ones (`apps/web/src/lib/*-policy/templates.ts`).

const _approvalLabels = {
  'AUTO': 'Approved automatically',
  'MANAGER': 'Manager approves',
  'MANAGER_THEN_HR': 'Manager approves, then HR',
  'HR': 'HR approves',
};

FieldSpec _approval(FieldSpec f) => FieldSpec(f.key, 'Who approves', kind: f.kind, options: f.options, optionLabels: _approvalLabels);

// ---- attendance -------------------------------------------------------------------------------

Map<String, dynamic> _band(int min, int? max, String status) => {'min_minutes': min, 'max_minutes': max, 'result_status': status};

/// Under half the full-day hours is absent, up to the full day is a half-day, then present.
List<Map<String, dynamic>> _hourBands(int fullDay) => [_band(0, fullDay ~/ 2 - 1, 'ABSENT'), _band(fullDay ~/ 2, fullDay - 1, 'HALF_DAY'), _band(fullDay, null, 'PRESENT')];

final attendancePolicySetup = PolicySetupConfig(
  title: 'New attendance policy',
  path: '/attendance-policies',
  policyKind: 'ATTENDANCE_POLICY',
  rules: rulesWithout(attendancePolicyVersionSpec),
  everydayKeys: const ['grace_in_minutes', 'grace_out_minutes', 'hour_bands', 'missing_punch_behaviour', 'lates_to_half_day_count', 'early_departure_requires_approval'],
  base: const {
    'grace_in_minutes': 0,
    'grace_out_minutes': 0,
    'geofence_mode': 'DISABLED',
    'geofence_max_accuracy_m': 100,
    'geofence_max_age_seconds': 60,
    'punch_rounding': 'NONE',
    'missing_punch_behaviour': 'INCOMPLETE',
    'auto_close_uses_shift_end': true,
    'missing_shift_behaviour': 'INCOMPLETE',
    'half_day_split': 'BY_HOURS',
    'multi_punch_mode': 'PAIR_ALL',
    'duplicate_punch_window_seconds': 60,
    'core_hours_breach_behaviour': 'FLAG',
    'early_out_uses_core_end': false,
    'split_shift_block_mandatory': true,
    'split_shift_missed_block_behaviour': 'HALF_DAY',
    'split_shift_allow_hours_compensation': false,
    'wfh_requires_punch': true,
    'on_duty_requires_punch': false,
    'wfh_uses_shift_hours': true,
    'work_on_leave_behaviour': 'KEEP_LEAVE',
    'excess_break_behaviour': 'FLAG',
    'early_departure_requires_approval': false,
    'incomplete_at_lock_behaviour': 'TREAT_ABSENT',
    'hour_bands': <Map<String, dynamic>>[],
    'late_bands': <Map<String, dynamic>>[],
    'early_departure_bands': <Map<String, dynamic>>[],
  },
  templates: [
    SetupTemplate(key: 'standard', label: 'Standard office', description: '10 minutes grace, 8 hours for a full day, 4 for a half-day.', defaultName: 'Standard office', values: {'grace_in_minutes': 10, 'grace_out_minutes': 10, 'hour_bands': _hourBands(480)}),
    SetupTemplate(key: 'flexible', label: 'Flexible hours', description: '30 minutes grace, 6 hours for a full day, 3 for a half-day.', defaultName: 'Flexible hours', values: {'grace_in_minutes': 30, 'grace_out_minutes': 30, 'hour_bands': _hourBands(360)}),
    SetupTemplate(
      key: 'strict',
      label: 'Strict attendance',
      description: 'No grace, 8 hours for a full day. Every third late day in a month is a half-day, and leaving early needs approval.',
      defaultName: 'Strict attendance',
      values: {'lates_to_half_day_count': 3, 'early_departure_requires_approval': true, 'hour_bands': _hourBands(480)},
    ),
    const SetupTemplate(key: 'blank', label: 'Start from scratch', description: 'Set every rule yourself.', defaultName: ''),
  ],
);

// ---- overtime ---------------------------------------------------------------------------------

const _otLabels = [
  {'day_class': 'NORMAL', 'classification_code': 'OT_NORMAL'},
  {'day_class': 'WEEKLY_OFF', 'classification_code': 'OT_WEEKOFF'},
  {'day_class': 'HOLIDAY', 'classification_code': 'OT_HOLIDAY'},
];

final overtimePolicySetup = PolicySetupConfig(
  title: 'New overtime policy',
  path: '/overtime-policies',
  policyKind: 'OVERTIME_POLICY',
  rules: rulesWithout(overtimePolicyVersionSpec, changes: {
    'approval_chain': _approval(overtimePolicyVersionSpec.fields.firstWhere((f) => f.key == 'approval_chain')),
  }),
  everydayKeys: const ['eligibility', 'approval_chain', 'min_ot_minutes', 'requires_post_approval', 'daily_cap_minutes', 'comp_off_instead_of_pay'],
  base: const {
    'eligibility': 'SHIFT_FLAG',
    'min_ot_minutes': 0,
    'rounding_mode': 'NONE',
    'requires_pre_approval': false,
    'requires_post_approval': true,
    'comp_off_instead_of_pay': false,
    'night_ot_mode': 'SHIFT_FLAG',
    'approval_chain': 'MANAGER',
    'rate_rows': <Map<String, dynamic>>[],
  },
  templates: const [
    SetupTemplate(key: 'manager', label: 'Manager approves', description: 'Overtime counts on shifts marked eligible, and the manager approves it afterwards. No limits.', defaultName: 'Manager approves overtime', values: {'approval_chain': 'MANAGER', 'rate_rows': _otLabels}),
    SetupTemplate(key: 'manager-hr', label: 'Manager, then HR approve', description: 'The same, but HR approves after the manager.', defaultName: 'Manager and HR approve overtime', values: {'approval_chain': 'MANAGER_THEN_HR', 'rate_rows': _otLabels}),
    SetupTemplate(key: 'none', label: 'Overtime not allowed', description: 'Nobody earns overtime under this policy.', defaultName: 'No overtime', values: {'eligibility': 'NEVER'}),
    SetupTemplate(key: 'blank', label: 'Start from scratch', description: 'Set every rule yourself.', defaultName: ''),
  ],
);

// ---- regularization ---------------------------------------------------------------------------

final _allTypes = [for (final t in regularizationTypes) {'regularization_type': t}];

final regularizationPolicySetup = PolicySetupConfig(
  title: 'New regularization policy',
  path: '/regularization-policies',
  policyKind: 'REGULARIZATION_POLICY',
  rules: rulesWithout(regularizationPolicyVersionSpec, changes: {
    'approval_chain': _approval(regularizationPolicyVersionSpec.fields.firstWhere((f) => f.key == 'approval_chain')),
  }),
  everydayKeys: const ['approval_chain', 'allowed_types', 'allow_employee_request', 'allow_manager_request', 'allow_hr_request', 'reason_required', 'max_backdated_days'],
  base: const {
    'allow_employee_request': true,
    'allow_manager_request': true,
    'allow_hr_request': true,
    'reason_required': true,
    'attachment_required': false,
    'approval_chain': 'MANAGER',
    'blocked_when_locked': true,
    'allowed_types': <Map<String, dynamic>>[],
  },
  requiredToPublish: const {'allowed_types': 'Choose at least one kind of correction before publishing.'},
  templates: [
    SetupTemplate(key: 'manager', label: 'Manager approves', description: 'Everyone can ask for any kind of correction, with a reason. The manager approves. No limits.', defaultName: 'Manager approves corrections', values: {'approval_chain': 'MANAGER', 'allowed_types': _allTypes}),
    SetupTemplate(key: 'manager-hr', label: 'Manager, then HR approve', description: 'The same, but HR approves after the manager.', defaultName: 'Manager and HR approve corrections', values: {'approval_chain': 'MANAGER_THEN_HR', 'allowed_types': _allTypes}),
    SetupTemplate(key: 'hr', label: 'HR approves', description: 'The same, but only HR approves.', defaultName: 'HR approves corrections', values: {'approval_chain': 'HR', 'allowed_types': _allTypes}),
    const SetupTemplate(key: 'blank', label: 'Start from scratch', description: 'Choose each kind of correction yourself.', defaultName: ''),
  ],
);

// ---- shifts -----------------------------------------------------------------------------------

FormSpec _shiftRules() {
  final all = {for (final f in shiftVersionSpec().fields) f.key: f};
  FieldSpec f(String key, {String? showWhen, bool? required}) => adjusted(all[key]!, showWhen: showWhen, required: required);
  return FormSpec(name: 'shift_setup', label: 'Shift', fields: [
    f('shift_type', required: true),
    f('start_time', showWhen: 'shift_type=FIXED', required: true),
    f('end_time', showWhen: 'shift_type=FIXED', required: true),
    f('window_start', showWhen: 'shift_type=FLEXIBLE', required: true),
    f('window_end', showWhen: 'shift_type=FLEXIBLE', required: true),
    f('required_minutes', showWhen: 'shift_type=FLEXIBLE', required: true),
    f('core_start', showWhen: 'shift_type=FLEXIBLE'),
    f('core_end', showWhen: 'shift_type=FLEXIBLE'),
    f('is_night_shift'),
    f('is_ot_eligible'),
    f('breaks'),
    f('timezone'),
    f('operates_on_holiday'),
    f('operates_on_weekly_off'),
    f('weekly_off_pattern_id'),
    f('scheduled_minutes'),
    f('min_scheduled_minutes'),
    f('max_scheduled_minutes'),
  ]);
}

Map<String, dynamic> _fixed(String start, String end, {bool night = false}) => {'shift_type': 'FIXED', 'start_time': start, 'end_time': end, 'is_night_shift': night};

final shiftSetup = PolicySetupConfig(
  title: 'New shift',
  path: '/shifts',
  rules: _shiftRules(),
  everydayKeys: const ['shift_type', 'start_time', 'end_time', 'window_start', 'window_end', 'required_minutes', 'core_start', 'core_end', 'is_night_shift', 'is_ot_eligible', 'breaks'],
  base: const {
    'timezone': 'Asia/Kolkata',
    'is_night_shift': false,
    'is_ot_eligible': false,
    'operates_on_holiday': false,
    'operates_on_weekly_off': false,
    'breaks': <Map<String, dynamic>>[],
  },
  templates: [
    SetupTemplate(key: 'general', label: 'General (9 to 6)', description: 'A fixed day shift from 09:00 to 18:00.', defaultName: 'General shift', values: _fixed('09:00', '18:00')),
    SetupTemplate(key: 'morning', label: 'Morning (6 to 2)', description: 'A fixed shift from 06:00 to 14:00.', defaultName: 'Morning shift', values: _fixed('06:00', '14:00')),
    SetupTemplate(key: 'evening', label: 'Evening (2 to 10)', description: 'A fixed shift from 14:00 to 22:00.', defaultName: 'Evening shift', values: _fixed('14:00', '22:00')),
    SetupTemplate(key: 'night', label: 'Night (10 to 6)', description: 'A fixed shift from 22:00 to 06:00 the next morning, marked as a night shift.', defaultName: 'Night shift', values: _fixed('22:00', '06:00', night: true)),
    const SetupTemplate(
      key: 'flexible',
      label: 'Flexible hours',
      description: 'Arrive any time between 08:00 and 11:00 and work 8 hours.',
      defaultName: 'Flexible shift',
      values: {'shift_type': 'FLEXIBLE', 'window_start': '08:00', 'window_end': '11:00', 'required_minutes': 480},
    ),
    const SetupTemplate(key: 'blank', label: 'Start from scratch', description: 'Set the schedule yourself.', defaultName: ''),
  ],
);
