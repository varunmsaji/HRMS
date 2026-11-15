import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:go_router/go_router.dart';
import 'package:hrms_mobile/core/api/api_error.dart';
import 'package:hrms_mobile/core/auth/permissions.dart';
import 'package:hrms_mobile/core/nav/nav_entries.dart';
import 'package:hrms_mobile/core/providers.dart';
import 'package:hrms_mobile/core/theme/app_theme.dart';
import 'package:hrms_mobile/features/approvals/data/approvals_repository.dart';
import 'package:hrms_mobile/features/approvals/presentation/approvals_screen.dart';

import 'support/fake_api_client.dart';
import 'support/fake_auth.dart';
import 'support/test_themes.dart';

Map<String, dynamic> _leave(String id, String employeeId) => {
      'id': id,
      'employee_id': employeeId,
      'leave_type_id': 'lt-1',
      'start_date': '2026-11-12',
      'end_date': '2026-11-13',
      'total_days': '2',
      'status': 'SUBMITTED',
      'submitted_at': '2026-11-10T09:00:00Z',
    };

FakeApiClient _api({List<Map<String, dynamic>> leave = const [], List<Map<String, dynamic>> corrections = const [], Map<String, Object> failing = const {}}) => FakeApiClient(
      lists: {
        '/leave-applications': leave,
        '/regularizations': corrections,
        '/overtime': const [],
        '/leave-types': [
          {'id': 'lt-1', 'name': 'Casual leave'},
        ],
      },
      objects: {
        '/employees/e-2': {'id': 'e-2', 'employee_code': 'EMP-2', 'first_name': 'Ravi', 'last_name': 'Kumar', 'status': 'ACTIVE', 'is_active': true, 'version': 1},
      },
      failing: failing,
    );

void main() {
  setUpAll(primeThemes);

  group('which queues a user gets', () {
    test('one queue per approve permission; onboarding needs review and view', () {
      expect(approvalKindsFor([leaveApplicationApprove]), [ApprovalKind.leave]);
      expect(approvalKindsFor([attendanceRegularizationApprove, attendanceOvertimeApprove]), [ApprovalKind.correction, ApprovalKind.overtime]);
      expect(approvalKindsFor([onboardingReview]), isEmpty);
      expect(approvalKindsFor([onboardingReview, onboardingView]), [ApprovalKind.onboarding]);
      expect(canApproveAnything([attendancePunch, leaveApplicationSubmit]), isFalse);
    });

    test('the menu offers Approvals to approvers only', () {
      bool listed(List<String> p) => visibleNavGroups(p).expand((g) => g.items).any((e) => e.route == '/app/approvals');
      expect(listed([leaveApplicationApprove]), isTrue);
      expect(listed([onboardingReview]), isTrue);
      expect(listed([attendancePunch, leaveApplicationSubmit]), isFalse);
    });
  });

  group('ApprovalsRepository', () {
    test('lists others\' requests with names and readable dates, never the user\'s own', () async {
      final repo = ApprovalsRepository(_api(leave: [_leave('a-1', 'e-2'), _leave('a-mine', 'e-1')]));
      final queues = await repo.load([leaveApplicationApprove], myEmployeeId: 'e-1');
      expect(queues, hasLength(1));
      final q = queues.single;
      expect(q.total, 1, reason: 'the user\'s own request is not counted');
      expect(q.items.map((i) => i.id), ['a-1']);
      final item = q.items.single;
      expect(item.name, 'Ravi Kumar');
      expect(item.title, 'Casual leave');
      expect(item.subtitle, '12–13 Nov · 2 days');
      expect(item.route, '/app/leave-applications/a-1');
    });

    test('a queue that cannot be read is marked failed; the others still load', () async {
      final repo = ApprovalsRepository(_api(
        leave: [_leave('a-1', 'e-2')],
        failing: {'/regularizations': ApiError(status: 500, code: 'X', message: 'down')},
      ));
      final queues = await repo.load([leaveApplicationApprove, attendanceRegularizationApprove], myEmployeeId: 'e-1');
      expect(queues.firstWhere((q) => q.kind == ApprovalKind.leave).total, 1);
      expect(queues.firstWhere((q) => q.kind == ApprovalKind.correction).failed, isTrue);
    });

    test('count adds every queue', () async {
      final repo = ApprovalsRepository(_api(
        leave: [_leave('a-1', 'e-2')],
        corrections: [
          {'id': 'r-1', 'employee_id': 'e-2', 'attendance_date': '2026-11-11', 'request_type': 'MISSING_PUNCH', 'status': 'SUBMITTED'},
        ],
      ));
      expect(await repo.count([leaveApplicationApprove, attendanceRegularizationApprove], myEmployeeId: 'e-1'), 2);
    });
  });

  group('ApprovalsScreen', () {
    Future<GoRouter> pump(WidgetTester tester, FakeApiClient api, List<String> permissions) async {
      final router = GoRouter(initialLocation: '/app/approvals', routes: [
        GoRoute(path: '/app/approvals', builder: (_, __) => const ApprovalsScreen()),
        GoRoute(path: '/app/leave-applications/:id', builder: (_, s) => Scaffold(body: Text('leave ${s.pathParameters['id']}'))),
        GoRoute(path: '/app/leave-applications', builder: (_, __) => const Scaffold(body: Text('leave list'))),
      ]);
      await tester.pumpWidget(ProviderScope(
        overrides: [fakeAuth(permissions, employeeId: 'e-1'), apiClientProvider.overrideWithValue(api)],
        child: MaterialApp.router(theme: AppTheme.light, routerConfig: router),
      ));
      await tester.pumpAndSettle();
      return router;
    }

    testWidgets('nothing waiting: says so plainly', (tester) async {
      await pump(tester, _api(), [leaveApplicationApprove]);
      expect(find.text('You\'re all caught up'), findsOneWidget);
    });

    testWidgets('a waiting request shows who and what, and a tap opens that request', (tester) async {
      await pump(tester, _api(leave: [_leave('a-1', 'e-2')]), [leaveApplicationApprove]);
      expect(find.text('Leave · 1'), findsOneWidget);
      expect(find.text('Ravi Kumar · Casual leave'), findsOneWidget);
      await tester.tap(find.text('Ravi Kumar · Casual leave'));
      await tester.pumpAndSettle();
      expect(find.text('leave a-1'), findsOneWidget);
    });

    testWidgets('a queue that failed says so with a retry, instead of looking empty', (tester) async {
      await pump(tester, _api(failing: {'/leave-applications': ApiError(status: 500, code: 'X', message: 'down')}), [leaveApplicationApprove]);
      expect(find.text('Couldn\'t load these requests.'), findsOneWidget);
      expect(find.text('Try again'), findsOneWidget);
      expect(find.text('You\'re all caught up'), findsNothing);
    });
  });
}
