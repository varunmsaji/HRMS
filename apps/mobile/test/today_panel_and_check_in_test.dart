import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:hrms_mobile/core/widgets/employee/check_in_action.dart';
import 'package:hrms_mobile/core/widgets/employee/today_status_panel.dart';
import 'package:hrms_mobile/features/attendance/data/attendance_repository.dart';
import 'package:hrms_mobile/features/attendance/domain/today_state.dart';

import 'support/test_themes.dart';

const _zone = 'Asia/Kolkata';
const _today = '2026-10-30';

AttendanceDay _row(String status, {String? firstIn, String? calculatedAt, Map<String, dynamic> over = const {}}) => AttendanceDay.fromJson({
      'id': 'd',
      'employee_id': 'e',
      'attendance_date': _today,
      'attendance_status': status,
      'actual_first_in': firstIn,
      'worked_minutes': 95,
      'is_locked': false,
      'calculated_at': calculatedAt,
      ...over,
    });

Punch _p(String direction, String at) => Punch.fromJson({'id': at, 'employee_id': 'e', 'punch_time': at, 'direction': direction, 'source': 'MOBILE'});

TodayState _state({List<Punch>? punches = const [], AttendanceDay? day, bool dayFailed = false}) =>
    resolveTodayState(hasEmployee: true, loading: false, punches: punches, day: day, dayFailed: dayFailed, zone: _zone, today: _today);

Future<void> _pumpPanel(WidgetTester tester, TodayState state, {double width = 390, double scale = 1.0}) => tester.pumpWidget(MaterialApp(
      theme: ThemeData(useMaterial3: true),
      home: MediaQuery(
        data: MediaQueryData(size: Size(width, 800), textScaler: TextScaler.linear(scale)),
        child: Scaffold(body: SingleChildScrollView(child: SizedBox(width: width, child: Padding(padding: const EdgeInsets.all(16), child: TodayStatusPanel(state: state, zone: _zone))))),
      ),
    ));

Finder _filled(String label) => find.ancestor(of: find.text(label), matching: find.byWidgetPredicate((w) => w is FilledButton));

void main() {
  setUpAll(primeThemes);

  group('TodayStatusPanel, one state at a time (API matrix §5.3)', () {
    final cases = <String, (TodayState, String)>{
      'no data': (_state(), 'No attendance recorded yet today.'),
      'not punched in (provisional ABSENT row)': (_state(day: _row('ABSENT')), 'Not punched in yet.'),
      'punched in': (_state(punches: [_p('IN', '2026-10-30T04:00:00Z')], day: _row('INCOMPLETE', firstIn: '2026-10-30T04:00:00Z', calculatedAt: '2026-10-30T04:01:00Z')), 'Punched in at 9:30 am IST'),
      'punched in, row not caught up': (_state(punches: [_p('IN', '2026-10-30T04:00:00Z')]), 'Punched in at 9:30 am IST'),
      'punched out': (_state(punches: [_p('OUT', '2026-10-30T12:00:00Z')], day: _row('PRESENT', firstIn: '2026-10-30T04:00:00Z', calculatedAt: '2026-10-30T12:01:00Z')), 'Punched out at 5:30 pm IST'),
      'forgotten punch-out from yesterday': (_state(punches: [_p('IN', '2026-10-29T04:00:00Z')]), 'Punched in yesterday at 9:30 am IST'),
      'calculation failed': (_state(day: _row('CONFIG_ERROR')), 'We couldn\'t calculate this day. Contact HR.'),
      'holiday': (_state(day: _row('NOT_EXPECTED', over: {'calendar_day_type': 'HOLIDAY', 'holiday_name': 'Diwali'})), 'Holiday: Diwali'),
      'weekly off': (_state(day: _row('NOT_EXPECTED', over: {'calendar_day_type': 'WEEKLY_OFF'})), 'Weekly off'),
      'on leave': (_state(day: _row('LEAVE')), 'On leave'),
      'unavailable': (_state(punches: null, dayFailed: true), 'Today\'s status is unavailable.'),
      'not employed': (_state(day: _row('EXITED')), 'Not employed on this date.'),
    };
    for (final c in cases.entries) {
      testWidgets(c.key, (tester) async {
        await _pumpPanel(tester, c.value.$1);
        expect(find.text(c.value.$2), findsOneWidget);
        expect(tester.takeException(), isNull);
      });
    }

    testWidgets('a provisional ABSENT row never shows the word Absent', (tester) async {
      await _pumpPanel(tester, _state(day: _row('ABSENT')));
      expect(find.textContaining('Absent'), findsNothing);
    });

    testWidgets('a stale row shows no status chip and no worked time', (tester) async {
      await _pumpPanel(tester, _state(punches: [_p('OUT', '2026-10-30T12:00:00Z')], day: _row('PRESENT', calculatedAt: '2026-10-30T05:00:00Z')));
      expect(find.text('Attendance is being calculated.'), findsOneWidget);
      expect(find.text('Present'), findsNothing);
      expect(find.text('Worked'), findsNothing);
    });

    for (final width in [320.0, 360.0, 390.0]) {
      testWidgets('a full panel does not overflow at ${width.toInt()} px and text scale 2.0', (tester) async {
        final state = _state(
          punches: [_p('OUT', '2026-10-30T12:00:00Z')],
          day: _row('PRESENT', firstIn: '2026-10-30T04:00:00Z', calculatedAt: '2026-10-30T12:01:00Z', over: {'actual_last_out': '2026-10-30T12:00:00Z', 'is_late': true, 'late_minutes': 7, 'missing_punch': true}),
        );
        await _pumpPanel(tester, state, width: width, scale: 2.0);
        expect(tester.takeException(), isNull);
      });
    }

    testWidgets('unavailable offers a reload only when a callback is given', (tester) async {
      var reloads = 0;
      await tester.pumpWidget(MaterialApp(home: Scaffold(body: TodayStatusPanel(state: _state(punches: null, dayFailed: true), zone: _zone, onRetry: () => reloads++))));
      await tester.tap(find.text('Reload status'));
      expect(reloads, 1);
    });
  });

  group('CheckInAction', () {
    Future<List<String>> pump(WidgetTester tester, {LikelyPunch likely = LikelyPunch.equal, bool face = false, bool busy = false, bool ready = true, String? busyLabel}) async {
      final taps = <String>[];
      await tester.pumpWidget(MaterialApp(
        home: Scaffold(body: Padding(padding: const EdgeInsets.all(16), child: CheckInAction(likely: likely, faceRequired: face, busy: busy, ready: ready, busyLabel: busyLabel, onPunch: taps.add))),
      ));
      return taps;
    }

    testWidgets('unknown last punch: two equal buttons, both directions reachable', (tester) async {
      final taps = await pump(tester);
      await tester.tap(find.text('Punch in'));
      await tester.tap(find.text('Punch out'));
      expect(taps, ['IN', 'OUT']);
    });

    testWidgets('after an IN the primary is Punch out and Punch in stays reachable', (tester) async {
      final taps = await pump(tester, likely: LikelyPunch.punchOut);
      expect(_filled('Punch out'), findsOneWidget);
      await tester.tap(find.text('Punch in instead'));
      expect(taps, ['IN']);
    });

    testWidgets('after an OUT (or nothing) the primary is Punch in and Punch out stays reachable', (tester) async {
      final taps = await pump(tester, likely: LikelyPunch.punchIn);
      expect(_filled('Punch in'), findsOneWidget);
      await tester.tap(find.text('Punch out instead'));
      expect(taps, ['OUT']);
    });

    testWidgets('face required: only face labels', (tester) async {
      await pump(tester, likely: LikelyPunch.punchIn, face: true);
      expect(find.text('Face punch in'), findsOneWidget);
      expect(find.text('Face punch out instead'), findsOneWidget);
      expect(find.text('Punch in'), findsNothing);
    });

    testWidgets('not ready (face status unknown): both disabled and it says why', (tester) async {
      final taps = await pump(tester, ready: false);
      await tester.tap(find.text('Punch in'), warnIfMissed: false);
      await tester.tap(find.text('Punch out'), warnIfMissed: false);
      expect(taps, isEmpty);
      expect(find.text('Checking your punch options…'), findsOneWidget);
    });

    testWidgets('busy: both disabled, the caption says what is happening', (tester) async {
      final taps = await pump(tester, likely: LikelyPunch.punchOut, busy: true, busyLabel: 'Recording punch…');
      await tester.tap(find.text('Punch out'), warnIfMissed: false);
      await tester.tap(find.text('Punch in instead'), warnIfMissed: false);
      expect(taps, isEmpty);
      expect(find.text('Recording punch…'), findsOneWidget);
    });

    testWidgets('buttons are at least 48 px tall', (tester) async {
      await pump(tester, likely: LikelyPunch.punchIn);
      expect(tester.getSize(_filled('Punch in')).height, greaterThanOrEqualTo(48));
    });
  });
}
