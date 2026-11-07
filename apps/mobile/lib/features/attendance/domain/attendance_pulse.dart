import '../data/attendance_repository.dart';
import '../presentation/attendance_summary.dart' show attendanceBucketOf;
import 'attendance_insights.dart';

/// The "how are we doing today" half of the web attendance dashboard, as pure logic: the focus
/// day's rate and how it compares, the KPI counts, punctuality, the weekday pattern, the
/// department / branch breakdown and the attendance-period helpers. Ported from
/// `apps/web/src/lib/attendance/insights.ts` and `dashboard.ts`; the rules and wording match.
/// Every figure counts or sums values the backend already computed.

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

// ---- rate and comparison -----------------------------------------------------------------------

class RatePoint {
  const RatePoint(this.date, this.rate, this.expected, this.present);
  final String date;

  /// Present ÷ expected, 0–100; null when nobody was expected (weekend, holiday).
  final double? rate;
  final int expected;
  final int present;
}

/// One point per calendar day from [from] to [to].
List<RatePoint> dailyAttendanceRate(List<AttendanceDay> rows, String from, String to) {
  final expected = <String, int>{};
  final present = <String, int>{};
  for (final d in rows) {
    final b = attendanceBucketOf(d);
    if (isExpectedBucket(b)) expected[d.attendanceDate] = (expected[d.attendanceDate] ?? 0) + 1;
    if (isAttendingBucket(b)) present[d.attendanceDate] = (present[d.attendanceDate] ?? 0) + 1;
  }
  return [
    for (final date in eachDateIso(from, to)) RatePoint(date, pct(present[date] ?? 0, expected[date] ?? 0), expected[date] ?? 0, present[date] ?? 0),
  ];
}

String sameWeekdayLastWeek(String date) => addDaysIso(date, -7);

const _weekdays = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'];

/// 0 = Monday … 6 = Sunday.
int weekdayIndexIso(String iso) => DateTime.utc(int.parse(iso.substring(0, 4)), int.parse(iso.substring(5, 7)), int.parse(iso.substring(8, 10))).weekday - 1;

String weekdayShort(String iso) => _weekdays[weekdayIndexIso(iso)];

/// Percentage points, the focus day minus the baseline; null when either side has no rate.
double? rateDelta(List<RatePoint> points, String date, String baselineDate) {
  double? rateOn(String d) {
    for (final p in points) {
      if (p.date == d) return p.rate;
    }
    return null;
  }

  final now = rateOn(date);
  final before = rateOn(baselineDate);
  return now != null && before != null ? now - before : null;
}

// ---- KPIs and distribution ---------------------------------------------------------------------

class KpiSet {
  int employed = 0;
  int present = 0;
  int remote = 0;
  int onDuty = 0;
  int absent = 0;
  int leave = 0;
  int halfDay = 0;
  int holiday = 0;
  int weeklyOff = 0;
  int incomplete = 0;
  int late = 0;
  int notCheckedIn = 0;
  int checkedIn = 0;
  int exceptions = 0;
  int overtimeEmployees = 0;
  int overtimeMinutesDetected = 0;
  int overtimeMinutesApproved = 0;

  /// Office + remote + on duty: someone who is working.
  int get presentTotal => present + remote + onDuty;
}

/// Counts for one day's rows (web `computeKpis`). Mobile has no "no record yet" count: web derives
/// it from the full employee list with joining dates, which this screen does not load.
KpiSet computeKpis(List<AttendanceDay> rowsOnFocus) {
  final k = KpiSet();
  for (final d in rowsOnFocus) {
    final b = attendanceBucketOf(d);
    if (b == 'NOT_EMPLOYED') continue;
    k.employed += 1;
    switch (b) {
      case 'PRESENT':
        k.present += 1;
      case 'REMOTE':
        k.remote += 1;
      case 'ON_DUTY':
        k.onDuty += 1;
      case 'ABSENT':
        k.absent += 1;
      case 'LEAVE':
        k.leave += 1;
      case 'HALF_DAY':
        k.halfDay += 1;
      case 'HOLIDAY':
        k.holiday += 1;
      case 'WEEKLY_OFF':
        k.weeklyOff += 1;
      case 'INCOMPLETE':
        k.incomplete += 1;
    }
    if (_checkedIn(d)) k.checkedIn += 1;
    if (isLate(d)) k.late += 1;
    if (isNotCheckedIn(d)) k.notCheckedIn += 1;
    if (hasException(d)) k.exceptions += 1;
    final ot = _int(d, 'ot_minutes_detected');
    if (ot > 0) {
      k.overtimeEmployees += 1;
      k.overtimeMinutesDetected += ot;
      k.overtimeMinutesApproved += _int(d, 'ot_minutes_approved');
    }
  }
  return k;
}

/// Count per bucket for one day's rows, in web order, only buckets that occur.
List<({String bucket, String label, int count})> statusDistribution(List<AttendanceDay> rowsOnFocus) {
  final counts = <String, int>{};
  for (final d in rowsOnFocus) {
    final b = attendanceBucketOf(d);
    counts[b] = (counts[b] ?? 0) + 1;
  }
  return [
    for (final e in dayBucketLabels.entries)
      if ((counts[e.key] ?? 0) > 0) (bucket: e.key, label: e.value, count: counts[e.key]!),
  ];
}

// ---- punctuality -------------------------------------------------------------------------------

const lateBands = [
  (label: '1–15 min', min: 1, max: 15),
  (label: '16–30 min', min: 16, max: 30),
  (label: '31–60 min', min: 31, max: 60),
  (label: 'Over an hour', min: 61, max: 1 << 30),
];

class PunctualitySummary {
  const PunctualitySummary({required this.checkedIn, required this.late, required this.avgLateMinutes, required this.bands});
  final int checkedIn;
  final int late;
  final double? avgLateMinutes;
  final List<({String label, int count})> bands;

  int get onTime => checkedIn - late;
  double? get lateRate => pct(late, checkedIn);
  double? get onTimeRate => pct(onTime, checkedIn);
}

PunctualitySummary punctualitySummary(List<AttendanceDay> rows) {
  var checkedIn = 0;
  var late = 0;
  var lateMinutes = 0;
  final counts = List.filled(lateBands.length, 0);
  for (final d in rows) {
    if (!_checkedIn(d)) continue;
    checkedIn += 1;
    if (!isLate(d)) continue;
    late += 1;
    lateMinutes += lateMinutesOf(d);
    // A late day with no minutes recorded is still late; it lands in the smallest band.
    final m = lateMinutesOf(d) < 1 ? 1 : lateMinutesOf(d);
    final i = lateBands.indexWhere((b) => m >= b.min && m <= b.max);
    if (i >= 0) counts[i] += 1;
  }
  return PunctualitySummary(
    checkedIn: checkedIn,
    late: late,
    avgLateMinutes: late > 0 ? lateMinutes / late : null,
    bands: [for (var i = 0; i < lateBands.length; i++) (label: lateBands[i].label, count: counts[i])],
  );
}

/// Employees late on at least [minDays] days, most first (ties: more minutes first).
List<({String employeeId, int lateDays, int totalLateMinutes})> frequentLateArrivals(List<AttendanceDay> rows, {int limit = 5, int minDays = 2}) {
  final days = <String, int>{};
  final minutes = <String, int>{};
  for (final d in rows) {
    if (!isLate(d)) continue;
    days[d.employeeId] = (days[d.employeeId] ?? 0) + 1;
    minutes[d.employeeId] = (minutes[d.employeeId] ?? 0) + lateMinutesOf(d);
  }
  final out = [
    for (final id in days.keys)
      if (days[id]! >= minDays) (employeeId: id, lateDays: days[id]!, totalLateMinutes: minutes[id]!),
  ]..sort((a, b) => b.lateDays != a.lateDays ? b.lateDays.compareTo(a.lateDays) : b.totalLateMinutes.compareTo(a.totalLateMinutes));
  return out.take(limit).toList();
}

// ---- weekday pattern ---------------------------------------------------------------------------

class WeekdayStat {
  WeekdayStat(this.label);
  final String label;
  int expected = 0;
  int absent = 0;

  /// Absent ÷ expected, 0–100; null when that weekday never had anyone expected.
  double? get rate => pct(absent, expected);
}

/// Absence rate for each weekday, Monday to Sunday.
List<WeekdayStat> weekdayAbsence(List<AttendanceDay> rows) {
  final stats = [for (final l in _weekdays) WeekdayStat(l)];
  for (final d in rows) {
    final b = attendanceBucketOf(d);
    if (!isExpectedBucket(b)) continue;
    final s = stats[weekdayIndexIso(d.attendanceDate)];
    s.expected += 1;
    if (b == 'ABSENT') s.absent += 1;
  }
  return stats;
}

/// The weekday with the highest absence rate, or null when there is nothing worth naming (no
/// absences, or fewer than two weekdays with data).
WeekdayStat? worstWeekday(List<WeekdayStat> stats) {
  final withData = stats.where((s) => s.rate != null).toList();
  if (withData.length < 2) return null;
  final worst = withData.reduce((a, b) => (b.rate ?? 0) > (a.rate ?? 0) ? b : a);
  return (worst.rate ?? 0) > 0 ? worst : null;
}

// ---- department / branch breakdown -------------------------------------------------------------

const unassignedGroup = 'Unassigned';

String groupName(String? value) => value != null && value.trim().isNotEmpty ? value.trim() : unassignedGroup;

class GroupStat {
  GroupStat(this.name);
  final String name;
  int headcount = 0;
  int expected = 0;
  int present = 0;
  int absent = 0;
  int leave = 0;
  int late = 0;
  double? get rate => pct(present, expected);
}

/// Attendance per group on one day (one row per employee), lowest rate first and groups nobody was
/// expected in last, so the places that need a look are at the top (web `breakdownBy`).
List<GroupStat> breakdownBy(List<AttendanceDay> rowsOnDay, String? Function(String employeeId) groupOf) {
  final groups = <String, GroupStat>{};
  for (final d in rowsOnDay) {
    final b = attendanceBucketOf(d);
    final g = groups.putIfAbsent(groupName(groupOf(d.employeeId)), () => GroupStat(groupName(groupOf(d.employeeId))));
    g.headcount += 1;
    if (isExpectedBucket(b)) g.expected += 1;
    if (isAttendingBucket(b)) g.present += 1;
    if (b == 'ABSENT') g.absent += 1;
    if (b == 'LEAVE') g.leave += 1;
    if (isLate(d)) g.late += 1;
  }
  return groups.values.toList()
    ..sort((a, b) {
      if (a.rate == null && b.rate == null) return a.name.compareTo(b.name);
      if (a.rate == null) return 1;
      if (b.rate == null) return -1;
      final r = a.rate!.compareTo(b.rate!);
      if (r != 0) return r;
      final h = b.headcount.compareTo(a.headcount);
      return h != 0 ? h : a.name.compareTo(b.name);
    });
}

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
