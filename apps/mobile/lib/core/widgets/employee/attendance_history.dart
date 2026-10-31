import 'package:flutter/material.dart';

import '../../../features/attendance/data/attendance_repository.dart';
import '../../../features/attendance/presentation/attendance_summary.dart';
import '../../theme/employee_tokens.dart';
import '../../time.dart';
import 'layout.dart';
import 'status_map.dart';

/// The word shown for a day in history. Today's row is provisional until the employee punches (the
/// 09:30 sweep writes `ABSENT`/`INCOMPLETE` before anyone has), so for [today] it reads "Not punched
/// in yet" and never "Absent" (API matrix §5.1 fact 7). Every other day uses the shared bucket.
String historyStatusLabel(AttendanceDay day, {required String today}) {
  if (day.attendanceDate == today && isNotCheckedIn(day) && !day.isLocked) return 'Not punched in yet';
  return statusForAttendanceBucket(attendanceBucketOf(day)).label;
}

/// "9:30 am – 6:15 pm IST · 8h 45m", "9:30 am – … IST" while open, or "No punches".
String historyCaption(AttendanceDay day) {
  if (day.actualFirstIn == null) return 'No punches';
  final out = day.actualLastOut == null ? '…' : formatClockTime(day.actualLastOut, day.timezone);
  final worked = (day.workedMinutes ?? 0) > 0 ? ' · ${formatMinutes(day.workedMinutes)}' : '';
  return '${formatClockTime(day.actualFirstIn, day.timezone)} – $out$worked';
}

/// "Last 14 days" as one grouped list (T1-06): date block, status word, time range, chevron.
class AttendanceHistoryGroup extends StatelessWidget {
  const AttendanceHistoryGroup({super.key, required this.days, required this.today, required this.onTap, this.margin = EdgeInsets.zero});

  final List<AttendanceDay> days;
  final String today;
  final ValueChanged<AttendanceDay> onTap;
  final EdgeInsetsGeometry margin;

  @override
  Widget build(BuildContext context) => EmployeeListGroup(
        margin: margin,
        children: [
          for (final d in days)
            EmployeeListRow(
              leading: _DateBlock(date: d.attendanceDate),
              title: historyStatusLabel(d, today: today),
              caption: historyCaption(d),
              onTap: () => onTap(d),
            ),
        ],
      );
}

/// Placeholder rows while history loads (the punch bar stays active).
class AttendanceHistorySkeleton extends StatelessWidget {
  const AttendanceHistorySkeleton({super.key, this.rows = 3});
  final int rows;

  @override
  Widget build(BuildContext context) => EmployeeListGroup(
        margin: EdgeInsets.zero,
        children: [
          for (var i = 0; i < rows; i++)
            const Padding(
              padding: EdgeInsets.all(16),
              child: Row(children: [
                SkeletonBlock(width: 44, height: 44, radius: 8),
                SizedBox(width: 12),
                Expanded(child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [SkeletonBlock(width: 120, height: 16), SizedBox(height: 8), SkeletonBlock(width: 180)])),
              ]),
            ),
        ],
      );
}

class _DateBlock extends StatelessWidget {
  const _DateBlock({required this.date});
  final String date;

  @override
  Widget build(BuildContext context) {
    final t = EmployeeTokens.of(context);
    final d = DateTime.tryParse(date);
    const months = ['JAN', 'FEB', 'MAR', 'APR', 'MAY', 'JUN', 'JUL', 'AUG', 'SEP', 'OCT', 'NOV', 'DEC'];
    return ExcludeSemantics(
      child: Container(
        width: 44,
        padding: const EdgeInsets.symmetric(vertical: 6),
        decoration: BoxDecoration(color: t.inset, borderRadius: BorderRadius.circular(EmployeeTokens.radiusControl)),
        child: d == null
            ? Icon(Icons.event_outlined, size: 20, color: t.inkSecondary)
            : Column(mainAxisSize: MainAxisSize.min, children: [
                Text(months[d.month - 1], style: TextStyle(fontSize: 10, fontWeight: FontWeight.w700, letterSpacing: 0.6, color: t.inkSecondary)),
                Text('${d.day}', style: TextStyle(fontSize: 18, fontWeight: FontWeight.w700, height: 1.15, color: t.ink)),
              ]),
      ),
    );
  }
}
