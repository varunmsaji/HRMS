import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:hrms_mobile/core/auth/permissions.dart';
import 'package:hrms_mobile/core/forms/form_spec.dart';
import 'package:hrms_mobile/core/providers.dart';
import 'package:hrms_mobile/features/attendance/domain/roster_form.dart';
import 'package:hrms_mobile/features/attendance/presentation/roster_calendar_screen.dart';
import 'package:hrms_mobile/features/attendance/presentation/rosters_screen.dart';

import 'support/fake_api_client.dart';
import 'support/fake_auth.dart';

Map<String, dynamic> _roster({String id = 'r1', String date = '2026-10-05', String status = 'DRAFT', String? shiftId = 'sh-1', bool weekOff = false, bool holiday = false, int version = 2}) => {
      'id': id,
      'employee_id': 'e1',
      'roster_date': date,
      'shift_id': shiftId,
      'is_week_off_override': weekOff,
      'is_holiday_working_override': holiday,
      'status': status,
      'reason': null,
      'version': version,
    };

FakeApiClient _api(List<Map<String, dynamic>> rows) => FakeApiClient(lists: {
      '/rosters': rows,
      '/employees': [
        {'id': 'e1', 'first_name': 'Asha', 'last_name': 'Rao', 'employee_code': 'E-1'}
      ],
      '/shifts': [
        {'id': 'sh-1', 'name': 'General', 'is_active': true},
        {'id': 'sh-2', 'name': 'Night', 'is_active': true},
      ],
    });

Future<void> _pump(WidgetTester tester, FakeApiClient api, List<String> permissions, Widget home) async {
  tester.view.physicalSize = const Size(800, 4000);
  tester.view.devicePixelRatio = 1;
  addTearDown(tester.view.reset);
  await tester.pumpWidget(ProviderScope(overrides: [apiClientProvider.overrideWithValue(api), fakeAuth(permissions, employeeId: 'e1')], child: MaterialApp(home: home)));
  await tester.pumpAndSettle();
}

void main() {
  group('roster form logic', () {
    final spec = rosterSpec(employeeLocked: false);
    Map<String, dynamic> v(Map<String, dynamic> over) => rowFromWire(spec, {'employee_id': 'e1', 'roster_date': '2026-10-05', 'day_kind': 'SHIFT', 'shift_id': 'sh-1', ...over});

    test('an assigned shift needs a shift; overrides do not', () {
      expect(validateRow(spec, v({})), isEmpty);
      expect(validateRow(spec, v({'shift_id': ''})).keys, ['shift_id']);
      expect(validateRow(spec, v({'day_kind': 'WEEK_OFF', 'shift_id': ''})), isEmpty);
    });

    test('day_kind collapses into the three backend fields', () {
      expect(rosterPatchBody({'day_kind': 'SHIFT', 'shift_id': 'sh-1'}), {'shift_id': 'sh-1', 'is_week_off_override': false, 'is_holiday_working_override': false});
      expect(rosterPatchBody({'day_kind': 'WEEK_OFF', 'shift_id': 'sh-1'}), {'shift_id': null, 'is_week_off_override': true, 'is_holiday_working_override': false});
      expect(rosterPatchBody({'day_kind': 'HOLIDAY_WORKING', 'shift_id': null, 'reason': 'Festival'}), {'shift_id': null, 'is_week_off_override': false, 'is_holiday_working_override': true, 'reason': 'Festival'});
    });

    test('an existing entry maps back to a day kind', () {
      expect(rosterToFormWire(_roster())['day_kind'], 'SHIFT');
      expect(rosterToFormWire(_roster(weekOff: true))['day_kind'], 'WEEK_OFF');
      expect(rosterToFormWire(_roster(holiday: true))['day_kind'], 'HOLIDAY_WORKING');
    });

    test('day labels name the shift', () {
      const names = {'sh-1': 'General'};
      expect(rosterDayLabel(_roster(), names), 'General');
      expect(rosterDayLabel(_roster(weekOff: true), names), 'Week off');
      expect(rosterDayLabel(_roster(holiday: true), names), 'Working holiday · General');
    });
  });

  group('list', () {
    testWidgets('shows entries by employee with the shift, and offers actions only to managers', (tester) async {
      await _pump(tester, _api([_roster(), _roster(id: 'r2', date: '2026-10-06', weekOff: true, shiftId: null, status: 'PUBLISHED')]), const [], const RostersScreen());
      expect(find.text('Asha Rao (E-1) · 2026-10-05'), findsOneWidget);
      expect(find.text('General'), findsOneWidget);
      expect(find.text('Week off'), findsOneWidget);
      expect(find.byType(PopupMenuButton<String>), findsNothing);
      expect(find.text('Add roster entry'), findsNothing);
    });

    testWidgets('the status filter is sent to the server', (tester) async {
      final api = _api([_roster()]);
      await _pump(tester, api, const [], const RostersScreen());
      await tester.tap(find.byType(DropdownButtonFormField<String>).last);
      await tester.pumpAndSettle();
      await tester.tap(find.text('Published').last);
      await tester.pumpAndSettle();
      expect(api.listCalls.where((c) => c.path == '/rosters').last.filters!['status'], 'PUBLISHED');
    });

    testWidgets('a manager can publish a draft entry with its version', (tester) async {
      final api = _api([_roster(version: 7)]);
      await _pump(tester, api, [attendanceRosterManage], const RostersScreen());
      await tester.tap(find.byType(PopupMenuButton<String>));
      await tester.pumpAndSettle();
      await tester.tap(find.text('Publish'));
      await tester.pumpAndSettle();
      final call = api.calls.single;
      expect(call.path, '/rosters/r1/publish');
      expect(call.ifMatch, '7');
    });

    testWidgets('a published entry cannot be published again', (tester) async {
      await _pump(tester, _api([_roster(status: 'PUBLISHED')]), [attendanceRosterManage], const RostersScreen());
      await tester.tap(find.byType(PopupMenuButton<String>));
      await tester.pumpAndSettle();
      expect(find.text('Publish'), findsNothing);
      expect(find.text('Edit'), findsOneWidget);
    });

    testWidgets('removing asks first and sends the version', (tester) async {
      final api = _api([_roster(version: 5)]);
      await _pump(tester, api, [attendanceRosterManage], const RostersScreen());
      await tester.tap(find.byType(PopupMenuButton<String>));
      await tester.pumpAndSettle();
      await tester.tap(find.text('Remove'));
      await tester.pumpAndSettle();
      await tester.tap(find.widgetWithText(FilledButton, 'Remove'));
      await tester.pumpAndSettle();
      final call = api.calls.single;
      expect(call.method, 'DELETE');
      expect(call.path, '/rosters/r1');
      expect(call.ifMatch, '5');
    });

    testWidgets('editing sends the whole day definition, not just what changed', (tester) async {
      final api = _api([_roster(version: 3)]);
      await _pump(tester, api, [attendanceRosterManage], const RostersScreen());
      await tester.tap(find.byType(PopupMenuButton<String>));
      await tester.pumpAndSettle();
      await tester.tap(find.text('Edit'));
      await tester.pumpAndSettle();
      // change the day to a week off
      await tester.tap(find.byType(DropdownButtonFormField<String>).first);
      await tester.pumpAndSettle();
      await tester.tap(find.text('Week off').last);
      await tester.pumpAndSettle();
      await tester.tap(find.widgetWithText(FilledButton, 'Save changes'));
      await tester.pumpAndSettle();
      final call = api.calls.single;
      expect(call.method, 'PATCH');
      expect(call.path, '/rosters/r1');
      expect(call.ifMatch, '3');
      expect(call.body, {'shift_id': null, 'is_week_off_override': true, 'is_holiday_working_override': false});
    });

    testWidgets('creating validates, then posts the entry', (tester) async {
      final api = _api(const []);
      await _pump(tester, api, [attendanceRosterManage], const RostersScreen());
      await tester.tap(find.text('Add roster entry'));
      await tester.pumpAndSettle();
      await tester.tap(find.widgetWithText(FilledButton, 'Create'));
      await tester.pumpAndSettle();
      expect(find.text('Employee is required.'), findsOneWidget);
      expect(find.text('Date is required.'), findsOneWidget);
      expect(find.text('Choose a shift, or pick a week-off / holiday-working override instead.'), findsOneWidget);
      expect(api.calls, isEmpty);
    });
  });

  group('calendar', () {
    testWidgets('shows the employee\'s entries in the month grid and only managers can tap a cell to edit', (tester) async {
      final today = DateTime.now();
      final iso = '${today.year}-${today.month.toString().padLeft(2, '0')}-15';
      final api = _api([_roster(date: iso, shiftId: 'sh-2')]);
      await _pump(tester, api, const [], const RosterCalendarScreen());
      expect(api.listCalls.where((c) => c.path == '/rosters').first.filters!['employee_id'], 'e1');
      expect(find.text('Night'), findsOneWidget);
      await tester.tap(find.text('Night'));
      await tester.pumpAndSettle();
      expect(find.text('Edit roster entry'), findsNothing); // read-only for non-managers
    });

    testWidgets('a manager tapping a day opens the form for that employee and date', (tester) async {
      final api = _api(const []);
      await _pump(tester, api, [attendanceRosterManage], const RosterCalendarScreen());
      await tester.tap(find.text('15'));
      await tester.pumpAndSettle();
      expect(find.text('New roster entry'), findsOneWidget);
      expect(find.text('Employee'), findsNothing); // locked to the calendar's employee
    });
  });
}
