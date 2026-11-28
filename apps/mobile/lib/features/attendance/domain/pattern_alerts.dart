/// `GET /v1/attendance/pattern-alerts`: who keeps being late or absent. The server decides who is
/// flagged (thresholds live in the API settings); this file only parses and words it. Mirrors
/// `apps/web/src/lib/attendance/patterns.ts`.
class PatternThresholds {
  const PatternThresholds({required this.windowDays, required this.weekdayWindowDays, required this.lateDays, required this.absentDays, required this.incompleteDays, required this.weekdayAbsences});
  final int windowDays;
  final int weekdayWindowDays;
  final int lateDays;
  final int absentDays;
  final int incompleteDays;
  final int weekdayAbsences;

  factory PatternThresholds.fromJson(Map<String, dynamic> j) => PatternThresholds(
        windowDays: (j['window_days'] as num).toInt(),
        weekdayWindowDays: (j['weekday_window_days'] as num).toInt(),
        lateDays: (j['late_days'] as num).toInt(),
        absentDays: (j['absent_days'] as num).toInt(),
        incompleteDays: (j['incomplete_days'] as num).toInt(),
        weekdayAbsences: (j['weekday_absences'] as num).toInt(),
      );
}

const patternKindLabels = {
  'repeat_late': 'Often late',
  'frequent_absence': 'Often absent',
  'repeat_missing_punch': 'Missing punches',
  'repeat_absent_weekday': 'Absent on the same weekday',
};

const _weekdays = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday'];

class PatternAlert {
  const PatternAlert({required this.employeeId, required this.kind, required this.count, required this.dates, this.weekday});
  final String employeeId;
  final String kind;
  final int count;

  /// The days behind the alert, newest first (at most five).
  final List<String> dates;

  /// For `repeat_absent_weekday`: 0 = Monday … 6 = Sunday.
  final int? weekday;

  factory PatternAlert.fromJson(Map<String, dynamic> j) => PatternAlert(
        employeeId: j['employee_id'] as String,
        kind: j['kind'] as String,
        count: (j['count'] as num).toInt(),
        dates: ((j['dates'] as List?) ?? const []).cast<String>(),
        weekday: (j['weekday'] as num?)?.toInt(),
      );

  String get label => patternKindLabels[kind] ?? kind;

  /// The pattern in a few words, e.g. "late on 6 days in the last 30".
  String describe(PatternThresholds t) => switch (kind) {
        'repeat_late' => 'late on $count days in the last ${t.windowDays}',
        'frequent_absence' => 'absent on $count days in the last ${t.windowDays}',
        'repeat_missing_punch' => 'missing a punch on $count days in the last ${t.windowDays}',
        'repeat_absent_weekday' => 'absent on $count ${_weekdays[(weekday ?? 0).clamp(0, 6)]}s in the last ${t.weekdayWindowDays} days',
        _ => '$count times in the last ${t.windowDays} days',
      };
}

class PatternAlerts {
  const PatternAlerts({required this.asOf, required this.thresholds, required this.alerts});
  final String asOf;
  final PatternThresholds thresholds;
  final List<PatternAlert> alerts;

  factory PatternAlerts.fromJson(Map<String, dynamic> j) => PatternAlerts(
        asOf: j['as_of'] as String,
        thresholds: PatternThresholds.fromJson(j['thresholds'] as Map<String, dynamic>),
        alerts: [for (final a in (j['alerts'] as List? ?? const [])) PatternAlert.fromJson(a as Map<String, dynamic>)],
      );
}
