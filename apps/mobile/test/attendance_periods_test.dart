import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:hrms_mobile/core/api/api_error.dart';
import 'package:hrms_mobile/core/api/envelope.dart' show ErrorDetail;
import 'package:hrms_mobile/core/auth/permissions.dart';
import 'package:hrms_mobile/core/forms/form_spec.dart';
import 'package:hrms_mobile/core/providers.dart';
import 'package:hrms_mobile/features/attendance/presentation/attendance_period_detail_screen.dart';
import 'package:hrms_mobile/features/attendance/presentation/attendance_periods_screen.dart';

import 'support/fake_api_client.dart';
import 'support/fake_auth.dart';

Map<String, dynamic> _period({String status = 'OPEN', int version = 3, String? label}) => {
      'id': 'p1',
      'legal_entity_id': 'le-1',
      'period_start': '2026-09-01',
      'period_end': '2026-09-30',
      'label': label,
      'status': status,
      'opened_at': '2026-09-01T03:30:00Z',
      'closed_at': null,
      'reopen_reason': null,
      'version': version,
      'actions': [
        {'action': 'OPENED', 'comment': null, 'created_at': '2026-09-01T03:30:00Z'},
      ],
    };

FakeApiClient _api({Map<String, Object> failing = const {}, Map<String, Map<String, dynamic>> objects = const {}, List<Map<String, dynamic>> summary = const []}) => FakeApiClient(
      lists: {
        '/attendance-periods': [_period()],
        '/attendance-periods/p1/summary': summary,
        '/legal-entities': [
          {'id': 'le-1', 'name': 'Acme Pvt Ltd', 'is_active': true}
        ],
        '/employees': [
          {'id': 'e1', 'first_name': 'Asha', 'last_name': 'Rao', 'employee_code': 'E-1'}
        ],
      },
      objects: {'/attendance-periods/p1': _period(), ...objects},
      failing: failing,
    );

Future<void> _pump(WidgetTester tester, FakeApiClient api, List<String> permissions, Widget home) async {
  tester.view.physicalSize = const Size(800, 5000);
  tester.view.devicePixelRatio = 1;
  addTearDown(tester.view.reset);
  await tester.pumpWidget(ProviderScope(overrides: [apiClientProvider.overrideWithValue(api), fakeAuth(permissions)], child: MaterialApp(home: home)));
  await tester.pumpAndSettle();
}

void main() {
  group('open-period form', () {
    Map<String, dynamic> v(Map<String, dynamic> over) => rowFromWire(attendancePeriodSpec, {'legal_entity_id': 'le-1', 'month': '2026-09', ...over});

    test('a month needs the YYYY-MM shape', () {
      expect(validateRow(attendancePeriodSpec, v({})), isEmpty);
      expect(validateRow(attendancePeriodSpec, v({'month': '2026-13'})).keys, ['month']);
      expect(validateRow(attendancePeriodSpec, v({'month': 'September'})).keys, ['month']);
    });

    test('a custom range needs both days in order, and no month', () {
      expect(validateRow(attendancePeriodSpec, v({'custom_range': true, 'month': '', 'period_start': '2026-09-05', 'period_end': '2026-10-04'})), isEmpty);
      expect(validateRow(attendancePeriodSpec, v({'custom_range': true, 'period_start': '2026-09-05', 'period_end': '2026-09-01'})).keys, ['period_end']);
      expect(validateRow(attendancePeriodSpec, v({'custom_range': true, 'period_start': '', 'period_end': ''})).keys, containsAll(['period_start', 'period_end']));
    });
  });

  group('list', () {
    testWidgets('shows periods with their legal entity and status; opening needs ATTENDANCE.LOCK', (tester) async {
      await _pump(tester, _api(), const [], const AttendancePeriodsScreen());
      expect(find.textContaining('Acme Pvt Ltd'), findsOneWidget);
      expect(find.text('Open'), findsOneWidget);
      expect(find.text('Open period'), findsNothing);
    });

    testWidgets('opening a period posts the month, entity and no UI-only fields', (tester) async {
      final api = _api();
      await _pump(tester, api, [attendanceLock], const AttendancePeriodsScreen());
      await tester.tap(find.text('Open period'));
      await tester.pumpAndSettle();
      // single legal entity is preselected and the month defaults to the business month
      await tester.tap(find.widgetWithText(FilledButton, 'Open period'));
      await tester.pumpAndSettle();
      final call = api.calls.single;
      expect(call.path, '/attendance-periods');
      final body = call.body as Map<String, dynamic>;
      expect(body['legal_entity_id'], 'le-1');
      expect(body['month'], matches(RegExp(r'^\d{4}-\d{2}$')));
      expect(body.containsKey('custom_range'), isFalse);
      expect(body.containsKey('period_start'), isFalse);
    });
  });

  group('detail', () {
    testWidgets('shows the period, entity, times in company zone and timeline', (tester) async {
      await _pump(tester, _api(), const [], const AttendancePeriodDetailScreen(periodId: 'p1'));
      expect(find.text('Acme Pvt Ltd'), findsOneWidget);
      expect(find.text('Oct 1, 2026, 9:00 am IST'), findsNothing); // sanity: wrong month
      expect(find.text('Sep 1, 2026, 9:00 am IST'), findsWidgets);
      expect(find.text('Period opened'), findsOneWidget);
    });

    testWidgets('actions depend on state and permission', (tester) async {
      await _pump(tester, _api(), const [], const AttendancePeriodDetailScreen(periodId: 'p1'));
      expect(find.text('Validate'), findsNothing);
      expect(find.text('Finalize'), findsNothing);
    });

    testWidgets('validate shows blocking reasons with readable labels', (tester) async {
      final api = _api(objects: {
        '/attendance-periods/p1/validate': {
          'status': 'BLOCKED',
          'validated_at': '2026-09-30T10:00:00Z',
          'reasons': [
            {'code': 'PENDING_REGULARIZATION', 'count': 3, 'message': '3 regularization requests are pending.'}
          ],
        },
      });
      await _pump(tester, api, [attendanceLock], const AttendancePeriodDetailScreen(periodId: 'p1'));
      await tester.tap(find.widgetWithText(OutlinedButton, 'Validate'));
      await tester.pumpAndSettle();
      expect(find.text('BLOCKED'), findsOneWidget);
      expect(find.text('Pending regularization requests — 3'), findsOneWidget);
    });

    testWidgets('finalize carries the version and surfaces blocking reasons from a refusal', (tester) async {
      final api = _api(failing: {
        '/attendance-periods/p1/finalize': ApiError(status: 409, code: 'ATTENDANCE_PERIOD_BLOCKED', message: 'blocked', details: [
          ErrorDetail(code: 'x', message: 'x', context: {
            'reasons': [
              {'code': 'UNPUBLISHED_ROSTER', 'count': 2, 'message': 'Publish the roster first.'}
            ]
          })
        ]),
      });
      await _pump(tester, api, [attendanceLock], const AttendancePeriodDetailScreen(periodId: 'p1'));
      await tester.tap(find.widgetWithText(FilledButton, 'Finalize'));
      await tester.pumpAndSettle();
      await tester.tap(find.widgetWithText(FilledButton, 'Finalize').last);
      await tester.pumpAndSettle();
      expect(api.calls.single.ifMatch, '3');
      expect(find.text('This period is not ready:'), findsOneWidget);
      expect(find.textContaining('Unpublished (DRAFT) roster entries — 2'), findsOneWidget);
    });

    testWidgets('calculating queues the range clamped to the business today', (tester) async {
      final api = _api(objects: {'/attendance/days/calculate-range': const {}});
      await _pump(tester, api, [attendanceRecompute], const AttendancePeriodDetailScreen(periodId: 'p1'));
      await tester.tap(find.widgetWithText(OutlinedButton, 'Calculate attendance'));
      await tester.pumpAndSettle();
      final body = api.calls.single.body as Map<String, dynamic>;
      expect(api.calls.single.path, '/attendance/days/calculate-range');
      expect(body['date_from'], '2026-09-01');
      expect(body['date_to'], '2026-09-30'); // the period is long past, so its own end
      expect(body['legal_entity_id'], 'le-1');
    });

    testWidgets('reopen needs a reason and the unlock permission, on a closed period only', (tester) async {
      final closed = _period(status: 'CLOSED', version: 8);
      final api = _api(objects: {'/attendance-periods/p1': closed});
      await _pump(tester, api, [attendanceUnlock], const AttendancePeriodDetailScreen(periodId: 'p1'));
      expect(find.text('Closed & locked'), findsOneWidget);
      await tester.tap(find.widgetWithText(OutlinedButton, 'Reopen'));
      await tester.pumpAndSettle();
      await tester.tap(find.widgetWithText(FilledButton, 'Reopen'));
      await tester.pumpAndSettle();
      expect(find.text('A reason is required.'), findsOneWidget);
      await tester.enterText(find.byType(TextField).last, 'Correct a punch');
      await tester.tap(find.widgetWithText(FilledButton, 'Reopen'));
      await tester.pumpAndSettle();
      final call = api.calls.single;
      expect(call.path, '/attendance-periods/p1/reopen');
      expect(call.ifMatch, '8');
      expect(call.body, {'reason': 'Correct a punch'});
    });

    testWidgets('the summary lists each employee by name with every column', (tester) async {
      final summary = [
        {'employee_id': 'e1', 'paid_days': '28.00', 'lop_days': '1.00', 'present_days': '27.00', 'half_days': '0.00', 'frozen': false},
      ];
      await _pump(tester, _api(summary: summary), const [], const AttendancePeriodDetailScreen(periodId: 'p1'));
      expect(find.text('Summary (live preview)'), findsOneWidget);
      await tester.tap(find.text('Asha Rao (E-1)'));
      await tester.pumpAndSettle();
      expect(find.text('Paid days'), findsOneWidget);
      expect(find.text('28.00'), findsWidgets);
    });
  });
}
