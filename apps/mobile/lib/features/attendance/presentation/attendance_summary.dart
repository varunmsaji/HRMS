import 'package:flutter/material.dart';

import '../data/attendance_repository.dart';
import '../../../core/widgets/ui.dart';

/// Mirrors `bucketOf` / `BUCKET_LABELS` in `apps/web/src/lib/attendance/dashboard.ts`.
const attendanceBucketLabels = {
  'PRESENT': 'Present',
  'REMOTE': 'Remote (WFH)',
  'ON_DUTY': 'On duty',
  'HALF_DAY': 'Half day',
  'ABSENT': 'Absent',
  'LEAVE': 'On leave',
  'INCOMPLETE': 'Incomplete',
  'CONFIG_ERROR': 'Config error',
  'HOLIDAY': 'Holiday',
  'WEEKLY_OFF': 'Weekly off',
  'NON_WORKING': 'Other non-working',
  'NOT_EMPLOYED': 'Not employed',
};

String attendanceBucketOf(AttendanceDay day) {
  switch (day.attendanceStatus) {
    case 'NOT_JOINED':
    case 'EXITED':
      return 'NOT_EMPLOYED';
    case 'PRESENT':
      return 'PRESENT';
    case 'WFH':
      return 'REMOTE';
    case 'ON_DUTY':
      return 'ON_DUTY';
    case 'HALF_DAY':
      return 'HALF_DAY';
    case 'ABSENT':
      return 'ABSENT';
    case 'LEAVE':
      return 'LEAVE';
    case 'INCOMPLETE':
      return 'INCOMPLETE';
    case 'CONFIG_ERROR':
      return 'CONFIG_ERROR';
    case 'NOT_EXPECTED':
      if (day.raw['calendar_day_type'] == 'HOLIDAY') return 'HOLIDAY';
      if (day.raw['calendar_day_type'] == 'WEEKLY_OFF') return 'WEEKLY_OFF';
      return 'NON_WORKING';
    default:
      return 'NON_WORKING';
  }
}

/// Expected to work but no first-in punch (web `isNotCheckedIn`).
bool isNotCheckedIn(AttendanceDay d) {
  final b = attendanceBucketOf(d);
  return (b == 'ABSENT' || b == 'INCOMPLETE') && d.actualFirstIn == null;
}

/// Web `hasException`: missing punch, config error, pending approval or unresolved work-on-leave.
bool hasAttendanceException(AttendanceDay d) =>
    d.raw['missing_punch'] == true ||
    d.attendanceStatus == 'CONFIG_ERROR' ||
    d.raw['is_pending_approval'] == true ||
    (d.raw['work_on_leave_flagged'] == true && d.raw['work_on_leave_resolution'] == null);

/// Counts for the one day's rows the Team attendance list has loaded (the header of that list,
/// like web's "who's in"). The dashboard totals come from `GET /v1/attendance/summary` instead.
class AttendanceSummary {
  AttendanceSummary.compute(List<AttendanceDay> rows) {
    for (final d in rows) {
      final b = attendanceBucketOf(d);
      distribution[b] = (distribution[b] ?? 0) + 1;
      if (b == 'NOT_EMPLOYED') continue;
      employed++;
      if (d.actualFirstIn != null) checkedIn++;
      if ((d.lateMinutes ?? 0) > 0 || d.raw['is_late'] == true) late++;
      if (isNotCheckedIn(d)) notCheckedIn++;
      if (hasAttendanceException(d)) exceptions++;
      final ot = (d.raw['ot_minutes_detected'] as num?)?.toInt() ?? 0;
      if (ot > 0) {
        overtimeEmployees++;
        overtimeMinutes += ot;
      }
    }
  }

  final distribution = <String, int>{};
  int employed = 0;
  int checkedIn = 0;
  int late = 0;
  int notCheckedIn = 0;
  int exceptions = 0;
  int overtimeEmployees = 0;
  int overtimeMinutes = 0;

  int count(String bucket) => distribution[bucket] ?? 0;
  int get present => count('PRESENT') + count('REMOTE') + count('ON_DUTY');
}

String _hm(int minutes) => '${minutes ~/ 60}h ${(minutes % 60).toString().padLeft(2, '0')}m';

/// KPI tiles plus status distribution for the selected day. Tapping a status row calls
/// [onBucketTap] (the screen turns it into a list filter).
class AttendanceSummaryCard extends StatelessWidget {
  const AttendanceSummaryCard({super.key, required this.summary, required this.selectedBucket, required this.onBucketTap});
  final AttendanceSummary summary;
  final String? selectedBucket;
  final ValueChanged<String?> onBucketTap;

  static const _barColors = {
    'PRESENT': Colors.green,
    'REMOTE': Colors.teal,
    'ON_DUTY': Colors.blue,
    'HALF_DAY': Colors.amber,
    'ABSENT': Colors.red,
    'LEAVE': Colors.purple,
    'INCOMPLETE': Colors.orange,
    'CONFIG_ERROR': Colors.deepOrange,
  };

  @override
  Widget build(BuildContext context) {
    final scheme = Theme.of(context).colorScheme;
    final tiles = <(String, String, Color?)>[
      ('Employees', '${summary.employed}', null),
      ('Present', '${summary.present}', Colors.green),
      ('Absent', '${summary.count('ABSENT')}', Colors.red),
      ('On leave', '${summary.count('LEAVE')}', Colors.purple),
      ('Late', '${summary.late}', Colors.orange),
      ('Not checked in', '${summary.notCheckedIn}', Colors.red),
      ('Needs attention', '${summary.exceptions}', Colors.deepOrange),
      ('Overtime', summary.overtimeEmployees == 0 ? '0' : '${summary.overtimeEmployees} · ${_hm(summary.overtimeMinutes)}', null),
    ];
    final entries = [for (final e in attendanceBucketLabels.entries) if (e.key != 'NOT_EMPLOYED' && summary.count(e.key) > 0) e];
    final total = summary.employed == 0 ? 1 : summary.employed;
    return AppCard(
      padding: const EdgeInsets.all(14),
      child: Padding(
        padding: EdgeInsets.zero,
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Wrap(spacing: 8, runSpacing: 8, children: [
            for (final t in tiles)
              Container(
                width: 104,
                padding: const EdgeInsets.all(10),
                decoration: BoxDecoration(color: scheme.surfaceContainerLow, borderRadius: BorderRadius.circular(14)),
                child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                  Text(t.$1, style: TextStyle(fontSize: 11, color: scheme.onSurfaceVariant)),
                  const SizedBox(height: 2),
                  Text(t.$2, style: TextStyle(fontSize: 18, fontWeight: FontWeight.w800, color: t.$3)),
                ]),
              ),
          ]),
          if (entries.isNotEmpty) ...[
            const SizedBox(height: 12),
            Text('Status distribution', style: Theme.of(context).textTheme.titleSmall?.copyWith(fontWeight: FontWeight.w700)),
            for (final e in entries)
              InkWell(
                onTap: () => onBucketTap(selectedBucket == e.key ? null : e.key),
                child: Padding(
                  padding: const EdgeInsets.symmetric(vertical: 4),
                  child: Row(children: [
                    SizedBox(width: 108, child: Text(e.value, style: TextStyle(fontSize: 12, fontWeight: selectedBucket == e.key ? FontWeight.w700 : FontWeight.w400))),
                    Expanded(
                      child: ClipRRect(
                        borderRadius: BorderRadius.circular(3),
                        child: LinearProgressIndicator(
                          value: summary.count(e.key) / total,
                          minHeight: 8,
                          color: _barColors[e.key] ?? scheme.outline,
                          backgroundColor: scheme.surfaceContainerHighest,
                        ),
                      ),
                    ),
                    SizedBox(width: 32, child: Text('${summary.count(e.key)}', textAlign: TextAlign.end, style: const TextStyle(fontSize: 12))),
                  ]),
                ),
              ),
          ],
        ]),
      ),
    );
  }
}
