import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../core/time.dart';
import '../../attendance/data/attendance_repository.dart';

/// Pure helpers for Home's stat tiles and charts. Every figure comes from the backend's own day
/// rows; nothing here recalculates attendance policy (mirrors `apps/web/src/lib/dashboard/employee.ts`).

const _present = {'PRESENT', 'HALF_DAY', 'WFH', 'ON_DUTY'};
const _notCounted = {'NOT_JOINED', 'EXITED', 'NOT_EXPECTED'};

class MonthSummary {
  const MonthSummary({required this.present, required this.onLeave, required this.absent, required this.other, required this.weeklyOffs, required this.holidays});
  final int present;
  final int onLeave;
  final int absent;
  final int other;
  final int weeklyOffs;
  final int holidays;
  int get total => present + onLeave + absent + other;
}

/// Today's row before the employee has punched: the 09:30 sweep writes `ABSENT`/`INCOMPLETE`, which
/// is provisional, so it is neither absent nor tracked yet (same rule as `todayStateOf`).
bool _isProvisionalToday(AttendanceDay d, String? today) =>
    today != null && d.attendanceDate == today && (d.attendanceStatus == 'ABSENT' || d.attendanceStatus == 'INCOMPLETE') && d.actualFirstIn == null && !d.isLocked;

/// Counts the month's day rows. Pass [today] so today's provisional row is not counted as absent.
MonthSummary summariseMonth(Iterable<AttendanceDay> days, {String? today}) {
  var present = 0, onLeave = 0, absent = 0, other = 0, offs = 0, holidays = 0;
  for (final d in days) {
    if (_isProvisionalToday(d, today)) continue;
    final dayType = d.raw['calendar_day_type'];
    if (dayType == 'WEEKLY_OFF') offs++;
    if (dayType == 'HOLIDAY') holidays++;
    final s = d.attendanceStatus;
    if (_notCounted.contains(s)) continue;
    if (_present.contains(s)) {
      present++;
    } else if (s == 'LEAVE') {
      onLeave++;
    } else if (s == 'ABSENT') {
      absent++;
    } else {
      other++;
    }
  }
  return MonthSummary(present: present, onLeave: onLeave, absent: absent, other: other, weeklyOffs: offs, holidays: holidays);
}

/// Worked hours for Monday..Sunday of the week containing [today] (`YYYY-MM-DD`); no row = 0.
List<({String date, String label, double hours})> weekBars(Iterable<AttendanceDay> days, String today) {
  const labels = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'];
  final t = DateTime.parse(today);
  final monday = DateTime.utc(t.year, t.month, t.day - (t.weekday - 1));
  final byDate = {for (final d in days) d.attendanceDate: d};
  return [
    for (var i = 0; i < 7; i++)
      () {
        final dt = monday.add(Duration(days: i));
        final date = '${dt.year.toString().padLeft(4, '0')}-${dt.month.toString().padLeft(2, '0')}-${dt.day.toString().padLeft(2, '0')}';
        final minutes = byDate[date]?.workedMinutes ?? 0;
        return (date: date, label: labels[i], hours: (minutes / 60 * 10).round() / 10);
      }(),
  ];
}

/// This week's and this month's day rows in one read (the earlier of the two starts).
final homeMonthDaysProvider = FutureProvider.autoDispose.family<List<AttendanceDay>, ({String employeeId, String zone})>((ref, key) {
  final today = businessToday(key.zone);
  final t = DateTime.parse(today);
  final monthStart = DateTime.utc(t.year, t.month, 1);
  final weekStart = DateTime.utc(t.year, t.month, t.day - (t.weekday - 1));
  final from = weekStart.isBefore(monthStart) ? weekStart : monthStart;
  String iso(DateTime d) => '${d.year.toString().padLeft(4, '0')}-${d.month.toString().padLeft(2, '0')}-${d.day.toString().padLeft(2, '0')}';
  return ref.watch(attendanceRepositoryProvider).listAttendanceDays(employeeId: key.employeeId, dateFrom: iso(from), dateTo: today);
});
