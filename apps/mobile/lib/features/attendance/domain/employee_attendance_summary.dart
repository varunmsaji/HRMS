import '../data/attendance_repository.dart';
import '../presentation/attendance_summary.dart';

/// One employee's attendance over a range — web `summarizeMonth` in
/// `apps/web/src/lib/attendance/dashboard.ts`. Every figure is read off the backend's day rows.
class AttendanceRangeSummary {
  AttendanceRangeSummary.compute(List<AttendanceDay> rows) {
    for (final d in rows) {
      final b = attendanceBucketOf(d);
      counts[b] = (counts[b] ?? 0) + 1;
      if (d.raw['is_late'] == true) late++;
      if (d.raw['is_early_out'] == true) earlyOut++;
      if (d.raw['missing_punch'] == true) missingPunch++;
      otDetectedMinutes += (d.raw['ot_minutes_detected'] as num?)?.toInt() ?? 0;
      otApprovedMinutes += (d.raw['ot_minutes_approved'] as num?)?.toInt() ?? 0;
      if (d.actualFirstIn != null) workedMinutes += d.workedMinutes ?? 0;
    }
  }

  final counts = <String, int>{};
  int late = 0;
  int earlyOut = 0;
  int missingPunch = 0;
  int otDetectedMinutes = 0;
  int otApprovedMinutes = 0;
  int workedMinutes = 0;

  int count(String bucket) => counts[bucket] ?? 0;
  int get present => count('PRESENT') + count('REMOTE') + count('ON_DUTY');
}

String _addDays(String iso, int days) {
  final d = DateTime.utc(int.parse(iso.substring(0, 4)), int.parse(iso.substring(5, 7)), int.parse(iso.substring(8, 10))).add(Duration(days: days));
  return d.toIso8601String().substring(0, 10);
}

typedef RangePreset = ({String key, String label, String from, String to});

/// Web `rangePresets` (`lib/attendance/day-detail.ts`): last 7 days, this month, last month.
/// [today] is the company's business date, never the device's.
List<RangePreset> attendanceRangePresets(String today) {
  final monthStart = '${today.substring(0, 7)}-01';
  final lastMonthEnd = _addDays(monthStart, -1);
  return [
    (key: '7d', label: 'Last 7 days', from: _addDays(today, -6), to: today),
    (key: 'month', label: 'This month', from: monthStart, to: today),
    (key: 'last-month', label: 'Last month', from: '${lastMonthEnd.substring(0, 7)}-01', to: lastMonthEnd),
  ];
}

/// The first and last date of [month] (`YYYY-MM`), the end capped at [today] (web `monthBounds`).
({String from, String to}) attendanceMonthBounds(String month, String today) {
  final y = int.parse(month.substring(0, 4));
  final m = int.parse(month.substring(5, 7));
  final last = DateTime.utc(y, m + 1, 0).toIso8601String().substring(0, 10);
  return (from: '$month-01', to: last.compareTo(today) > 0 ? today : last);
}

/// Why a day is listed under "Attendance issues" (web `problemLabels` in `employee-month-view.tsx`).
List<String> attendanceProblemLabels(AttendanceDay d) => [
      if (d.raw['missing_punch'] == true) 'Missing punch',
      if (d.attendanceStatus == 'CONFIG_ERROR') 'Config error',
      if (d.attendanceStatus == 'INCOMPLETE') 'Incomplete',
      if (d.raw['is_pending_approval'] == true) 'Pending approval',
      if (d.raw['work_on_leave_flagged'] == true && d.raw['work_on_leave_resolution'] == null) 'Work on leave',
    ];

/// Web `presenceOf` + `PRESENCE_LABELS`: what the last calculation says about today.
String attendancePresenceLabel(AttendanceDay d) {
  if (d.actualFirstIn == null) return isNotCheckedIn(d) ? 'Not checked in' : '—';
  if (d.actualLastOut != null) return 'Checked out';
  final breaks = ((d.raw['breaks'] as List?) ?? const []).cast<Map<String, dynamic>>();
  return breaks.any((b) => b['break_start'] != null && b['break_end'] == null) ? 'On break' : 'Working';
}
