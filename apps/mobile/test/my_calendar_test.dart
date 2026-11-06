import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:hrms_mobile/core/api/api_error.dart';
import 'package:hrms_mobile/core/auth/permissions.dart';
import 'package:hrms_mobile/core/nav/nav_entries.dart';
import 'package:hrms_mobile/core/providers.dart';
import 'package:hrms_mobile/features/attendance/domain/employee_calendar.dart';
import 'package:hrms_mobile/features/attendance/presentation/my_calendar_screen.dart';

import 'support/fake_api_client.dart';
import 'support/fake_auth.dart';

const _path = '/employee-calendar/me';

Map<String, dynamic> _day(String date, {String? type = 'WORKING', bool configured = true, String? holiday, List<Map<String, dynamic>> leave = const []}) => {
      'date': date,
      'configured': configured,
      'day_type': type,
      'holiday_name': holiday,
      'holiday_type': null,
      'holiday_on_weekly_off': false,
      'is_holiday_named': holiday != null,
      'optional_holiday_name': null,
      'restricted_holiday_name': null,
      'exception_type': null,
      'weekly_off_fraction': type == 'WEEKLY_OFF' ? '1.00' : null,
      'leave': leave,
    };

Map<String, dynamic> _november({String configuration = 'COMPLETE', bool leaveIncluded = true}) {
  final days = <Map<String, dynamic>>[];
  for (final date in datesBetween('2026-10-26', '2026-12-06')) {
    final weekday = DateTime.parse('${date}T00:00:00Z').weekday;
    days.add(switch (date) {
      '2026-11-09' => _day(date, type: 'HOLIDAY', holiday: 'Founders Day'),
      '2026-11-10' => _day(date, leave: [{'status': 'APPROVED', 'fraction': '1.00', 'half': null}]),
      '2026-11-11' => _day(date, leave: [{'status': 'PENDING', 'fraction': '0.50', 'half': 'FIRST_HALF'}]),
      _ => weekday == DateTime.sunday ? _day(date, type: 'WEEKLY_OFF') : _day(date),
    });
  }
  return {'from_date': '2026-10-26', 'to_date': '2026-12-06', 'configuration': configuration, 'leave_included': leaveIncluded, 'days': days};
}

/// Records the query the screen asks for (the base fake drops it).
class _CalendarApi extends FakeApiClient {
  _CalendarApi({super.objects, super.failing});
  final asked = <String>[];

  @override
  Future<T> get<T>(String path, {required T Function(dynamic) parse, bool authenticated = true}) {
    asked.add(path);
    return super.get(path, parse: parse, authenticated: authenticated);
  }
}

Future<_CalendarApi> _pump(WidgetTester tester, {Map<String, dynamic>? calendar, Object? failure, String? employeeId = 'e-1'}) async {
  tester.view.physicalSize = const Size(390, 1400);
  tester.view.devicePixelRatio = 1;
  addTearDown(tester.view.reset);
  final api = _CalendarApi(objects: {_path: calendar ?? _november()}, failing: {if (failure != null) _path: failure});
  await tester.pumpWidget(ProviderScope(
    overrides: [apiClientProvider.overrideWithValue(api), fakeAuth([attendanceView], employeeId: employeeId)],
    child: MaterialApp(home: MyCalendarScreen(now: DateTime.utc(2026, 11, 5, 6))),
  ));
  await tester.pumpAndSettle();
  return api;
}

void main() {
  group('month helpers', () {
    test('the grid runs Monday to Sunday around the month', () {
      expect(monthGridRange('2026-11'), (from: '2026-10-26', to: '2026-12-06'));
      expect(monthGridRange('2027-02'), (from: '2027-02-01', to: '2027-02-28'));
      expect(monthGridRange('2024-02'), (from: '2024-01-29', to: '2024-03-03'));
    });

    test('months cross year ends', () {
      expect(shiftMonthKey('2026-12', 1), '2027-01');
      expect(shiftMonthKey('2026-01', -1), '2025-12');
    });

    test('dates are spelled out without a timezone moving them', () {
      expect(formatLongIsoDate('2026-09-09'), 'Wednesday, 9 September 2026');
      expect(formatMonthKey('2026-10'), 'October 2026');
    });
  });

  group('day labels match the web', () {
    test('an unresolved date is never called working', () {
      final day = EmployeeCalendarDay.fromJson(_day('2026-11-01', type: null, configured: false));
      expect(day.kind, CalendarDayKind.notSetUp);
      expect(day.label, 'Not set up');
    });

    test('a half-day weekly off, and holidays on a working day', () {
      expect(EmployeeCalendarDay.fromJson({..._day('2026-11-01', type: 'WEEKLY_OFF'), 'weekly_off_fraction': '0.50'}).label, 'Half-day weekly off');
      final optional = EmployeeCalendarDay.fromJson({..._day('2026-11-02'), 'optional_holiday_name': 'Diwali'});
      expect(optional.label, 'Working');
      expect(optional.detail, 'Optional holiday: Diwali (still a working day)');
    });

    test('leave says which half, and whether it is approved', () {
      expect(const EmployeeCalendarLeave(status: 'APPROVED', fraction: 1).label, 'Approved leave');
      expect(const EmployeeCalendarLeave(status: 'PENDING', fraction: 0.5, half: 'SECOND_HALF').label, 'Pending leave (second half)');
      expect(const EmployeeCalendarLeave(status: 'APPROVED', fraction: 0.5).label, 'Approved leave (half day)');
    });

    test('the summary counts only the days of the month', () {
      final s = summariseCalendarMonth(EmployeeCalendar.fromJson(_november()), '2026-11');
      expect(s.working, 24);
      expect(s.nonWorking, 6);
      expect(s.approvedLeave, 1);
      expect(s.pendingLeave, 1);
    });
  });

  group('the screen', () {
    testWidgets('opens on this month and asks for the whole Monday-first grid', (tester) async {
      final api = await _pump(tester);
      expect(find.text('November 2026'), findsOneWidget);
      expect(api.asked.single, '$_path?from=2026-10-26&to=2026-12-06');
      expect(find.textContaining('24 working days · 6 non-working · 1 approved leave day · 1 pending leave day'), findsOneWidget);
    });

    testWidgets('tapping a day explains it', (tester) async {
      await _pump(tester);
      await tester.tap(find.bySemanticsLabel(RegExp(r'^Monday, 9 November 2026')));
      await tester.pumpAndSettle();
      expect(find.text('Monday, 9 November 2026'), findsOneWidget);
      expect(find.text('Holiday'), findsOneWidget);
      expect(find.text('Founders Day'), findsOneWidget);
    });

    testWidgets('a day with pending leave says so', (tester) async {
      await _pump(tester);
      await tester.tap(find.bySemanticsLabel(RegExp(r'^Wednesday, 11 November 2026')));
      await tester.pumpAndSettle();
      expect(find.textContaining('Pending leave (first half)'), findsOneWidget);
    });

    testWidgets('moving months asks for that month, and This month comes back', (tester) async {
      final api = await _pump(tester);
      await tester.tap(find.byTooltip('Next month'));
      await tester.pumpAndSettle();
      expect(find.text('December 2026'), findsOneWidget);
      expect(api.asked.last, '$_path?from=2026-11-30&to=2027-01-03');
      await tester.tap(find.text('This month'));
      await tester.pumpAndSettle();
      expect(find.text('November 2026'), findsOneWidget);
    });

    testWidgets('no work calendar: says so instead of showing working days', (tester) async {
      await _pump(tester, calendar: _november(configuration: 'INCOMPLETE'));
      expect(find.text('Your work calendar is not set up yet'), findsOneWidget);
      expect(find.textContaining('working days ·'), findsNothing);
    });

    testWidgets('a part-covered month warns, and hidden leave is explained', (tester) async {
      await _pump(tester, calendar: _november(configuration: 'PARTIAL', leaveIncluded: false));
      expect(find.textContaining('only for part of this month'), findsOneWidget);
      expect(find.text('Leave is not shown for your account.'), findsOneWidget);
    });

    testWidgets('a failure offers a retry', (tester) async {
      await _pump(tester, failure: ApiError(status: 500, code: 'X', message: 'Server trouble'));
      expect(find.text('Server trouble'), findsOneWidget);
      expect(find.text('Retry'), findsOneWidget);
    });

    testWidgets('the company account sees no personal calendar and asks the API nothing', (tester) async {
      final api = await _pump(tester, employeeId: null);
      expect(find.text('No employee record'), findsOneWidget);
      expect(api.asked, isEmpty);
    });

    testWidgets('fits a small phone at large text', (tester) async {
      tester.view.physicalSize = const Size(320, 1400);
      tester.view.devicePixelRatio = 1;
      addTearDown(tester.view.reset);
      await tester.pumpWidget(ProviderScope(
        overrides: [apiClientProvider.overrideWithValue(_CalendarApi(objects: {_path: _november()})), fakeAuth([attendanceView], employeeId: 'e-1')],
        child: MaterialApp(
          builder: (context, child) => MediaQuery(data: MediaQuery.of(context).copyWith(textScaler: const TextScaler.linear(1.5)), child: child!),
          home: MyCalendarScreen(now: DateTime.utc(2026, 11, 5, 6)),
        ),
      ));
      await tester.pumpAndSettle();
      expect(tester.takeException(), isNull);
    });
  });

  group('the menu', () {
    test('an employee and an admin with an employee record get it', () {
      expect(visibleEmployeeEntries([attendanceView]).map((e) => e.route), contains('/app/me/calendar'));
      expect(visibleNavGroups([attendanceView], hasEmployee: true).expand((g) => g.items).map((e) => e.route), contains('/app/me/calendar'));
    });

    test('the company account does not', () {
      expect(visibleNavGroups([attendanceView, employeeViewAll], hasEmployee: false).expand((g) => g.items).map((e) => e.route), isNot(contains('/app/me/calendar')));
    });
  });
}
