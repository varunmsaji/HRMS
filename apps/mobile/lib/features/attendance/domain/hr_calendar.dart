import '../../profile/data/employee_repository.dart';
import '../data/attendance_repository.dart';
import '../presentation/attendance_summary.dart';
import 'month_payroll.dart';

/// Every employee's attendance for a month — the same rules as the web's `lib/attendance/hr-calendar.ts`.
class HrCalendarRow {
  HrCalendarRow({required this.employeeId, required this.name, this.code});
  final String employeeId;
  final String name;
  final String? code;
  final cells = <String, AttendanceDay>{};
  double present = 0;
  double absent = 0;
  double leave = 0;
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

/// Replaces each row's totals with the payroll month figures (R-B03), so the list adds up the way
/// payroll will: a half-day leave with the other half worked is half leave and half present, a band
/// half day is half a day. A row without a payroll entry keeps its own totals; the cells stay.
List<HrCalendarRow> withPayrollTotals(List<HrCalendarRow> rows, List<MonthPayroll> payroll) {
  final byId = {for (final p in payroll) p.employeeId: p};
  return [
    for (final row in rows)
      if (byId[row.employeeId] case final p?)
        (HrCalendarRow(employeeId: row.employeeId, name: row.name, code: row.code)
          ..cells.addAll(row.cells)
          ..present = p.presentForGrid
          ..absent = p.absent
          ..leave = p.leave
          ..late = p.lateCount)
      else
        row,
  ];
}

List<HrCalendarRow> filterHrRows(List<HrCalendarRow> rows, String query) {
  final q = query.trim().toLowerCase();
  if (q.isEmpty) return rows;
  return rows.where((r) => r.name.toLowerCase().contains(q) || (r.code ?? '').toLowerCase().contains(q)).toList();
}

/// 6, or 2.5 for a half day.
String formatHrCount(double value) => value == value.roundToDouble() ? value.toInt().toString() : value.toString();

/// The rows with whoever needs a look first: most absent days, then most late arrivals, then by
/// name (the list view; [rows] is not changed).
List<HrCalendarRow> sortByAttention(List<HrCalendarRow> rows) => [...rows]
  ..sort((a, b) {
    final absent = b.absent.compareTo(a.absent);
    if (absent != 0) return absent;
    final late = b.late.compareTo(a.late);
    return late != 0 ? late : a.name.toLowerCase().compareTo(b.name.toLowerCase());
  });
