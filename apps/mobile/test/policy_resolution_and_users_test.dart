import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:hrms_mobile/core/auth/permissions.dart';
import 'package:hrms_mobile/core/providers.dart';
import 'package:hrms_mobile/features/attendance/presentation/policy_resolution_screen.dart';
import 'package:hrms_mobile/features/onboarding/presentation/users_screen.dart';

import 'support/fake_api_client.dart';
import 'support/fake_auth.dart';

Future<void> _pump(WidgetTester tester, FakeApiClient api, List<String> permissions, Widget home) async {
  tester.view.physicalSize = const Size(800, 4000);
  tester.view.devicePixelRatio = 1;
  addTearDown(tester.view.reset);
  await tester.pumpWidget(ProviderScope(overrides: [apiClientProvider.overrideWithValue(api), fakeAuth(permissions)], child: MaterialApp(home: home)));
  await tester.pumpAndSettle();
}

void main() {
  group('policy resolution', () {
    FakeApiClient api(Map<String, Map<String, dynamic>> objects) => FakeApiClient(lists: {
          '/employees': [
            {'id': 'e1', 'first_name': 'Asha', 'last_name': 'Rao', 'employee_code': 'E-1'}
          ],
        }, objects: objects);

    Future<void> chooseEmployee(WidgetTester tester) async {
      await tester.tap(find.byType(DropdownButtonFormField<String>).first);
      await tester.pumpAndSettle();
      await tester.tap(find.text('Asha Rao (E-1)').last);
      await tester.pumpAndSettle();
    }

    testWidgets('needs an employee first', (tester) async {
      await _pump(tester, api(const {}), const [], const PolicyResolutionScreen());
      await tester.tap(find.text('Resolve'));
      await tester.pumpAndSettle();
      expect(find.text('Choose an employee and a date.'), findsOneWidget);
    });

    testWidgets('an attendance policy resolves through the endpoint with kind, employee and date', (tester) async {
      final client = api({
        '/attendance-policy-resolution': {'config_incomplete': false, 'resolved_policy_name': 'Standard', 'resolved_policy_code': 'STD', 'resolved_through': 'BRANCH', 'resolved_version_id': 'v-1'},
      });
      await _pump(tester, client, const [], const PolicyResolutionScreen());
      await chooseEmployee(tester);
      await tester.tap(find.text('Resolve'));
      await tester.pumpAndSettle();
      expect(find.text('Standard (STD)'), findsOneWidget);
      expect(find.text('Branch'), findsOneWidget);
      expect(find.text('v-1'), findsOneWidget);
    });

    testWidgets('an unassigned kind says CONFIG_INCOMPLETE rather than inventing a default', (tester) async {
      final client = api({'/attendance-policy-resolution': {'config_incomplete': true}});
      await _pump(tester, client, const [], const PolicyResolutionScreen());
      await chooseEmployee(tester);
      await tester.tap(find.text('Resolve'));
      await tester.pumpAndSettle();
      expect(find.text('CONFIG_INCOMPLETE'), findsOneWidget);
      expect(find.textContaining('never silently falls back'), findsOneWidget);
    });

    testWidgets('the work calendar uses the calendar-resolution endpoint', (tester) async {
      final client = api({
        '/calendar-resolution': {
          'config_incomplete': false,
          'work_calendar_name': 'Standard 5-day',
          'resolved_scope_type': 'COMPANY',
          'weekly_off_resolved_scope_type': 'COMPANY',
          'day_type': {'day_type': 'WEEKLY_OFF', 'holiday_name': null},
        },
      });
      await _pump(tester, client, const [], const PolicyResolutionScreen());
      await chooseEmployee(tester);
      await tester.tap(find.byType(DropdownButtonFormField<String>).last);
      await tester.pumpAndSettle();
      await tester.tap(find.text('Work Calendar').last);
      await tester.pumpAndSettle();
      await tester.tap(find.text('Resolve'));
      await tester.pumpAndSettle();
      expect(find.text('Standard 5-day'), findsOneWidget);
      expect(find.text('Weekly off'), findsOneWidget);
    });
  });

  group('users', () {
    final users = [
      {'user_id': 'u1', 'email': 'admin@example.com', 'first_name': 'Asha', 'last_name': 'Rao', 'status': 'ACTIVE', 'is_primary': true, 'role_codes': ['COMPANY_ADMIN']},
      {'user_id': 'u2', 'email': null, 'first_name': null, 'last_name': null, 'status': 'ACTIVE', 'is_primary': false, 'role_codes': <String>[]},
    ];

    testWidgets('lists users with readable roles and handles a user without email or roles', (tester) async {
      await _pump(tester, FakeApiClient(lists: {'/users': users}), const [], const UsersScreen());
      expect(find.text('Asha Rao'), findsOneWidget);
      expect(find.textContaining('Company admin'), findsOneWidget);
      expect(find.text('No email'), findsWidgets);
      expect(find.textContaining('No roles'), findsOneWidget);
      expect(find.text('Invite user'), findsNothing);
    });

    test('role labels read as words, including the branch manager role', () {
      expect(roleLabel('HR_ADMIN'), 'HR admin');
      expect(roleLabel('BRANCH_MANAGER'), 'Branch manager');
      expect(roleLabel('REPORTING_MANAGER'), 'Reporting manager');
    });

    testWidgets('inviting needs SETTINGS.USER.MANAGE', (tester) async {
      await _pump(tester, FakeApiClient(lists: {'/users': users}), [settingsUserManage], const UsersScreen());
      expect(find.text('Invite user'), findsOneWidget);
    });

    testWidgets('changing roles needs SETTINGS.ROLE.MANAGE, and offers every assignable role', (tester) async {
      final api = FakeApiClient(lists: {'/users': users}, objects: {'/users/u2/roles': const {}});
      await _pump(tester, api, [settingsRoleManage], const UsersScreen());
      await tester.tap(find.text('No email').first);
      await tester.pumpAndSettle();
      for (final r in const ['Company admin', 'HR admin', 'Reporting manager', 'Branch manager', 'Employee']) {
        expect(find.text(r), findsWidgets);
      }
    });
  });
}
