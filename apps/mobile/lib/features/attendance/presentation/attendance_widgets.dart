import 'package:flutter/material.dart';

import '../../../core/time.dart';
import '../../../core/widgets/ui.dart';
import '../data/attendance_repository.dart';

/// Defensive enum-mapping (the backend's `attendance_status` set isn't frozen client-side) —
/// mirrors the web app's `AttendanceStatusBadge`.
class AttendanceStatusBadge extends StatelessWidget {
  const AttendanceStatusBadge({super.key, required this.status});
  final String status;

  @override
  Widget build(BuildContext context) {
    final tone = switch (status) {
      'PRESENT' => Tone.success,
      'HALF_DAY' || 'INCOMPLETE' => Tone.warning,
      'ABSENT' || 'CONFIG_ERROR' => Tone.danger,
      'ON_DUTY' || 'WFH' => Tone.info,
      _ => Tone.neutral,
    };
    return StatusChip(label: humanize(status), tone: tone);
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
    final date = DateTime.tryParse(day.attendanceDate);
    const months = ['JAN', 'FEB', 'MAR', 'APR', 'MAY', 'JUN', 'JUL', 'AUG', 'SEP', 'OCT', 'NOV', 'DEC'];
    return Padding(
      padding: const EdgeInsets.only(bottom: 10),
      child: AppCard(
        onTap: onTap,
        padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 12),
        child: Row(children: [
          Container(
            width: 46,
            padding: const EdgeInsets.symmetric(vertical: 6),
            decoration: BoxDecoration(color: scheme.primary.withValues(alpha: 0.08), borderRadius: BorderRadius.circular(12)),
            child: date == null
                ? const Icon(Icons.event_outlined, size: 20)
                : Column(children: [
                    Text(months[date.month - 1], style: TextStyle(fontSize: 10, fontWeight: FontWeight.w700, letterSpacing: 0.6, color: scheme.primary)),
                    Text('${date.day}', style: TextStyle(fontSize: 18, fontWeight: FontWeight.w800, height: 1.15, color: scheme.onSurface)),
                  ]),
          ),
          const SizedBox(width: 14),
          Expanded(
            child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
              Text(employeeLabel ?? day.attendanceDate, style: const TextStyle(fontWeight: FontWeight.w600)),
              const SizedBox(height: 2),
              Text(times, style: TextStyle(fontSize: 12.5, color: scheme.onSurfaceVariant)),
            ]),
          ),
          AttendanceStatusBadge(status: day.attendanceStatus),
        ]),
      ),
    );
  }
}
