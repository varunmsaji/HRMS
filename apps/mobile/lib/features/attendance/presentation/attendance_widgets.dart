import 'package:flutter/material.dart';

import '../../../core/time.dart';
import '../../../core/widgets/ui.dart';
import '../data/attendance_repository.dart';
import '../domain/mark_day.dart' show canMarkPresent;
import 'mismatch_fixes.dart';

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
  const AttendanceDayTile({super.key, required this.day, required this.onTap, this.employeeLabel, this.onMarkPresent, this.mismatch});
  final AttendanceDay day;
  final VoidCallback onTap;
  final String? employeeLabel;

  /// When set, an absent day with no punches offers "Mark present" (web's Who's in row action).
  /// The caller gates it on `ATTENDANCE.PUNCH_ON_BEHALF`.
  final VoidCallback? onMarkPresent;

  /// What is wrong with the day and how to fix it here. When set it replaces the generic
  /// "Mark present" button, which would only be one of the possible fixes.
  final RowMismatch? mismatch;

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
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Row(children: [
          Container(
            width: 46,
            padding: const EdgeInsets.symmetric(vertical: 6),
            decoration: BoxDecoration(color: scheme.primary.withValues(alpha: 0.08), borderRadius: BorderRadius.circular(12)),
            child: date == null
                ? const Icon(Icons.event_outlined, size: 20)
                : Column(children: [
                    Text(months[date.month - 1], style: TextStyle(fontSize: 11, fontWeight: FontWeight.w700, letterSpacing: 0.6, color: scheme.primary)),
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
        if (mismatch != null) MismatchFixBlock(mismatch: mismatch!),
        if (mismatch == null && onMarkPresent != null && canMarkPresent(status: day.attendanceStatus, firstIn: day.actualFirstIn, lastOut: day.actualLastOut, hasRecord: true))
          Padding(
            padding: const EdgeInsets.only(top: 8),
            child: OutlinedButton(
              style: OutlinedButton.styleFrom(visualDensity: VisualDensity.compact),
              onPressed: onMarkPresent,
              child: const Text('Mark present'),
            ),
          ),
        ]),
      ),
    );
  }
}
