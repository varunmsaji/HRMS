import '../../../core/api/api_error.dart';

const outsideShiftWindowCode = 'OUTSIDE_SHIFT_WINDOW';

/// The server's refusal of a punch-in that is too early for the employee's shift. It carries only
/// the shift times and the policy values; the app builds the sentence itself.
class OutsideShiftWindow {
  const OutsideShiftWindow({
    required this.shiftStart,
    required this.shiftEnd,
    required this.graceInMinutes,
    required this.graceOutMinutes,
    required this.earlyInAllowanceMinutes,
    required this.earliestPunchIn,
  });

  final DateTime shiftStart;
  final DateTime shiftEnd;
  final int graceInMinutes;
  final int graceOutMinutes;
  final int earlyInAllowanceMinutes;
  final DateTime earliestPunchIn;

  /// The refusal in [error], or null when it is some other error (or its details are unreadable).
  static OutsideShiftWindow? fromError(Object error) {
    if (error is! ApiError || error.code != outsideShiftWindowCode) return null;
    for (final detail in error.details) {
      final c = detail.context;
      if (c == null) continue;
      try {
        return OutsideShiftWindow(
          shiftStart: DateTime.parse(c['shift_start'] as String).toLocal(),
          shiftEnd: DateTime.parse(c['shift_end'] as String).toLocal(),
          graceInMinutes: c['grace_in_minutes'] as int,
          graceOutMinutes: c['grace_out_minutes'] as int,
          earlyInAllowanceMinutes: c['early_in_allowance_minutes'] as int,
          earliestPunchIn: DateTime.parse(c['earliest_punch_in'] as String).toLocal(),
        );
      } on Object {
        return null;
      }
    }
    return null;
  }

  /// "You can't punch in yet. Your shift starts at 9:30 AM, and you can punch in from 8:30 AM."
  /// [formatTime] renders a local time in the user's locale and clock preference.
  String message(String Function(DateTime) formatTime) =>
      "You can't punch in yet. Your shift starts at ${formatTime(shiftStart)}, "
      'and you can punch in from ${formatTime(earliestPunchIn)}.';
}
