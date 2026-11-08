import '../../../core/auth/permissions.dart';
import '../../../core/forms/form_spec.dart';
import '../../../core/resource/resource_config.dart';
import '../../../core/time.dart';
import '../presentation/face_enrollment_policy_card.dart';
import '../presentation/shift_delete_screen.dart' show openShiftDelete;
import '../presentation/policy_followers_section.dart' show followersFooter;

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
  FieldSpec('grace_in_minutes', 'Late arrival grace (minutes)', kind: FieldKind.integer),
  FieldSpec('grace_out_minutes', 'Early leaving grace (minutes)', kind: FieldKind.integer),
  FieldSpec('early_in_allowance_minutes', 'Earliest punch-in before shift start (minutes)', kind: FieldKind.integer),
  FieldSpec('punch_rounding', 'Punch rounding', kind: FieldKind.select, options: _roundings),
  FieldSpec('rounding_minutes', 'Rounding step (minutes)', kind: FieldKind.integer),
  FieldSpec('missing_punch_behaviour', 'When a punch in or out is missing', kind: FieldKind.select, options: ['INCOMPLETE', 'ABSENT', 'AUTO_CLOSE', 'REQUIRE_REGULARIZATION']),
  FieldSpec('auto_close_after_minutes', 'Auto-close after (minutes)', kind: FieldKind.integer),
  FieldSpec('auto_close_uses_shift_end', 'Auto-close at shift end', kind: FieldKind.toggle),
  FieldSpec('missing_shift_behaviour', 'When no shift can be worked out and no punches exist', kind: FieldKind.select, options: ['INCOMPLETE', 'ABSENT']),
  FieldSpec('half_day_split', 'Half-day split', kind: FieldKind.select, options: ['BY_HOURS', 'BY_MIDPOINT']),
  FieldSpec('half_day_boundary_minutes', 'Half-day boundary (minutes)', kind: FieldKind.integer),
  FieldSpec('multi_punch_mode', 'When someone punches several times a day', kind: FieldKind.select, options: ['PAIR_ALL', 'FIRST_IN_LAST_OUT']),
  FieldSpec('duplicate_punch_window_seconds', 'Treat repeat punches as one within (seconds)', kind: FieldKind.integer),
  FieldSpec('core_hours_breach_behaviour', 'Flexible shifts: missing core hours', kind: FieldKind.select, options: ['IGNORE', 'FLAG', 'HALF_DAY', 'ABSENT']),
  FieldSpec('early_out_uses_core_end', 'Early departure measured from core end', kind: FieldKind.toggle),
  FieldSpec('split_shift_block_mandatory', 'Every split-shift block is mandatory', kind: FieldKind.toggle),
  FieldSpec('split_shift_missed_block_behaviour', 'Split shifts: no punch in one block', kind: FieldKind.select, options: ['IGNORE', 'HALF_DAY', 'ABSENT', 'REQUIRE_REGULARIZATION']),
  FieldSpec('split_shift_allow_hours_compensation', 'Allow hours compensation across blocks', kind: FieldKind.toggle),
  FieldSpec('wfh_requires_punch', 'Work-from-home needs a punch', kind: FieldKind.toggle),
  FieldSpec('on_duty_requires_punch', 'On-duty days still need punches', kind: FieldKind.toggle, hint: 'Off: on-duty day fully paid, no overtime'),
  FieldSpec('wfh_uses_shift_hours', 'Work-from-home uses shift hours', kind: FieldKind.toggle),
  FieldSpec('work_on_leave_behaviour', 'Work on a leave day', kind: FieldKind.select, options: ['KEEP_LEAVE', 'PRESENT_CANCEL_LEAVE_HINT']),
  FieldSpec('excess_break_behaviour', 'Excess break', kind: FieldKind.select, options: ['IGNORE', 'DEDUCT', 'FLAG', 'REQUIRE_APPROVAL']),
  FieldSpec('late_count_window', 'Late-count window', kind: FieldKind.select, options: ['MONTH']),
  FieldSpec('lates_to_half_day_count', 'Late days before a half-day (per month)', kind: FieldKind.integer),
  FieldSpec('early_departure_requires_approval', 'Leaving early needs approval', kind: FieldKind.toggle),
  FieldSpec('excess_break_count_window', 'Excess-break count window', kind: FieldKind.select, options: ['MONTH']),
  FieldSpec('excess_break_days_to_half_day_count', 'Long-break days before a half-day (per month)', kind: FieldKind.integer),
  FieldSpec('geofence_mode', 'Location check', kind: FieldKind.select, options: ['DISABLED', 'OPTIONAL', 'REQUIRED'], optionLabels: geofenceModeLabels),
  FieldSpec('geofence_max_accuracy_m', 'Worst acceptable GPS accuracy (metres)', kind: FieldKind.integer, hint: '5-500', showWhen: 'geofence_mode!=DISABLED'),
  FieldSpec('geofence_max_age_seconds', 'Oldest acceptable reading (seconds)', kind: FieldKind.integer, hint: '5-300', showWhen: 'geofence_mode!=DISABLED'),
  FieldSpec('incomplete_at_lock_behaviour', 'Days still incomplete when the month closes', kind: FieldKind.select, options: ['TREAT_ABSENT', 'TREAT_PRESENT', 'KEEP_INCOMPLETE']),
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
  // As on web: the company's face-enrollment requirement sits above the attendance policies.
  listHeader: (context) => const FaceEnrollmentPolicyCard(),
  versions: VersionsConfig(
    spec: attendancePolicyVersionSpec,
    noun: 'policy version',
    summary: (v) => 'Grace ${v['grace_in_minutes']}/${v['grace_out_minutes']} min · ${prettyEnum('${v['missing_punch_behaviour']}')}',
  ),
  detailFooter: followersFooter('ATTENDANCE_POLICY', manage: attendancePolicyManage, versionsPath: '/attendance-policies'),
);

// ---- overtime policy --------------------------------------------------------------------------

const overtimePolicyIdentitySpec = FormSpec(name: 'overtime_policy', label: 'Overtime policy', fields: [
  FieldSpec('name', 'Name', required: true),
  _active,
]);

const overtimePolicyVersionSpec = FormSpec(name: 'overtime_policy_version', label: 'Overtime policy version', fields: [
  FieldSpec('effective_from', 'Effective from', kind: FieldKind.date),
  FieldSpec('eligibility', 'Who can earn overtime', kind: FieldKind.select, options: ['SHIFT_FLAG', 'ALWAYS', 'NEVER', 'GRADE_VIA_ASSIGNMENT']),
  FieldSpec('min_ot_minutes', 'Minimum overtime (minutes)', kind: FieldKind.integer),
  FieldSpec('rounding_mode', 'Round overtime', kind: FieldKind.select, options: _roundings),
  FieldSpec('rounding_minutes', 'Round to (minutes)', kind: FieldKind.integer),
  FieldSpec('requires_pre_approval', 'Needs approval before the work', kind: FieldKind.toggle),
  FieldSpec('requires_post_approval', 'Approve after the overtime is worked', kind: FieldKind.toggle),
  FieldSpec('daily_cap_minutes', 'Limit per day (minutes)', kind: FieldKind.integer),
  FieldSpec('weekly_cap_minutes', 'Limit per week (minutes)', kind: FieldKind.integer, hint: 'Counts approved and waiting overtime'),
  FieldSpec('monthly_cap_minutes', 'Limit per month (minutes)', kind: FieldKind.integer, hint: 'Counts approved and waiting overtime'),
  FieldSpec('comp_off_instead_of_pay', 'Give comp-off days instead of paying overtime', kind: FieldKind.toggle),
  FieldSpec('comp_off_expiry_days', 'Days to use a comp-off', kind: FieldKind.integer),
  FieldSpec('comp_off_day_length_minutes', 'Minutes that make one comp-off day', kind: FieldKind.integer),
  FieldSpec('night_ot_mode', 'What counts as night overtime', kind: FieldKind.select, options: ['SHIFT_FLAG', 'WINDOW', 'BOTH']),
  FieldSpec('night_window_start', 'Night starts', kind: FieldKind.time),
  FieldSpec('night_window_end', 'Night ends', kind: FieldKind.time),
  FieldSpec('approval_chain', 'Who approves overtime', kind: FieldKind.select, options: _approvalChains),
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
  detailFooter: followersFooter('OVERTIME_POLICY', manage: attendancePolicyManage, versionsPath: '/overtime-policies'),
);

// ---- regularization policy --------------------------------------------------------------------

const regularizationPolicyIdentitySpec = FormSpec(name: 'regularization_policy', label: 'Correction policy', fields: [
  FieldSpec('name', 'Name', required: true),
  _active,
]);

const regularizationTypes = ['MISSING_PUNCH', 'WRONG_PUNCH', 'WRONG_SHIFT', 'WRONG_STATUS', 'WFH', 'ON_DUTY', 'EXCESS_BREAK', 'FULL_DAY'];

const regularizationPolicyVersionSpec = FormSpec(name: 'regularization_policy_version', label: 'Regularization policy version', fields: [
  FieldSpec('effective_from', 'Effective from', kind: FieldKind.date),
  FieldSpec('allow_employee_request', 'Employees can ask for themselves', kind: FieldKind.toggle),
  FieldSpec('allow_manager_request', 'Managers can ask for their team', kind: FieldKind.toggle),
  FieldSpec('allow_hr_request', 'HR can ask for anyone', kind: FieldKind.toggle),
  FieldSpec('max_backdated_days', 'How many days back a correction can reach', kind: FieldKind.integer),
  FieldSpec('max_requests_per_month', 'Requests per person per month', kind: FieldKind.integer),
  FieldSpec('reason_required', 'The requester must give a reason', kind: FieldKind.toggle),
  FieldSpec('attachment_required', 'The requester must attach proof', kind: FieldKind.toggle),
  FieldSpec('approval_chain', 'Who approves corrections', kind: FieldKind.select, options: _approvalChains),
  FieldSpec('auto_approve_within_minutes', 'Auto-approve within (minutes)', kind: FieldKind.integer),
  FieldSpec('blocked_when_locked', 'Refuse corrections for days that have been locked', kind: FieldKind.toggle),
  FieldSpec('allowed_types', 'Allowed request types', kind: FieldKind.rows, rowNoun: 'type', orderKey: 'sort_order', rowSpec: FormSpec(name: 'allowed_type', label: 'Allowed type', fields: [
    FieldSpec('regularization_type', 'Type', kind: FieldKind.select, required: true, options: regularizationTypes),
  ])),
]);

final regularizationPolicyResource = ResourceConfig(
  title: 'Correction Policies',
  singular: 'Correction policy',
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
  detailFooter: followersFooter('REGULARIZATION_POLICY', manage: attendancePolicyManage, versionsPath: '/regularization-policies'),
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
      const FieldSpec('window_start', 'Window start', kind: FieldKind.time),
      const FieldSpec('window_end', 'Window end', kind: FieldKind.time),
      const FieldSpec('core_start', 'Core hours start', kind: FieldKind.time),
      const FieldSpec('core_end', 'Core hours end', kind: FieldKind.time),
      const FieldSpec('required_minutes', 'Required minutes', kind: FieldKind.integer),
      const FieldSpec('scheduled_minutes', 'Scheduled minutes', kind: FieldKind.integer),
      const FieldSpec('min_scheduled_minutes', 'Min scheduled minutes', kind: FieldKind.integer),
      const FieldSpec('max_scheduled_minutes', 'Max scheduled minutes', kind: FieldKind.integer),
      const FieldSpec('is_night_shift', 'Night shift', kind: FieldKind.toggle),
      const FieldSpec('is_ot_eligible', 'Overtime eligible', kind: FieldKind.toggle),
      const FieldSpec('operates_on_holiday', 'Operates on holidays', kind: FieldKind.toggle),
      const FieldSpec('operates_on_weekly_off', 'Operates on weekly offs', kind: FieldKind.toggle),
      const FieldSpec('weekly_off_pattern_id', 'Shift-specific weekly-off pattern', kind: FieldKind.choice, choiceKey: 'weekly_off_patterns'),
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
      // Web's permanent delete: in-use check, typed name, reason and acknowledgement.
      guardedDelete: openShiftDelete,
      versions: VersionsConfig(
        spec: shiftVersionSpec(),
        noun: 'shift version',
        summary: (v) => _join([prettyEnum('${v['shift_type'] ?? ''}'), v['start_time'] != null ? '${v['start_time']}–${v['end_time']}' : null]),
      ),
    );
