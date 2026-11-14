import '../data/attendance_repository.dart';
import '../presentation/attendance_summary.dart' show attendanceBucketOf;
import 'attendance_insights.dart';

/// Helpers for the attendance insights screen: the fetch window, the day buckets the per-person
/// views use, weekday names and the attendance-period helpers. The dashboard's totals (rate, KPIs,
/// distribution, punctuality, weekday pattern, department / branch breakdown) are the backend's,
/// from `GET /v1/attendance/summary` (see `attendance_totals.dart`); nothing here re-counts them.

// ---- window ------------------------------------------------------------------------------------

/// Trends and patterns need context: never fewer than this many days (web `MIN_CONTEXT_DAYS`).
const minContextDays = 14;

/// The span fetched: the range widened to at least [minContextDays] (web `windowRange`).
({String from, String to}) windowRangeIso(String from, String to) {
  final contextFrom = addDaysIso(to, -(minContextDays - 1));
  return (from: from.compareTo(contextFrom) < 0 ? from : contextFrom, to: to);
}

List<AttendanceDay> rowsOn(List<AttendanceDay> rows, String date) => [for (final d in rows) if (d.attendanceDate == date) d];

List<AttendanceDay> rowsBetween(List<AttendanceDay> rows, String from, String to) =>
    [for (final d in rows) if (d.attendanceDate.compareTo(from) >= 0 && d.attendanceDate.compareTo(to) <= 0) d];

// ---- buckets -----------------------------------------------------------------------------------

/// Web `DAY_BUCKETS` order and `BUCKET_LABELS` wording.
const dayBucketLabels = {
  'PRESENT': 'Present',
  'REMOTE': 'Remote (WFH)',
  'ON_DUTY': 'On duty',
  'HALF_DAY': 'Half day',
  'ABSENT': 'Absent',
  'LEAVE': 'On leave',
  'INCOMPLETE': 'Incomplete',
  'CONFIG_ERROR': 'Config error',
  'HOLIDAY': 'Holiday',
  'WEEKLY_OFF': 'Weekly off',
  'NON_WORKING': 'Other non-working',
  'NOT_EMPLOYED': 'Not employed',
};

const _attendingBuckets = {'PRESENT', 'REMOTE', 'ON_DUTY'};
const _notExpectedBuckets = {'NOT_EMPLOYED', 'HOLIDAY', 'WEEKLY_OFF', 'NON_WORKING'};

bool isAttendingBucket(String bucket) => _attendingBuckets.contains(bucket);

/// Expected to work — the denominator of every rate, so a weekend does not drag a rate down.
bool isExpectedBucket(String bucket) => !_notExpectedBuckets.contains(bucket);

int _int(AttendanceDay d, String key) => (d.raw[key] as num?)?.toInt() ?? 0;
bool _flag(AttendanceDay d, String key) => d.raw[key] == true;

int lateMinutesOf(AttendanceDay d) => d.lateMinutes ?? _int(d, 'late_minutes');
bool _checkedIn(AttendanceDay d) => d.actualFirstIn != null;

/// Expected to work but no IN punch (zero-punch ABSENT, or INCOMPLETE with no IN).
bool isNotCheckedIn(AttendanceDay d) {
  final b = attendanceBucketOf(d);
  return (b == 'ABSENT' || b == 'INCOMPLETE') && !_checkedIn(d);
}

bool hasException(AttendanceDay d) =>
    _flag(d, 'missing_punch') || d.attendanceStatus == 'CONFIG_ERROR' || _flag(d, 'is_pending_approval') || workOnLeaveUnresolved(d);

// ---- weekdays ----------------------------------------------------------------------------------

String sameWeekdayLastWeek(String date) => addDaysIso(date, -7);

const _weekdays = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'];

/// 0 = Monday … 6 = Sunday.
int weekdayIndexIso(String iso) => DateTime.utc(int.parse(iso.substring(0, 4)), int.parse(iso.substring(5, 7)), int.parse(iso.substring(8, 10))).weekday - 1;

String weekdayShort(String iso) => _weekdays[weekdayIndexIso(iso)];

// ---- attendance periods ------------------------------------------------------------------------

/// The period to show by default: the one covering [today], else the most recent (web
/// `pickDefaultPeriod`).
Map<String, dynamic>? pickDefaultPeriod(List<Map<String, dynamic>> periods, String today) {
  if (periods.isEmpty) return null;
  for (final p in periods) {
    if ('${p['period_start']}'.compareTo(today) <= 0 && today.compareTo('${p['period_end']}') <= 0) return p;
  }
  return ([...periods]..sort((a, b) => '${b['period_start']}'.compareTo('${a['period_start']}'))).first;
}

/// The period's title: its label, else its dates.
String periodTitle(Map<String, dynamic> p) => (p['label'] as String?)?.trim().isNotEmpty == true ? p['label'] as String : '${shortDate('${p['period_start']}')} – ${shortDate('${p['period_end']}')}';

class PeriodProgress {
  const PeriodProgress(this.totalDays, this.elapsedDays, this.daysLeft);
  final int totalDays;
  final int elapsedDays;

  /// 0 = ends today; negative once it has ended.
  final int daysLeft;
  double get fraction => totalDays > 0 ? elapsedDays / totalDays : 0;
}

PeriodProgress periodProgress(Map<String, dynamic> p, String today) {
  final start = '${p['period_start']}';
  final end = '${p['period_end']}';
  final total = dayDiffIso(start, end) + 1;
  final elapsed = (dayDiffIso(start, today) + 1).clamp(0, total);
  return PeriodProgress(total, elapsed, dayDiffIso(today, end));
}

/// Web `countdown` wording.
String periodCountdown(int daysLeft) {
  if (daysLeft < 0) return 'Ended ${-daysLeft} day${daysLeft == -1 ? '' : 's'} ago';
  if (daysLeft == 0) return 'Ends today';
  return '$daysLeft day${daysLeft == 1 ? '' : 's'} left';
}

/// Totals of the backend's per-employee period summary (web `sumPeriodSummary`). Day counts arrive
/// as decimal strings; a field null on every row stays null ("—"), not zero.
class PeriodTotals {
  const PeriodTotals(this.values, {required this.employees, required this.frozen, required this.otMinutes, required this.lateCount});
  final Map<String, double?> values;
  final int employees;
  final bool frozen;
  final int otMinutes;
  final int lateCount;
}

/// Web's monthly-summary tiles, in order: label → summary field.
const periodDayFields = [
  ('Payable days', 'payable_days'),
  ('Paid days', 'paid_days'),
  ('Present', 'present_days'),
  ('Half days', 'half_days'),
  ('Absent', 'absent_days'),
  ('Leave', 'leave_days'),
  ('Holidays', 'holiday_days'),
  ('Weekly offs', 'weekly_off_days'),
  ('On duty', 'on_duty_days'),
  ('Incomplete', 'incomplete_days'),
  ('LOP', 'lop_days'),
  ('Not employed', 'not_employed_days'),
];

/// Fields web treats as always present: a missing value counts as 0 rather than unknown.
const _alwaysSummed = {'present_days', 'half_days', 'absent_days', 'leave_days', 'holiday_days', 'weekly_off_days', 'lop_days'};

PeriodTotals sumPeriodSummary(List<Map<String, dynamic>> rows) {
  final values = <String, double?>{};
  for (final (_, field) in periodDayFields) {
    double? total;
    for (final r in rows) {
      final v = r[field];
      if (v == null) continue;
      total = (total ?? 0) + (double.tryParse('$v') ?? 0);
    }
    values[field] = total ?? (_alwaysSummed.contains(field) ? 0 : null);
  }
  int sumInt(String key) => rows.fold(0, (a, r) => a + ((r[key] as num?)?.toInt() ?? 0));
  return PeriodTotals(
    values,
    employees: rows.length,
    frozen: rows.isNotEmpty && rows.every((r) => r['frozen'] == true),
    otMinutes: sumInt('ot_minutes_normal') + sumInt('ot_minutes_weekly_off') + sumInt('ot_minutes_holiday') + sumInt('ot_minutes_night'),
    lateCount: sumInt('late_count'),
  );
}

/// A day count as web shows it: whole numbers plain, halves to one decimal, unknown as "—".
String formatDays(double? v) => v == null ? '—' : (v == v.roundToDouble() ? '${v.toInt()}' : v.toStringAsFixed(1));
