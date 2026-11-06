import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:hrms_mobile/core/api/api_client.dart';
import 'package:hrms_mobile/core/api/api_error.dart';
import 'package:hrms_mobile/core/api/envelope.dart';
import 'package:hrms_mobile/core/auth/permissions.dart';
import 'package:hrms_mobile/core/nav/nav_entries.dart';
import 'package:hrms_mobile/core/providers.dart';
import 'package:hrms_mobile/features/attendance/data/attendance_repository.dart';
import 'package:hrms_mobile/features/attendance/domain/hr_calendar.dart';
import 'package:hrms_mobile/features/attendance/presentation/attendance_calendar_screen.dart';
import 'package:hrms_mobile/features/attendance/presentation/attendance_day_detail_screen.dart';
import 'package:hrms_mobile/features/profile/data/employee_repository.dart';

import 'support/fake_api_client.dart';
import 'support/fake_auth.dart';

final _now = DateTime.utc(2026, 11, 5, 6);

Map<String, dynamic> _person(int n, String first) => {'id': 'e-$n', 'employee_code': 'E$n', 'first_name': first, 'last_name': 'Test', 'display_name': '$first Test', 'status': 'ACTIVE', 'is_active': true, 'version': 1, 'company_id': 'c-1'};

Map<String, dynamic> _day(String id, String who, String date, String status, {bool late = false, String? type}) => {
      'id': id,
      'employee_id': who,
      'attendance_date': date,
      'attendance_status': status,
      'is_locked': false,
      'is_late': late,
      'timezone': 'Asia/Kolkata',
      'calendar_day_type': type,
      'actual_first_in': status == 'PRESENT' ? '2026-11-02T03:45:00Z' : null,
      'actual_last_out': null,
    };

final _days = [
  _day('d1', 'e-1', '2026-11-02', 'PRESENT'),
  _day('d2', 'e-1', '2026-11-03', 'PRESENT', late: true),
  _day('d3', 'e-1', '2026-11-04', 'HALF_DAY'),
  _day('d4', 'e-2', '2026-11-02', 'ABSENT'),
  _day('d5', 'e-2', '2026-11-03', 'LEAVE'),
  _day('d6', 'e-2', '2026-11-01', 'NOT_EXPECTED', type: 'WEEKLY_OFF'),
];

FakeApiClient _api({List<Map<String, dynamic>>? days, Map<String, Object> failing = const {}, int people = 2}) => FakeApiClient(
      lists: {
        '/employees': [_person(1, 'Asha'), _person(2, 'Ben'), for (var i = 3; i <= people; i++) _person(i, 'Person$i')],
        '/attendance/days': days ?? _days,
      },
      objects: {'/attendance/days/d1': _days.first},
      failing: failing,
    );

Future<void> _pump(WidgetTester tester, ApiClient api, {List<String> permissions = const [attendanceViewAll, attendanceView, employeeViewAll], double width = 700, double scale = 1}) async {
  tester.view.physicalSize = Size(width, 2600);
  tester.view.devicePixelRatio = 1;
  addTearDown(tester.view.reset);
  await tester.pumpWidget(ProviderScope(
    overrides: [apiClientProvider.overrideWithValue(api), fakeAuth(permissions)],
    child: MaterialApp(
      builder: (context, c) => MediaQuery(data: MediaQuery.of(context).copyWith(textScaler: TextScaler.linear(scale)), child: c!),
      home: AttendanceCalendarScreen(now: _now),
    ),
  ));
  await tester.pumpAndSettle();
}

class _PagedDays extends FakeApiClient {
  _PagedDays(this.pages, this.total);
  final int pages;
  final int total;
  final asked = <int>[];

  @override
  Future<ListEnvelope<T>> getList<T>(String path, {required T Function(dynamic) parseItem, PageQuery? query, Map<String, dynamic>? filters, bool authenticated = true}) async {
    final page = query?.page ?? 1;
    asked.add(page);
    return ListEnvelope(data: [parseItem(_day('d$page', 'e-1', '2026-11-02', 'PRESENT'))], pagination: PaginationMeta(page: page, perPage: 500, total: total, totalPages: pages), meta: ResponseMeta(requestId: 'r'));
  }
}

void main() {
  group('rules', () {
    final dates = hrMonthDates('2026-11');
    final employees = [Employee.fromJson(_person(2, 'Ben')), Employee.fromJson(_person(1, 'Asha')), Employee.fromJson(_person(3, 'Cy'))];
    final rows = buildHrCalendar(_days.map(AttendanceDay.fromJson).toList(), employees, dates);

    test('a month has its real length', () {
      expect(dates.first, '2026-11-01');
      expect(dates.last, '2026-11-30');
      expect(hrMonthDates('2024-02').last, '2024-02-29');
    });

    test('everyone is listed, by name, even with no records', () {
      expect(rows.map((r) => r.name), ['Asha Test', 'Ben Test', 'Cy Test']);
      expect(rows.last.cells, isEmpty);
    });

    test('totals: a half day counts half, late sits inside present', () {
      final asha = rows.first;
      expect(asha.present, 2.5);
      expect(asha.late, 1);
      expect(formatHrCount(asha.present), '2.5');
      final ben = rows[1];
      expect(ben.absent, 1);
      expect(ben.leave, 1);
      expect(ben.present, 0, reason: 'a weekly off is not presence');
    });

    test('someone outside the loaded directory still appears', () {
      final extra = buildHrCalendar([AttendanceDay.fromJson(_day('x', 'e-9', '2026-11-02', 'PRESENT'))], const [], dates);
      expect(extra.single.name, 'Employee');
    });

    test('a day outside the month is ignored', () {
      final none = buildHrCalendar([AttendanceDay.fromJson(_day('x', 'e-1', '2026-12-02', 'PRESENT'))], [employees[1]], dates);
      expect(none.single.present, 0);
    });

    test('search covers name and code', () {
      expect(filterHrRows(rows, 'ben').single.name, 'Ben Test');
      expect(filterHrRows(rows, 'e3').single.name, 'Cy Test');
      expect(filterHrRows(rows, ' '), rows);
    });

    test('a month is read across pages, up to the bound, and says if more exist', () async {
      final api = _PagedDays(25, 25);
      final result = await AttendanceRepository(api).listMonthDays(dateFrom: '2026-11-01', dateTo: '2026-11-30');
      expect(api.asked.length, 20);
      expect(result.items.length, 20);
      expect(result.total, 25);
    });
  });

  group('screen', () {
    testWidgets('opens on this month with a box per recorded day and totals', (tester) async {
      final api = _api();
      await _pump(tester, api);
      expect(find.text('November 2026'), findsOneWidget);
      expect(api.listCalls.firstWhere((c) => c.path == '/attendance/days').filters, {'date_from': '2026-11-01', 'date_to': '2026-11-30'});
      expect(find.text('Asha Test'), findsOneWidget);
      expect(find.text('2.5'), findsOneWidget);
      expect(find.bySemanticsLabel(RegExp(r'^Ben Test, 2026-11-02: Absent')), findsOneWidget);
    });

    testWidgets('the legend shows only the statuses in use', (tester) async {
      await _pump(tester, _api());
      expect(find.text('Half day'), findsOneWidget);
      expect(find.text('Config error'), findsNothing);
    });

    testWidgets('a future month cannot be opened, and This month comes back', (tester) async {
      final api = _api();
      await _pump(tester, api);
      expect(tester.widget<IconButton>(find.widgetWithIcon(IconButton, Icons.chevron_right)).onPressed, isNull);
      await tester.tap(find.byTooltip('Previous month'));
      await tester.pumpAndSettle();
      expect(find.text('October 2026'), findsOneWidget);
      expect(api.listCalls.last.filters, {'date_from': '2026-10-01', 'date_to': '2026-10-31'});
      await tester.tap(find.text('This month'));
      await tester.pumpAndSettle();
      expect(find.text('November 2026'), findsOneWidget);
    });

    testWidgets('tapping a box opens that day', (tester) async {
      await _pump(tester, _api());
      await tester.tap(find.bySemanticsLabel(RegExp(r'^Asha Test, 2026-11-02: Present')));
      await tester.pumpAndSettle();
      expect(find.byType(AttendanceDayDetailScreen), findsOneWidget);
    });

    testWidgets('search filters the rows', (tester) async {
      await _pump(tester, _api());
      await tester.enterText(find.byType(TextField), 'ben');
      await tester.pumpAndSettle();
      expect(find.text('Asha Test'), findsNothing);
      expect(find.text('Ben Test'), findsOneWidget);
      await tester.enterText(find.byType(TextField), 'zzz');
      await tester.pumpAndSettle();
      expect(find.text('No employees match.'), findsOneWidget);
    });

    testWidgets('a large company shows people in batches', (tester) async {
      await _pump(tester, _api(people: 60));
      expect(find.text('Show more (10 left)'), findsOneWidget);
      await tester.tap(find.text('Show more (10 left)'));
      await tester.pumpAndSettle();
      expect(find.textContaining('Show more'), findsNothing);
    });

    testWidgets('it says when no access was the reason it cannot load', (tester) async {
      await _pump(tester, _api(failing: {'/attendance/days': ApiError(status: 403, code: 'P', message: 'x')}));
      expect(find.text('You do not have permission to view attendance for everyone.'), findsOneWidget);
    });

    testWidgets('without the permission it asks the API nothing', (tester) async {
      final api = _api();
      await _pump(tester, api, permissions: const [attendanceView]);
      expect(find.text('No access'), findsOneWidget);
      expect(api.listCalls, isEmpty);
    });

    testWidgets('fits a small phone at large text', (tester) async {
      await _pump(tester, _api(), width: 320, scale: 2);
      expect(tester.takeException(), isNull);
    });
  });

  testWidgets('without the read grants its calls need it asks the API nothing', (tester) async {
    final api = _api();
    await _pump(tester, api, permissions: const [attendanceViewAll]);
    expect(find.text('No access'), findsOneWidget);
    expect(api.listCalls, isEmpty);
  });

  test('it is in the menu only for those who can view everyone and read what it loads', () {
    List<String> routes(List<String> p) => [for (final g in visibleNavGroups(p)) for (final e in g.items) e.route];
    expect(routes(const [attendanceViewAll, attendanceView, employeeViewAll]), contains('/app/attendance/calendar'));
    // VIEW_ALL alone: /employees and /attendance/days would both answer 403.
    expect(routes(const [attendanceViewAll]), isNot(contains('/app/attendance/calendar')));
    expect(routes(const [attendanceView, employeeViewAll]), isNot(contains('/app/attendance/calendar')));
  });

  test('roster views need the roster read grant', () {
    List<String> routes(List<String> p) => [for (final g in visibleNavGroups(p)) for (final e in g.items) e.route];
    // ROSTER_MANAGE alone: GET /rosters checks ATTENDANCE.VIEW.
    expect(routes(const [attendanceRosterManage]), isNot(contains('/app/rosters')));
    expect(routes(const [attendanceRosterManage]), isNot(contains('/app/roster-calendar')));
    expect(routes(const [attendanceRosterManage, attendanceView]), containsAll(['/app/rosters', '/app/roster-calendar', '/app/schedule']));
  });
}
