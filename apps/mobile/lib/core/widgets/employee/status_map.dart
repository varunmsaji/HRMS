import 'package:flutter/material.dart';

import '../../theme/app_colors.dart';
import '../../theme/employee_tokens.dart';
import '../ui.dart';

/// The kinds of status the employee surface shows. Each has a fill, a glyph/border colour, a
/// text colour that passes AA on the fill, and a glyph so colour is never the only signal.
enum StatusKind { success, warning, danger, info, onLeave, holiday, wfh, neutral }

typedef EmployeeStatus = ({StatusKind kind, String label, IconData glyph});

IconData glyphFor(StatusKind kind) => switch (kind) {
      StatusKind.success => Icons.check_rounded,
      StatusKind.warning => Icons.schedule_rounded,
      StatusKind.danger => Icons.close_rounded,
      StatusKind.info => Icons.work_outline_rounded,
      StatusKind.onLeave => Icons.event_busy_outlined,
      StatusKind.holiday || StatusKind.neutral => Icons.circle,
      StatusKind.wfh => Icons.home_outlined,
    };

EmployeeStatus _s(StatusKind kind, String label) => (kind: kind, label: label, glyph: glyphFor(kind));

/// The one mapping from an attendance bucket (`attendanceBucketOf`) to a status.
EmployeeStatus statusForAttendanceBucket(String bucket) => switch (bucket) {
      'PRESENT' => _s(StatusKind.success, 'Present'),
      'REMOTE' => _s(StatusKind.wfh, 'Work from home'),
      'ON_DUTY' => _s(StatusKind.info, 'On duty'),
      'HALF_DAY' => _s(StatusKind.warning, 'Half day'),
      'ABSENT' => _s(StatusKind.danger, 'Absent'),
      'LEAVE' => _s(StatusKind.onLeave, 'On leave'),
      'INCOMPLETE' => _s(StatusKind.warning, 'Incomplete'),
      'CONFIG_ERROR' => _s(StatusKind.danger, 'Needs attention'),
      'HOLIDAY' => _s(StatusKind.holiday, 'Holiday'),
      'WEEKLY_OFF' => _s(StatusKind.holiday, 'Weekly off'),
      'NOT_EMPLOYED' => _s(StatusKind.neutral, 'Not employed'),
      _ => _s(StatusKind.holiday, 'Non-working day'),
    };

/// The one mapping from a request status (leave application, correction, overtime) to a status.
/// "Cancelled" is neutral, not danger: the employee chose it.
EmployeeStatus statusForRequest(String status, {Map<String, String> labels = const {}}) {
  final code = status.toUpperCase();
  final kind = switch (code) {
    'SUBMITTED' || 'PENDING' || 'PENDING_APPROVAL' || 'DRAFT' => StatusKind.warning,
    'APPROVED' || 'AUTO_APPROVED' || 'COMPLETED' || 'COMPLETE' => StatusKind.success,
    'REJECTED' || 'FAILED' => StatusKind.danger,
    'CANCELLED' || 'CANCELED' || 'WITHDRAWN' => StatusKind.holiday,
    _ => StatusKind.neutral,
  };
  final label = labels[status] ?? (code == 'AUTO_APPROVED' ? 'Auto-approved' : humanize(status));
  return _s(kind, label);
}

/// Fill, glyph and text colours of a [StatusKind] for the active theme.
({Color fill, Color glyph, Color text}) statusColors(BuildContext context, StatusKind kind) {
  final theme = Theme.of(context);
  final status = theme.extension<AppStatusColors>() ?? AppStatusColors.light;
  final t = EmployeeTokens.of(context);
  return switch (kind) {
    StatusKind.success => (fill: status.successSubtle, glyph: status.success, text: t.successText),
    StatusKind.warning => (fill: status.warningSubtle, glyph: status.warning, text: t.warningText),
    StatusKind.danger => (fill: status.dangerSubtle, glyph: status.danger, text: t.dangerText),
    StatusKind.info => (fill: status.infoSubtle, glyph: status.info, text: t.infoText),
    StatusKind.onLeave => (fill: status.onLeaveSubtle, glyph: status.onLeave, text: t.onLeaveText),
    StatusKind.holiday => (fill: status.holidaySubtle, glyph: status.holiday, text: t.holidayText),
    StatusKind.wfh => (fill: status.wfhSubtle, glyph: status.wfh, text: t.wfhText),
    StatusKind.neutral => (fill: t.inset, glyph: t.inkTertiary, text: t.inkSecondary),
  };
}
