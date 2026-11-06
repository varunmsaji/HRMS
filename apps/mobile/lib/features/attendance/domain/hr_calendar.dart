import '../../profile/data/employee_repository.dart';
import '../data/attendance_repository.dart';
import '../presentation/attendance_summary.dart';

/// Every employee's attendance for a month — the same rules as the web's `lib/attendance/hr-calendar.ts`.
class HrCalendarRow {
  HrCalendarRow({required this.employeeId, required this.name, this.code});
  final String employeeId;
  final String name;
  final String? code;
  final cells = <String, AttendanceDay>{};
  double present = 0;
  int absent = 0;
  int leave = 0;
  int late = 0;
}

/// Every date of a `YYYY-MM` month, in UTC so a device's timezone can never move one.
List<String> hrMonthDates(String month) {
  final parts = month.split('-').map(int.parse).toList();
  final last = DateTime.utc(parts[0], parts[1] + 1, 0).day;
  return [for (var d = 1; d <= last; d++) '$month-${d.toString().padLeft(2, '0')}'];
}

const _presentBuckets = {'PRESENT', 'REMOTE', 'ON_DUTY', 'HALF_DAY'};

/// One row per employee, even with no records, plus anyone who appears only in the day rows (outside
/// the loaded directory). A half day counts as half.
List<HrCalendarRow> buildHrCalendar(List<AttendanceDay> days, List<Employee> employees, List<String> dates) {
  final inRange = dates.toSet();
  final known = {for (final e in employees) e.id: e};
  final rows = <String, HrCalendarRow>{};
  HrCalendarRow ensure(String id) => rows.putIfAbsent(id, () {
        final e = known[id];
        final name = e == null ? 'Employee' : (e.fullName.isEmpty ? e.employeeCode : e.fullName);
        return HrCalendarRow(employeeId: id, name: name, code: e?.employeeCode);
      });
  for (final e in employees) {
    ensure(e.id);
  }
  for (final day in days) {
    if (!inRange.contains(day.attendanceDate)) continue;
    final row = ensure(day.employeeId)..cells[day.attendanceDate] = day;
    final bucket = attendanceBucketOf(day);
    if (_presentBuckets.contains(bucket)) row.present += bucket == 'HALF_DAY' ? 0.5 : 1;
    if (bucket == 'ABSENT') row.absent += 1;
    if (bucket == 'LEAVE') row.leave += 1;
    if (day.raw['is_late'] == true) row.late += 1;
  }
  return rows.values.toList()..sort((a, b) => a.name.toLowerCase().compareTo(b.name.toLowerCase()));
}

List<HrCalendarRow> filterHrRows(List<HrCalendarRow> rows, String query) {
  final q = query.trim().toLowerCase();
  if (q.isEmpty) return rows;
  return rows.where((r) => r.name.toLowerCase().contains(q) || (r.code ?? '').toLowerCase().contains(q)).toList();
}

/// 6, or 2.5 for a half day.
String formatHrCount(double value) => value == value.roundToDouble() ? value.toInt().toString() : value.toString();
