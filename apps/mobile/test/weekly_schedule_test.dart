import 'dart:convert';
import 'dart:io';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:hrms_mobile/core/auth/permissions.dart';
import 'package:hrms_mobile/core/providers.dart';
import 'package:hrms_mobile/features/attendance/domain/weekly_schedule.dart';
import 'package:hrms_mobile/features/attendance/presentation/shift_swaps_screen.dart';
import 'package:hrms_mobile/features/attendance/presentation/weekly_schedule_screen.dart';

import 'support/fake_api_client.dart';
import 'support/fake_auth.dart';

Map<String, dynamic> _fixture() => jsonDecode(File('test/fixtures/weekly_schedule.json').readAsStringSync()) as Map<String, dynamic>;

Map<String, dynamic> _party(String id, String name, String shift) => {'employee_id': id, 'name': name, 'code': id.toUpperCase(), 'department': 'Engineering', 'shift_id': 's-$shift', 'shift_name': shift, 'shift_start': '09:00:00', 'shift_end': '17:00:00'};

Map<String, dynamic> _swap({String id = 'w1', String status = 'PENDING', bool consented = false, String requester = 'e1', String counterpart = 'e2'}) => {
      'id': id,
      'reference': 'SW-201',
      'swap_date': '2026-11-10',
      'status': status,
      'reason': 'Dentist',
      'counterpart_consented': consented,
      'coverage_ok': true,
      'requester': _party(requester, 'Asha Rao', 'Day'),
      'counterpart': _party(counterpart, 'Ben Cole', 'Night'),
      'created_at': '2026-11-03T08:00:00Z',
      'decided_at': null,
      'decision_note': null,
    };

Future<void> _pump(WidgetTester tester, FakeApiClient api, List<String> permissions, Widget home, {String employeeId = 'e1'}) async {
  tester.view.physicalSize = const Size(800, 4000);
  tester.view.devicePixelRatio = 1;
  addTearDown(tester.view.reset);
  await tester.pumpWidget(ProviderScope(overrides: [apiClientProvider.overrideWithValue(api), fakeAuth(permissions, employeeId: employeeId)], child: MaterialApp(home: home)));
  await tester.pumpAndSettle();
}

void main() {
  group('weekly schedule parsing', () {
    final schedule = WeeklySchedule.fromJson(_fixture());

    test('reads the totals and shifts', () {
      expect(schedule.totals.coveragePct, 66.7);
      expect(schedule.totals.nightStaff, 2);
      expect(schedule.totals.nightShiftCount, 1);
      expect(schedule.totals.scheduledPct, 80);
      expect(schedule.totals.cellsBelowTarget, 2);
      expect(schedule.totals.pendingSwaps, 1);
      expect(schedule.shifts.map((s) => s.name), ['General', 'Night']);
      expect(schedule.shifts.first.timeRange, '09:00 – 17:00');
      expect(schedule.shifts.last.minStaff, isNull);
    });

    test('a day lists only shifts with people, most staffed first', () {
      final monday = schedule.onDay('2026-11-09');
      expect(monday.map((e) => e.shift.name), ['General', 'Night']);
      expect(schedule.onDay('2026-11-11'), isEmpty);
      expect(schedule.onDay('2026-11-10').single.cell.hasPendingSwap, isTrue);
    });

    test('people beyond the preview are counted as hidden', () {
      final night = schedule.shifts.last.cellOn('2026-11-09')!;
      expect(night.count, 2);
      expect(night.hidden, 1);
    });

    test('date helpers snap to Monday and add days', () {
      expect(mondayOf('2026-11-12'), '2026-11-09');
      expect(mondayOf('2026-11-09'), '2026-11-09');
      expect(addDaysIso('2026-11-30', 1), '2026-12-01');
      expect(longDay('2026-11-10'), 'Tue 10 Nov');
    });
  });

  group('swap rules', () {
    test('only the colleague who has not agreed has an answer to give', () {
      final swap = SwapRequest.fromJson(_swap());
      expect(swap.needsAnswerFrom('e2'), isTrue);
      expect(swap.needsAnswerFrom('e1'), isFalse);
      expect(SwapRequest.fromJson(_swap(consented: true)).needsAnswerFrom('e2'), isFalse);
      expect(SwapRequest.fromJson(_swap(status: 'APPROVED')).needsAnswerFrom('e2'), isFalse);
      expect(swap.needsAnswerFrom(null), isFalse);
    });
  });

  group('schedule screen', () {
    testWidgets('shows totals and a day of shifts with the target', (tester) async {
      final api = FakeApiClient(objects: {'/rosters/weekly-schedule': _fixture()});
      await _pump(tester, api, [attendanceView, attendanceRosterManage], const WeeklyScheduleScreen());
      // Web's four KPI cards, same wording.
      expect(find.text('Rostered staff'), findsOneWidget);
      expect(find.text('80% scheduled'), findsOneWidget);
      expect(find.text('4 of 5 active headcount assigned'), findsOneWidget);
      expect(find.text('Coverage efficiency'), findsOneWidget);
      expect(find.text('67%'), findsOneWidget);
      expect(find.text('2 shift days are below its minimum'), findsOneWidget);
      expect(find.text('Night shift coverage'), findsOneWidget);
      expect(find.text('2 Staff'), findsOneWidget);
      expect(find.text('Rostered across 1 night shift this week'), findsOneWidget);
      expect(find.text('Shift swap requests'), findsOneWidget);
      expect(find.text('Peer swaps awaiting a supervisor decision'), findsOneWidget);
      expect(find.text('What is schedule coverage?'), findsOneWidget);
    });

    testWidgets('department and branch narrow the week', (tester) async {
      final api = FakeApiClient(objects: {'/rosters/weekly-schedule': _fixture()}, lists: {
        '/departments': [
          {'id': 'dep-1', 'name': 'Engineering'},
        ],
        '/branches': [
          {'id': 'br-1', 'name': 'Pune'},
        ],
      });
      final asked = <String>[];
      final spy = _SpyApi(api, asked);
      await _pump(tester, spy, [attendanceView, attendanceRosterManage], const WeeklyScheduleScreen());
      expect(find.text('All Departments (1)'), findsOneWidget);
      expect(find.text('All Branches (1)'), findsOneWidget);
      await tester.tap(find.text('All Departments (1)'));
      await tester.pumpAndSettle();
      await tester.tap(find.text('Engineering').last);
      await tester.pumpAndSettle();
      expect(asked.last, contains('department_id=dep-1'));
      expect(asked.last, isNot(contains('branch_id')));
      await tester.tap(find.text('All Branches (1)'));
      await tester.pumpAndSettle();
      await tester.tap(find.text('Pune').last);
      await tester.pumpAndSettle();
      expect(asked.last, allOf(contains('department_id=dep-1'), contains('branch_id=br-1')));
    });

    testWidgets('a week with nobody rostered says so instead of an empty day', (tester) async {
      final empty = _fixture();
      empty['totals'] = {...(empty['totals'] as Map<String, dynamic>), 'rostered_staff': 0};
      await _pump(tester, FakeApiClient(objects: {'/rosters/weekly-schedule': empty}), [attendanceView], const WeeklyScheduleScreen());
      expect(find.text('No one is rostered for this week.'), findsOneWidget);
    });
  });

  group('swaps screen', () {
    testWidgets('the colleague can agree to a request', (tester) async {
      final api = FakeApiClient(lists: {'/rosters/swap-requests': [_swap()]}, objects: {'/rosters/swap-requests/w1/consent': _swap(consented: true)});
      await _pump(tester, api, [attendanceView], const ShiftSwapsScreen(), employeeId: 'e2');
      expect(find.text('Needs your action'), findsOneWidget);
      await tester.tap(find.text('Agree'));
      await tester.pumpAndSettle();
      expect(api.calls.map((c) => c.path), contains('/rosters/swap-requests/w1/consent'));
    });

    testWidgets('the requester can only withdraw', (tester) async {
      final api = FakeApiClient(lists: {'/rosters/swap-requests': [_swap()]}, objects: {'/rosters/swap-requests/w1/withdraw': _swap(status: 'DECLINED')});
      await _pump(tester, api, [attendanceView], const ShiftSwapsScreen());
      expect(find.text('Agree'), findsNothing);
      await tester.tap(find.text('Withdraw'));
      await tester.pumpAndSettle();
      expect(api.calls.map((c) => c.path), contains('/rosters/swap-requests/w1/withdraw'));
    });

    testWidgets('a manager cannot approve until the colleague has agreed', (tester) async {
      final api = FakeApiClient(lists: {'/rosters/swap-requests': [_swap(requester: 'e8', counterpart: 'e9')]});
      await _pump(tester, api, [attendanceView, attendanceRosterManage], const ShiftSwapsScreen(), employeeId: 'e1');
      expect(find.text('Waiting'), findsOneWidget);
      expect(tester.widget<FilledButton>(find.widgetWithText(FilledButton, 'Approve')).onPressed, isNull);
    });
  });
}

/// Records the full path of each GET (the fake drops the query) and forwards to [inner].
class _SpyApi extends FakeApiClient {
  _SpyApi(FakeApiClient inner, this.asked) : super(lists: inner.lists, objects: inner.objects);
  final List<String> asked;

  @override
  Future<T> get<T>(String path, {required T Function(dynamic) parse, bool authenticated = true}) {
    asked.add(path);
    return super.get(path, parse: parse, authenticated: authenticated);
  }
}
