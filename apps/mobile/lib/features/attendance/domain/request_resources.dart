import '../../../core/auth/permissions.dart';
import '../../../core/forms/form_spec.dart';
import '../../../core/requests/request_config.dart';
import '../../../core/time.dart';

/// Regularization requests and overtime records — the attendance module's approval workflows,
/// configured on the shared request framework. Mirrors `apps/web/src/app/app/{regularizations,overtime}`.

const regularizationTypeLabels = {
  'MISSING_PUNCH': 'Missing punch',
  'WRONG_PUNCH': 'Wrong punch time',
  'WRONG_SHIFT': 'Wrong shift',
  'WRONG_STATUS': 'Wrong status',
  'WFH': 'Work from home',
  'ON_DUTY': 'On duty',
  'EXCESS_BREAK': 'Excess break',
  'FULL_DAY': 'Full day correction',
  'EARLY_DEPARTURE_APPROVAL': 'Early departure pre-approval',
};

const requestStatusLabels = {'SUBMITTED': 'Submitted', 'APPROVED': 'Approved', 'REJECTED': 'Rejected', 'CANCELLED': 'Cancelled'};

String _s(Map<String, dynamic> r, String k) => (r[k] ?? '—').toString();

/// UI-only `correct_shift` chooses between correcting punch times and correcting the shift; it is
/// never sent. At least one corrected punch time (or a shift) is needed whatever the policy says.
Map<String, String> _validateRegularization(Map<String, dynamic> v) {
  String t(String k) => ((v[k] ?? '') as String).trim();
  final errors = <String, String>{};
  if (v['correct_shift'] == true) {
    if (t('requested_shift_id').isEmpty) errors['requested_shift_id'] = 'Choose the correct shift.';
  } else if (t('punch_in_time').isEmpty && t('punch_out_time').isEmpty) {
    errors['punch_in_time'] = 'Enter at least one corrected punch time.';
  }
  return errors;
}

FormSpec regularizationSpec(bool onBehalf) => FormSpec(
      name: 'regularization',
      label: 'Regularization request',
      extraValidate: _validateRegularization,
      fields: [
        if (onBehalf) const FieldSpec('employee_id', 'Employee', kind: FieldKind.choice, choiceKey: 'employees', required: true),
        const FieldSpec('attendance_date', 'Attendance date', kind: FieldKind.date, required: true),
        const FieldSpec('request_type', 'Request type', kind: FieldKind.select, required: true, options: ['MISSING_PUNCH', 'WRONG_PUNCH', 'WRONG_SHIFT', 'WRONG_STATUS', 'WFH', 'ON_DUTY', 'EXCESS_BREAK', 'FULL_DAY', 'EARLY_DEPARTURE_APPROVAL'], optionLabels: regularizationTypeLabels),
        const FieldSpec('correct_shift', 'Correct the assigned shift instead of punch times', kind: FieldKind.toggle),
        const FieldSpec('requested_shift_id', 'Correct shift', kind: FieldKind.choice, choiceKey: 'shifts', showWhen: 'correct_shift'),
        const FieldSpec('punch_in_time', 'Check-in time', kind: FieldKind.time, showWhen: '!correct_shift'),
        const FieldSpec('punch_out_time', 'Check-out time', kind: FieldKind.time, showWhen: '!correct_shift'),
        const FieldSpec('reason', 'Reason', kind: FieldKind.multiline),
        const FieldSpec('attachment_reference', 'Attachment reference'),
      ],
    );

/// The form payload as the API body. Punch times are wall-clock in the *company* zone and sent as
/// UTC instants (TZ-06) — never the device's zone.
Map<String, dynamic> buildRegularizationBody(Map<String, dynamic> p, String zone) {
  final date = p['attendance_date'] as String;
  String? instant(String? time) => time == null ? null : wallTimeToUtcIso('${date}T$time', zone);
  final inTime = instant(p['punch_in_time'] as String?);
  final outTime = instant(p['punch_out_time'] as String?);
  return {
    'attendance_date': date,
    'request_type': p['request_type'],
    if (p['employee_id'] != null) 'employee_id': p['employee_id'],
    if (p['reason'] != null) 'reason': p['reason'],
    if (p['attachment_reference'] != null) 'attachment_reference': p['attachment_reference'],
    if (p['correct_shift'] == true)
      'requested_shift_id': p['requested_shift_id']
    else
      'requested_punches': [
        if (inTime != null) {'direction': 'IN', 'requested_time': inTime},
        if (outTime != null) {'direction': 'OUT', 'requested_time': outTime},
      ],
  };
}

List<DetailSection> _regularizationSections(Map<String, dynamic> r, String tz) {
  final punches = ((r['requested_punches'] as List?) ?? const []).cast<Map<String, dynamic>>();
  final actions = ((r['actions'] as List?) ?? const []).cast<Map<String, dynamic>>();
  return [
    DetailSection('Request', [
      ('Attendance date', _s(r, 'attendance_date')),
      ('Type', regularizationTypeLabels[r['request_type']] ?? _s(r, 'request_type')),
      ('Reason', _s(r, 'reason')),
      ('Attachment reference', _s(r, 'attachment_reference')),
      ('Approval chain', prettyEnum(_s(r, 'approval_chain'))),
      ('Approval stage', prettyEnum(_s(r, 'approval_stage'))),
      ('Submitted at', formatDateTime(r['submitted_at'] as String?, tz)),
    ]),
    if (punches.isNotEmpty) DetailSection('Requested punches', const [], lines: [for (final p in punches) '${p['direction']} · ${formatDateTime(p['requested_time'] as String?, tz)}']),
    if (r['status'] != 'SUBMITTED')
      DetailSection('Outcome', [
        ('Reviewed at', formatDateTime(r['reviewed_at'] as String?, tz)),
        ('Reviewer comment', _s(r, 'reviewer_comment')),
        ('Rejection reason', _s(r, 'rejection_reason')),
        if (r['applied_at'] != null) ('Applied to attendance at', formatDateTime(r['applied_at'] as String?, tz)),
        if (r['cancelled_at'] != null) ('Cancelled at', formatDateTime(r['cancelled_at'] as String?, tz)),
      ]),
    if (actions.isNotEmpty)
      DetailSection('History', const [], lines: [
        for (final a in actions) '${prettyEnum('${a['action']}')}${a['stage'] != null ? ' · ${a['stage']}' : ''} — ${formatDateTime(a['created_at'] as String?, tz)}${a['comment'] != null ? '\n${a['comment']}' : ''}',
      ]),
  ];
}

final regularizationConfig = RequestConfig(
  title: 'Regularizations',
  singular: 'Regularization request',
  path: '/regularizations',
  statuses: const ['SUBMITTED', 'APPROVED', 'REJECTED', 'CANCELLED'],
  statusLabels: requestStatusLabels,
  statusParam: 'request_status',
  filters: [
    RequestFilter(param: 'request_type', label: 'Type', options: [for (final e in regularizationTypeLabels.entries) (e.key, e.value)]),
  ],
  approvePermission: attendanceRegularizationApprove,
  submitPermission: attendanceRegularizationRequest,
  onBehalfPermission: attendanceRegularizationRequestOnBehalf,
  rowTitle: (r, who) => '${who.isEmpty ? '' : '$who · '}${regularizationTypeLabels[r['request_type']] ?? r['request_type']} · ${r['attendance_date']}',
  rowSubtitle: (r) => r['reason'] as String?,
  createSpec: regularizationSpec,
  // `GET /shifts` needs ORG.SHIFT.MANAGE, which an employee does not hold: optional, so a 403 only
  // disables the "correct the shift" option (docs/design/employee-mobile/T3-03_SHIFTS_DEPENDENCY.md).
  optionalChoiceKeys: const ['shifts'],
  buildCreateBody: buildRegularizationBody,
  sections: _regularizationSections,
  isPending: (r) => r['status'] == 'SUBMITTED' && r['approval_stage'] != null,
  canCancel: (r, user) => r['status'] == 'SUBMITTED' && r['submitted_by_user_id'] == user.id,
  selfApprovalCode: 'REGULARIZATION_SELF_APPROVAL_NOT_ALLOWED',
  approverMismatchCode: 'REGULARIZATION_APPROVER_MISMATCH',
);

// ---- overtime ---------------------------------------------------------------------------------

List<DetailSection> _overtimeSections(Map<String, dynamic> r, String tz) {
  final actions = ((r['actions'] as List?) ?? const []).cast<Map<String, dynamic>>();
  return [
    DetailSection('Overtime', [
      ('Attendance date', _s(r, 'attendance_date')),
      ('Day class', prettyEnum(_s(r, 'day_class'))),
      ('Classification', _s(r, 'classification_code')),
      ('Configured multiplier', _s(r, 'configured_multiplier')),
      ('Minutes detected', formatMinutes(r['minutes_detected'] as int?)),
      ('Minutes approved', formatMinutes(r['minutes_approved'] as int?)),
      if ((r['comp_off_minutes'] as int? ?? 0) > 0) ('Comp-off earned', formatMinutes(r['comp_off_minutes'] as int?)),
      if (r['comp_off_expiry_date'] != null) ('Comp-off expires', _s(r, 'comp_off_expiry_date')),
    ]),
    DetailSection('Approval', [
      ('Approval chain', prettyEnum(_s(r, 'approval_chain'))),
      ('Approval stage', prettyEnum(_s(r, 'approval_stage'))),
      if (r['status'] != 'PENDING') ...[
        ('Reviewed at', formatDateTime(r['reviewed_at'] as String?, tz)),
        ('Reviewer comment', _s(r, 'reviewer_comment')),
        ('Rejection reason', _s(r, 'rejection_reason')),
      ],
    ]),
    if (actions.isNotEmpty)
      DetailSection('History', const [], lines: [
        for (final a in actions) '${prettyEnum('${a['action']}')}${a['stage'] != null ? ' · ${a['stage']}' : ''} — ${formatDateTime(a['created_at'] as String?, tz)}${a['comment'] != null ? '\n${a['comment']}' : ''}',
      ]),
  ];
}

final overtimeConfig = RequestConfig(
  title: 'Overtime',
  singular: 'Overtime record',
  path: '/overtime',
  statuses: const ['PENDING', 'AUTO_APPROVED', 'APPROVED', 'REJECTED'],
  statusParam: 'record_status',
  approvePermission: attendanceOvertimeApprove,
  rowTitle: (r, who) => '${who.isEmpty ? '' : '$who · '}${r['attendance_date']}',
  rowSubtitle: (r) => 'Detected ${formatMinutes(r['minutes_detected'] as int?)}${(r['minutes_approved'] as int? ?? 0) > 0 ? ' · approved ${formatMinutes(r['minutes_approved'] as int?)}' : ''}',
  sections: _overtimeSections,
  isPending: (r) => r['status'] == 'PENDING',
  selfApprovalCode: 'OVERTIME_SELF_APPROVAL_NOT_ALLOWED',
  approverMismatchCode: 'OVERTIME_APPROVER_MISMATCH',
  // The manager step of a two-step chain only passes it on; the final approver sets the minutes.
  editableMinutes: (r) => r['approval_chain'] == 'MANAGER_THEN_HR' && r['approval_stage'] == 'MANAGER' ? null : r['minutes_detected'] as int?,
);
