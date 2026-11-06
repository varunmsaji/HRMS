import '../../../core/auth/permissions.dart';
import '../../../core/forms/form_spec.dart';
import '../../../core/resource/resource_config.dart';
import '../../../core/time.dart';

/// Versioned resources of the attendance module — attendance / overtime / regularization policies
/// and shifts. Each version spec mirrors a `*VersionCreate`/`*VersionUpdate` schema (and the web
/// version form), with the nested lists as `FieldKind.rows`.

const _active = FieldSpec('is_active', 'Active', kind: FieldKind.toggle, editOnly: true);

String? _join(Iterable<dynamic> parts, [String sep = ' · ']) {
  final s = parts.where((p) => p != null && p.toString().isNotEmpty).join(sep);
  return s.isEmpty ? null : s;
}

const _approvalChains = ['AUTO', 'MANAGER', 'MANAGER_THEN_HR', 'HR'];
const _roundings = ['NONE', 'NEAREST', 'UP', 'DOWN'];

// ---- attendance policy ------------------------------------------------------------------------

const attendancePolicyIdentitySpec = FormSpec(name: 'attendance_policy', label: 'Attendance policy', fields: [
  FieldSpec('name', 'Name', required: true),
  _active,
]);

const geofenceModeLabels = {
  'DISABLED': 'Disabled: location is not checked',
  'OPTIONAL': 'Optional: record and flag location, never block a punch',
  'REQUIRED': 'Required: block self-service punches outside an approved workplace',
};

const attendancePolicyVersionSpec = FormSpec(name: 'attendance_policy_version', label: 'Attendance policy version', fields: [
  FieldSpec('effective_from', 'Effective from', kind: FieldKind.date),
  FieldSpec('grace_in_minutes', 'Grace in (minutes)', kind: FieldKind.integer),
  FieldSpec('grace_out_minutes', 'Grace out (minutes)', kind: FieldKind.integer),
  FieldSpec('early_in_allowance_minutes', 'Earliest punch-in before shift start (minutes)', kind: FieldKind.integer),
  FieldSpec('punch_rounding', 'Punch rounding', kind: FieldKind.select, options: _roundings),
  FieldSpec('rounding_minutes', 'Rounding step (minutes)', kind: FieldKind.integer),
  FieldSpec('missing_punch_behaviour', 'Missing punch', kind: FieldKind.select, options: ['INCOMPLETE', 'ABSENT', 'AUTO_CLOSE', 'REQUIRE_REGULARIZATION']),
  FieldSpec('auto_close_after_minutes', 'Auto-close after (minutes)', kind: FieldKind.integer),
  FieldSpec('auto_close_uses_shift_end', 'Auto-close at shift end', kind: FieldKind.toggle),
  FieldSpec('missing_shift_behaviour', 'No shift assigned', kind: FieldKind.select, options: ['INCOMPLETE', 'ABSENT']),
  FieldSpec('half_day_split', 'Half-day split', kind: FieldKind.select, options: ['BY_HOURS', 'BY_MIDPOINT']),
  FieldSpec('half_day_boundary_minutes', 'Half-day boundary (minutes)', kind: FieldKind.integer),
  FieldSpec('multi_punch_mode', 'Multiple punches', kind: FieldKind.select, options: ['PAIR_ALL', 'FIRST_IN_LAST_OUT']),
  FieldSpec('duplicate_punch_window_seconds', 'Duplicate-punch window (seconds)', kind: FieldKind.integer),
  FieldSpec('core_hours_breach_behaviour', 'Core-hours breach', kind: FieldKind.select, options: ['IGNORE', 'FLAG', 'HALF_DAY', 'ABSENT']),
  FieldSpec('early_out_uses_core_end', 'Early departure measured from core end', kind: FieldKind.toggle),
  FieldSpec('split_shift_block_mandatory', 'Every split-shift block is mandatory', kind: FieldKind.toggle),
  FieldSpec('split_shift_missed_block_behaviour', 'Missed split-shift block', kind: FieldKind.select, options: ['IGNORE', 'HALF_DAY', 'ABSENT', 'REQUIRE_REGULARIZATION']),
  FieldSpec('split_shift_allow_hours_compensation', 'Allow hours compensation across blocks', kind: FieldKind.toggle),
  FieldSpec('wfh_requires_punch', 'Work-from-home needs a punch', kind: FieldKind.toggle),
  FieldSpec('on_duty_requires_punch', 'On-duty needs a punch', kind: FieldKind.toggle),
  FieldSpec('wfh_uses_shift_hours', 'Work-from-home uses shift hours', kind: FieldKind.toggle),
  FieldSpec('work_on_leave_behaviour', 'Work on a leave day', kind: FieldKind.select, options: ['KEEP_LEAVE', 'PRESENT_CANCEL_LEAVE_HINT']),
  FieldSpec('excess_break_behaviour', 'Excess break', kind: FieldKind.select, options: ['IGNORE', 'DEDUCT', 'FLAG', 'REQUIRE_APPROVAL']),
  FieldSpec('late_count_window', 'Late-count window', kind: FieldKind.select, options: ['MONTH']),
  FieldSpec('lates_to_half_day_count', 'Lates that make a half day', kind: FieldKind.integer),
  FieldSpec('early_departure_requires_approval', 'Early departure needs approval', kind: FieldKind.toggle),
  FieldSpec('excess_break_count_window', 'Excess-break count window', kind: FieldKind.select, options: ['MONTH']),
  FieldSpec('excess_break_days_to_half_day_count', 'Excess-break days that make a half day', kind: FieldKind.integer),
  FieldSpec('geofence_mode', 'Location check', kind: FieldKind.select, options: ['DISABLED', 'OPTIONAL', 'REQUIRED'], optionLabels: geofenceModeLabels),
  FieldSpec('geofence_max_accuracy_m', 'Worst acceptable GPS accuracy (metres)', kind: FieldKind.integer, hint: '5-500', showWhen: 'geofence_mode!=DISABLED'),
  FieldSpec('geofence_max_age_seconds', 'Oldest acceptable reading (seconds)', kind: FieldKind.integer, hint: '5-300', showWhen: 'geofence_mode!=DISABLED'),
  FieldSpec('incomplete_at_lock_behaviour', 'Incomplete day at lock', kind: FieldKind.select, options: ['TREAT_ABSENT', 'TREAT_PRESENT', 'KEEP_INCOMPLETE']),
  FieldSpec('hour_bands', 'Worked-hours bands', kind: FieldKind.rows, rowNoun: 'band', orderKey: 'sort_order', rowSpec: FormSpec(name: 'hour_band', label: 'Hour band', fields: [
    FieldSpec('min_minutes', 'From (minutes)', kind: FieldKind.integer, required: true),
    FieldSpec('max_minutes', 'To (minutes)', kind: FieldKind.integer),
    FieldSpec('result_status', 'Result', kind: FieldKind.select, required: true, options: ['PRESENT', 'HALF_DAY', 'ABSENT']),
  ])),
  FieldSpec('late_bands', 'Late-arrival bands', kind: FieldKind.rows, rowNoun: 'band', orderKey: 'sort_order', rowSpec: FormSpec(name: 'late_band', label: 'Late band', defaults: {'counts_toward_cap': true}, fields: [
    FieldSpec('min_minutes', 'From (minutes)', kind: FieldKind.integer, required: true),
    FieldSpec('max_minutes', 'To (minutes)', kind: FieldKind.integer),
    FieldSpec('classification', 'Classification', kind: FieldKind.select, required: true, options: ['NONE', 'LATE', 'HALF_DAY', 'ABSENT']),
    FieldSpec('counts_toward_cap', 'Counts toward the late cap', kind: FieldKind.toggle),
  ])),
  FieldSpec('early_departure_bands', 'Early-departure bands', kind: FieldKind.rows, rowNoun: 'band', orderKey: 'sort_order', rowSpec: FormSpec(name: 'early_band', label: 'Early-departure band', defaults: {'counts_toward_cap': true}, fields: [
    FieldSpec('min_minutes', 'From (minutes)', kind: FieldKind.integer, required: true),
    FieldSpec('max_minutes', 'To (minutes)', kind: FieldKind.integer),
    FieldSpec('classification', 'Classification', kind: FieldKind.select, required: true, options: ['NONE', 'EARLY_DEPARTURE', 'HALF_DAY', 'ABSENT']),
    FieldSpec('counts_toward_cap', 'Counts toward the cap', kind: FieldKind.toggle),
  ])),
]);

final attendancePolicyResource = ResourceConfig(
  title: 'Attendance Policies',
  singular: 'Attendance policy',
  path: '/attendance-policies',
  spec: attendancePolicyIdentitySpec,
  rowTitle: (r) => r['name'] as String,
  rowSubtitle: (r) => r['code'] as String?,
  manage: attendancePolicyManage,
  versions: VersionsConfig(
    spec: attendancePolicyVersionSpec,
    noun: 'policy version',
    summary: (v) => 'Grace ${v['grace_in_minutes']}/${v['grace_out_minutes']} min · ${prettyEnum('${v['missing_punch_behaviour']}')}',
  ),
);

// ---- overtime policy --------------------------------------------------------------------------

const overtimePolicyIdentitySpec = FormSpec(name: 'overtime_policy', label: 'Overtime policy', fields: [
  FieldSpec('name', 'Name', required: true),
  _active,
]);

const overtimePolicyVersionSpec = FormSpec(name: 'overtime_policy_version', label: 'Overtime policy version', fields: [
  FieldSpec('effective_from', 'Effective from', kind: FieldKind.date),
  FieldSpec('eligibility', 'Eligibility', kind: FieldKind.select, options: ['SHIFT_FLAG', 'ALWAYS', 'NEVER', 'GRADE_VIA_ASSIGNMENT']),
  FieldSpec('min_ot_minutes', 'Minimum overtime (minutes)', kind: FieldKind.integer),
  FieldSpec('rounding_mode', 'Rounding', kind: FieldKind.select, options: _roundings),
  FieldSpec('rounding_minutes', 'Rounding step (minutes)', kind: FieldKind.integer),
  FieldSpec('requires_pre_approval', 'Needs approval before the work', kind: FieldKind.toggle),
  FieldSpec('requires_post_approval', 'Needs approval after the work', kind: FieldKind.toggle),
  FieldSpec('daily_cap_minutes', 'Daily cap (minutes)', kind: FieldKind.integer),
  FieldSpec('weekly_cap_minutes', 'Weekly cap (minutes)', kind: FieldKind.integer),
  FieldSpec('monthly_cap_minutes', 'Monthly cap (minutes)', kind: FieldKind.integer),
  FieldSpec('comp_off_instead_of_pay', 'Comp-off instead of pay', kind: FieldKind.toggle),
  FieldSpec('comp_off_expiry_days', 'Comp-off expires after (days)', kind: FieldKind.integer),
  FieldSpec('comp_off_day_length_minutes', 'Comp-off day length (minutes)', kind: FieldKind.integer),
  FieldSpec('night_ot_mode', 'Night overtime', kind: FieldKind.select, options: ['SHIFT_FLAG', 'WINDOW', 'BOTH']),
  FieldSpec('night_window_start', 'Night window starts', kind: FieldKind.time),
  FieldSpec('night_window_end', 'Night window ends', kind: FieldKind.time),
  FieldSpec('approval_chain', 'Approval chain', kind: FieldKind.select, options: _approvalChains),
  FieldSpec('rate_rows', 'Rate rows', kind: FieldKind.rows, rowNoun: 'rate', orderKey: 'sort_order', rowSpec: FormSpec(name: 'rate_row', label: 'Rate row', fields: [
    FieldSpec('day_class', 'Day class', kind: FieldKind.select, required: true, options: ['NORMAL', 'WEEKLY_OFF', 'HOLIDAY', 'NIGHT']),
    FieldSpec('classification_code', 'Classification code', kind: FieldKind.upper, required: true),
    FieldSpec('multiplier_decimal', 'Multiplier', kind: FieldKind.decimal, hint: 'e.g. 2 for double pay'),
  ])),
]);

final overtimePolicyResource = ResourceConfig(
  title: 'Overtime Policies',
  singular: 'Overtime policy',
  path: '/overtime-policies',
  spec: overtimePolicyIdentitySpec,
  rowTitle: (r) => r['name'] as String,
  rowSubtitle: (r) => r['code'] as String?,
  manage: attendancePolicyManage,
  versions: VersionsConfig(
    spec: overtimePolicyVersionSpec,
    noun: 'policy version',
    summary: (v) => '${prettyEnum('${v['eligibility']}')} · min ${v['min_ot_minutes']} min',
  ),
);

// ---- regularization policy --------------------------------------------------------------------

const regularizationPolicyIdentitySpec = FormSpec(name: 'regularization_policy', label: 'Regularization policy', fields: [
  FieldSpec('name', 'Name', required: true),
  _active,
]);

const regularizationTypes = ['MISSING_PUNCH', 'WRONG_PUNCH', 'WRONG_SHIFT', 'WRONG_STATUS', 'WFH', 'ON_DUTY', 'EXCESS_BREAK', 'FULL_DAY'];

const regularizationPolicyVersionSpec = FormSpec(name: 'regularization_policy_version', label: 'Regularization policy version', fields: [
  FieldSpec('effective_from', 'Effective from', kind: FieldKind.date),
  FieldSpec('allow_employee_request', 'Employees can request', kind: FieldKind.toggle),
  FieldSpec('allow_manager_request', 'Managers can request on behalf', kind: FieldKind.toggle),
  FieldSpec('allow_hr_request', 'HR can request on behalf', kind: FieldKind.toggle),
  FieldSpec('max_backdated_days', 'Maximum backdated days', kind: FieldKind.integer),
  FieldSpec('max_requests_per_month', 'Maximum requests per month', kind: FieldKind.integer),
  FieldSpec('reason_required', 'Reason required', kind: FieldKind.toggle),
  FieldSpec('attachment_required', 'Attachment required', kind: FieldKind.toggle),
  FieldSpec('approval_chain', 'Approval chain', kind: FieldKind.select, options: _approvalChains),
  FieldSpec('auto_approve_within_minutes', 'Auto-approve within (minutes)', kind: FieldKind.integer),
  FieldSpec('blocked_when_locked', 'Blocked once the period is locked', kind: FieldKind.toggle),
  FieldSpec('allowed_types', 'Allowed request types', kind: FieldKind.rows, rowNoun: 'type', orderKey: 'sort_order', rowSpec: FormSpec(name: 'allowed_type', label: 'Allowed type', fields: [
    FieldSpec('regularization_type', 'Type', kind: FieldKind.select, required: true, options: regularizationTypes),
  ])),
]);

final regularizationPolicyResource = ResourceConfig(
  title: 'Regularization Policies',
  singular: 'Regularization policy',
  path: '/regularization-policies',
  spec: regularizationPolicyIdentitySpec,
  rowTitle: (r) => r['name'] as String,
  rowSubtitle: (r) => r['code'] as String?,
  manage: attendancePolicyManage,
  versions: VersionsConfig(
    spec: regularizationPolicyVersionSpec,
    noun: 'policy version',
    summary: (v) => '${prettyEnum('${v['approval_chain']}')}${v['max_backdated_days'] != null ? ' · back ${v['max_backdated_days']} days' : ''}',
  ),
);

// ---- shifts -----------------------------------------------------------------------------------

const shiftIdentitySpec = FormSpec(name: 'shift', label: 'Shift', fields: [
  FieldSpec('name', 'Name', required: true),
  _active,
]);

/// Shift types a user may pick. SPLIT stays valid on the wire and in stored data (an existing split
/// shift still displays; the dropdown keeps its current value), but it is not offered for new
/// configuration until its calculation rules are verified.
const shiftTypeOptions = ['FIXED', 'FLEXIBLE'];

/// Built at first use: the timezone options come from the tz database.
FormSpec shiftVersionSpec() => FormSpec(name: 'shift_version', label: 'Shift version', fields: [
      const FieldSpec('effective_from', 'Effective from', kind: FieldKind.date),
      const FieldSpec('shift_type', 'Shift type', kind: FieldKind.select, options: shiftTypeOptions),
      FieldSpec('timezone', 'Timezone', kind: FieldKind.select, options: allTimeZones()),
      const FieldSpec('start_time', 'Start time', kind: FieldKind.time),
      const FieldSpec('end_time', 'End time', kind: FieldKind.time),
      const FieldSpec('window_start', 'Flexible window opens', kind: FieldKind.time),
      const FieldSpec('window_end', 'Flexible window closes', kind: FieldKind.time),
      const FieldSpec('core_start', 'Core hours start', kind: FieldKind.time),
      const FieldSpec('core_end', 'Core hours end', kind: FieldKind.time),
      const FieldSpec('required_minutes', 'Required minutes', kind: FieldKind.integer),
      const FieldSpec('scheduled_minutes', 'Scheduled minutes', kind: FieldKind.integer),
      const FieldSpec('min_scheduled_minutes', 'Minimum scheduled minutes', kind: FieldKind.integer),
      const FieldSpec('max_scheduled_minutes', 'Maximum scheduled minutes', kind: FieldKind.integer),
      const FieldSpec('is_night_shift', 'Night shift', kind: FieldKind.toggle),
      const FieldSpec('is_ot_eligible', 'Overtime eligible', kind: FieldKind.toggle),
      const FieldSpec('operates_on_holiday', 'Operates on holidays', kind: FieldKind.toggle),
      const FieldSpec('operates_on_weekly_off', 'Operates on weekly offs', kind: FieldKind.toggle),
      const FieldSpec('weekly_off_pattern_id', 'Weekly-off pattern', kind: FieldKind.choice, choiceKey: 'weekly_off_patterns'),
      const FieldSpec('breaks', 'Breaks', kind: FieldKind.rows, rowNoun: 'break', orderKey: 'sort_order', rowSpec: FormSpec(name: 'shift_break', label: 'Break', defaults: {'is_mandatory': true}, fields: [
        FieldSpec('name', 'Name', required: true),
        FieldSpec('break_kind', 'Kind', kind: FieldKind.select, required: true, options: ['FIXED_WINDOW', 'FLEXIBLE_DURATION']),
        FieldSpec('start_time', 'Starts', kind: FieldKind.time),
        FieldSpec('end_time', 'Ends', kind: FieldKind.time),
        FieldSpec('window_start', 'Window opens', kind: FieldKind.time),
        FieldSpec('window_end', 'Window closes', kind: FieldKind.time),
        FieldSpec('min_minutes', 'Minimum minutes', kind: FieldKind.integer),
        FieldSpec('max_minutes', 'Maximum minutes', kind: FieldKind.integer),
        FieldSpec('scheduled_minutes', 'Scheduled minutes', kind: FieldKind.integer),
        FieldSpec('is_paid', 'Paid', kind: FieldKind.toggle),
        FieldSpec('is_mandatory', 'Mandatory', kind: FieldKind.toggle),
        FieldSpec('allows_split', 'Can be split', kind: FieldKind.toggle),
      ])),
      const FieldSpec('duty_blocks', 'Duty blocks (split shifts)', kind: FieldKind.rows, rowNoun: 'block', orderKey: 'sequence', orderStart: 1, rowSpec: FormSpec(name: 'duty_block', label: 'Duty block', fields: [
        FieldSpec('start_time', 'Starts', kind: FieldKind.time, required: true),
        FieldSpec('end_time', 'Ends', kind: FieldKind.time, required: true),
      ])),
    ]);

ResourceConfig shiftResource() => ResourceConfig(
      title: 'Shifts',
      singular: 'Shift',
      path: '/shifts',
      spec: shiftIdentitySpec,
      rowTitle: (r) => r['name'] as String,
      rowSubtitle: (r) => _join([r['code'], r['current_version_id'] == null ? 'no published version' : null, r['draft_version_id'] != null ? 'draft pending' : null]),
      manage: orgShiftManage,
      versions: VersionsConfig(
        spec: shiftVersionSpec(),
        noun: 'shift version',
        summary: (v) => _join([prettyEnum('${v['shift_type'] ?? ''}'), v['start_time'] != null ? '${v['start_time']}–${v['end_time']}' : null]),
      ),
    );
