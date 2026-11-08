import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:hrms_mobile/core/auth/permissions.dart';
import 'package:hrms_mobile/core/providers.dart';
import 'package:hrms_mobile/core/theme/app_theme.dart';
import 'package:hrms_mobile/features/attendance/data/attendance_repository.dart';
import 'package:hrms_mobile/features/attendance/presentation/attendance_day_detail_screen.dart';
import 'package:hrms_mobile/features/auth/presentation/widgets/auth_form_field.dart';

import 'support/fake_api_client.dart';
import 'support/fake_auth.dart';

/// The Corrections section of the attendance day screen — web `components/attendance/day/day-regularization.tsx`.

Map<String, dynamic> _day({Map<String, dynamic> over = const {}}) => {
      'id': 'd-1',
      'employee_id': 'e-1',
      'attendance_date': '2026-10-01',
      'attendance_status': 'PRESENT',
      'timezone': 'Asia/Kolkata',
      'actual_first_in': '2026-10-01T04:00:00Z',
      'actual_last_out': '2026-10-01T12:30:00Z',
      'worked_minutes': 510,
      'is_locked': false,
      ...over,
    };

class _Repo implements AttendanceRepository {
  _Repo(this.row);
  final Map<String, dynamic> row;

  @override
  Future<AttendanceDay> getAttendanceDay(String id) async => AttendanceDay.fromJson(row);

  @override
  Future<List<LeaveDayProjection>> listLeaveProjections({required String employeeId, required String dateFrom, required String dateTo}) async => const [];

  @override
  dynamic noSuchMethod(Invocation invocation) => super.noSuchMethod(invocation);
}

Map<String, dynamic> _request(String status, {String date = '2026-10-01'}) => {
      'id': 'r-$status',
      'employee_id': 'e-1',
      'attendance_date': date,
      'request_type': 'MISSING_PUNCH',
      'status': status,
      'submitted_at': '2026-10-02T05:00:00Z',
    };

void main() {
  Future<FakeApiClient> pump(
    WidgetTester tester, {
    required List<String> permissions,
    String? employeeId,
    List<Map<String, dynamic>> requests = const [],
    Map<String, dynamic> day = const {},
  }) async {
    tester.view.physicalSize = const Size(400, 2400);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.reset);
    final api = FakeApiClient(lists: {'/regularizations': requests});
    await tester.pumpWidget(ProviderScope(
      overrides: [
        attendanceRepositoryProvider.overrideWithValue(_Repo(_day(over: day))),
        apiClientProvider.overrideWithValue(api),
        fakeAuth(permissions, employeeId: employeeId),
      ],
      child: MaterialApp(theme: AppTheme.employee, home: const AttendanceDayDetailScreen(dayId: 'd-1')),
    ));
    await tester.pumpAndSettle();
    return api;
  }

  testWidgets('asks only for this employee and date', (tester) async {
    final api = await pump(tester, permissions: const [attendanceView, attendanceRegularizationRequest], employeeId: 'e-1');
    final call = api.listCalls.singleWhere((c) => c.path == '/regularizations');
    expect(call.filters, {'employee_id': 'e-1', 'date_from': '2026-10-01', 'date_to': '2026-10-01'});
  });

  testWidgets('own day with the request permission: empty note and the button', (tester) async {
    await pump(tester, permissions: const [attendanceView, attendanceRegularizationRequest], employeeId: 'e-1');
    expect(find.text('CORRECTIONS'), findsOneWidget);
    expect(find.text('No correction has been requested for this day.'), findsOneWidget);
    expect(find.widgetWithText(OutlinedButton, 'Request a correction'), findsOneWidget);
  });

  testWidgets('the button is emphasised when the day looks like it needs fixing', (tester) async {
    await pump(tester, permissions: const [attendanceView, attendanceRegularizationRequest], employeeId: 'e-1', day: const {'missing_punch': true});
    expect(find.widgetWithText(FilledButton, 'Request a correction'), findsOneWidget);
  });

  testWidgets("someone else's day without on-behalf and no requests: no section", (tester) async {
    await pump(tester, permissions: const [attendanceView, attendanceRegularizationRequest], employeeId: 'e-2');
    expect(find.text('CORRECTIONS'), findsNothing);
    expect(find.text('Request a correction'), findsNothing);
  });

  testWidgets('lists the requests for the day; an open one hides the button', (tester) async {
    await pump(tester, permissions: const [attendanceView, attendanceRegularizationRequest], employeeId: 'e-1', requests: [_request('SUBMITTED'), _request('REJECTED', date: '2026-10-02')]);
    expect(find.text('Missing punch'), findsWidgets);
    expect(find.text('Submitted'), findsOneWidget);
    expect(find.text('Rejected'), findsNothing, reason: 'another date is not shown');
    expect(find.text('Request a correction'), findsNothing);
  });

  testWidgets('HR raising one for someone else sends that employee and the date', (tester) async {
    final api = await pump(tester, permissions: const [attendanceView, attendanceRegularizationRequestOnBehalf], employeeId: 'e-9');
    await tester.tap(find.text('Request a correction'));
    await tester.pumpAndSettle();
    expect(find.text('Raise a regularization request'), findsOneWidget);
    expect(find.text('Employee', findRichText: true), findsNothing, reason: 'the day fixes the employee');
    expect(find.text('2026-10-01'), findsWidgets, reason: 'the date comes from the day');
    await tester.tap(find.byType(DropdownButtonFormField<String>).first);
    await tester.pumpAndSettle();
    await tester.tap(find.text('Wrong status').last);
    await tester.pumpAndSettle();
    final label = find.text('Check-in time', findRichText: true);
    final checkIn = find.descendant(of: find.ancestor(of: label, matching: find.byType(AuthFormField)).first, matching: find.byType(TextField));
    await tester.tap(checkIn);
    await tester.pumpAndSettle();
    await tester.tap(find.text('OK'));
    await tester.pumpAndSettle();
    await tester.ensureVisible(find.text('Submit request'));
    await tester.tap(find.text('Submit request'));
    await tester.pumpAndSettle();
    final post = api.calls.singleWhere((c) => c.method == 'POST' && c.path == '/regularizations');
    expect(post.body['employee_id'], 'e-1');
    expect(post.body['attendance_date'], '2026-10-01');
    expect(post.body['request_type'], 'WRONG_STATUS');
  });
}
