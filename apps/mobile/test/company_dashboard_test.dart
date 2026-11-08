import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:hrms_mobile/core/auth/permissions.dart';
import 'package:hrms_mobile/core/nav/nav_entries.dart';
import 'package:hrms_mobile/core/theme/app_theme.dart';
import 'package:hrms_mobile/features/dashboard/data/dashboard_repository.dart';
import 'package:hrms_mobile/features/dashboard/presentation/dashboard_screen.dart';

import 'support/fake_auth.dart';

/// The company dashboard — web `components/dashboard/dashboard-overview.tsx`.

class _Repo implements DashboardRepository {
  @override
  Future<CompanyDashboardSummary> getCompanyDashboard() async => CompanyDashboardSummary.fromJson({
        'setup_progress': {'status': 'COMPLETE', 'steps_completed': 5, 'steps_total': 5},
        'employee_count': 12,
      });

  @override
  Future<CompanyProfileSummary> getCompanyProfile() async => CompanyProfileSummary(id: 'c-1', name: 'Acme', status: 'ACTIVE');

  @override
  Future<AttendanceOverviewSummary> getAttendanceOverview() async => AttendanceOverviewSummary.fromJson({'total': 12, 'present': 8, 'on_leave': 1, 'absent': 1, 'not_checked_in': 2});

  @override
  Future<CompanyInsights> getInsights() async => CompanyInsights.fromJson(const {});

  @override
  Future<int> countPending(String path, Map<String, dynamic> filters) async => 0;

  @override
  dynamic noSuchMethod(Invocation invocation) => super.noSuchMethod(invocation);
}

Future<void> _pump(WidgetTester tester, List<String> permissions) async {
  tester.view.physicalSize = const Size(400, 3000);
  tester.view.devicePixelRatio = 1;
  addTearDown(tester.view.reset);
  await tester.pumpWidget(ProviderScope(
    overrides: [dashboardRepositoryProvider.overrideWithValue(_Repo()), fakeAuth(permissions)],
    child: MaterialApp(theme: AppTheme.light, home: const DashboardScreen()),
  ));
  await tester.pumpAndSettle();
}

void main() {
  group('shortcut tiles', () {
    testWidgets('offer only what the viewer can open, as the menu does', (tester) async {
      await _pump(tester, const [dashboardCompanyView, employeeViewAll]);
      expect(find.text('Employees'), findsOneWidget);
      expect(find.text('Onboarding'), findsNothing);
      expect(find.text('Company'), findsNothing);
      expect(find.text('Rosters'), findsNothing);
    });

    testWidgets('no tiles at all when none can be opened', (tester) async {
      await _pump(tester, const [dashboardCompanyView]);
      for (final label in ['Employees', 'Onboarding', 'Attendance', 'Leave', 'Rosters', 'Requests', 'Company']) {
        expect(find.text(label), findsNothing, reason: label);
      }
    });
  });

  test('menuAllows follows the menu entry, and payroll stays hidden while paused', () {
    expect(menuAllows('/app/employees', const [employeeViewAll]), isTrue);
    expect(menuAllows('/app/employees', const [attendanceView]), isFalse);
    expect(menuAllows('/app/payroll/pay-runs', const [payrollRunView], payroll: false), isFalse);
    expect(menuAllows('/app/payroll/pay-runs', const [payrollRunView], payroll: true), isTrue);
    expect(menuAllows('/app/not-in-the-menu', const []), isTrue);
  });
}
