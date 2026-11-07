import '../../../core/time.dart';
import '../data/attendance_repository.dart';
import '../presentation/attendance_summary.dart' show attendanceBucketOf;
import 'attendance_insights.dart';
import 'attendance_pulse.dart';

/// The read-only reports of the web attendance dashboard (`components/attendance/dashboard/
/// reports-panel.tsx`): the same six reports, columns, search, sort and 15-row pages, over data the
/// dashboard already loaded. Like web there is no export: the backend has no export endpoint for
/// these yet.

typedef Rec = Map<String, dynamic>;

/// One column: its heading, how a row shows in it, and what it sorts by.
class ReportColumn {
  const ReportColumn(this.key, this.label, this.render, this.sort, {this.numeric = false});
  final String key;
  final String label;
  final String Function(dynamic row) render;
  final Comparable<Object> Function(dynamic row) sort;

  /// Right-aligned on web; on a phone it marks a figure rather than text.
  final bool numeric;
}

class ReportDef {
  const ReportDef({required this.key, required this.label, required this.rows, required this.columns, required this.rowKey, required this.searchText, required this.empty, this.titleColumns = 1});
  final String key;
  final String label;
  final List<dynamic> rows;
  final List<ReportColumn> columns;
  final String Function(dynamic row) rowKey;
  final String Function(dynamic row) searchText;
  final String empty;

  /// How many leading columns make up a row's title on a phone (e.g. date and employee).
  final int titleColumns;
}

/// Web report keys and labels, in web order.
const reportLabels = {
  'daily': 'Daily attendance',
  'present_absent': 'Present / absent',
  'late_early': 'Late / early',
  'hours': 'Work hours',
  'overtime': 'Overtime',
  'payroll': 'Payroll attendance',
};

/// Rows per page, as on web.
const reportPageSize = 15;

/// One page of a report after search and sort. [page] is clamped to what exists.
({List<dynamic> rows, int total, int page, int pages}) reportView(ReportDef def, {String query = '', String? sortKey, bool ascending = true, int page = 1}) {
  final q = query.trim().toLowerCase();
  final filtered = q.isEmpty ? def.rows : def.rows.where((r) => def.searchText(r).toLowerCase().contains(q)).toList();
  final col = def.columns.firstWhere((c) => c.key == sortKey, orElse: () => def.columns.first);
  final sorted = [...filtered]..sort((a, b) => ascending ? col.sort(a).compareTo(col.sort(b)) : col.sort(b).compareTo(col.sort(a)));
  final pages = sorted.isEmpty ? 1 : (sorted.length + reportPageSize - 1) ~/ reportPageSize;
  final current = page.clamp(1, pages);
  return (rows: sorted.skip((current - 1) * reportPageSize).take(reportPageSize).toList(), total: sorted.length, page: current, pages: pages);
}

int _int(Rec r, String key) => (r[key] as num?)?.toInt() ?? 0;
int _dayInt(AttendanceDay d, String key) => (d.raw[key] as num?)?.toInt() ?? 0;
bool _dayFlag(AttendanceDay d, String key) => d.raw[key] == true;
String _bucketLabel(AttendanceDay d) => dayBucketLabels[attendanceBucketOf(d)] ?? attendanceBucketOf(d);

/// Per-employee tallies over the range (web `perEmployee`).
class EmployeeTally {
  EmployeeTally(this.id);
  final String id;
  int present = 0;
  int absent = 0;
  int leave = 0;
  int half = 0;
  int worked = 0;
  int scheduled = 0;

  /// Days with an IN punch — the base for hours.
  int days = 0;
}

List<EmployeeTally> tallyByEmployee(List<AttendanceDay> rows) {
  final map = <String, EmployeeTally>{};
  for (final d in rows) {
    final e = map.putIfAbsent(d.employeeId, () => EmployeeTally(d.employeeId));
    final b = attendanceBucketOf(d);
    if (b == 'PRESENT' || b == 'REMOTE' || b == 'ON_DUTY') e.present += 1;
    if (b == 'ABSENT') e.absent += 1;
    if (b == 'LEAVE') e.leave += 1;
    if (b == 'HALF_DAY') e.half += 1;
    if (d.actualFirstIn != null) {
      e.days += 1;
      e.worked += workedMinutes(d);
      e.scheduled += _dayInt(d, 'scheduled_minutes');
    }
  }
  return map.values.toList();
}

const overtimeStatusLabels = {'PENDING': 'Pending', 'AUTO_APPROVED': 'Auto-approved', 'APPROVED': 'Approved', 'REJECTED': 'Rejected'};

/// The five reports built from the range's days and overtime records. The payroll report reads a
/// period summary and is built by [payrollReport] once that has loaded.
List<ReportDef> buildReports({required List<AttendanceDay> days, required List<Rec> overtime, required String Function(String id) name, required String zone}) {
  final tallies = tallyByEmployee(days);
  ReportColumn nameCol<T>(String Function(T) id) => ReportColumn('name', 'Employee', (r) => name(id(r as T)), (r) => name(id(r as T)).toLowerCase());
  final dayDate = ReportColumn('date', 'Date', (r) => shortDate((r as AttendanceDay).attendanceDate), (r) => (r as AttendanceDay).attendanceDate);
  final dayName = nameCol<AttendanceDay>((d) => d.employeeId);
  final tallyName = nameCol<EmployeeTally>((e) => e.id);
  return [
    ReportDef(
      key: 'daily',
      label: reportLabels['daily']!,
      rows: days,
      titleColumns: 2,
      rowKey: (r) => (r as AttendanceDay).id,
      searchText: (r) => '${name((r as AttendanceDay).employeeId)} ${_bucketLabel(r)}',
      empty: 'No attendance days in this range.',
      columns: [
        dayDate,
        dayName,
        ReportColumn('status', 'Status', (r) => _bucketLabel(r as AttendanceDay), (r) => _bucketLabel(r as AttendanceDay)),
        ReportColumn('in', 'In', (r) => formatClockTime((r as AttendanceDay).actualFirstIn, zone), (r) => (r as AttendanceDay).actualFirstIn ?? ''),
        ReportColumn('out', 'Out', (r) => formatClockTime((r as AttendanceDay).actualLastOut, zone), (r) => (r as AttendanceDay).actualLastOut ?? ''),
        ReportColumn('worked', 'Worked', (r) => formatMinutes(workedMinutes(r as AttendanceDay)), (r) => workedMinutes(r as AttendanceDay), numeric: true),
      ],
    ),
    ReportDef(
      key: 'present_absent',
      label: reportLabels['present_absent']!,
      rows: tallies,
      rowKey: (r) => (r as EmployeeTally).id,
      searchText: (r) => name((r as EmployeeTally).id),
      empty: 'No attendance days in this range.',
      columns: [
        tallyName,
        ReportColumn('present', 'Present', (r) => '${(r as EmployeeTally).present}', (r) => (r as EmployeeTally).present, numeric: true),
        ReportColumn('half', 'Half day', (r) => '${(r as EmployeeTally).half}', (r) => (r as EmployeeTally).half, numeric: true),
        ReportColumn('absent', 'Absent', (r) => '${(r as EmployeeTally).absent}', (r) => (r as EmployeeTally).absent, numeric: true),
        ReportColumn('leave', 'Leave', (r) => '${(r as EmployeeTally).leave}', (r) => (r as EmployeeTally).leave, numeric: true),
      ],
    ),
    ReportDef(
      key: 'late_early',
      label: reportLabels['late_early']!,
      rows: [for (final d in days) if (isLate(d) || _dayFlag(d, 'is_early_out')) d],
      titleColumns: 2,
      rowKey: (r) => (r as AttendanceDay).id,
      searchText: (r) => name((r as AttendanceDay).employeeId),
      empty: 'No late arrivals or early departures in this range.',
      columns: [
        dayDate,
        dayName,
        ReportColumn('late', 'Late (min)', (r) => isLate(r as AttendanceDay) ? '${lateMinutesOf(r)}' : '—', (r) => isLate(r as AttendanceDay) ? lateMinutesOf(r) : -1, numeric: true),
        ReportColumn(
          'early',
          'Early out (min)',
          (r) => _dayFlag(r as AttendanceDay, 'is_early_out') ? '${_dayInt(r, 'early_departure_minutes')}' : '—',
          (r) => _dayFlag(r as AttendanceDay, 'is_early_out') ? _dayInt(r, 'early_departure_minutes') : -1,
          numeric: true,
        ),
      ],
    ),
    ReportDef(
      key: 'hours',
      label: reportLabels['hours']!,
      rows: [for (final e in tallies) if (e.days > 0) e],
      rowKey: (r) => (r as EmployeeTally).id,
      searchText: (r) => name((r as EmployeeTally).id),
      empty: 'No worked hours in this range.',
      columns: [
        tallyName,
        ReportColumn('days', 'Days', (r) => '${(r as EmployeeTally).days}', (r) => (r as EmployeeTally).days, numeric: true),
        ReportColumn('worked', 'Worked', (r) => formatMinutes((r as EmployeeTally).worked), (r) => (r as EmployeeTally).worked, numeric: true),
        ReportColumn('avg', 'Average', (r) => formatMinutes(((r as EmployeeTally).worked / r.days).round()), (r) => (r as EmployeeTally).worked / r.days, numeric: true),
        ReportColumn('scheduled', 'Scheduled', (r) => formatMinutes((r as EmployeeTally).scheduled), (r) => (r as EmployeeTally).scheduled, numeric: true),
      ],
    ),
    ReportDef(
      key: 'overtime',
      label: reportLabels['overtime']!,
      rows: overtime,
      titleColumns: 2,
      rowKey: (r) => '${(r as Rec)['id']}',
      searchText: (r) => name('${(r as Rec)['employee_id']}'),
      empty: 'No overtime recorded for this range.',
      columns: [
        ReportColumn('date', 'Date', (r) => shortDate('${(r as Rec)['attendance_date']}'), (r) => '${(r as Rec)['attendance_date']}'),
        nameCol<Rec>((r) => '${r['employee_id']}'),
        ReportColumn('class', 'Day class', (r) => (r as Rec)['day_class'] == null ? '—' : overtimeDayClassLabels[r['day_class']] ?? '${r['day_class']}', (r) => '${(r as Rec)['day_class'] ?? ''}'),
        ReportColumn('detected', 'Detected', (r) => formatMinutes(_int(r as Rec, 'minutes_detected')), (r) => _int(r as Rec, 'minutes_detected'), numeric: true),
        ReportColumn('approved', 'Approved', (r) => formatMinutes(_int(r as Rec, 'minutes_approved')), (r) => _int(r as Rec, 'minutes_approved'), numeric: true),
        ReportColumn('status', 'Status', (r) => overtimeStatusLabels[(r as Rec)['status']] ?? '${r['status']}', (r) => '${(r as Rec)['status']}'),
      ],
    ),
  ];
}

/// Payroll attendance: the period summary per employee, as payroll will read it. Day counts are
/// shown as the backend sends them (decimal strings); an unknown payable/paid count sorts first.
ReportDef payrollReport(List<Rec> summary, String Function(String id) name) {
  double num(Object? v) => v == null ? -1 : double.tryParse('$v') ?? -1;
  int ot(Rec r) => _int(r, 'ot_minutes_normal') + _int(r, 'ot_minutes_weekly_off') + _int(r, 'ot_minutes_holiday') + _int(r, 'ot_minutes_night');
  ReportColumn day(String key, String label, String field) =>
      ReportColumn(key, label, (r) => (r as Rec)[field] == null ? '—' : '${r[field]}', (r) => num((r as Rec)[field]), numeric: true);
  return ReportDef(
    key: 'payroll',
    label: reportLabels['payroll']!,
    rows: summary,
    rowKey: (r) => '${(r as Rec)['employee_id']}',
    searchText: (r) => name('${(r as Rec)['employee_id']}'),
    empty: 'No employees in this period summary.',
    columns: [
      ReportColumn('name', 'Employee', (r) => name('${(r as Rec)['employee_id']}'), (r) => name('${(r as Rec)['employee_id']}').toLowerCase()),
      day('payable', 'Payable', 'payable_days'),
      day('paid', 'Paid', 'paid_days'),
      day('present', 'Present', 'present_days'),
      day('absent', 'Absent', 'absent_days'),
      day('leave', 'Leave', 'leave_days'),
      day('lop', 'LOP', 'lop_days'),
      ReportColumn('ot', 'OT', (r) => formatMinutes(ot(r as Rec)), (r) => ot(r as Rec), numeric: true),
    ],
  );
}
