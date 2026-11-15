import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:hrms_mobile/core/auth/permissions.dart';
import 'package:hrms_mobile/core/format.dart';
import 'package:hrms_mobile/core/providers.dart';
import 'package:hrms_mobile/core/theme/app_theme.dart';
import 'package:hrms_mobile/features/leave/data/leave_repository.dart';
import 'package:hrms_mobile/features/leave/presentation/leave_apply_screen.dart';

import 'support/fake_api_client.dart';
import 'support/fake_auth.dart';
import 'support/test_themes.dart';

class _Leave implements LeaveRepository {
  final submitted = <Map<String, dynamic>>[];

  @override
  Future<List<LeaveBalance>> listLeaveBalances(String employeeId) async => [
        LeaveBalance.fromJson({'employee_id': employeeId, 'leave_type_id': 'lt-cl', 'leave_type_code': 'CL', 'leave_type_name': 'Casual leave', 'balance': '4', 'reserved_balance': '0'}),
      ];

  @override
  Future<LeaveApplication> submitLeaveApplication(Map<String, dynamic> body, {String? idempotencyKey}) async {
    submitted.add(body);
    throw UnimplementedError();
  }

  @override
  dynamic noSuchMethod(Invocation invocation) => super.noSuchMethod(invocation);
}

FakeApiClient _api() => FakeApiClient(lists: {
      '/leave-types': [
        {'id': 'lt-cl', 'name': 'Casual leave', 'is_active': true},
        {'id': 'lt-ml', 'name': 'Maternity leave', 'is_active': true, 'statutory_category': 'MATERNITY'},
        {'id': 'lt-old', 'name': 'Retired type', 'is_active': false},
      ],
    });

Future<_Leave> _pump(WidgetTester tester) async {
  final repo = _Leave();
  tester.view.physicalSize = const Size(390, 1600);
  tester.view.devicePixelRatio = 1;
  addTearDown(tester.view.reset);
  await tester.pumpWidget(ProviderScope(
    overrides: [fakeAuth([leaveApplicationSubmit, leaveBalanceView], employeeId: 'e-1'), leaveRepositoryProvider.overrideWithValue(repo), apiClientProvider.overrideWithValue(_api())],
    child: MaterialApp(theme: AppTheme.employee, home: const LeaveApplyScreen()),
  ));
  await tester.pumpAndSettle();
  return repo;
}

void main() {
  setUpAll(primeThemes);

  testWidgets('leave types are chips showing what is left; inactive types are not offered', (tester) async {
    await _pump(tester);
    expect(find.widgetWithText(ChoiceChip, 'Casual leave · 4 left'), findsOneWidget);
    expect(find.widgetWithText(ChoiceChip, 'Maternity leave'), findsOneWidget);
    expect(find.text('Retired type'), findsNothing);
  });

  testWidgets('the delivery date is asked for maternity leave only', (tester) async {
    await _pump(tester);
    expect(find.text('Expected delivery date', findRichText: true), findsNothing);
    await tester.tap(find.text('Maternity leave'));
    await tester.pumpAndSettle();
    expect(find.text('Expected delivery date', findRichText: true), findsOneWidget);
    await tester.tap(find.text('Casual leave · 4 left'));
    await tester.pumpAndSettle();
    expect(find.text('Expected delivery date', findRichText: true), findsNothing);
  });

  testWidgets('choosing a type shows its balance; the summary says the rules decide the charge', (tester) async {
    await _pump(tester);
    await tester.tap(find.text('Casual leave · 4 left'));
    await tester.pumpAndSettle();
    expect(find.text('Casual leave: 4 available'), findsOneWidget);
    expect(find.text('Your company\'s leave rules decide the days charged.'), findsOneWidget);
  });

  testWidgets('submitting without type or dates says what is missing and sends nothing', (tester) async {
    final repo = await _pump(tester);
    await tester.tap(find.widgetWithText(FilledButton, 'Submit request'));
    await tester.pumpAndSettle();
    expect(find.text('Choose a leave type.'), findsOneWidget);
    expect(find.text('Choose the dates of your leave.'), findsOneWidget);
    expect(repo.submitted, isEmpty);
  });

  testWidgets('the document reference is tucked away until asked for', (tester) async {
    await _pump(tester);
    expect(find.text('Document reference', findRichText: true), findsNothing);
    await tester.tap(find.text('Add a document reference'));
    await tester.pumpAndSettle();
    expect(find.text('Document reference', findRichText: true), findsOneWidget);
  });

  test('day formatting', () {
    expect(formatDayDate('2026-11-12', now: DateTime(2026, 6)), 'Thu, 12 Nov');
    expect(formatDayDate('2027-01-04', now: DateTime(2026, 6)), 'Mon, 4 Jan 2027');
    expect(formatLeaveDays(4), '4');
    expect(formatLeaveDays(8.5), '8.5');
    expect(formatDateRange('2026-11-12', '2026-11-13'), '12–13 Nov');
    expect(formatDateRange('2026-10-30', '2026-11-02'), '30 Oct – 2 Nov');
  });
}
