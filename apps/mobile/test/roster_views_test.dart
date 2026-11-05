import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:hrms_mobile/core/api/api_client.dart';
import 'package:hrms_mobile/core/api/api_error.dart';
import 'package:hrms_mobile/core/api/envelope.dart';
import 'package:hrms_mobile/core/auth/permissions.dart';
import 'package:hrms_mobile/core/providers.dart';
import 'package:hrms_mobile/features/attendance/data/roster_repository.dart';
import 'package:hrms_mobile/features/attendance/domain/roster_views.dart';
import 'package:hrms_mobile/features/attendance/presentation/shift_board_screen.dart';
import 'package:hrms_mobile/features/attendance/presentation/workforce_roster_screen.dart';

import 'support/fake_api_client.dart';
import 'support/fake_auth.dart';

final _now = DateTime.utc(2026, 11, 5, 6); // a Thursday
const _day = '2026-11-05';

Map<String, dynamic> _employee(int n) => {'id': 'e-$n', 'employee_code': 'E$n', 'first_name': 'Person', 'last_name': '$n', 'display_name': 'Person $n', 'status': 'ACTIVE', 'is_active': true, 'version': 1, 'company_id': 'c-1'};
const _general = {'id': 'sh-1', 'name': 'General', 'code': 'GEN', 'is_active': true};
const _night = {'id': 'sh-2', 'name': 'Night', 'code': 'NGT', 'is_active': true, 'is_night_shift': true};
Map<String, dynamic> _entry(String id, String employee, {String date = _day, String? shift = 'sh-1', bool off = false, bool holiday = false, String status = 'PUBLISHED', int version = 3}) => {
      'id': id,
      'employee_id': employee,
      'roster_date': date,
      'shift_id': shift,
      'is_week_off_override': off,
      'is_holiday_working_override': holiday,
      'status': status,
      'version': version,
    };

FakeApiClient _api({List<Map<String, dynamic>> entries = const [], Map<String, Object> failing = const {}, Map<String, Map<String, dynamic>> objects = const {}, int people = 3}) => FakeApiClient(
      lists: {
        '/shifts': const [_general, _night],
        '/employees': [for (var i = 1; i <= people; i++) _employee(i)],
        '/rosters': entries,
      },
      objects: objects,
      failing: failing,
    );

Future<void> _pump(WidgetTester tester, ApiClient api, Widget child, {List<String> permissions = const [attendanceRosterManage, employeeViewAll], Size size = const Size(390, 2400), double scale = 1}) async {
  tester.view.physicalSize = size;
  tester.view.devicePixelRatio = 1;
  addTearDown(tester.view.reset);
  await tester.pumpWidget(ProviderScope(
    overrides: [apiClientProvider.overrideWithValue(api), fakeAuth(permissions)],
    child: MaterialApp(
      builder: (context, c) => MediaQuery(data: MediaQuery.of(context).copyWith(textScaler: TextScaler.linear(scale)), child: c!),
      home: child,
    ),
  ));
  await tester.pumpAndSettle();
}

/// Records each entry returned for a page, and pages through them as the server does.
class _PagedRosters extends FakeApiClient {
  _PagedRosters(this.pages, this.total);
  final int pages;
  final int total;
  final asked = <int>[];

  @override
  Future<ListEnvelope<T>> getList<T>(String path, {required T Function(dynamic) parseItem, PageQuery? query, Map<String, dynamic>? filters, bool authenticated = true}) async {
    final page = query?.page ?? 1;
    asked.add(page);
    return ListEnvelope(
      data: [parseItem(_entry('r-$page', 'e-$page'))],
      pagination: PaginationMeta(page: page, perPage: query?.perPage ?? 500, total: total, totalPages: pages),
      meta: ResponseMeta(requestId: 'r'),
    );
  }
}

void main() {
  group('rules', () {
    test('which column someone is in', () {
      expect(boardColumnOf(null), unassignedColumn);
      expect(boardColumnOf(RosterEntry.fromJson(_entry('r', 'e'))), 'sh-1');
      expect(boardColumnOf(RosterEntry.fromJson(_entry('r', 'e', off: true, shift: null))), weekOffColumn);
      expect(boardColumnOf(RosterEntry.fromJson(_entry('r', 'e', shift: null))), unassignedColumn);
    });

    test('cell labels', () {
      final shifts = {'sh-1': RosterShift.fromJson(_general)};
      expect(rosterCellLabel(RosterEntry.fromJson(_entry('r', 'e')), shifts), 'GEN');
      expect(rosterCellLabel(RosterEntry.fromJson(_entry('r', 'e', holiday: true)), shifts), 'GEN*');
      expect(rosterCellLabel(RosterEntry.fromJson(_entry('r', 'e', off: true)), shifts), 'OFF');
      expect(rosterCellLabel(RosterEntry.fromJson(_entry('r', 'e', shift: 'gone')), shifts), '—');
    });

    test('coverage counts per day and per person, week off last', () {
      final rows = buildRosterCoverage(
        [
          RosterEntry.fromJson(_entry('1', 'a')),
          RosterEntry.fromJson(_entry('2', 'b')),
          RosterEntry.fromJson(_entry('3', 'a', date: '2026-11-06')),
          RosterEntry.fromJson(_entry('4', 'c', off: true, shift: null)),
          RosterEntry.fromJson(_entry('5', 'd', shift: null)),
          RosterEntry.fromJson(_entry('6', 'e', date: '2026-12-25')),
        ],
        const [_day, '2026-11-06'],
        {'sh-1': RosterShift.fromJson(_general)},
      );
      expect(rows.map((r) => r.label), ['General', 'Week off']);
      expect(rows.first.byDate, {_day: 2, '2026-11-06': 1});
      expect(rows.first.people, 2);
    });

    test('dates do not move across a month end, and a week starts on Monday', () {
      expect(addDaysIso('2026-11-30', 1), '2026-12-01');
      expect(mondayOfIso(_day), '2026-11-02');
      expect(mondayOfIso('2026-11-02'), '2026-11-02');
      expect(mondayOfIso('2026-11-08'), '2026-11-02');
    });

    test('a range is read across pages, up to the bound, and says if more exist', () async {
      final api = _PagedRosters(12, 12);
      final range = await RosterRepository(api).listEntries(_day, _day);
      expect(api.asked.length, 10);
      expect(range.entries.length, 10);
      expect(range.total, 12);
    });
  });

  group('moving someone', () {
    final saved = _entry('r-9', 'e-1', status: 'DRAFT', version: 1);
    final published = _entry('r-9', 'e-1', version: 2);

    test('a new assignment is created and published at once', () async {
      final api = _api(objects: {'/rosters': saved, '/rosters/r-9/publish': published});
      final result = await RosterRepository(api).moveEmployee(employeeId: 'e-1', date: _day, existing: null, target: 'sh-1');
      expect(api.calls.first.method, 'POST');
      expect(api.calls.first.body, {'employee_id': 'e-1', 'roster_date': _day, 'shift_id': 'sh-1', 'is_week_off_override': false});
      expect(api.calls.last.path, '/rosters/r-9/publish');
      expect(api.calls.last.ifMatch, '1');
      expect(result?.status, 'PUBLISHED');
    });

    test('an existing entry is changed against its version', () async {
      final api = _api(objects: {'/rosters/r-1': _entry('r-1', 'e-1', off: true, shift: null, version: 4)});
      await RosterRepository(api).moveEmployee(employeeId: 'e-1', date: _day, existing: RosterEntry.fromJson(_entry('r-1', 'e-1')), target: weekOffColumn);
      expect(api.calls.single.method, 'PATCH');
      expect(api.calls.single.ifMatch, '3');
      expect(api.calls.single.body, {'shift_id': null, 'is_week_off_override': true});
    });

    test('back to Unassigned removes the entry', () async {
      final api = _api();
      final result = await RosterRepository(api).moveEmployee(employeeId: 'e-1', date: _day, existing: RosterEntry.fromJson(_entry('r-1', 'e-1')), target: unassignedColumn);
      expect(api.calls.single.method, 'DELETE');
      expect(result, isNull);
    });
  });

  group('shift board', () {
    Widget screen() => ShiftBoardScreen(now: _now);

    testWidgets('sorts people into columns, with counts', (tester) async {
      await _pump(tester, _api(entries: [_entry('r-1', 'e-1'), _entry('r-2', 'e-2', off: true, shift: null)]), screen());
      expect(find.text('5 Nov 2026'), findsOneWidget);
      expect(find.text('Unassigned'), findsOneWidget);
      expect(find.text('General'), findsOneWidget, reason: 'the frozen legacy shift times are not repeated under it');
      expect(find.text('Week off'), findsOneWidget);
      final general = tester.getTopLeft(find.text('General')).dy;
      expect(tester.getTopLeft(find.text('Person 1')).dy, greaterThan(general));
      expect(find.text('No one'), findsOneWidget, reason: 'Night has nobody');
    });

    testWidgets('search narrows the people shown', (tester) async {
      await _pump(tester, _api(), screen());
      await tester.enterText(find.byType(TextField), 'E2');
      await tester.pumpAndSettle();
      expect(find.text('Person 2'), findsOneWidget);
      expect(find.text('Person 1'), findsNothing);
    });

    testWidgets('a manager taps someone, picks a shift, and can undo it', (tester) async {
      final api = _api(objects: {
        '/rosters': _entry('r-9', 'e-1', status: 'DRAFT', version: 1),
        '/rosters/r-9/publish': _entry('r-9', 'e-1', version: 2),
      });
      await _pump(tester, api, screen());
      await tester.tap(find.text('Person 1'));
      await tester.pumpAndSettle();
      expect(find.text('Move Person 1 to'), findsOneWidget);
      await tester.tap(find.text('General').last);
      await tester.pumpAndSettle();
      expect(api.calls.map((c) => c.path), ['/rosters', '/rosters/r-9/publish']);

      await tester.tap(find.text('Undo: Person 1'));
      await tester.pumpAndSettle();
      expect(api.calls.last.method, 'DELETE');
      expect(api.calls.last.path, '/rosters/r-9');
      expect(api.calls.last.ifMatch, '2');
      expect(find.text('Undo'), findsOneWidget);
    });

    testWidgets('someone without roster permission can look but not move', (tester) async {
      final api = _api();
      await _pump(tester, api, screen(), permissions: const [attendanceViewAll, employeeViewAll]);
      await tester.tap(find.text('Person 1'));
      await tester.pumpAndSettle();
      expect(find.text('Move Person 1 to'), findsNothing);
      expect(find.text('Copy to next day'), findsNothing);
      expect(api.calls, isEmpty);
    });

    testWidgets('a failed move says so and reloads', (tester) async {
      final client = _EmptyRosters(lists: _api().lists, failing: {'/rosters': ApiError(status: 422, code: 'X', message: 'Period is locked')});
      await _pump(tester, client, screen());
      await tester.tap(find.text('Person 1'));
      await tester.pumpAndSettle();
      await tester.tap(find.text('General').last);
      await tester.pumpAndSettle();
      expect(find.text('Could not change shift: Period is locked'), findsOneWidget);
      expect(find.text('Undo'), findsOneWidget);
    });

    testWidgets('moving days asks for that day', (tester) async {
      final api = _api();
      await _pump(tester, api, screen());
      await tester.tap(find.byTooltip('Next day'));
      await tester.pumpAndSettle();
      expect(find.text('6 Nov 2026'), findsOneWidget);
      expect(api.listCalls.lastWhere((c) => c.path == '/rosters').filters, {'date_from': '2026-11-06', 'date_to': '2026-11-06'});
    });

    testWidgets('copy asks first, then copies published entries to the next day', (tester) async {
      final api = _EmptyRosters(lists: _api().lists, onDay: [_entry('r-1', 'e-1')], objects: {
        '/rosters': _entry('r-5', 'e-1', date: '2026-11-06', status: 'DRAFT', version: 1),
        '/rosters/r-5/publish': _entry('r-5', 'e-1', date: '2026-11-06', version: 2),
      });
      await _pump(tester, api, screen());
      await tester.tap(find.text('Copy to next day'));
      await tester.pumpAndSettle();
      expect(find.textContaining('They take effect immediately'), findsOneWidget);
      await tester.tap(find.widgetWithText(FilledButton, 'Copy'));
      await tester.pumpAndSettle();
      expect(api.calls.first.path, '/rosters');
      expect((api.calls.first.body as Map)['roster_date'], '2026-11-06');
      expect(api.calls.last.path, '/rosters/r-5/publish');
      expect(find.textContaining('Copied 1 to 6 Nov 2026'), findsOneWidget);
    });

    testWidgets('fits a small phone at large text', (tester) async {
      await _pump(tester, _api(entries: [_entry('r-1', 'e-1', status: 'DRAFT')]), screen(), size: const Size(320, 3000), scale: 2);
      expect(tester.takeException(), isNull);
    });
  });

  group('workforce roster', () {
    Widget screen() => WorkforceRosterScreen(now: _now);

    testWidgets('opens on this week, with people as rows and the shift in each cell', (tester) async {
      final api = _api(entries: [_entry('r-1', 'e-1'), _entry('r-2', 'e-2', off: true, shift: null), _entry('r-3', 'e-3', shift: 'sh-2', status: 'DRAFT', holiday: true)]);
      await _pump(tester, api, screen());
      expect(find.text('2 Nov 2026 – 15 Nov 2026'), findsOneWidget);
      expect(find.text('Person 1'), findsOneWidget);
      expect(find.text('OFF'), findsOneWidget);
      expect(find.text('NGT*'), findsOneWidget);
      expect(api.listCalls.firstWhere((c) => c.path == '/rosters').filters, {'date_from': '2026-11-02', 'date_to': '2026-11-15'});
    });

    testWidgets('counts everyone rostered per day below the grid', (tester) async {
      await _pump(tester, _api(entries: [_entry('r-1', 'e-1'), _entry('r-2', 'e-2')]), screen());
      expect(find.text('Rostered per day (all employees)'), findsOneWidget);
      expect(find.text('General (2)'), findsOneWidget);
      expect(find.text('2'), findsOneWidget, reason: 'two on the day, in the visible columns');
    });

    testWidgets('next and the day choices change the range; Today comes back', (tester) async {
      final api = _api();
      await _pump(tester, api, screen());
      await tester.tap(find.text('7 days'));
      await tester.pumpAndSettle();
      expect(api.listCalls.last.filters, {'date_from': '2026-11-02', 'date_to': '2026-11-08'});
      await tester.tap(find.byTooltip('Next'));
      await tester.pumpAndSettle();
      expect(api.listCalls.last.filters, {'date_from': '2026-11-09', 'date_to': '2026-11-15'});
      await tester.tap(find.text('Today'));
      await tester.pumpAndSettle();
      expect(api.listCalls.last.filters, {'date_from': '2026-11-02', 'date_to': '2026-11-08'});
    });

    testWidgets('search goes to the server', (tester) async {
      final api = _api();
      await _pump(tester, api, screen());
      await tester.enterText(find.byType(TextField), 'asha');
      await tester.pump(const Duration(milliseconds: 350));
      await tester.pumpAndSettle();
      expect(api.listCalls.lastWhere((c) => c.path == '/employees').filters, {'q': 'asha'});
    });

    testWidgets('only rostered hides everyone else', (tester) async {
      await _pump(tester, _api(entries: [_entry('r-1', 'e-1')]), screen());
      await tester.tap(find.byType(SwitchListTile));
      await tester.pumpAndSettle();
      expect(find.text('Person 1'), findsOneWidget);
      expect(find.text('Person 2'), findsNothing);
    });

    testWidgets('a manager taps a blank cell to add an entry for that person and day', (tester) async {
      await _pump(tester, _api(), screen());
      await tester.tap(find.bySemanticsLabel('Add roster entry for Person 1 on 2026-11-02'));
      await tester.pumpAndSettle();
      expect(find.text('New roster entry'), findsOneWidget);
      expect(find.text('2026-11-02'), findsOneWidget);
    });

    testWidgets('a manager taps a filled cell to edit it', (tester) async {
      await _pump(tester, _api(entries: [_entry('r-1', 'e-1', date: '2026-11-02')]), screen());
      await tester.tap(find.text('GEN'));
      await tester.pumpAndSettle();
      expect(find.text('Edit roster entry'), findsOneWidget);
    });

    testWidgets('without roster permission cells are read-only', (tester) async {
      await _pump(tester, _api(entries: [_entry('r-1', 'e-1', date: '2026-11-02')]), screen(), permissions: const [attendanceViewAll, employeeViewAll]);
      expect(find.text('+'), findsNothing);
      await tester.tap(find.text('GEN'));
      await tester.pumpAndSettle();
      expect(find.text('Edit roster entry'), findsNothing);
    });

    testWidgets('no access is explained', (tester) async {
      await _pump(tester, _api(failing: {'/employees': ApiError(status: 403, code: 'P', message: 'x')}), screen());
      expect(find.text("You don't have permission to see this."), findsOneWidget);
    });

    testWidgets('fits a small phone at large text', (tester) async {
      await _pump(tester, _api(entries: [_entry('r-1', 'e-1')]), screen(), size: const Size(320, 3000), scale: 2);
      expect(tester.takeException(), isNull);
    });
  });
}

/// No entries on any day but the ones given, while writes follow the base fake.
class _EmptyRosters extends FakeApiClient {
  _EmptyRosters({super.lists, super.objects, super.failing, this.onDay = const []});
  final List<Map<String, dynamic>> onDay;

  @override
  Future<ListEnvelope<T>> getList<T>(String path, {required T Function(dynamic) parseItem, PageQuery? query, Map<String, dynamic>? filters, bool authenticated = true}) async {
    if (path == '/rosters') {
      listCalls.add((path: path, filters: filters));
      return ListEnvelope(data: filters?['date_from'] == _day ? onDay.map(parseItem).toList() : <T>[], pagination: null, meta: ResponseMeta(requestId: 'r'));
    }
    return super.getList(path, parseItem: parseItem, query: query, filters: filters);
  }
}
