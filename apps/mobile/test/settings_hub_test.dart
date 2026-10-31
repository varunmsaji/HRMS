import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:hrms_mobile/core/auth/auth_types.dart';
import 'package:hrms_mobile/core/auth/permissions.dart';
import 'package:hrms_mobile/features/auth/state/auth_controller.dart';
import 'package:hrms_mobile/features/auth/state/auth_state.dart';
import 'package:hrms_mobile/features/shell/settings_hub_screen.dart';

/// T3-01: the More menu shows what the signed-in user may open, and nothing else.
const _employeeGrants = [
  'EMPLOYEE.VIEW', 'EMPLOYEE.VIEW_COMPENSATION', 'EMPLOYEE.VIEW_DOCUMENTS', //
  leaveApplicationSubmit, leaveBalanceView, attendancePunch, attendanceView, attendanceRegularizationRequest, payrollPayslipViewOwn,
];

class _Auth extends StateNotifier<AuthState> implements AuthController {
  _Auth(super.state);
  var logouts = 0;
  @override
  Future<void> logout() async => logouts++;
  @override
  dynamic noSuchMethod(Invocation invocation) => super.noSuchMethod(invocation);
}

Future<_Auth> _pump(WidgetTester tester, List<String> permissions, {String? employeeId = 'e-1'}) async {
  final auth = _Auth(AuthState(
    status: AuthStatus.authenticated,
    user: UserProfile(id: 'u', email: 'a@b.c', companyId: 'c', employeeId: employeeId, permissions: permissions, companyTimezone: 'Asia/Kolkata'),
  ));
  await tester.pumpWidget(ProviderScope(
    overrides: [authControllerProvider.overrideWith((ref) => auth)],
    child: const MaterialApp(home: SettingsHubScreen()),
  ));
  await tester.pumpAndSettle();
  return auth;
}

/// A `Text` with this label (the search box's own text is not a `Text` widget).
Finder _t(String label) => find.byWidgetPredicate((w) => w is Text && w.data == label);

Future<void> _search(WidgetTester tester, String text) async {
  await tester.enterText(find.byType(TextField), text);
  await tester.pumpAndSettle();
}

const _adminOnlyLabels = ['Users', 'Payroll', 'Departments', 'Employees', 'Company', 'Shifts', 'Leave Types', 'Salary Components', 'Setup', 'Branches'];

void main() {
  group('employee', () {
    testWidgets('sees exactly their four destinations, in employee wording, and Sign out', (tester) async {
      await _pump(tester, _employeeGrants);
      for (final label in ['Leave balances', 'Attendance corrections', 'Overtime', 'Sign out']) {
        expect(_t(label), findsOneWidget, reason: label);
      }
      expect(_t('Payslips'), findsNothing, reason: 'payroll is outside the attendance-only release');
      for (final label in _adminOnlyLabels) {
        expect(_t(label), findsNothing, reason: '$label must not be offered to an employee');
      }
      expect(_t('Quick links'), findsNothing);
    });

    testWidgets('search can not reveal a hidden entry', (tester) async {
      await _pump(tester, _employeeGrants);
      for (final word in ['Users', 'Payroll', 'Departments', 'Employees', 'Shifts']) {
        await _search(tester, word);
        expect(_t('No matches'), findsOneWidget, reason: word);
      }
      await _search(tester, 'payslip');
      expect(_t('No matches'), findsOneWidget, reason: 'payslips are unavailable in this release');
    });

    testWidgets('an entry whose permission is missing is not shown', (tester) async {
      await _pump(tester, [...?null, attendanceView, leaveBalanceView]);
      expect(_t('Payslips'), findsNothing);
      expect(_t('Overtime'), findsOneWidget);
    });
  });

  group('administrators and managers keep what they may use', () {
    testWidgets('an administrator with only user management sees Users and nothing from payroll or organisation', (tester) async {
      await _pump(tester, [dashboardCompanyView, settingsUserManage]);
      await _search(tester, 'Users');
      expect(_t('Users'), findsOneWidget);
      for (final word in ['Payroll', 'Departments', 'Company', 'Shifts']) {
        await _search(tester, word);
        expect(_t('No matches'), findsOneWidget, reason: word);
      }
    });

    testWidgets('an administrator with broad grants sees the full structure', (tester) async {
      await _pump(tester, [
        dashboardCompanyView, employeeViewAll, attendanceViewAll, attendanceView, leaveBalanceView, payrollPayslipViewOwn,
        orgCompanyManage, orgDepartmentManage, settingsUserManage, payrollRunView, //
      ]);
      expect(_t('Quick links'), findsOneWidget);
      expect(_t('Employees'), findsOneWidget);
      await _search(tester, 'Departments');
      expect(_t('Departments'), findsOneWidget);
      await _search(tester, 'Payroll');
      expect(_t('No matches'), findsOneWidget, reason: 'payroll is unavailable in this release even for an administrator');
    });

    testWidgets('a branch manager (employee surface with team permissions) keeps Employees and Team attendance', (tester) async {
      await _pump(tester, [..._employeeGrants, employeeViewAll]);
      expect(_t('Your work'), findsOneWidget);
      expect(_t('Payslips'), findsNothing);
      await _search(tester, 'Employees');
      expect(_t('Employees'), findsOneWidget);
      await _search(tester, 'Team Attendance');
      expect(_t('Team Attendance'), findsOneWidget);
      await _search(tester, 'Users');
      expect(_t('No matches'), findsOneWidget);
    });

    testWidgets('an administrator keeps the original labels', (tester) async {
      await _pump(tester, [dashboardCompanyView, attendanceView, leaveBalanceView, payrollPayslipViewOwn]);
      expect(_t('Regularizations'), findsOneWidget);
      expect(_t('Leave Balances'), findsOneWidget);
      expect(_t('My Payslips'), findsNothing);
      expect(_t('Attendance corrections'), findsNothing);
    });
  });

  group('Sign out (the existing confirmation, unchanged)', () {
    testWidgets('Cancel keeps the session', (tester) async {
      final auth = await _pump(tester, _employeeGrants);
      await tester.tap(_t('Sign out'));
      await tester.pumpAndSettle();
      expect(_t('Sign out?'), findsOneWidget);
      expect(_t('You will need to sign in again to use the app.'), findsOneWidget);
      await tester.tap(_t('Cancel'));
      await tester.pumpAndSettle();
      expect(auth.logouts, 0);
    });

    testWidgets('Confirm signs out', (tester) async {
      final auth = await _pump(tester, _employeeGrants);
      await tester.tap(_t('Sign out'));
      await tester.pumpAndSettle();
      await tester.tap(find.widgetWithText(FilledButton, 'Sign out'));
      await tester.pumpAndSettle();
      expect(auth.logouts, 1);
    });
  });
}
