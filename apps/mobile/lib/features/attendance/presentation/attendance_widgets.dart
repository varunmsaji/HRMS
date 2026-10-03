import 'package:flutter/material.dart';

import '../../../core/time.dart';
import '../data/attendance_repository.dart';

/// Defensive enum-mapping (the backend's `attendance_status` set isn't frozen client-side) —
/// mirrors the web app's `AttendanceStatusBadge`.
class AttendanceStatusBadge extends StatelessWidget {
  const AttendanceStatusBadge({super.key, required this.status});
  final String status;

  @override
  Widget build(BuildContext context) {
    final scheme = Theme.of(context).colorScheme;
    final Color color = switch (status) {
      'PRESENT' => Colors.green,
      'HALF_DAY' || 'INCOMPLETE' => Colors.amber.shade800,
      'ABSENT' || 'CONFIG_ERROR' => Colors.red,
      'ON_DUTY' || 'WFH' => Colors.blue,
      'LEAVE' => Colors.purple,
      _ => scheme.onSurfaceVariant,
    };
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 3),
      decoration: BoxDecoration(color: color.withValues(alpha: 0.15), borderRadius: BorderRadius.circular(4)),
      child: Text(status.replaceAll('_', ' '), style: TextStyle(color: color, fontSize: 11, fontWeight: FontWeight.w600)),
    );
  }
}

/// One attendance day in a list: date, status, and the times in the day's own zone.
class AttendanceDayTile extends StatelessWidget {
  const AttendanceDayTile({super.key, required this.day, required this.onTap, this.employeeLabel});
  final AttendanceDay day;
  final VoidCallback onTap;
  final String? employeeLabel;

  @override
  Widget build(BuildContext context) {
    final scheme = Theme.of(context).colorScheme;
    final times = day.actualFirstIn == null
        ? 'No punches'
        : '${formatClockTime(day.actualFirstIn, day.timezone)} – ${day.actualLastOut == null ? '…' : formatClockTime(day.actualLastOut, day.timezone)}'
            '${day.workedMinutes != null ? ' · ${formatMinutes(day.workedMinutes)}' : ''}';
    return InkWell(
      onTap: onTap,
      child: Container(
        margin: const EdgeInsets.only(bottom: 8),
        padding: const EdgeInsets.all(12),
        decoration: BoxDecoration(color: scheme.surfaceContainerLowest, borderRadius: BorderRadius.circular(10), border: Border.all(color: scheme.outlineVariant)),
        child: Row(children: [
          Expanded(
            child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
              Text(employeeLabel == null ? day.attendanceDate : '$employeeLabel · ${day.attendanceDate}', style: const TextStyle(fontWeight: FontWeight.w600)),
              const SizedBox(height: 2),
              Text(times, style: TextStyle(fontSize: 12, color: scheme.onSurfaceVariant)),
            ]),
          ),
          AttendanceStatusBadge(status: day.attendanceStatus),
        ]),
      ),
    );
  }
}
