import '../data/attendance_repository.dart';
import '../presentation/attendance_summary.dart' show attendanceBucketOf;
import 'attendance_totals.dart' show TotalsDay;

/// Pure view-model logic for the Attendance Insights screen — mirrors
/// `apps/web/src/lib/attendance/dashboard.ts`. The trend reads the backend's per-day counts
/// (`GET /v1/attendance/summary`); the per-person panels (work hours, needs attention, repeat
/// absences, muster) read the attendance days. Percentages are `null` when the denominator is zero.

// ---- dates (ISO `YYYY-MM-DD`, pure UTC arithmetic) -------------------------------------------

DateTime _parse(String iso) => DateTime.utc(int.parse(iso.substring(0, 4)), int.parse(iso.substring(5, 7)), int.parse(iso.substring(8, 10)));

String _fmt(DateTime d) => '${d.year.toString().padLeft(4, '0')}-${d.month.toString().padLeft(2, '0')}-${d.day.toString().padLeft(2, '0')}';

String addDaysIso(String iso, int n) => _fmt(_parse(iso).add(Duration(days: n)));

int dayDiffIso(String from, String to) => _parse(to).difference(_parse(from)).inDays;

List<String> eachDateIso(String from, String to) {
  final out = <String>[];
  final span = dayDiffIso(from, to);
  for (var i = 0; i <= span && i < 400; i++) {
    out.add(addDaysIso(from, i));
  }
  return out;
}

/// Monday of the ISO week containing [iso].
String weekStartIso(String iso) => addDaysIso(iso, -(_parse(iso).weekday - 1));

const _months = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];

String shortDate(String iso) => '${iso.substring(8, 10)} ${_months[int.parse(iso.substring(5, 7)) - 1]}';

double? pct(num numerator, num denominator) => denominator > 0 ? numerator / denominator * 100 : null;

String formatPct(double? v) => v == null ? '—' : '${v.toStringAsFixed(1)}%';

// ---- range -------------------------------------------------------------------------------------

enum InsightsRange { week, month, last14, last30 }

const insightsRangeLabels = {
  InsightsRange.week: 'This week',
  InsightsRange.month: 'This month',
  InsightsRange.last14: 'Last 14 days',
  InsightsRange.last30: 'Last 30 days',
};

({String from, String to}) resolveInsightsRange(InsightsRange r, String today) => switch (r) {
      InsightsRange.week => (from: weekStartIso(today), to: today),
      InsightsRange.month => (from: '${today.substring(0, 7)}-01', to: today),
      InsightsRange.last14 => (from: addDaysIso(today, -13), to: today),
      InsightsRange.last30 => (from: addDaysIso(today, -29), to: today),
    };

// ---- row helpers -------------------------------------------------------------------------------

const _worked = {'PRESENT', 'REMOTE', 'ON_DUTY', 'HALF_DAY', 'INCOMPLETE'};

int _int(AttendanceDay d, String key) => (d.raw[key] as num?)?.toInt() ?? 0;
bool _flag(AttendanceDay d, String key) => d.raw[key] == true;

bool isLate(AttendanceDay d) => d.raw.containsKey('is_late') ? _flag(d, 'is_late') : (d.lateMinutes ?? 0) > 0;
bool workOnLeaveUnresolved(AttendanceDay d) => _flag(d, 'work_on_leave_flagged') && d.raw['work_on_leave_resolution'] == null;

int workedMinutes(AttendanceDay d) => d.workedMinutes ?? _int(d, 'worked_minutes');

// ---- trend -------------------------------------------------------------------------------------

enum TrendMetric { presentPct, absentPct, leavePct, latePct, remotePct, avgHours }

const trendMetricLabels = {
  TrendMetric.presentPct: 'Present %',
  TrendMetric.absentPct: 'Absent %',
  TrendMetric.leavePct: 'Leave %',
  TrendMetric.latePct: 'Late %',
  TrendMetric.remotePct: 'Remote %',
  TrendMetric.avgHours: 'Avg hours',
};

class TrendPoint {
  TrendPoint(this.key, this.label, this.value);
  final String key;
  final String label;

  /// Percent (0–100) or hours; `null` where the denominator is zero (a gap).
  final double? value;
}

class _Tally {
  int expected = 0, present = 0, remote = 0, absent = 0, leave = 0, late = 0, checkedIn = 0, workedMin = 0;

  void add(TotalsDay d) {
    expected += d.expected;
    present += d.present;
    remote += d.remote;
    absent += d.absent;
    leave += d.leave;
    late += d.late;
    checkedIn += d.checkedIn;
    workedMin += d.workedMinutes;
  }

  double? value(TrendMetric m) => switch (m) {
        TrendMetric.presentPct => pct(present, expected),
        TrendMetric.absentPct => pct(absent, expected),
        TrendMetric.leavePct => pct(leave, expected),
        TrendMetric.remotePct => pct(remote, expected),
        TrendMetric.latePct => pct(late, checkedIn),
        TrendMetric.avgHours => checkedIn > 0 ? workedMin / 60 / checkedIn : null,
      };
}

/// The trend from the summary's per-day counts. A week adds its days' numerators and denominators,
/// so a weekly rate is never an average of daily rates.
List<TrendPoint> buildTrend(List<TotalsDay> days, String from, String to, TrendMetric metric, {required bool weekly}) {
  String keyFor(String date) => weekly ? weekStartIso(date) : date;
  final tallies = <String, _Tally>{};
  for (final date in eachDateIso(from, to)) {
    tallies.putIfAbsent(keyFor(date), _Tally.new);
  }
  for (final d in days) {
    if (d.date.compareTo(from) < 0 || d.date.compareTo(to) > 0) continue;
    tallies.putIfAbsent(keyFor(d.date), _Tally.new).add(d);
  }
  return [for (final e in tallies.entries) TrendPoint(e.key, weekly ? 'Wk ${shortDate(e.key)}' : shortDate(e.key), e.value.value(metric))];
}

// ---- work hours --------------------------------------------------------------------------------

class WorkHoursSummary {
  int totalMinutes = 0;
  int checkedInDays = 0;
  int? avgMinutes;
  int expectedMinutes = 0;
  int actualOnExpectedMinutes = 0;
  int underTimeMinutes = 0;
  int otDetectedMinutes = 0;
  int otApprovedMinutes = 0;
  int get deviationMinutes => actualOnExpectedMinutes - expectedMinutes;
}

WorkHoursSummary summarizeWorkHours(List<AttendanceDay> rows) {
  final s = WorkHoursSummary();
  for (final d in rows) {
    s.otDetectedMinutes += _int(d, 'ot_minutes_detected');
    s.otApprovedMinutes += _int(d, 'ot_minutes_approved');
    if (d.actualFirstIn == null) continue;
    final w = workedMinutes(d);
    s.totalMinutes += w;
    s.checkedInDays++;
    final scheduled = _int(d, 'scheduled_minutes');
    if (scheduled > 0 && _worked.contains(attendanceBucketOf(d))) {
      s.expectedMinutes += scheduled;
      s.actualOnExpectedMinutes += w;
      if (d.actualLastOut != null && w < scheduled) s.underTimeMinutes += scheduled - w;
    }
  }
  s.avgMinutes = s.checkedInDays > 0 ? (s.totalMinutes / s.checkedInDays).round() : null;
  return s;
}

class DailyHours {
  DailyHours(this.date) : label = shortDate(date);
  final String date;
  final String label;
  int workedMinutes = 0;
  int scheduledMinutes = 0;
}

List<DailyHours> dailyHours(List<AttendanceDay> rows, String from, String to) {
  final byDate = {for (final date in eachDateIso(from, to)) date: DailyHours(date)};
  for (final d in rows) {
    final e = byDate[d.attendanceDate];
    if (e == null || d.actualFirstIn == null) continue;
    e.workedMinutes += workedMinutes(d);
    if (_worked.contains(attendanceBucketOf(d))) e.scheduledMinutes += _int(d, 'scheduled_minutes');
  }
  return byDate.values.toList();
}

// ---- overtime (the backend's OvertimeRecord rows) ---------------------------------------------

const overtimeDayClassLabels = {'NORMAL': 'Normal', 'WEEKLY_OFF': 'Weekly off', 'HOLIDAY': 'Holiday', 'NIGHT': 'Night'};

class OvertimeSummary {
  int totalDetectedMinutes = 0;
  int totalApprovedMinutes = 0;
  int employees = 0;
  int? avgDetectedPerEmployee;
  int pendingCount = 0;
  int pendingMinutes = 0;
  int approvedCount = 0;
  int rejectedCount = 0;
  List<({String dayClass, int minutes})> byDayClass = const [];
  List<({String date, String label, int minutes})> trend = const [];
}

OvertimeSummary summarizeOvertime(List<Map<String, dynamic>> records, String from, String to) {
  final s = OvertimeSummary();
  final employees = <String>{};
  final byClass = <String, int>{};
  final byDate = {for (final date in eachDateIso(from, to)) date: 0};
  for (final r in records) {
    final detected = (r['minutes_detected'] as num?)?.toInt() ?? 0;
    s.totalDetectedMinutes += detected;
    s.totalApprovedMinutes += (r['minutes_approved'] as num?)?.toInt() ?? 0;
    employees.add(r['employee_id'] as String? ?? '');
    switch (r['status']) {
      case 'PENDING':
        s.pendingCount++;
        s.pendingMinutes += detected;
      case 'APPROVED' || 'AUTO_APPROVED':
        s.approvedCount++;
      case 'REJECTED':
        s.rejectedCount++;
    }
    final cls = r['day_class'] as String? ?? 'UNCLASSIFIED';
    byClass[cls] = (byClass[cls] ?? 0) + detected;
    final date = r['attendance_date'] as String?;
    if (date != null && byDate.containsKey(date)) byDate[date] = byDate[date]! + detected;
  }
  s.employees = employees.length;
  s.avgDetectedPerEmployee = employees.isEmpty ? null : (s.totalDetectedMinutes / employees.length).round();
  s.byDayClass = [for (final e in byClass.entries) (dayClass: e.key, minutes: e.value)]..sort((a, b) => b.minutes.compareTo(a.minutes));
  s.trend = [for (final e in byDate.entries) (date: e.key, label: shortDate(e.key), minutes: e.value)];
  return s;
}

// ---- needs attention ---------------------------------------------------------------------------

enum Severity { critical, high, medium, low }

class AttentionItem {
  AttentionItem(this.label, this.hint, this.count, this.unit, this.severity, {this.route, this.employees});
  final String label;
  final String hint;
  final int count;
  final String unit;
  final Severity severity;

  /// Where the workflow lives (null = this screen already shows the rows).
  final String? route;
  final int? employees;
}

int _distinct(Iterable<AttendanceDay> rows) => rows.map((d) => d.employeeId).toSet().length;

List<AttentionItem> buildAttentionItems({
  required List<AttendanceDay> rows,
  required int pendingRegularizations,
  required int pendingOvertime,
  required int blockedPeriods,
}) {
  final items = <AttentionItem>[];
  void add(String label, String hint, Severity sev, Iterable<AttendanceDay> matches) {
    final list = matches.toList();
    if (list.isNotEmpty) items.add(AttentionItem(label, hint, list.length, 'days', sev, employees: _distinct(list)));
  }

  add('Configuration errors', 'Days that could not be calculated — shift or policy is missing.', Severity.critical, rows.where((d) => attendanceBucketOf(d) == 'CONFIG_ERROR'));
  add('Missing punches', 'A day with an IN or OUT punch missing.', Severity.high, rows.where((d) => _flag(d, 'missing_punch')));
  add('Incomplete attendance', 'Needs manual resolution before the period can close.', Severity.high, rows.where((d) => attendanceBucketOf(d) == 'INCOMPLETE'));
  add('Work on approved leave', 'Punches on a full-day leave awaiting an HR decision.', Severity.high, rows.where(workOnLeaveUnresolved));
  add('Days pending approval', 'Attendance days waiting on an approval.', Severity.medium, rows.where((d) => _flag(d, 'is_pending_approval')));
  add('Late arrivals', 'Checked in after the grace window.', Severity.medium, rows.where(isLate));
  add('Early departures', 'Checked out before shift end.', Severity.low, rows.where((d) => _flag(d, 'is_early_out')));
  if (pendingRegularizations > 0) {
    items.add(AttentionItem('Regularization pending', 'Employee correction requests awaiting a decision.', pendingRegularizations, 'requests', Severity.high, route: '/app/regularizations'));
  }
  if (pendingOvertime > 0) {
    items.add(AttentionItem('Overtime awaiting approval', 'Detected overtime not yet approved or rejected.', pendingOvertime, 'records', Severity.medium, route: '/app/overtime'));
  }
  if (blockedPeriods > 0) {
    items.add(AttentionItem('Payroll period blocked', 'An open attendance period failed validation and cannot be finalized.', blockedPeriods, 'periods', Severity.critical, route: '/app/attendance-periods'));
  }
  items.sort((a, b) {
    final c = a.severity.index.compareTo(b.severity.index);
    return c != 0 ? c : b.count.compareTo(a.count);
  });
  return items;
}

// ---- absence insights --------------------------------------------------------------------------

const repeatAbsenceThreshold = 3;

class RepeatAbsence {
  RepeatAbsence(this.employeeId);
  final String employeeId;
  int absentDays = 0;
  int leaveDays = 0;
}

List<RepeatAbsence> repeatAbsences(List<AttendanceDay> rows, {int threshold = repeatAbsenceThreshold}) {
  final by = <String, RepeatAbsence>{};
  for (final d in rows) {
    final b = attendanceBucketOf(d);
    if (b != 'ABSENT' && b != 'LEAVE') continue;
    final e = by.putIfAbsent(d.employeeId, () => RepeatAbsence(d.employeeId));
    if (b == 'ABSENT') {
      e.absentDays++;
    } else {
      e.leaveDays++;
    }
  }
  return by.values.where((e) => e.absentDays >= threshold).toList()
    ..sort((a, b) {
      final c = b.absentDays.compareTo(a.absentDays);
      return c != 0 ? c : b.leaveDays.compareTo(a.leaveDays);
    });
}

// ---- muster / heatmap --------------------------------------------------------------------------

const maxMusterDays = 14;

/// The last [maxMusterDays] days of the range, so the grid stays readable on a phone.
List<String> musterDates(String from, String to) {
  final start = dayDiffIso(from, to) >= maxMusterDays ? addDaysIso(to, -(maxMusterDays - 1)) : from;
  return eachDateIso(start, to);
}

class MusterRow {
  MusterRow(this.employeeId, this.name);
  final String employeeId;
  final String name;
  final cells = <String, AttendanceDay>{};
}

List<MusterRow> buildMuster(List<AttendanceDay> rows, List<String> dates, String Function(String employeeId) nameOf) {
  final visible = dates.toSet();
  final by = <String, MusterRow>{};
  for (final d in rows) {
    if (!visible.contains(d.attendanceDate)) continue;
    by.putIfAbsent(d.employeeId, () => MusterRow(d.employeeId, nameOf(d.employeeId))).cells[d.attendanceDate] = d;
  }
  return by.values.toList()..sort((a, b) => a.name.compareTo(b.name));
}
