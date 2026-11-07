import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:hrms_mobile/core/api/api_client.dart';
import 'package:hrms_mobile/core/api/api_error.dart';
import 'package:hrms_mobile/core/api/envelope.dart';
import 'package:hrms_mobile/core/auth/permissions.dart';
import 'package:hrms_mobile/core/providers.dart';
import 'package:hrms_mobile/features/organisation/domain/calendar_views.dart';
import 'package:hrms_mobile/features/organisation/presentation/holiday_year_view.dart';
import 'package:hrms_mobile/features/organisation/presentation/work_calendar_month_view.dart';

import 'support/fake_api_client.dart';
import 'support/fake_auth.dart';

/// Records every GET (with its query) and serves `/days` per requested range.
class _Api extends FakeApiClient {
  _Api({super.lists, super.failing, this.days = const []});
  final List<Map<String, dynamic>> days;
  final gets = <String>[];
  final listFilters = <Map<String, dynamic>?>[];

  @override
  Future<T> get<T>(String path, {required T Function(dynamic) parse, bool authenticated = true}) async {
    gets.add(path);
    if (failing.containsKey(path.split('?').first)) throw failing[path.split('?').first]!;
    if (path.contains('/days?')) {
      return parse({'days': days, 'holiday_calendar_ids': const [], 'restricted_holidays_are_off_by_default': false});
    }
    return super.get(path, parse: parse, authenticated: authenticated);
  }

  @override
  Future<ListEnvelope<T>> getList<T>(String path, {required T Function(dynamic) parseItem, PageQuery? query, Map<String, dynamic>? filters, bool authenticated = true}) {
    listFilters.add(filters);
    return super.getList(path, parseItem: parseItem, query: query, filters: filters, authenticated: authenticated);
  }
}

Future<void> _pump(WidgetTester tester, FakeApiClient api, Widget child, {List<String> perms = const []}) async {
  tester.view.physicalSize = const Size(420, 2600);
  tester.view.devicePixelRatio = 1;
  addTearDown(tester.view.reset);
  await tester.pumpWidget(ProviderScope(
    overrides: [apiClientProvider.overrideWithValue(api), fakeAuth(perms)],
    child: MaterialApp(home: Scaffold(body: SingleChildScrollView(child: child))),
  ));
  await tester.pumpAndSettle();
}

void main() {
  group('day presentation (web presentDay)', () {
    String show(Map<String, dynamic> d) {
      final v = presentDay(d);
      return [v.key, v.glyph, v.label, if (v.detail != null) v.detail].join('|');
    }

    test('each day type reads as on web', () {
      expect(show({'day_type': 'SHUTDOWN', 'holiday_name': 'Plant closed'}), 'SHUTDOWN|✕|Shutdown|Plant closed');
      expect(show({'day_type': 'HOLIDAY', 'holiday_name': 'Diwali'}), 'HOLIDAY|★|Holiday|Diwali');
      expect(show({'day_type': 'WEEKLY_OFF', 'weekly_off_fraction': '1.00'}), 'WEEKLY_OFF|○|Weekly off');
      expect(show({'day_type': 'WEEKLY_OFF', 'weekly_off_fraction': '0.50'}), 'WEEKLY_OFF|○|Half-day weekly off');
      expect(show({'day_type': 'WEEKLY_OFF', 'holiday_on_weekly_off': true, 'holiday_name': 'Holi'}), 'WEEKLY_OFF|○|Weekly off|Holi (on weekly off)');
      expect(show({'day_type': 'SPECIAL_WORKING', 'holiday_name': 'Make-up day'}), 'SPECIAL_WORKING|◆|Special working day|Make-up day');
      expect(show({'day_type': 'WORKING'}), 'WORKING|·|Working');
    });

    test('named optional, restricted and working holidays are still working days', () {
      expect(show({'day_type': 'WORKING', 'optional_holiday_name': 'Onam'}), 'WORKING_OPTIONAL|·|Working|Optional holiday: Onam (still a working day)');
      expect(show({'day_type': 'WORKING', 'restricted_holiday_name': 'Eid'}), 'WORKING_RESTRICTED|·|Working|Restricted holiday: Eid (still a working day)');
      expect(show({'day_type': 'WORKING', 'is_holiday_named': true, 'holiday_name': 'Founders Day'}), 'WORKING_HOLIDAY|·|Working|Founders Day (working holiday)');
    });
  });

  group('grid maths', () {
    test('a month is fetched as whole Monday-first weeks', () {
      final r = monthGridRange(2026, 11); // 1 Nov 2026 is a Sunday, 30 Nov a Monday
      expect(r, (from: '2026-10-26', to: '2026-12-06'));
      expect(gridDates(r.from, r.to), hasLength(42));
      expect(monthGridRange(2026, 12), (from: '2026-11-30', to: '2027-01-03'), reason: 'crosses the year');
    });

    test('a year-view month starts on its weekday', () {
      final feb = yearMonthCells(2026, 2); // 1 Feb 2026 is a Sunday
      expect(feb.take(7), [null, null, null, null, null, null, 1]);
      expect(feb.whereType<int>(), hasLength(28));
      expect(yearMonthCells(2028, 2).whereType<int>(), hasLength(29), reason: 'leap year');
    });

    test('inactive holidays are not shown', () {
      final m = holidaysByDate([
        {'date': '2026-03-04', 'name': 'Holi', 'is_active': true},
        {'date': '2026-03-04', 'name': 'Old', 'is_active': false},
        {'date': '2026-08-15', 'name': 'Independence Day'},
      ]);
      expect(m['2026-03-04']!.map((h) => h['name']), ['Holi']);
      expect(m.keys, ['2026-03-04', '2026-08-15']);
    });
  });

  group('work calendar month view', () {
    const calendar = {'id': 'w1', 'name': 'Main', 'is_active': true, 'restricted_holidays_are_off_by_default': false};

    testWidgets('loads whole weeks for the month and explains a tapped day', (tester) async {
      final api = _Api(days: [
        {'date': '2026-11-01', 'day_type': 'WEEKLY_OFF', 'weekly_off_fraction': '1.00'},
        {'date': '2026-11-14', 'day_type': 'HOLIDAY', 'holiday_name': 'Diwali'},
        {'date': '2026-11-16', 'day_type': 'WORKING'},
      ]);
      await _pump(tester, api, WorkCalendarMonthView(calendar: calendar, now: DateTime(2026, 11, 20)));
      expect(api.gets.single, '/work-calendars/w1/days?from=2026-10-26&to=2026-12-06');
      expect(find.text('November 2026'), findsOneWidget);
      expect(find.text('Holiday (non-working)'), findsOneWidget, reason: 'legend');
      expect(find.bySemanticsLabel('2026-11-14: Holiday, Diwali'), findsOneWidget);
      expect(find.bySemanticsLabel('2026-11-20: not loaded'), findsOneWidget);
      expect(find.text('No holiday calendar is linked to this work calendar, so no holidays are shown.'), findsOneWidget);
      expect(find.textContaining('(this calendar does not treat them as off)'), findsOneWidget);

      await tester.tap(find.bySemanticsLabel('2026-11-14: Holiday, Diwali'));
      await tester.pumpAndSettle();
      expect(find.text('Diwali'), findsOneWidget);
    });

    testWidgets('next month asks for the next whole weeks', (tester) async {
      final api = _Api(days: [
        {'date': '2026-12-01', 'day_type': 'WORKING'},
      ]);
      await _pump(tester, api, WorkCalendarMonthView(calendar: calendar, now: DateTime(2026, 11, 20)));
      await tester.tap(find.byTooltip('Next month'));
      await tester.pumpAndSettle();
      expect(find.text('December 2026'), findsOneWidget);
      expect(api.gets.last, '/work-calendars/w1/days?from=2026-11-30&to=2027-01-03');
    });

    testWidgets('a forbidden calendar says so and offers no grid', (tester) async {
      final api = _Api(failing: {'/work-calendars/w1/days': ApiError(status: 403, code: 'PERMISSION_DENIED', message: 'no')});
      await _pump(tester, api, WorkCalendarMonthView(calendar: calendar, now: DateTime(2026, 11, 20)));
      expect(find.text('You do not have permission to view this calendar.'), findsOneWidget);
      expect(find.text('Try again'), findsOneWidget);
    });
  });

  group('holiday year view', () {
    final holidays = [
      {'id': 'h1', 'date': '2026-03-04', 'name': 'Holi', 'holiday_type': 'PUBLIC', 'is_active': true},
      {'id': 'h2', 'date': '2026-05-01', 'name': 'Old', 'holiday_type': 'COMPANY', 'is_active': false},
    ];

    testWidgets('asks for the year, highlights active holidays and names them on tap', (tester) async {
      final api = _Api(lists: {'/holiday-calendars/hc1/holidays': holidays});
      await _pump(tester, api, HolidayYearView(calendarId: 'hc1', now: DateTime(2026, 6, 1)));
      expect(api.listFilters.single, {'year': 2026});
      expect(find.text('2026'), findsOneWidget);
      expect(find.text('1 holidays in 2026.'), findsOneWidget);
      expect(find.bySemanticsLabel('2026-03-04: Holi'), findsOneWidget);
      expect(find.bySemanticsLabel('2026-05-01: Old'), findsNothing);
      await tester.tap(find.bySemanticsLabel('2026-03-04: Holi'));
      await tester.pumpAndSettle();
      expect(find.text('Public'), findsOneWidget);
    });

    testWidgets('a holiday manager can start adding a holiday from an empty day', (tester) async {
      final api = _Api(lists: {'/holiday-calendars/hc1/holidays': holidays});
      await _pump(tester, api, HolidayYearView(calendarId: 'hc1', now: DateTime(2026, 6, 1)), perms: const [orgHolidayManage]);
      await tester.tap(find.bySemanticsLabel('Add holiday on 2026-06-10'));
      await tester.pumpAndSettle();
      expect(find.text('Add holiday'), findsOneWidget);
    });

    testWidgets('without the holiday grant empty days do nothing', (tester) async {
      final api = _Api(lists: {'/holiday-calendars/hc1/holidays': holidays});
      await _pump(tester, api, HolidayYearView(calendarId: 'hc1', now: DateTime(2026, 6, 1)));
      expect(find.bySemanticsLabel('Add holiday on 2026-06-10'), findsNothing);
    });

    testWidgets('switching year asks again; a parent refresh reloads', (tester) async {
      final api = _Api(lists: {'/holiday-calendars/hc1/holidays': const []});
      await _pump(tester, api, HolidayYearView(calendarId: 'hc1', now: DateTime(2026, 6, 1)));
      expect(find.text('No holidays in this calendar for 2026.'), findsOneWidget);
      await tester.tap(find.byTooltip('Next year'));
      await tester.pumpAndSettle();
      expect(api.listFilters.last, {'year': 2027});
    });

    testWidgets('a refresh from the panel (holiday list changed) reloads the same view', (tester) async {
      final api = _Api(lists: {'/holiday-calendars/hc1/holidays': const []});
      var refresh = 0;
      late StateSetter rebuild;
      await _pump(
        tester,
        api,
        StatefulBuilder(builder: (context, setState) {
          rebuild = setState;
          return HolidayYearView(calendarId: 'hc1', refresh: refresh, now: DateTime(2026, 6, 1));
        }),
      );
      expect(api.listFilters, hasLength(1));
      rebuild(() => refresh = 1);
      await tester.pumpAndSettle();
      expect(api.listFilters, hasLength(2));
      rebuild(() {});
      await tester.pumpAndSettle();
      expect(api.listFilters, hasLength(2), reason: 'an unrelated rebuild does not reload');
    });
  });
}
