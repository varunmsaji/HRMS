import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:hrms_mobile/core/api/api_error.dart';
import 'package:hrms_mobile/core/auth/permissions.dart';
import 'package:hrms_mobile/core/providers.dart';
import 'package:hrms_mobile/core/resource/resource_config.dart';
import 'package:hrms_mobile/features/organisation/domain/org_resources.dart';
import 'package:hrms_mobile/features/organisation/presentation/change_impact_screen.dart';

import 'support/fake_api_client.dart';
import 'support/fake_auth.dart';

/// `ImpactPreview` from `apps/api/.../organisation/calendar_impact.py`.
Map<String, dynamic> _preview({bool protected = false}) => {
      'change_type': 'HOLIDAY_CREATE',
      'window_from': '2026-11-05',
      'window_to': '2027-05-03',
      'population': {'employees_in_scope': 12, 'employees_analysed': 12, 'groups_analysed': 2, 'complete': true},
      'changed_date_count': 1,
      'affected_employee_count': 12,
      'rows': [
        {
          'date': '2026-12-25',
          'previous': {'configured': true, 'day_type': 'WORKING', 'label': null, 'weekly_off_fraction': null},
          'proposed': {'configured': true, 'day_type': 'HOLIDAY', 'label': 'Christmas', 'weekly_off_fraction': null},
          'affected_employee_count': 12,
        },
      ],
      'rows_truncated': false,
      'employee_samples': const [],
      'excluded_not_employed_employee_dates': 0,
      'incomplete_configuration': {'employees': 0, 'dates': 0},
      'leave_impact': {'approved_day_records': 2, 'pending_day_records': 1, 'applications': 3, 'employees': 3, 'items': const [], 'items_truncated': false, 'records_modified': 0},
      'protected_periods': protected
          ? [
              {'id': 'p-1', 'kind': 'ATTENDANCE_PERIOD', 'legal_entity_id': 'le-1', 'period_start': '2026-12-01', 'period_end': '2026-12-31', 'status': 'LOCKED', 'changed_dates_in_period': 1},
            ]
          : const [],
      'warnings': const [],
      'requires_acknowledgement': protected,
      'impact_digest': 'd' * 64,
    };

const _change = {'change_type': 'HOLIDAY_CREATE', 'holiday_calendar_id': 'cal-1', 'body': {'date': '2026-12-25', 'name': 'Christmas'}};

const _previewPath = '/work-calendar-changes/preview';
const _confirmPath = '/work-calendar-changes/confirm';

Future<void> _pumpScreen(WidgetTester tester, FakeApiClient api) async {
  tester.view.physicalSize = const Size(600, 2000);
  tester.view.devicePixelRatio = 1;
  addTearDown(tester.view.reset);
  await tester.pumpWidget(ProviderScope(
    overrides: [apiClientProvider.overrideWithValue(api), fakeAuth([orgHolidayManage])],
    child: const MaterialApp(home: ChangeImpactScreen(title: 'Add holiday', change: _change)),
  ));
  await tester.pumpAndSettle();
}

/// [ResourceConfig.reviewEdit] with the screen it would open stubbed out by a popping route.
Future<Map<String, dynamic>?> _reviewedChange(WidgetTester tester, ResourceConfig config, Map<String, dynamic> changed) async {
  await tester.pumpWidget(ProviderScope(
    overrides: [apiClientProvider.overrideWithValue(FakeApiClient(failing: {_previewPath: ApiError(status: 500, code: 'X', message: 'x')})), fakeAuth(const [])],
    child: MaterialApp(home: Builder(builder: (c) {
      return TextButton(onPressed: () => config.reviewEdit!(c, const {'id': 'r-1', 'version': 4}, changed), child: const Text('go'));
    })),
  ));
  await tester.tap(find.text('go'));
  await tester.pumpAndSettle();
  final screens = find.byType(ChangeImpactScreen);
  if (screens.evaluate().isEmpty) return null;
  final change = tester.widget<ChangeImpactScreen>(screens).change;
  return change;
}

void main() {
  group('the review screen', () {
    testWidgets('previews without saving, then confirms with the digest it showed', (tester) async {
      final api = FakeApiClient(objects: {_previewPath: _preview()});
      await _pumpScreen(tester, api);
      expect(api.calls.single.path, _previewPath);
      expect(find.textContaining('12 employees affected on 1 date'), findsOneWidget);
      expect(find.textContaining('Working day → Holiday — Christmas'), findsOneWidget);
      expect(find.textContaining('2 approved and 1 pending'), findsOneWidget);

      await tester.tap(find.text('Confirm change'));
      await tester.pumpAndSettle();
      final confirm = api.calls.last;
      expect(confirm.path, _confirmPath);
      final body = confirm.body as Map;
      expect(body['change'], _change);
      expect(body['impact_digest'], 'd' * 64);
      expect(body['acknowledge_protected_impact'], false);
    });

    testWidgets('a locked period blocks Confirm until it is acknowledged', (tester) async {
      final api = FakeApiClient(objects: {_previewPath: _preview(protected: true)});
      await _pumpScreen(tester, api);
      expect(find.textContaining('Attendance period 2026-12-01 to 2026-12-31 (locked): 1 changed date(s)'), findsOneWidget);
      await tester.tap(find.text('Confirm change'));
      await tester.pumpAndSettle();
      expect(api.calls.where((c) => c.path == _confirmPath), isEmpty);

      await tester.tap(find.byType(CheckboxListTile));
      await tester.pumpAndSettle();
      await tester.tap(find.text('Confirm change'));
      await tester.pumpAndSettle();
      expect((api.calls.last.body as Map)['acknowledge_protected_impact'], true);
    });

    testWidgets('a stale preview applies nothing and offers a fresh one', (tester) async {
      final api = FakeApiClient(objects: {_previewPath: _preview()}, failing: {_confirmPath: ApiError(status: 409, code: 'CALENDAR_PREVIEW_STALE', message: 'stale')});
      await _pumpScreen(tester, api);
      await tester.tap(find.text('Confirm change'));
      await tester.pumpAndSettle();
      expect(find.textContaining('Nothing was applied'), findsOneWidget);
      await tester.tap(find.text('Refresh preview'));
      await tester.pumpAndSettle();
      expect(find.textContaining('Nothing was applied'), findsNothing);
      expect(api.calls.last.path, _previewPath);
    });

    testWidgets('Back resolves as not applied and sends no confirm', (tester) async {
      final api = FakeApiClient(objects: {_previewPath: _preview()});
      late Future<bool> result;
      await tester.pumpWidget(ProviderScope(
        overrides: [apiClientProvider.overrideWithValue(api), fakeAuth(const [])],
        child: MaterialApp(home: Builder(builder: (c) => TextButton(onPressed: () => result = reviewCalendarChange(c, title: 'Add holiday', change: _change), child: const Text('go')))),
      ));
      await tester.tap(find.text('go'));
      await tester.pumpAndSettle();
      await tester.tap(find.text('Back'));
      await tester.pumpAndSettle();
      expect(await result, isFalse);
      expect(api.calls.where((c) => c.path == _confirmPath), isEmpty);
    });
  });

  group('holidays on a calendar', () {
    final holiday = {'id': 'h-1', 'version': 7, 'date': '2026-12-25', 'name': 'Christmas', 'holiday_type': 'PUBLIC', 'is_paid': true, 'is_working': false, 'is_active': true};

    Future<FakeApiClient> open(WidgetTester tester) async {
      tester.view.physicalSize = const Size(800, 2400);
      tester.view.devicePixelRatio = 1;
      addTearDown(tester.view.reset);
      final api = FakeApiClient(lists: {'/holiday-calendars/cal-1/holidays': [holiday]}, objects: {_previewPath: _preview()});
      await tester.pumpWidget(ProviderScope(
        overrides: [apiClientProvider.overrideWithValue(api), fakeAuth([orgHolidayManage])],
        child: MaterialApp(home: Scaffold(body: Builder(builder: (c) => SingleChildScrollView(child: holidayCalendarResource.detailExtras!(c, const {'id': 'cal-1'}, () {}))))),
      ));
      await tester.pumpAndSettle();
      return api;
    }

    Future<void> editName(WidgetTester tester) async {
      await tester.tap(find.byType(PopupMenuButton<String>));
      await tester.pumpAndSettle();
      await tester.tap(find.text('Edit'));
      await tester.pumpAndSettle();
      await tester.enterText(find.widgetWithText(TextField, 'Christmas'), 'Christmas Day');
      await tester.tap(find.widgetWithText(FilledButton, 'Save changes'));
      await tester.pumpAndSettle();
    }

    testWidgets('backing out of the review returns to the form with nothing saved', (tester) async {
      final api = await open(tester);
      await editName(tester);
      expect(find.byType(ChangeImpactScreen), findsOneWidget);
      await tester.tap(find.text('Back'));
      await tester.pumpAndSettle();
      expect(find.widgetWithText(FilledButton, 'Save changes'), findsOneWidget);
      expect(find.text('Something went wrong.'), findsNothing);
      expect(api.calls.map((c) => c.path), isNot(contains(_confirmPath)));
      expect(api.calls.where((c) => c.method == 'PATCH'), isEmpty);
    });

    testWidgets('an edit is saved through the review, never by a plain PATCH', (tester) async {
      final api = await open(tester);
      await editName(tester);
      await tester.tap(find.text('Confirm change'));
      await tester.pumpAndSettle();
      expect(find.text('Saved.'), findsOneWidget);
      expect(api.calls.where((c) => c.method == 'PATCH'), isEmpty);
      final change = (api.calls.last.body as Map)['change'] as Map;
      expect(change['change_type'], 'HOLIDAY_UPDATE');
      expect(change['holiday_id'], 'h-1');
      expect(change['expected_version'], 7);
      expect(change['patch'], {'name': 'Christmas Day'});
    });

    testWidgets('removing a holiday is reviewed too', (tester) async {
      final api = await open(tester);
      await tester.tap(find.byType(PopupMenuButton<String>));
      await tester.pumpAndSettle();
      await tester.tap(find.text('Deactivate'));
      await tester.pumpAndSettle();
      expect(find.byType(ChangeImpactScreen), findsOneWidget);
      expect(((api.calls.last.body as Map)['change'] as Map)['patch'], {'is_active': false});
      expect(api.calls.where((c) => c.method == 'PATCH'), isEmpty);
    });
  });

  test('day descriptions match the web', () {
    expect(describeDaySnapshot(const {'configured': false}), 'Not set up');
    expect(describeDaySnapshot(const {'configured': true, 'day_type': 'WORKING'}), 'Working day');
    expect(describeDaySnapshot(const {'configured': true, 'day_type': 'WEEKLY_OFF', 'weekly_off_fraction': '0.50', 'label': 'Founders Day'}), 'Weekly off (half day) — Founders Day');
  });

  group('which calendar edits are reviewed', () {
    testWidgets('holiday calendar: validity dates yes, a rename no', (tester) async {
      final change = await _reviewedChange(tester, holidayCalendarResource, const {'valid_to': '2027-12-31'});
      expect(change?['change_type'], 'HOLIDAY_CALENDAR_UPDATE');
      expect(change?['expected_version'], 4);
      expect(await holidayCalendarResource.reviewEdit!(tester.element(find.byType(Scaffold)), const {'id': 'r-1', 'version': 4}, const {'name': 'New'}), isNull);
    });

    testWidgets('work calendar: what days mean yes, a rename no', (tester) async {
      final change = await _reviewedChange(tester, workCalendarResource, const {'weekly_off_pattern_id': 'p-2'});
      expect(change?['change_type'], 'WORK_CALENDAR_UPDATE');
      expect(await workCalendarResource.reviewEdit!(tester.element(find.byType(Scaffold)), const {'id': 'r-1', 'version': 4}, const {'name': 'New'}), isNull);
    });
  });
}
