import '../../../core/time.dart';
import '../data/attendance_repository.dart' show Punch;

/// "Mark attendance": HR records a whole day (an IN and an OUT) for up to [markDayMaxEmployees]
/// employees. Mirrors `apps/web/src/components/attendance/mark-day-dialog.tsx` and the day-entry
/// types in `apps/web/src/lib/attendance/types.ts`
/// (`POST /attendance/punches/day-entries[/preview]`).
const markDayMaxEmployees = 50;

/// The server refuses a longer IN to OUT span.
const markDayMaxSpanHours = 20;

const markDayReasonPresets = ['Biometric device was offline', 'Forgot to punch', 'On-site / field work', 'App or network issue'];

/// Plain-language versions of the server's refusal codes. An unknown code falls back to the
/// server's own message.
const markDayBlockReasons = {
  'EXISTING_PUNCHES': 'Already has punches on this day. Fix it with Record punch instead.',
  'ATTENDANCE_PERIOD_CLOSED': 'The attendance period for this date is closed. Reopen it first.',
  'EMPLOYEE_TERMINATED': "This date is after the employee's last working day.",
  'PUNCH_TIME_BEFORE_EMPLOYMENT': 'This date is before the employee joined.',
  'PUNCH_TIME_IN_FUTURE': 'The time is in the future.',
  'NOT_FOUND': 'Not found, or outside the employees you manage.',
  'SELF_ENTRY_NOT_ALLOWED': "You can't mark your own attendance. Ask another HR admin, or raise a regularization.",
};

/// `READY` (preview only), `RECORDED` (both punches stored) or `BLOCKED` (nothing stored).
class ManualDayResult {
  const ManualDayResult({required this.employeeId, required this.outcome, this.code, this.message, this.replayed = false, this.existingPunches = const []});
  final String employeeId;
  final String outcome;
  final String? code;
  final String? message;
  final bool replayed;
  final List<Punch> existingPunches;

  bool get isReady => outcome == 'READY';
  bool get isBlocked => outcome == 'BLOCKED';

  factory ManualDayResult.fromJson(Map<String, dynamic> json) => ManualDayResult(
        employeeId: json['employee_id'] as String,
        outcome: json['outcome'] as String,
        code: json['code'] as String?,
        message: json['message'] as String?,
        replayed: json['replayed'] == true,
        existingPunches: [for (final p in (json['existing_punches'] as List?) ?? const []) Punch.fromJson(p as Map<String, dynamic>)],
      );

  /// Why this employee was skipped.
  String get blockReason => (code != null ? markDayBlockReasons[code] : null) ?? message ?? 'Could not be recorded.';
}

class ManualDayResponse {
  const ManualDayResponse({required this.readyCount, required this.recordedCount, required this.blockedCount, required this.results});
  final int readyCount;
  final int recordedCount;
  final int blockedCount;
  final List<ManualDayResult> results;

  factory ManualDayResponse.fromJson(Map<String, dynamic> json) => ManualDayResponse(
        readyCount: (json['ready_count'] as num?)?.toInt() ?? 0,
        recordedCount: (json['recorded_count'] as num?)?.toInt() ?? 0,
        blockedCount: (json['blocked_count'] as num?)?.toInt() ?? 0,
        results: [for (final r in (json['results'] as List?) ?? const []) ManualDayResult.fromJson(r as Map<String, dynamic>)],
      );
}

/// The two instants for a day: wall-clock times in the company zone, never the device's. An OUT at
/// or before the IN is the next day (an overnight shift).
class MarkDayInstants {
  const MarkDayInstants({required this.punchIn, required this.punchOut, required this.spanMinutes, required this.overnight, required this.outDate});
  final String punchIn;
  final String punchOut;
  final int spanMinutes;
  final bool overnight;
  final String outDate;
}

String _addDays(String date, int days) {
  final d = DateTime.parse(date);
  final n = DateTime.utc(d.year, d.month, d.day + days);
  return '${n.year.toString().padLeft(4, '0')}-${n.month.toString().padLeft(2, '0')}-${n.day.toString().padLeft(2, '0')}';
}

/// Null while a date or a time is missing or malformed.
MarkDayInstants? markDayInstants({required String date, required String inTime, required String outTime, required String zone}) {
  if (date.isEmpty || inTime.isEmpty || outTime.isEmpty) return null;
  try {
    final overnight = outTime.compareTo(inTime) <= 0;
    final outDate = overnight ? _addDays(date, 1) : date;
    final punchIn = wallTimeToUtcIso('${date}T$inTime', zone);
    final punchOut = wallTimeToUtcIso('${outDate}T$outTime', zone);
    final span = DateTime.parse(punchOut).difference(DateTime.parse(punchIn)).inMinutes;
    return MarkDayInstants(punchIn: punchIn, punchOut: punchOut, spanMinutes: span, overnight: overnight, outDate: outDate);
  } on FormatException {
    return null;
  }
}

/// The first thing wrong with the form, or null (web `validate`).
String? markDayProblem({
  required int selectedCount,
  required MarkDayInstants? instants,
  required String date,
  required String today,
  required String reason,
  required DateTime now,
}) {
  if (selectedCount == 0) return 'Choose at least one employee.';
  if (selectedCount > markDayMaxEmployees) return 'Choose at most $markDayMaxEmployees employees at a time.';
  if (instants == null) return 'Enter a date, an IN time and an OUT time.';
  if (date.compareTo(today) > 0) return "The date can't be in the future.";
  if (DateTime.parse(instants.punchOut).isAfter(now)) return "The OUT time hasn't happened yet. Record only the IN with Record punch, or wait.";
  if (instants.spanMinutes > markDayMaxSpanHours * 60) return 'IN to OUT can be at most $markDayMaxSpanHours hours.';
  if (reason.trim().length < 3) return 'Give a reason. It is saved with every punch and in the audit log.';
  return null;
}

/// "8h" or "8h 30m".
String formatMarkDaySpan(int minutes) {
  final h = minutes ~/ 60;
  final m = minutes % 60;
  return m == 0 ? '${h}h' : '${h}h ${m}m';
}

/// A day HR can mark present in one step: nothing was punched, and the day is not leave, a
/// holiday or a weekly off. Web `canMarkPresent`; a day with no record yet qualifies too.
bool canMarkPresent({required String? status, required String? firstIn, required String? lastOut, required bool hasRecord}) {
  if (!hasRecord) return true;
  return status == 'ABSENT' && firstIn == null && lastOut == null;
}
