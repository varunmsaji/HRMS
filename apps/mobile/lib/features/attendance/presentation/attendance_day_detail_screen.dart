import 'package:flutter/material.dart';

import '../data/attendance_repository.dart';

/// Mirrors the "Mobile Attendance Day Detail" Stitch screen — one employee's
/// attendance for one day.
class AttendanceDayDetailScreen extends StatelessWidget {
  const AttendanceDayDetailScreen({super.key, required this.day});
  final AttendanceDay day;

  @override
  Widget build(BuildContext context) {
    final scheme = Theme.of(context).colorScheme;
    return Scaffold(
      appBar: AppBar(title: Text(day.attendanceDate)),
      body: ListView(
        padding: const EdgeInsets.all(16),
        children: [
          Container(
            padding: const EdgeInsets.all(16),
            decoration: BoxDecoration(color: scheme.surfaceContainerLowest, borderRadius: BorderRadius.circular(12), border: Border.all(color: scheme.outlineVariant)),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                _row(context, 'Status', day.attendanceStatus.replaceAll('_', ' ')),
                _row(context, 'First in', day.actualFirstIn ?? '—'),
                _row(context, 'Last out', day.actualLastOut ?? '—'),
                _row(context, 'Worked minutes', day.workedMinutes?.toString() ?? '—'),
                _row(context, 'Late minutes', day.lateMinutes?.toString() ?? '—'),
                _row(context, 'Locked', day.isLocked ? 'Yes' : 'No'),
              ],
            ),
          ),
        ],
      ),
    );
  }

  Widget _row(BuildContext context, String label, String value) {
    final scheme = Theme.of(context).colorScheme;
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 6),
      child: Row(
        mainAxisAlignment: MainAxisAlignment.spaceBetween,
        children: [
          Text(label, style: TextStyle(color: scheme.onSurfaceVariant)),
          Text(value),
        ],
      ),
    );
  }
}
