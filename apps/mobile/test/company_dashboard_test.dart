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
  _Repo({this.overview = const {'total': 12, 'present': 8, 'on_leave': 1, 'absent': 1, 'not_checked_in': 2}, this.insights = const {}, this.queues = const {}, this.onboarding = const {}, this.branches = const []});
  final Map<String, dynamic> overview;
  final Map<String, dynamic> insights;
  final Map<String, PendingQueue> queues;
  final Map<String, int> onboarding;
  final List<({String id, String name})> branches;
  final insightScopes = <String>[];
  final insightBranches = <String?>[];
  final overviewBranches = <String?>[];

  @override
  Future<CompanyDashboardSummary> getCompanyDashboard() async => CompanyDashboardSummary.fromJson({
        'setup_progress': {'status': 'COMPLETE', 'steps_completed': 5, 'steps_total': 5},
        'employee_count': 12,
      });

  @override
  Future<CompanyProfileSummary> getCompanyProfile() async => CompanyProfileSummary(id: 'c-1', name: 'Acme', status: 'ACTIVE');

  @override
  Future<AttendanceOverviewSummary> getAttendanceOverview({String? branchId}) async {
    overviewBranches.add(branchId);
    return AttendanceOverviewSummary.fromJson(branchId == null ? overview : {...overview, 'present': 3});
  }

  @override
  Future<List<({String id, String name})>> activeBranches() async => branches;

  @override
  Future<CompanyInsights> getInsights({String leaveScope = 'month', String? branchId}) async {
    insightScopes.add(leaveScope);
    insightBranches.add(branchId);
    return CompanyInsights.fromJson({...insights, if (leaveScope == 'year') 'leave_statistics': {'total_days': 0, 'by_type': []}});
  }

  @override
  Future<int> countPending(String path, Map<String, dynamic> filters) async => onboarding[filters['status']] ?? 0;

  @override
  Future<PendingQueue> pendingQueue(String kind, String path, Map<String, dynamic> filters, {String timeField = 'submitted_at', int size = 5}) async =>
      queues[kind] ?? PendingQueue(total: 0, items: const []);

  @override
  Future<Map<String, String>> employeeNames(Iterable<String> ids) async => {'e-1': 'Asha Rao', 'e-2': 'Ravi K'};

  @override
  dynamic noSuchMethod(Invocation invocation) => super.noSuchMethod(invocation);
}

Future<_Repo> _pump(WidgetTester tester, List<String> permissions, [_Repo? r]) async {
  final repo = r ?? _Repo();
  tester.view.physicalSize = const Size(400, 3000);
  tester.view.devicePixelRatio = 1;
  addTearDown(tester.view.reset);
  await tester.pumpWidget(ProviderScope(
    overrides: [dashboardRepositoryProvider.overrideWithValue(repo), fakeAuth(permissions)],
    child: MaterialApp(theme: AppTheme.light, home: const DashboardScreen()),
  ));
  await tester.pumpAndSettle();
  return repo;
}

void main() {
  group('branch picker', () {
    testWidgets('hidden with one branch or none, as on web', (tester) async {
      await _pump(tester, const [dashboardCompanyView, attendanceView], _Repo(branches: const [(id: 'b-1', name: 'Kochi')]));
      expect(find.byKey(const Key('dashboard-branch')), findsNothing);
    });

    testWidgets('narrows the attendance overview and insights to one branch', (tester) async {
      final repo = await _pump(
        tester,
        const [dashboardCompanyView, attendanceView],
        _Repo(branches: const [(id: 'b-1', name: 'Kochi'), (id: 'b-2', name: 'Pune')]),
      );
      expect(find.text('All branches'), findsOneWidget);
      expect(repo.overviewBranches, [null]);
      expect(repo.insightBranches, [null]);

      await tester.tap(find.byKey(const Key('dashboard-branch')));
      await tester.pumpAndSettle();
      await tester.tap(find.text('Pune').last);
      await tester.pumpAndSettle();

      expect(repo.overviewBranches, [null, 'b-2']);
      expect(repo.insightBranches, [null, 'b-2']);
      expect(find.text('3'), findsWidgets, reason: "Pune's present count replaces the company's");
    });
  });

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

  group('figures', () {
    testWidgets("headline tiles carry web's comparisons and notes", (tester) async {
      await _pump(
        tester,
        const [dashboardCompanyView, attendanceView],
        _Repo(
          overview: const {'total': 20, 'present': 12, 'on_leave': 2, 'absent': 1, 'expected_employees': 18, 'late': 3, 'half_day_leave': 1},
          insights: const {'kpi_comparison': {'headcount_prev_month_end': 16, 'yesterday': '2026-11-08', 'yesterday_present': 10, 'yesterday_on_leave': 4}},
        ),
      );
      expect(find.text('TOTAL EMPLOYEES'), findsOneWidget); // tiles show labels in capitals
      expect(find.text('20'), findsWidgets); // the tile, and the chart's total
      expect(find.text('+25% vs last month · 18 expected to work today'), findsOneWidget);
      expect(find.text('+20% vs yesterday · 3 late arrivals'), findsOneWidget);
      expect(find.text('-50% vs yesterday · 1 half-day'), findsOneWidget);
    });

    testWidgets("the attendance chart uses web's buckets", (tester) async {
      await _pump(tester, const [dashboardCompanyView, attendanceView], _Repo(overview: const {'total': 10, 'present': 4, 'on_leave': 1, 'absent': 1, 'remote_work': 2, 'on_duty': 1}));
      expect(find.text('Attendance Overview'), findsOneWidget);
      for (final label in ['WFH', 'On duty', 'Others']) {
        expect(find.textContaining(label), findsWidgets, reason: label);
      }
    });

    testWidgets('nobody checked in yet: a note, not an empty ring', (tester) async {
      await _pump(tester, const [dashboardCompanyView, attendanceView], _Repo(overview: const {'total': 10, 'expected_employees': 9}));
      expect(find.text('No check-ins recorded yet'), findsOneWidget);
      expect(find.text('10 employees · 9 expected to work today'), findsOneWidget);
    });

    testWidgets('pending approvals count onboarding and list the newest requests with names', (tester) async {
      await _pump(
        tester,
        const [dashboardCompanyView, leaveApplicationApprove, onboardingReview, onboardingView],
        _Repo(
          queues: {
            'leave': PendingQueue(total: 3, items: [
              PendingItem(kind: 'leave', id: 'l-1', employeeId: 'e-1', at: '2026-11-08T05:00:00Z'),
              PendingItem(kind: 'leave', id: 'l-2', employeeId: 'e-2', at: '2026-11-09T05:00:00Z'),
            ]),
          },
          onboarding: const {'SUBMITTED': 2, 'INVITED': 1},
        ),
      );
      expect(find.text('PENDING APPROVALS'), findsOneWidget);
      expect(find.text('Pending Approvals'), findsOneWidget);
      expect(find.text('6'), findsOneWidget); // 3 leave + 2 awaiting HR + 1 with the candidate
      expect(find.text('3 Leave'), findsOneWidget);
      expect(find.text('Leave Request'), findsNWidgets(2));
      expect(find.textContaining('Ravi K'), findsOneWidget);
      expect(find.textContaining('Asha Rao'), findsOneWidget);
      // Newest first.
      expect(tester.getTopLeft(find.textContaining('Ravi K')).dy, lessThan(tester.getTopLeft(find.textContaining('Asha Rao')).dy));
    });

    testWidgets('onboarding is not counted without both onboarding permissions', (tester) async {
      await _pump(
        tester,
        const [dashboardCompanyView, leaveApplicationApprove, onboardingReview],
        _Repo(queues: {'leave': PendingQueue(total: 3, items: const [])}, onboarding: const {'SUBMITTED': 2}),
      );
      expect(find.text('3'), findsOneWidget);
      expect(find.text('Nothing pending.'), findsOneWidget);
    });

    testWidgets('leave statistics switch between this month and this year', (tester) async {
      final repo = await _pump(
        tester,
        const [dashboardCompanyView],
        _Repo(insights: const {
          'leave_statistics': {
            'period_start': '2026-11-01',
            'period_end': '2026-11-30',
            'total_days': 4,
            'by_type': [{'leave_type_id': 't-1', 'name': 'Casual Leave', 'days': 4}],
          },
        }),
      );
      expect(find.text('Leave Statistics'), findsOneWidget);
      expect(find.text('01 Nov 2026 – 30 Nov 2026'), findsOneWidget);
      expect(find.textContaining('Casual'), findsWidgets);
      await tester.tap(find.text('This Year'));
      await tester.pumpAndSettle();
      expect(repo.insightScopes.last, 'year');
      expect(find.text('No approved leave in this period.'), findsOneWidget);
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
