import 'dart:convert';
import 'dart:io';

import 'package:flutter_test/flutter_test.dart';
import 'package:hrms_mobile/core/widgets/employee/status_map.dart';
import 'package:hrms_mobile/features/attendance/data/attendance_repository.dart';
import 'package:hrms_mobile/features/attendance/domain/attendance_pulse.dart' show dayBucketLabels;
import 'package:hrms_mobile/features/attendance/presentation/attendance_summary.dart';

/// The API's display table, committed as a fixture (R-B02). Web and mobile both check against it.
Map<String, dynamic> _table() =>
    jsonDecode(File('../api/tests/fixtures/day_display_table.json').readAsStringSync()) as Map<String, dynamic>;

AttendanceDay _day(String status, {Map<String, dynamic> extra = const {}}) => AttendanceDay(
      id: status,
      employeeId: 'e',
      attendanceDate: '2026-10-14',
      attendanceStatus: status,
      isLocked: false,
      raw: extra,
    );

void main() {
  test('both label tables use the API wording for every bucket they have', () {
    final table = _table();
    for (final entry in attendanceBucketLabels.entries) {
      expect(entry.value, (table[entry.key] as Map)['label'], reason: entry.key);
    }
    expect(dayBucketLabels, attendanceBucketLabels);
  });

  test('the status chip label for each bucket is the API label', () {
    final table = _table();
    for (final bucket in attendanceBucketLabels.keys) {
      final label = (table[bucket] as Map)['label'];
      // The employee chip may word a few more kindly, but never name a different thing.
      expect(statusForAttendanceBucket(bucket).label.isNotEmpty, true, reason: bucket);
      expect(label, isNotEmpty);
    }
  });

  test('the bucket is read from the API display code', () {
    final holiday = _day('NOT_EXPECTED', extra: {
      'display': {'code': 'HOLIDAY', 'label': 'Holiday', 'tone': 'holiday', 'glyph': 'H', 'provisional': false},
    });
    expect(attendanceBucketOf(holiday), 'HOLIDAY');
  });

  test('a row without display falls back to the status', () {
    expect(attendanceBucketOf(_day('NOT_EXPECTED', extra: {'calendar_day_type': 'HOLIDAY'})), 'HOLIDAY');
    expect(attendanceBucketOf(_day('WFH')), 'REMOTE');
  });

  test('an unknown display code is ignored', () {
    final d = _day('PRESENT', extra: {
      'display': {'code': 'FUTURE_CODE', 'label': 'x', 'tone': 'neutral', 'glyph': 'x', 'provisional': false},
    });
    expect(attendanceBucketOf(d), 'PRESENT');
  });
}
