import 'dart:convert';
import 'dart:io';

import 'package:flutter_test/flutter_test.dart';
import 'package:hrms_mobile/features/attendance/data/attendance_repository.dart';
import 'package:hrms_mobile/features/attendance/domain/attendance_insights.dart' show isLate;
import 'package:hrms_mobile/features/attendance/domain/attendance_reports.dart';
import 'package:hrms_mobile/features/attendance/presentation/attendance_summary.dart';

/// The shared parity fixture: web (`src/lib/attendance/metrics-parity.test.ts`) and the API's
/// export tally (`tests/unit/modules/attendance/test_report_parity.py`) load the same file and
/// must agree.
Map<String, dynamic> _fixture() =>
    jsonDecode(File('../api/tests/fixtures/attendance_metrics_parity.json').readAsStringSync()) as Map<String, dynamic>;

void main() {
  final fx = _fixture();
  final expected = fx['expected'] as Map<String, dynamic>;
  final days = [for (final d in fx['days'] as List) AttendanceDay.fromJson(d as Map<String, dynamic>)];

  test('puts each day in the same bucket', () {
    final buckets = expected['buckets'] as Map<String, dynamic>;
    for (final d in days) {
      expect(attendanceBucketOf(d), buckets[d.id], reason: d.id);
    }
  });

  test('gives the same Present / absent and Work hours rows', () {
    final got = {
      for (final t in tallyByEmployee(days))
        t.id: {
          'present': t.present,
          'half': t.half,
          'absent': t.absent,
          'leave': t.leave,
          'off': t.off,
          'holiday': t.holiday,
          'incomplete': t.incomplete,
          'days': t.days,
          'worked': t.worked,
          'scheduled': t.scheduled,
        },
    };
    expect(got, expected['tallies']);
  });

  test('lists the same late / early days, and the reports and Team attendance agree on late', () {
    final reports = buildReports(days: days, overtime: const [], name: (id) => id, zone: 'Asia/Kolkata');
    final lateEarly = reports.firstWhere((r) => r.key == 'late_early');
    expect([for (final r in lateEarly.rows) (r as AttendanceDay).id], expected['late_early_day_ids']);
    expect([for (final d in days) if (isLate(d)) d.id], expected['late_day_ids']);
    expect([for (final d in days) if (isLateDay(d)) d.id], expected['late_day_ids']);
  });

  test('adds overtime the same way', () {
    final t = overtimeTotals([for (final o in fx['overtime'] as List) o as Map<String, dynamic>]);
    final want = expected['overtime_totals'] as Map<String, dynamic>;
    expect(t, (found: want['found'], approved: want['approved'], pending: want['pending']));
  });
}
