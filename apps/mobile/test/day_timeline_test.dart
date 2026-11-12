import 'package:flutter_test/flutter_test.dart';
import 'package:hrms_mobile/features/attendance/data/attendance_repository.dart';
import 'package:hrms_mobile/features/attendance/domain/day_timeline.dart';

/// Web `buildTimeline` / `punchesForDay` in `apps/web/src/lib/attendance/day-detail.test.ts`.

AttendanceDay _day({Map<String, dynamic> over = const {}}) => AttendanceDay.fromJson({
      'id': 'd-1',
      'employee_id': 'e-1',
      'attendance_date': '2026-08-10',
      'attendance_status': 'PRESENT',
      'scheduled_start': '2026-08-10T09:00:00Z',
      'scheduled_end': '2026-08-10T17:00:00Z',
      'is_locked': false,
      ...over,
    });

Punch _punch(String id, String at, String direction, [String source = 'WEB']) =>
    Punch(id: id, employeeId: 'e-1', punchTime: at, direction: direction, source: source);

void main() {
  test('orders punches and break events and labels sources', () {
    final items = buildTimeline(
      _day(),
      [_punch('2', '2026-08-10T17:20:00Z', 'OUT', 'MOBILE'), _punch('1', '2026-08-10T09:25:00Z', 'IN')],
      const [BreakEvent(id: 'b1', eventType: 'START', eventTime: '2026-08-10T13:00:00Z', breakName: 'Lunch', source: 'WEB')],
    );
    expect(items.map((i) => i.label), ['Punched in', 'Break started — Lunch', 'Punched out']);
    expect(items[2].source, 'Mobile app');
  });

  test('ends with a gap marker when the day is missing its punch-out', () {
    final items = buildTimeline(_day(over: {'missing_punch': true}), [_punch('1', '2026-08-10T09:25:00Z', 'IN')], const []);
    expect(items.last.kind, TimelineKind.missingOut);
    expect(items.last.label, 'Punch-out missing');
  });

  test('no gap marker when the last punch is an out', () {
    final items = buildTimeline(
      _day(over: {'missing_punch': true}),
      [_punch('1', '2026-08-10T09:25:00Z', 'IN'), _punch('2', '2026-08-10T17:00:00Z', 'OUT')],
      const [],
    );
    expect(items.any((i) => i.kind == TimelineKind.missingOut), isFalse);
  });

  test("drops punches far outside the day's window", () {
    final kept = punchesForDay([_punch('1', '2026-08-10T09:00:00Z', 'IN'), _punch('2', '2026-08-12T09:00:00Z', 'IN')], _day());
    expect(kept.map((p) => p.id), ['1']);
  });

  test('a day with no window keeps only its own punches, not the next day fetched alongside', () {
    final offDay = _day(over: {'scheduled_start': null, 'scheduled_end': null, 'actual_first_in': null, 'actual_last_out': null});
    final kept = punchesForDay([_punch('1', '2026-08-10T11:00:00Z', 'IN'), _punch('2', '2026-08-11T03:30:00Z', 'IN')], offDay);
    expect(kept.map((p) => p.id), ['1']);
  });

  test('skips a break event with no time and title-cases unknown sources', () {
    final items = buildTimeline(
      _day(),
      [_punch('1', '2026-08-10T09:25:00Z', 'IN', 'KIOSK')],
      const [BreakEvent(id: 'b1', eventType: 'END', eventTime: '', source: 'WEB')],
    );
    expect(items.map((i) => i.label), ['Punched in']);
    expect(items.single.source, 'Kiosk');
  });
}
