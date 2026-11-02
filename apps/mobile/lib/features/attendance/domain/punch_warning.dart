import '../../../core/api/api_error.dart';

const punchTooSoonCode = 'PUNCH_TOO_SOON';
const punchAlreadyRecordedCode = 'PUNCH_ALREADY_RECORDED';

enum PunchWarningKind { tooSoon, alreadyRecorded }

/// The server's refusal of a punch that repeats the previous one: too soon after it, or in the
/// same direction. Nothing was recorded. It carries the previous punch so the app can say exactly
/// what happened; the sentences are built here.
class PunchWarning {
  const PunchWarning({
    required this.kind,
    required this.lastDirection,
    required this.lastPunchTime,
    this.retryAfterSeconds,
    this.minGapSeconds,
  });

  final PunchWarningKind kind;

  /// 'IN' or 'OUT': the direction of the employee's latest punch.
  final String lastDirection;
  final DateTime lastPunchTime;

  /// Too-soon only: seconds left when the server answered.
  final int? retryAfterSeconds;
  final int? minGapSeconds;

  bool get lastWasIn => lastDirection == 'IN';

  String get title => kind == PunchWarningKind.tooSoon ? 'Slow down — you just punched' : (lastWasIn ? "You're already punched in" : "You're already punched out");

  String get explanation => switch (kind) {
        PunchWarningKind.tooSoon => 'Punches must be at least ${_gapText(minGapSeconds ?? 120)} apart. This one was not recorded, so nothing has changed on your attendance.',
        PunchWarningKind.alreadyRecorded => lastWasIn
            ? 'Your last punch was a punch in. You need to punch out before you can punch in again. Nothing new was recorded.'
            : 'Your last punch was a punch out. You need to punch in before you can punch out again. Nothing new was recorded.',
      };

  static String _gapText(int seconds) => seconds % 60 == 0 ? '${seconds ~/ 60} minute${seconds == 60 ? '' : 's'}' : '$seconds seconds';

  /// The refusal in [error], or null when it is some other error (or its details are unreadable).
  static PunchWarning? fromError(Object error) {
    if (error is! ApiError || (error.code != punchTooSoonCode && error.code != punchAlreadyRecordedCode)) return null;
    for (final detail in error.details) {
      final c = detail.context;
      if (c == null) continue;
      try {
        return PunchWarning(
          kind: error.code == punchTooSoonCode ? PunchWarningKind.tooSoon : PunchWarningKind.alreadyRecorded,
          lastDirection: c['last_direction'] as String,
          lastPunchTime: DateTime.parse(c['last_punch_time'] as String).toLocal(),
          retryAfterSeconds: c['retry_after_seconds'] as int?,
          minGapSeconds: c['min_gap_seconds'] as int?,
        );
      } on Object {
        return null;
      }
    }
    return null;
  }
}
