import 'attendance_insights.dart' show pct;

/// `GET /v1/attendance/summary`: the attendance dashboard's totals, counted by the backend over
/// every attendance day in the window (API `AttendanceSummaryRead`). The insights screen only
/// shows these; it never re-adds rows, so mobile and web show the same figures. A rate is 0–100,
/// and null when nothing was there to divide by.

int _i(Object? v) => (v as num?)?.toInt() ?? 0;
double? _d(Object? v) => (v as num?)?.toDouble();
List<Map<String, dynamic>> _list(Object? v) => [for (final e in (v as List?) ?? const []) e as Map<String, dynamic>];

/// One calendar day of the window.
class TotalsDay {
  const TotalsDay({
    required this.date,
    required this.expected,
    required this.present,
    required this.rate,
    this.remote = 0,
    this.absent = 0,
    this.leave = 0,
    this.late = 0,
    this.checkedIn = 0,
    this.workedMinutes = 0,
  });

  factory TotalsDay.fromJson(Map<String, dynamic> j) => TotalsDay(
        date: j['date'] as String,
        expected: _i(j['expected']),
        present: _i(j['present']),
        rate: _d(j['rate']),
        remote: _i(j['remote']),
        absent: _i(j['absent']),
        leave: _i(j['leave']),
        late: _i(j['late']),
        checkedIn: _i(j['checked_in']),
        workedMinutes: _i(j['worked_minutes']),
      );

  final String date;

  /// Employees expected to work (not on a holiday, weekly off, or outside their employment).
  final int expected;

  /// Of those, working: present, remote or on duty.
  final int present;
  final double? rate;
  final int remote;
  final int absent;
  final int leave;

  /// Late days, of [checkedIn] (days with a first punch).
  final int late;
  final int checkedIn;

  /// The engine's worked minutes, summed over the checked-in days.
  final int workedMinutes;
}

/// Counts for one day. [totalEmployees] = employed rows + [noRecord] (employees with no
/// attendance day yet, counted only when the day is today).
class TotalsKpis {
  const TotalsKpis({
    this.totalEmployees = 0,
    this.noRecord = 0,
    this.present = 0,
    this.remote = 0,
    this.onDuty = 0,
    this.absent = 0,
    this.leave = 0,
    this.halfDay = 0,
    this.holiday = 0,
    this.weeklyOff = 0,
    this.incomplete = 0,
    this.late = 0,
    this.notCheckedIn = 0,
    this.checkedIn = 0,
    this.exceptions = 0,
    this.overtimeEmployees = 0,
    this.overtimeMinutesDetected = 0,
    this.overtimeMinutesApproved = 0,
    this.notEmployed = 0,
  });

  factory TotalsKpis.fromJson(Map<String, dynamic> j) => TotalsKpis(
        totalEmployees: _i(j['total_employees']),
        noRecord: _i(j['no_record']),
        present: _i(j['present']),
        remote: _i(j['remote']),
        onDuty: _i(j['on_duty']),
        absent: _i(j['absent']),
        leave: _i(j['leave']),
        halfDay: _i(j['half_day']),
        holiday: _i(j['holiday']),
        weeklyOff: _i(j['weekly_off']),
        incomplete: _i(j['incomplete']),
        late: _i(j['late']),
        notCheckedIn: _i(j['not_checked_in']),
        checkedIn: _i(j['checked_in']),
        exceptions: _i(j['exceptions']),
        overtimeEmployees: _i(j['overtime_employees']),
        overtimeMinutesDetected: _i(j['overtime_minutes_detected']),
        overtimeMinutesApproved: _i(j['overtime_minutes_approved']),
        notEmployed: _i(j['not_employed']),
      );

  final int totalEmployees;
  final int noRecord;
  final int present;
  final int remote;
  final int onDuty;
  final int absent;
  final int leave;
  final int halfDay;
  final int holiday;
  final int weeklyOff;
  final int incomplete;
  final int late;
  final int notCheckedIn;
  final int checkedIn;
  final int exceptions;
  final int overtimeEmployees;
  final int overtimeMinutesDetected;
  final int overtimeMinutesApproved;
  final int notEmployed;

  /// Office + remote + on duty: someone who is working.
  int get presentTotal => present + remote + onDuty;
}

/// Only days with both a check-in and a check-out: an open day is not yet judged on time.
class TotalsPunctuality {
  const TotalsPunctuality({required this.checkedIn, required this.late, required this.avgLateMinutes, required this.bands});

  factory TotalsPunctuality.fromJson(Map<String, dynamic> j) => TotalsPunctuality(
        checkedIn: _i(j['checked_in']),
        late: _i(j['late']),
        avgLateMinutes: _d(j['avg_late_minutes']),
        bands: [for (final b in _list(j['bands'])) (label: '${b['label']}', count: _i(b['count']))],
      );

  final int checkedIn;
  final int late;
  final double? avgLateMinutes;
  final List<({String label, int count})> bands;

  int get onTime => checkedIn - late;
  double? get lateRate => pct(late, checkedIn);
  double? get onTimeRate => pct(onTime, checkedIn);
}

class WeekdayStat {
  const WeekdayStat({required this.label, required this.expected, required this.absent, required this.rate});

  factory WeekdayStat.fromJson(Map<String, dynamic> j) =>
      WeekdayStat(label: '${j['label']}', expected: _i(j['expected']), absent: _i(j['absent']), rate: _d(j['rate']));

  final String label;
  final int expected;
  final int absent;

  /// Absent ÷ expected; null when that weekday never had anyone expected.
  final double? rate;
}

/// One department or branch on the focus day. [id] is null for "Unassigned".
class GroupStat {
  const GroupStat({
    required this.id,
    required this.name,
    required this.headcount,
    required this.expected,
    required this.present,
    required this.absent,
    required this.leave,
    required this.late,
    required this.rate,
  });

  factory GroupStat.fromJson(Map<String, dynamic> j) => GroupStat(
        id: j['id'] as String?,
        name: '${j['name']}',
        headcount: _i(j['headcount']),
        expected: _i(j['expected']),
        present: _i(j['present']),
        absent: _i(j['absent']),
        leave: _i(j['leave']),
        late: _i(j['late']),
        rate: _d(j['rate']),
      );

  final String? id;
  final String name;
  final int headcount;
  final int expected;
  final int present;
  final int absent;
  final int leave;
  final int late;
  final double? rate;
}

class AttendanceTotals {
  const AttendanceTotals({
    required this.dateFrom,
    required this.dateTo,
    required this.focusDate,
    required this.compareDate,
    required this.daily,
    required this.focus,
    required this.compare,
    required this.distribution,
    required this.punctuality,
    required this.frequentLate,
    required this.weekdayAbsence,
    required this.byDepartment,
    required this.byBranch,
  });

  factory AttendanceTotals.fromJson(Map<String, dynamic> j) => AttendanceTotals(
        dateFrom: j['date_from'] as String,
        dateTo: j['date_to'] as String,
        focusDate: j['focus_date'] as String,
        compareDate: j['compare_date'] as String,
        daily: [for (final d in _list(j['daily'])) TotalsDay.fromJson(d)],
        focus: TotalsKpis.fromJson(j['focus'] as Map<String, dynamic>),
        compare: j['compare'] == null ? null : TotalsKpis.fromJson(j['compare'] as Map<String, dynamic>),
        distribution: [for (final d in _list(j['distribution'])) (bucket: '${d['bucket']}', count: _i(d['count']))],
        punctuality: TotalsPunctuality.fromJson(j['punctuality'] as Map<String, dynamic>),
        frequentLate: [
          for (final f in _list(j['frequent_late'])) (employeeId: '${f['employee_id']}', lateDays: _i(f['late_days']), totalLateMinutes: _i(f['total_late_minutes'])),
        ],
        weekdayAbsence: [for (final w in _list(j['weekday_absence'])) WeekdayStat.fromJson(w)],
        byDepartment: [for (final g in _list(j['by_department'])) GroupStat.fromJson(g)],
        byBranch: [for (final g in _list(j['by_branch'])) GroupStat.fromJson(g)],
      );

  final String dateFrom;

  /// Also [focusDate]: the day the KPIs, distribution and breakdown describe.
  final String dateTo;
  final String focusDate;

  /// The same weekday a week before [focusDate].
  final String compareDate;

  /// Every day of the window, in order, empty days included.
  final List<TotalsDay> daily;
  final TotalsKpis focus;

  /// Null when there were no rows on [compareDate].
  final TotalsKpis? compare;

  /// Count per status bucket on the focus day, only buckets that occur, in display order.
  final List<({String bucket, int count})> distribution;
  final TotalsPunctuality punctuality;
  final List<({String employeeId, int lateDays, int totalLateMinutes})> frequentLate;

  /// Monday to Sunday.
  final List<WeekdayStat> weekdayAbsence;
  final List<GroupStat> byDepartment;
  final List<GroupStat> byBranch;

  /// The focus day's rate, or null when nobody was expected.
  TotalsDay get focusDay => daily.lastWhere((d) => d.date == focusDate, orElse: () => TotalsDay(date: focusDate, expected: 0, present: 0, rate: null));

  /// Percentage points, the focus day against [compareDate]; null when either side has no rate.
  double? get rateDelta {
    double? rateOn(String date) {
      for (final d in daily) {
        if (d.date == date) return d.rate;
      }
      return null;
    }

    final now = rateOn(focusDate);
    final before = rateOn(compareDate);
    return now != null && before != null ? now - before : null;
  }
}

/// The weekday with the highest absence rate, or null when there is nothing worth naming (no
/// absences, or fewer than two weekdays with data).
WeekdayStat? worstWeekday(List<WeekdayStat> stats) {
  final withData = stats.where((s) => s.rate != null).toList();
  if (withData.length < 2) return null;
  final worst = withData.reduce((a, b) => (b.rate ?? 0) > (a.rate ?? 0) ? b : a);
  return (worst.rate ?? 0) > 0 ? worst : null;
}
