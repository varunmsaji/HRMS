import 'package:flutter_test/flutter_test.dart';
import 'package:hrms_mobile/features/attendance/data/attendance_repository.dart';
import 'package:hrms_mobile/features/attendance/domain/today_state.dart';

const _zone = 'Asia/Kolkata';
const _today = '2026-10-30';

Punch _punch(String direction, String utcIso) => Punch(id: 'p-$utcIso', employeeId: 'e', punchTime: utcIso, direction: direction, source: 'WEB');

AttendanceDay _day(String status, {String? firstIn, String? lastOut, int worked = 0, String? calculatedAt, bool locked = false, String date = _today, String? dayType}) => AttendanceDay(
      id: 'd',
      employeeId: 'e',
      attendanceDate: date,
      attendanceStatus: status,
      actualFirstIn: firstIn,
      actualLastOut: lastOut,
      workedMinutes: worked,
      isLocked: locked,
      raw: {'calculated_at': calculatedAt, 'calendar_day_type': dayType},
    );

TodayState _resolve({
  bool hasEmployee = true,
  bool loading = false,
  List<Punch>? punches = const [],
  AttendanceDay? day,
  bool dayFailed = false,
}) =>
    resolveTodayState(hasEmployee: hasEmployee, loading: loading, punches: punches, day: day, dayFailed: dayFailed, zone: _zone, today: _today);

// 2026-10-30 09:00 IST = 03:30Z.
const _in0900 = '2026-10-30T03:30:00Z';
const _out1800 = '2026-10-30T12:30:00Z';

void main() {
  windowTests();
  test('0 no employee record', () => expect(_resolve(hasEmployee: false).kind, TodayStateKind.noEmployee));
  test('1 loading', () => expect(_resolve(loading: true).kind, TodayStateKind.loading));

  group('2 no data vs 3 not punched in: missing data is never "absent"', () {
    test('no punches and no row is "no data", not a status', () {
      final s = _resolve();
      expect(s.kind, TodayStateKind.noData);
      expect(s.showRowStatus, isFalse);
      expect(s.day, isNull);
      expect(s.likely, LikelyPunch.punchIn);
    });
    test('no punches and no row, day read FAILED: unavailable (cannot even say "no data")', () {
      expect(_resolve(dayFailed: true).kind, TodayStateKind.unavailable);
    });
    for (final status in ['ABSENT', 'INCOMPLETE']) {
      test('a provisional $status row written by the sweep before any punch is "not punched in" with no status shown', () {
        final s = _resolve(day: _day(status, calculatedAt: '2026-10-30T04:00:00Z'));
        expect(s.kind, TodayStateKind.notPunchedIn);
        expect(s.showRowStatus, isFalse);
        expect(s.day, isNull);
      });
    }
    test('a LOCKED absent row is final, so it is shown', () {
      final s = _resolve(day: _day('ABSENT', locked: true));
      expect(s.kind, TodayStateKind.recorded);
      expect(s.showRowStatus, isTrue);
    });
    test('on duty / WFH with no punch is a recorded status', () {
      expect(_resolve(day: _day('ON_DUTY')).kind, TodayStateKind.recorded);
      expect(_resolve(day: _day('WFH')).kind, TodayStateKind.recorded);
    });
  });

  group('4 punched in / 5 punched out use the NEWEST punch, so several cycles work', () {
    test('IN, OUT, IN (second cycle) -> clocked in; likely action is punch out', () {
      final s = _resolve(
        punches: [_punch('IN', '2026-10-30T13:00:00Z'), _punch('OUT', _out1800), _punch('IN', _in0900)], // order must not matter
        day: _day('PRESENT', firstIn: _in0900, lastOut: _out1800, worked: 540, calculatedAt: '2026-10-30T13:01:00Z'),
      );
      expect(s.kind, TodayStateKind.punchedIn);
      expect(s.lastPunch!.punchTime, '2026-10-30T13:00:00Z');
      expect(s.likely, LikelyPunch.punchOut);
      expect(s.showRowStatus, isFalse, reason: 'an in-progress day shows no status chip');
      expect(s.showWorked, isTrue);
    });
    test('IN then OUT -> punched out; likely action is punch in; status and worked shown', () {
      final s = _resolve(
        punches: [_punch('OUT', _out1800), _punch('IN', _in0900)],
        day: _day('PRESENT', firstIn: _in0900, lastOut: _out1800, worked: 540, calculatedAt: '2026-10-30T12:31:00Z'),
      );
      expect(s.kind, TodayStateKind.punchedOut);
      expect(s.likely, LikelyPunch.punchIn);
      expect(s.showRowStatus, isTrue);
      expect(s.showWorked, isTrue);
    });
    test('forgotten punch-out from yesterday: an open IN is still "punched in", flagged as yesterday, no calculation claim', () {
      final s = _resolve(punches: [_punch('IN', '2026-10-29T12:30:00Z')]); // 6:00 pm IST on the 29th
      expect(s.kind, TodayStateKind.punchedIn);
      expect(s.lastPunchDay, PunchDay.yesterday);
      expect(s.likely, LikelyPunch.punchOut);
      expect(s.day, isNull);
    });
    test('an OUT from yesterday is a closed day, not a punch today', () {
      final s = _resolve(punches: [_punch('OUT', '2026-10-29T12:30:00Z')]);
      expect(s.kind, TodayStateKind.noData);
      expect(s.likely, LikelyPunch.punchIn);
    });
    test('the date uses the company zone: 11:30 pm IST on the 29th is 18:00Z on the 29th, 00:30 IST on the 30th is 19:00Z on the 29th', () {
      final s = _resolve(punches: [_punch('IN', '2026-10-29T19:00:00Z')], day: _day('PRESENT', calculatedAt: '2026-10-29T19:01:00Z'));
      expect(s.lastPunchDay, PunchDay.today, reason: '00:30 IST on the 30th');
      expect(s.kind, TodayStateKind.punchedIn);
    });
  });

  group('6 being calculated (the immediate calculation is best effort)', () {
    test('a punch but no row yet', () {
      final s = _resolve(punches: [_punch('IN', _in0900)]);
      expect(s.kind, TodayStateKind.calculating);
      expect(s.likely, LikelyPunch.punchOut);
      expect(s.showRowStatus, isFalse);
      expect(s.day, isNull);
    });
    test('a row older than the newest punch is stale: no status, no worked time', () {
      final s = _resolve(
        punches: [_punch('OUT', _out1800), _punch('IN', _in0900)],
        day: _day('INCOMPLETE', firstIn: _in0900, calculatedAt: '2026-10-30T03:31:00Z'),
      );
      expect(s.kind, TodayStateKind.calculating);
      expect(s.showRowStatus, isFalse);
      expect(s.showWorked, isFalse);
    });
    test('a row with no calculated_at cannot be proven fresh', () {
      expect(_resolve(punches: [_punch('IN', _in0900)], day: _day('PRESENT')).kind, TodayStateKind.calculating);
    });
  });

  group('the engine\'s explicit verdicts', () {
    test('7 CONFIG_ERROR is "calculation failed", whatever the punches say', () {
      final s = _resolve(punches: [_punch('IN', _in0900)], day: _day('CONFIG_ERROR'));
      expect(s.kind, TodayStateKind.calculationFailed);
      expect(s.showRowStatus, isTrue);
      expect(s.lastPunch, isNotNull, reason: 'raw punch facts remain available');
    });
    test('8 holiday / weekly off', () {
      final s = _resolve(day: _day('NOT_EXPECTED', dayType: 'HOLIDAY'));
      expect(s.kind, TodayStateKind.notWorkingDay);
      expect(s.likely, LikelyPunch.punchIn, reason: 'punching stays possible');
    });
    test('9 on leave', () => expect(_resolve(day: _day('LEAVE')).kind, TodayStateKind.onLeave));
    test('13 not joined / exited', () {
      expect(_resolve(day: _day('NOT_JOINED')).kind, TodayStateKind.notEmployed);
      expect(_resolve(day: _day('EXITED')).kind, TodayStateKind.notEmployed);
    });
  });

  group('10 unavailable / 11 partial: a failed read never becomes a claim', () {
    test('both reads failed', () {
      final s = _resolve(punches: null, dayFailed: true);
      expect(s.kind, TodayStateKind.unavailable);
      expect(s.likely, LikelyPunch.equal, reason: 'two equal buttons, as before');
    });
    test('punches failed, no row', () => expect(_resolve(punches: null).kind, TodayStateKind.unavailable));
    test('punches failed, row present: row facts and no direction hint', () {
      final s = _resolve(punches: null, day: _day('PRESENT', firstIn: _in0900, calculatedAt: '2026-10-30T09:00:00Z'));
      expect(s.kind, TodayStateKind.partial);
      expect(s.likely, LikelyPunch.equal);
    });
  });

  test('both directions are always offered by the UI; the resolver only says which is primary', () {
    expect(LikelyPunch.values, hasLength(3));
  });
}

void windowTests() {
  test('the punch window is one business day either side, so UTC-day filtering cannot cut off today', () {
    final w = todayPunchWindow('Asia/Kolkata', now: DateTime.utc(2026, 10, 30, 20, 0)); // already the 31st in IST
    expect(w.from, '2026-10-30');
    expect(w.to, '2026-11-01');
    final us = todayPunchWindow('America/New_York', now: DateTime.utc(2026, 10, 30, 2, 0)); // still the 29th there
    expect(us.from, '2026-10-28');
    expect(us.to, '2026-10-30');
  });
}
