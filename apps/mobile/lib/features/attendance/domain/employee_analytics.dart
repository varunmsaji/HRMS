import '../data/attendance_repository.dart';
import '../presentation/attendance_summary.dart' show attendanceBucketOf;

/// View-model logic for the employee profile's attendance analytics: the Today strip, the month
/// tiles, the month calendar and the two charts. Mirrors `apps/web/src/lib/attendance/employee-analytics.ts`;
/// everything is derived from the persisted attendance days and punches the API already serves, so
/// the numbers match the attendance pages.

/// Buckets on which the employee was expected to work.
const _expected = {'PRESENT', 'REMOTE', 'ON_DUTY', 'HALF_DAY', 'ABSENT', 'LEAVE', 'INCOMPLETE'};

/// The order the legend and the status list use (web `DAY_BUCKETS`).
const dayBuckets = ['PRESENT', 'REMOTE', 'ON_DUTY', 'HALF_DAY', 'ABSENT', 'LEAVE', 'INCOMPLETE', 'CONFIG_ERROR', 'HOLIDAY', 'WEEKLY_OFF', 'NON_WORKING', 'NOT_EMPLOYED'];

/// One-glyph code for the month grid, so status never relies on colour alone (web `BUCKET_GLYPHS`).
const bucketGlyphs = {
  'PRESENT': 'P',
  'REMOTE': 'R',
  'ON_DUTY': 'OD',
  'HALF_DAY': '½',
  'ABSENT': 'A',
  'LEAVE': 'L',
  'INCOMPLETE': '!',
  'CONFIG_ERROR': 'E',
  'HOLIDAY': 'H',
  'WEEKLY_OFF': 'W',
  'NON_WORKING': '–',
  'NOT_EMPLOYED': '·',
};

int _int(Object? v) => (v as num?)?.toInt() ?? 0;
bool _flag(AttendanceDay d, String key) => d.raw[key] == true;

class MonthStats {
  int expectedDays = 0;

  /// Present, remote and on-duty days, a half day counting 0.5.
  double daysWorked = 0;
  int absent = 0;
  int leave = 0;
  int halfDays = 0;
  int daysOff = 0;
  int lateDays = 0;
  int lateMinutes = 0;
  int earlyOutDays = 0;
  int earlyOutMinutes = 0;
  int workedMinutes = 0;

  /// Average over days with a first punch; null when there are none.
  int? avgWorkedMinutes;
  int otDetectedMinutes = 0;
  int otApprovedMinutes = 0;

  /// Share of days worked that were not late, 0 to 100; null when nothing was worked.
  int? punctuality;
  int missingPunch = 0;
}

MonthStats monthStats(List<AttendanceDay> days, String today) {
  final s = MonthStats();
  var checkedIn = 0;
  var onTimeWorked = 0;
  var workedDays = 0;
  for (final day in days) {
    if (day.attendanceDate.compareTo(today) > 0) continue;
    final bucket = attendanceBucketOf(day);
    final late = _flag(day, 'is_late');
    if (_expected.contains(bucket)) s.expectedDays += 1;
    if (bucket == 'PRESENT' || bucket == 'REMOTE' || bucket == 'ON_DUTY') {
      s.daysWorked += 1;
      workedDays += 1;
      if (!late) onTimeWorked += 1;
    } else if (bucket == 'HALF_DAY') {
      s.daysWorked += 0.5;
      s.halfDays += 1;
      workedDays += 1;
      if (!late) onTimeWorked += 1;
    } else if (bucket == 'ABSENT') {
      s.absent += 1;
    } else if (bucket == 'LEAVE') {
      s.leave += 1;
    } else if (bucket == 'HOLIDAY' || bucket == 'WEEKLY_OFF') {
      s.daysOff += 1;
    }
    if (late) {
      s.lateDays += 1;
      s.lateMinutes += _int(day.raw['late_minutes']);
    }
    if (_flag(day, 'is_early_out')) {
      s.earlyOutDays += 1;
      s.earlyOutMinutes += _int(day.raw['early_departure_minutes']);
    }
    if (_flag(day, 'missing_punch')) s.missingPunch += 1;
    s.otDetectedMinutes += _int(day.raw['ot_minutes_detected']);
    s.otApprovedMinutes += _int(day.raw['ot_minutes_approved']);
    if (day.actualFirstIn != null) {
      checkedIn += 1;
      s.workedMinutes += day.workedMinutes ?? 0;
    }
  }
  if (checkedIn > 0) s.avgWorkedMinutes = (s.workedMinutes / checkedIn).round();
  if (workedDays > 0) s.punctuality = ((onTimeWorked / workedDays) * 100).round();
  return s;
}

/// "18", "17.5": one decimal only when there is a half day.
String formatWorkedDays(double n) => n == n.roundToDouble() ? '${n.toInt()}' : n.toStringAsFixed(1);

/// All the dates of a `YYYY-MM` month.
List<String> monthDates(String month) {
  final y = int.parse(month.substring(0, 4));
  final m = int.parse(month.substring(5, 7));
  final last = DateTime.utc(y, m + 1, 0).day;
  return [for (var d = 1; d <= last; d++) '$month-${d.toString().padLeft(2, '0')}'];
}

/// `YYYY-MM` moved by [delta] months.
String shiftMonth(String month, int delta) {
  final y = int.parse(month.substring(0, 4));
  final m = int.parse(month.substring(5, 7));
  final d = DateTime.utc(y, m + delta);
  return '${d.year.toString().padLeft(4, '0')}-${d.month.toString().padLeft(2, '0')}';
}

({String from, String to}) monthRange(String month) {
  final dates = monthDates(month);
  return (from: dates.first, to: dates.last);
}

class CalendarCell {
  const CalendarCell({required this.date, required this.dayOfMonth, required this.day, required this.bucket, required this.isToday, required this.isFuture});
  final String date;
  final int dayOfMonth;
  final AttendanceDay? day;
  final String? bucket;
  final bool isToday;
  final bool isFuture;
}

/// The month as Monday-first weeks. Days outside the month are null so the grid stays aligned.
List<List<CalendarCell?>> monthWeeks(String month, List<AttendanceDay> days, String today) {
  final byDate = {for (final d in days) d.attendanceDate: d};
  final dates = monthDates(month);
  final cells = <CalendarCell?>[];
  final lead = (DateTime.parse('${dates.first}T00:00:00Z').weekday - 1) % 7; // Monday = 1
  for (var i = 0; i < lead; i++) {
    cells.add(null);
  }
  for (final date in dates) {
    final day = byDate[date];
    cells.add(CalendarCell(date: date, dayOfMonth: int.parse(date.substring(8, 10)), day: day, bucket: day == null ? null : attendanceBucketOf(day), isToday: date == today, isFuture: date.compareTo(today) > 0));
  }
  while (cells.length % 7 != 0) {
    cells.add(null);
  }
  return [for (var i = 0; i < cells.length; i += 7) cells.sublist(i, i + 7)];
}

enum TodayState { working, onBreak, checkedOut, notStarted, notCheckedIn, onLeave, holiday, weeklyOff, noShift, notEmployed, absent }

class TodayStatus {
  TodayStatus({required this.state, this.holidayName, this.firstIn, this.lastOut, this.workedMinutes, this.scheduledStart, this.scheduledEnd, this.minutesToShiftEnd, this.minutesToShiftStart});
  TodayState state;
  final String? holidayName;

  /// The first IN punch (the latest IN when the employee is in without one recorded).
  String? firstIn;
  final String? lastOut;

  /// Minutes since the first punch while still in, or the engine's worked minutes once out.
  int? workedMinutes;
  final String? scheduledStart;
  final String? scheduledEnd;

  /// Minutes until the shift ends (negative once it is over); null with no schedule.
  final int? minutesToShiftEnd;
  final int? minutesToShiftStart;
}

int _minutesBetween(DateTime later, DateTime earlier) => (later.difference(earlier).inMilliseconds / 60000).round();

/// Where the employee is right now. [punches] are today's, in any order; [day] is today's
/// attendance row if it has been calculated. Punches win over the day's calendar type, so someone
/// working on a holiday shows as working.
TodayStatus todayStatus(AttendanceDay? day, List<Punch> punches, DateTime now) {
  final sorted = [...punches]..sort((a, b) => a.punchTime.compareTo(b.punchTime));
  final first = sorted.where((p) => p.direction == 'IN').firstOrNull;
  final last = sorted.isEmpty ? null : sorted.last;
  final lastOut = sorted.reversed.where((p) => p.direction == 'OUT').firstOrNull;
  final scheduledStart = day?.raw['scheduled_start'] as String?;
  final scheduledEnd = day?.raw['scheduled_end'] as String?;
  final status = TodayStatus(
    state: TodayState.noShift,
    holidayName: day?.raw['holiday_name'] as String?,
    firstIn: first?.punchTime ?? day?.actualFirstIn,
    lastOut: lastOut?.punchTime ?? day?.actualLastOut,
    scheduledStart: scheduledStart,
    scheduledEnd: scheduledEnd,
    minutesToShiftEnd: scheduledEnd == null ? null : _minutesBetween(DateTime.parse(scheduledEnd), now),
    minutesToShiftStart: scheduledStart == null ? null : _minutesBetween(DateTime.parse(scheduledStart), now),
  );
  if (last != null) {
    if (last.direction == 'IN') {
      final breaks = (day?.raw['breaks'] as List?) ?? const [];
      final openBreak = breaks.any((b) => b is Map && b['break_start'] != null && b['break_end'] == null);
      status.state = openBreak ? TodayState.onBreak : TodayState.working;
      status.firstIn = first?.punchTime ?? last.punchTime;
      final since = _minutesBetween(now, DateTime.parse(status.firstIn!));
      status.workedMinutes = since < 0 ? 0 : since;
    } else {
      status.state = TodayState.checkedOut;
      status.workedMinutes = day?.workedMinutes;
    }
    return status;
  }
  final bucket = day == null ? null : attendanceBucketOf(day);
  if (bucket == 'LEAVE') {
    status.state = TodayState.onLeave;
  } else if (bucket == 'HOLIDAY') {
    status.state = TodayState.holiday;
  } else if (bucket == 'WEEKLY_OFF') {
    status.state = TodayState.weeklyOff;
  } else if (bucket == 'NOT_EMPLOYED') {
    status.state = TodayState.notEmployed;
  } else if (bucket == 'ABSENT') {
    status.state = TodayState.absent;
  } else if (scheduledStart != null) {
    status.state = (status.minutesToShiftStart ?? 0) > 0 ? TodayState.notStarted : TodayState.notCheckedIn;
  } else {
    status.state = TodayState.noShift;
  }
  return status;
}

/// "2h 10m" / "45m" for a positive minute count.
String formatCountdown(num minutes) {
  final m = minutes < 0 ? 0 : minutes.round();
  final h = m ~/ 60;
  final rest = m % 60;
  if (h == 0) return '${rest}m';
  return rest == 0 ? '${h}h' : '${h}h ${rest}m';
}

class DailyHoursBar {
  const DailyHoursBar({required this.date, required this.dayOfMonth, required this.minutes, required this.bucket, required this.isLate});
  final String date;
  final int dayOfMonth;
  final int minutes;
  final String bucket;
  final bool isLate;
}

/// One bar per day that has worked time, up to today, plus the shift length to draw as a
/// reference line (the most common scheduled length that month; null when none is scheduled).
({List<DailyHoursBar> bars, int? scheduledMinutes}) dailyHours(List<AttendanceDay> days, String today) {
  final bars = <DailyHoursBar>[];
  final lengths = <int, int>{};
  final sorted = [...days]..sort((a, b) => a.attendanceDate.compareTo(b.attendanceDate));
  for (final day in sorted) {
    if (day.attendanceDate.compareTo(today) > 0) continue;
    final scheduled = _int(day.raw['scheduled_minutes']);
    if (scheduled > 0) lengths[scheduled] = (lengths[scheduled] ?? 0) + 1;
    final worked = day.workedMinutes ?? 0;
    if (day.actualFirstIn == null || worked <= 0) continue;
    bars.add(DailyHoursBar(date: day.attendanceDate, dayOfMonth: int.parse(day.attendanceDate.substring(8, 10)), minutes: worked, bucket: attendanceBucketOf(day), isLate: _flag(day, 'is_late')));
  }
  int? scheduledMinutes;
  var best = 0;
  lengths.forEach((len, n) {
    if (n > best) {
      best = n;
      scheduledMinutes = len;
    }
  });
  return (bars: bars, scheduledMinutes: scheduledMinutes);
}

/// How the month's days split by status, up to today, in the order the legend uses. Days before
/// joining or after leaving are left out.
List<({String bucket, int count})> statusBreakdown(List<AttendanceDay> days, String today) {
  final counts = <String, int>{};
  for (final day in days) {
    if (day.attendanceDate.compareTo(today) > 0) continue;
    final bucket = attendanceBucketOf(day);
    if (bucket == 'NOT_EMPLOYED') continue;
    counts[bucket] = (counts[bucket] ?? 0) + 1;
  }
  return [for (final b in dayBuckets) if (counts.containsKey(b)) (bucket: b, count: counts[b]!)];
}

/// "6 yrs 2 mos" from a joining date (`YYYY-MM-DD`), or null before the joining date.
String? tenureLabel(String joiningDate, DateTime today) {
  final j = DateTime.tryParse(joiningDate);
  if (j == null) return null;
  var months = (today.year - j.year) * 12 + (today.month - j.month);
  if (today.day < j.day) months -= 1;
  if (months < 0) return null;
  if (months == 0) return 'Less than a month';
  final years = months ~/ 12;
  final rest = months % 12;
  return [
    if (years > 0) '$years ${years == 1 ? 'yr' : 'yrs'}',
    if (rest > 0) '$rest ${rest == 1 ? 'mo' : 'mos'}',
  ].join(' ');
}
