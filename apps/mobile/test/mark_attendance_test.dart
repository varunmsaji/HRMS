import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:hrms_mobile/core/providers.dart';
import 'package:hrms_mobile/features/attendance/domain/mark_day.dart';
import 'package:hrms_mobile/features/attendance/presentation/mark_attendance_screen.dart';

import 'support/fake_api_client.dart';
import 'support/fake_auth.dart';

// 19:30 on 18 Nov in Asia/Kolkata, so a 09:00 to 18:00 day today has already happened.
final _now = DateTime.utc(2026, 11, 18, 14);

Map<String, dynamic> _emp(String id, String first, String last, String code) => {'id': id, 'first_name': first, 'last_name': last, 'employee_code': code};

Map<String, dynamic> _result(String id, String outcome, {String? code, String? message, List<Map<String, dynamic>> existing = const []}) =>
    {'employee_id': id, 'outcome': outcome, 'code': code, 'message': message, 'replayed': false, 'existing_punches': existing, 'punches': <dynamic>[]};

Map<String, dynamic> _response(List<Map<String, dynamic>> results, {int recorded = 0}) => {
      'punch_in_at': '2026-11-18T03:30:00Z',
      'punch_out_at': '2026-11-18T12:30:00Z',
      'ready_count': results.where((r) => r['outcome'] == 'READY').length,
      'recorded_count': recorded,
      'blocked_count': results.where((r) => r['outcome'] == 'BLOCKED').length,
      'results': results,
    };

FakeApiClient _api({required Map<String, dynamic> preview, Map<String, dynamic>? record}) => FakeApiClient(
      lists: {
        '/employees': [_emp('own', 'Hira', 'Admin', 'E0'), _emp('e-1', 'Asha', 'Rao', 'E1'), _emp('e-2', 'Ben', 'Shah', 'E2')],
      },
      objects: {
        '/attendance/punches/day-entries/preview': preview,
        '/attendance/punches/day-entries': record ?? _response([], recorded: 0),
      },
    );

Future<void> _pump(WidgetTester tester, FakeApiClient api, {List<({String value, String label})> employees = const [], bool lock = false}) async {
  tester.view.physicalSize = const Size(800, 3000);
  tester.view.devicePixelRatio = 1;
  addTearDown(tester.view.reset);
  await tester.pumpWidget(ProviderScope(
    overrides: [apiClientProvider.overrideWithValue(api), fakeAuth(const [], employeeId: 'own')],
    child: MaterialApp(home: MarkAttendanceScreen(initialEmployees: employees, lockEmployees: lock, now: _now)),
  ));
  await tester.pumpAndSettle();
}

void main() {
  testWidgets('reviews first, then records only the employees the review marked ready', (tester) async {
    final api = _api(
      preview: _response([_result('e-1', 'READY'), _result('e-2', 'BLOCKED', code: 'EXISTING_PUNCHES')]),
      record: _response([_result('e-1', 'RECORDED')], recorded: 1),
    );
    await _pump(tester, api);
    await tester.tap(find.text('Asha Rao (E1)'));
    await tester.tap(find.text('Ben Shah (E2)'));
    await tester.enterText(find.widgetWithText(TextField, 'Reason'), 'Forgot to punch');
    await tester.pump();
    expect(find.byKey(const Key('mark-day-summary')), findsOneWidget);
    expect(find.textContaining('9h'), findsOneWidget);

    await tester.tap(find.byKey(const Key('mark-day-review-button')));
    await tester.pumpAndSettle();
    final preview = api.calls.singleWhere((c) => c.path == '/attendance/punches/day-entries/preview').body as Map;
    expect(preview['employee_ids'], ['e-1', 'e-2']);
    // Wall-clock times in the company zone (IST), sent as UTC instants.
    expect(preview['punch_in_at'], '2026-11-18T03:30:00.000Z');
    expect(preview['punch_out_at'], '2026-11-18T12:30:00.000Z');
    expect(preview.containsKey('idempotency_key'), isFalse);
    expect(find.text('1 ready · 1 will be skipped'), findsOneWidget);
    expect(find.textContaining('Already has punches on this day'), findsOneWidget);

    await tester.tap(find.byKey(const Key('mark-day-confirm')));
    await tester.pumpAndSettle();
    final record = api.calls.singleWhere((c) => c.path == '/attendance/punches/day-entries');
    expect((record.body as Map)['employee_ids'], ['e-1']);
    expect((record.body as Map)['idempotency_key'], startsWith('idem_'));
    expect((record.body as Map)['reason'], 'Forgot to punch');
    expect(find.byKey(const Key('mark-day-done')), findsOneWidget);
    expect(find.textContaining('Marked for 1 employee.'), findsOneWidget);
  });

  testWidgets('says what is missing before it asks the server anything', (tester) async {
    final api = _api(preview: _response([]));
    await _pump(tester, api);
    await tester.tap(find.byKey(const Key('mark-day-review-button')));
    await tester.pump();
    expect(find.text('Choose at least one employee.'), findsOneWidget);
    await tester.tap(find.text('Asha Rao (E1)'));
    await tester.tap(find.byKey(const Key('mark-day-review-button')));
    await tester.pump();
    expect(find.text('Give a reason. It is saved with every punch and in the audit log.'), findsOneWidget);
    expect(api.calls, isEmpty);
  });

  testWidgets('your own record is not offered, and a locked employee has no picker', (tester) async {
    final api = _api(preview: _response([]));
    await _pump(tester, api);
    expect(find.text('Hira Admin (E0)'), findsNothing);
    expect(find.text('Asha Rao (E1)'), findsOneWidget);

    final locked = _api(preview: _response([]));
    await _pump(tester, locked, employees: [(value: 'e-1', label: 'Asha Rao (E1)')], lock: true);
    expect(find.text('Filter employees'), findsNothing);
    expect(find.widgetWithText(InputDecorator, 'Employee'), findsOneWidget);
    expect(locked.listCalls, isEmpty);
  });

  testWidgets('editing after a review discards it', (tester) async {
    final api = _api(preview: _response([_result('e-1', 'READY')]));
    await _pump(tester, api);
    await tester.tap(find.text('Asha Rao (E1)'));
    await tester.tap(find.text('Forgot to punch'));
    await tester.pump();
    await tester.tap(find.byKey(const Key('mark-day-review-button')));
    await tester.pumpAndSettle();
    expect(find.byKey(const Key('mark-day-confirm')), findsOneWidget);
    await tester.tap(find.text('On-site / field work'));
    await tester.pump();
    expect(find.byKey(const Key('mark-day-confirm')), findsNothing);
    expect(find.byKey(const Key('mark-day-review')), findsNothing);
    expect(find.byKey(const Key('mark-day-review-button')), findsOneWidget);
  });

  group('mark day rules', () {
    const zone = 'Asia/Kolkata';

    test('an OUT at or before the IN is the next day', () {
      final i = markDayInstants(date: '2026-11-17', inTime: '22:00', outTime: '06:00', zone: zone)!;
      expect(i.overnight, isTrue);
      expect(i.outDate, '2026-11-18');
      expect(i.spanMinutes, 8 * 60);
      expect(formatMarkDaySpan(i.spanMinutes), '8h');
      expect(formatMarkDaySpan(510), '8h 30m');
    });

    test('problems follow web: future date, OUT not yet happened, span over 20 hours, short reason', () {
      final now = DateTime.utc(2026, 11, 18, 14);
      String? problem(String date, String inT, String outT, String reason, {int count = 1}) =>
          markDayProblem(selectedCount: count, instants: markDayInstants(date: date, inTime: inT, outTime: outT, zone: zone), date: date, today: '2026-11-18', reason: reason, now: now);
      expect(problem('2026-11-18', '09:00', '18:00', 'ok then'), isNull);
      expect(problem('2026-11-18', '09:00', '18:00', 'ok then', count: 51), 'Choose at most 50 employees at a time.');
      expect(problem('2026-11-19', '09:00', '18:00', 'ok then'), "The date can't be in the future.");
      expect(problem('2026-11-18', '09:00', '23:30', 'ok then'), startsWith("The OUT time hasn't happened yet"));
      expect(problem('2026-11-16', '01:00', '23:00', 'ok then'), 'IN to OUT can be at most 20 hours.');
      expect(problem('2026-11-18', '09:00', '18:00', 'a '), startsWith('Give a reason'));
    });

    test('only an absent day with no punches can be marked present', () {
      expect(canMarkPresent(status: 'ABSENT', firstIn: null, lastOut: null, hasRecord: true), isTrue);
      expect(canMarkPresent(status: 'ABSENT', firstIn: '2026-11-18T04:00:00Z', lastOut: null, hasRecord: true), isFalse);
      expect(canMarkPresent(status: 'LEAVE', firstIn: null, lastOut: null, hasRecord: true), isFalse);
      expect(canMarkPresent(status: null, firstIn: null, lastOut: null, hasRecord: false), isTrue);
    });
  });
}
