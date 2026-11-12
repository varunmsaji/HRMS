import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:go_router/go_router.dart';
import 'package:hrms_mobile/core/auth/auth_types.dart';
import 'package:hrms_mobile/core/auth/permissions.dart';
import 'package:hrms_mobile/core/nav/nav_entries.dart';
import 'package:hrms_mobile/core/router/app_router.dart';
import 'package:hrms_mobile/core/theme/app_theme.dart';
import 'package:hrms_mobile/core/theme/employee_theme_scope.dart';
import 'package:hrms_mobile/core/theme/employee_tokens.dart';
import 'package:hrms_mobile/features/attendance/data/attendance_repository.dart';
import 'package:hrms_mobile/features/auth/state/auth_state.dart';
import 'package:hrms_mobile/features/shell/settings_hub_screen.dart';
import 'package:hrms_mobile/main.dart';

import 'support/fake_auth.dart';
import 'support/test_themes.dart';

UserProfile _user(List<String> permissions, {String? employeeId}) => UserProfile(
      id: 'u',
      email: 'a@b.c',
      companyId: 'c',
      employeeId: employeeId,
      permissions: permissions,
      companyTimezone: 'Asia/Kolkata',
    );

AuthState _auth(UserProfile? user, {AuthStatus status = AuthStatus.authenticated}) => AuthState(status: status, user: user);

class _AttendanceRepo implements AttendanceRepository {
  @override
  Future<FaceEnrollmentStatus> getMyFaceEnrollment() async => FaceEnrollmentStatus();
  @override
  Future<List<AttendanceDay>> listAttendanceDays({String? employeeId, required String dateFrom, required String dateTo, String? attendanceStatus}) async => [];
  @override
  Future<List<Punch>> listPunches({required String employeeId, required String dateFrom, required String dateTo}) async => [];
  @override
  dynamic noSuchMethod(Invocation invocation) => super.noSuchMethod(invocation);
}

void main() {
  setUpAll(primeThemes);

  group('landingPathFor (D-01)', () {
    test('administrator -> dashboard', () => expect(landingPathFor(_user([dashboardCompanyView], employeeId: 'e')), '/app/dashboard'));
    test('employee -> Home', () => expect(landingPathFor(_user([attendancePunch], employeeId: 'e')), '/app/home'));
    test('manager -> Home', () => expect(landingPathFor(_user([leaveApplicationApprove], employeeId: 'e')), '/app/home'));
    test('no employee record -> the explanatory dashboard page', () => expect(landingPathFor(_user([])), '/app/dashboard'));
    test('no profile -> dashboard', () => expect(landingPathFor(null), '/app/dashboard'));
  });

  group('appRedirect', () {
    final employee = _auth(_user([attendancePunch], employeeId: 'e'));
    final admin = _auth(_user([dashboardCompanyView], employeeId: 'e'));
    final noRecord = _auth(_user([]));

    test('public token routes always pass, signed in or not', () {
      for (final path in ['/reset-password/t', '/verify-email/t', '/accept-invite/t', '/onboarding/t']) {
        expect(appRedirect(_auth(null, status: AuthStatus.unauthenticated), path), isNull);
        expect(appRedirect(employee, path), isNull);
      }
    });
    test('loading holds on the splash', () {
      expect(appRedirect(const AuthState(status: AuthStatus.loading), '/app/home'), '/splash');
      expect(appRedirect(const AuthState(status: AuthStatus.loading), '/splash'), isNull);
    });
    test('signed out goes to login, except on auth-only pages', () {
      final out = _auth(null, status: AuthStatus.unauthenticated);
      expect(appRedirect(out, '/app/home'), '/login');
      expect(appRedirect(out, '/app/users'), '/login');
      expect(appRedirect(out, '/login'), isNull);
      expect(appRedirect(out, '/forgot-password'), isNull);
    });
    test('signed in leaves splash and auth pages for the landing path', () {
      expect(appRedirect(employee, '/splash'), '/app/home');
      expect(appRedirect(employee, '/login'), '/app/home');
      expect(appRedirect(admin, '/splash'), '/app/dashboard');
      expect(appRedirect(admin, '/register'), '/app/dashboard');
      expect(appRedirect(noRecord, '/splash'), '/app/dashboard');
    });
    test('branch 0 cross-redirects: each user only gets their own Home', () {
      expect(appRedirect(employee, '/app/dashboard'), '/app/home');
      expect(appRedirect(employee, '/app/home'), isNull);
      expect(appRedirect(admin, '/app/home'), '/app/dashboard');
      expect(appRedirect(admin, '/app/dashboard'), isNull);
      expect(appRedirect(noRecord, '/app/home'), '/app/dashboard');
      expect(appRedirect(noRecord, '/app/dashboard'), isNull);
    });
    test('tabs are not redirected (the permission guard covers administrator destinations only)', () {
      expect(appRedirect(employee, '/app/attendance'), isNull);
      expect(appRedirect(admin, '/app/attendance'), isNull);
    });
  });


  group('route guard (D-09): UX only, the API stays the authority', () {
    const employeeGrants = [leaveApplicationSubmit, leaveBalanceView, attendancePunch, attendanceView, attendanceRegularizationRequest, payrollPayslipViewOwn];
    final employee = _auth(_user(employeeGrants, employeeId: 'e'));

    final adminOnly = [
      '/app/users', '/app/setup', '/app/employees', '/app/onboarding', '/app/team-attendance', '/app/attendance-insights', '/app/rosters',
      '/app/roster-calendar', '/app/attendance-periods', '/app/payroll/pay-runs', '/app/payroll/salary-components', '/app/payroll/salary-structures',
      '/app/payroll/statutory-rates', '/app/company', '/app/branches', '/app/departments', '/app/designations', '/app/grades', '/app/legal-entities',
      '/app/attendance-geofences', '/app/attendance/calendar', '/app/shifts', '/app/work-calendars', '/app/weekly-off-patterns', '/app/holiday-calendars', '/app/attendance-policies', '/app/overtime-policies',
      '/app/regularization-policies', '/app/policy-assignments', '/app/policy-resolution', '/app/leave-types', '/app/leave-policies',
      '/app/leave-combination-rules', '/app/leave-year-setting', '/app/statutory-leave-minimums',
    ];

    test('an employee following a link to any administrator screen lands on Home', () {
      for (final path in adminOnly) {
        expect(appRedirect(employee, path), '/app/home', reason: path);
      }
      expect(appRedirect(employee, '/app/payroll/pay-runs/abc'), '/app/home', reason: 'sub-paths are guarded too');
    });

    test('the employee destinations and the tabs are never redirected', () {
      for (final path in ['/app/home', '/app/attendance', '/app/leave-applications', '/app/me', '/app/more', '/app/leave-balances', '/app/regularizations', '/app/overtime']) {
        expect(appRedirect(employee, path), isNull, reason: path);
      }
    });

    test('the same screens open for a user who holds the permission', () {
      expect(appRedirect(_auth(_user([...employeeGrants, settingsUserManage], employeeId: 'e')), '/app/users'), isNull);
      expect(appRedirect(_auth(_user([...employeeGrants, employeeViewAll], employeeId: 'e')), '/app/employees'), isNull, reason: 'branch manager');
      expect(appRedirect(_auth(_user([...employeeGrants, employeeViewAll], employeeId: 'e')), '/app/team-attendance'), isNull);
      expect(guardRedirect('/app/payroll/pay-runs', _user([dashboardCompanyView, payrollRunView]), landing: '/app/dashboard', payroll: true), isNull, reason: 'the guard itself is unchanged when payroll is released');
    });

    test('an administrator is guarded too: without the permission they go to the dashboard', () {
      final admin = _auth(_user([dashboardCompanyView, settingsUserManage], employeeId: 'e'));
      expect(appRedirect(admin, '/app/users'), isNull);
      expect(appRedirect(admin, '/app/payroll/pay-runs'), '/app/dashboard');
      expect(appRedirect(admin, '/app/departments'), '/app/dashboard');
    });

    test('payroll routes open for whoever holds the permission; an employee reaches only their payslips', () {
      final admin = _auth(_user([dashboardCompanyView, payrollRunView, payrollPayslipViewOwn, payrollSetupManage, payrollStatutoryManage], employeeId: 'e'));
      for (final path in ['/app/payroll/pay-runs', '/app/payroll/pay-runs/abc', '/app/payroll/salary-components', '/app/payroll/salary-structures', '/app/payroll/statutory-rates', '/app/me/payslips']) {
        expect(appRedirect(admin, path), isNull, reason: path);
      }
      expect(appRedirect(employee, '/app/me/payslips'), isNull);
      expect(appRedirect(employee, '/app/payroll/pay-runs'), '/app/home');
    });

    test('the release switch still hides every payroll entry and route when it is off', () {
      const grants = [payrollRunView, payrollPayslipViewOwn, payrollSetupManage, payrollStatutoryManage];
      expect(visibleNavGroups(grants).expand((g) => g.items).where((e) => isPayrollRoute(e.route)), isNotEmpty);
      expect(visibleEmployeeEntries(grants).map((e) => e.route), contains('/app/me/payslips'));
      expect(visibleNavGroups(grants, payroll: false).expand((g) => g.items).where((e) => isPayrollRoute(e.route)), isEmpty);
      expect(visibleEmployeeEntries(grants, payroll: false), isEmpty);
      expect(guardRedirect('/app/payroll/pay-runs', _user([dashboardCompanyView, payrollRunView]), landing: '/app/dashboard', payroll: false), '/app/dashboard');
    });

    test('a signed-out user is sent to login, not to the landing page', () {
      expect(appRedirect(_auth(null, status: AuthStatus.unauthenticated), '/app/users'), '/login');
    });

    test('every menu destination is a real route in the router, and every guarded route is in the menu', () {
      final container = ProviderContainer(overrides: [fakeAuth(employeeGrants, employeeId: 'e')]);
      addTearDown(container.dispose);
      final router = container.read(appRouterProvider);
      final paths = <String>{};
      void walk(List<RouteBase> routes) {
        for (final r in routes) {
          if (r is GoRoute) paths.add(r.path);
          walk(r.routes);
        }
        for (final r in routes) {
          if (r is StatefulShellRoute) {
            for (final b in r.branches) {
              walk(b.routes);
            }
          }
        }
      }
      walk(router.configuration.routes);
      final menuRoutes = {for (final g in [navQuickLinks, ...navSettingsGroups]) for (final e in g.items) e.route, for (final e in employeeNavEntries) e.route};
      expect(menuRoutes.difference(paths), isEmpty, reason: 'menu entries without a route');
      for (final path in adminOnly) {
        expect(isGuardedRoute(path), isTrue, reason: '$path is reachable but not guarded');
        expect(menuRoutes.contains(path), isTrue, reason: '$path is guarded but not in the menu');
      }
    });
  });

  group('branch 0 holds two routes: tab behaviour (spike O-03)', () {
    GoRouter mirror(AuthState auth) => GoRouter(
          initialLocation: '/app/attendance',
          redirect: (_, state) => appRedirect(auth, state.matchedLocation),
          routes: [
            StatefulShellRoute.indexedStack(
              builder: (context, state, shell) => Scaffold(
                body: shell,
                bottomNavigationBar: Row(children: [
                  for (var i = 0; i < 4; i++)
                    TextButton(
                      key: Key('tab$i'),
                      onPressed: () => shell.goBranch(i, initialLocation: i == shell.currentIndex),
                      child: Text('tab$i'),
                    ),
                ]),
              ),
              branches: [
                StatefulShellBranch(routes: [
                  GoRoute(path: '/app/dashboard', builder: (_, __) => const Text('DASHBOARD')),
                  GoRoute(path: '/app/home', builder: (_, __) => const Text('HOME')),
                ]),
                StatefulShellBranch(routes: [GoRoute(path: '/app/attendance', builder: (_, __) => const Text('ATT'))]),
                StatefulShellBranch(routes: [GoRoute(path: '/app/leave-applications', builder: (_, __) => const Text('LEAVE'))]),
                StatefulShellBranch(routes: [GoRoute(path: '/app/me', builder: (_, __) => const Text('ME'))]),
              ],
            ),
          ],
        );

    for (final entry in {
      'employee': (_auth(_user([attendancePunch], employeeId: 'e')), 'HOME', '/app/home'),
      'administrator': (_auth(_user([dashboardCompanyView], employeeId: 'e')), 'DASHBOARD', '/app/dashboard'),
      'no employee record': (_auth(_user([])), 'DASHBOARD', '/app/dashboard'),
    }.entries) {
      final (auth, text, path) = entry.value;
      testWidgets('${entry.key}: Home tab lands on $path, from another tab and on re-tap', (tester) async {
        final router = mirror(auth);
        await tester.pumpWidget(MaterialApp.router(routerConfig: router));
        expect(find.text('ATT'), findsOneWidget);

        await tester.tap(find.byKey(const Key('tab0')));
        await tester.pumpAndSettle();
        expect(find.text(text), findsOneWidget);
        expect(router.routeInformationProvider.value.uri.path, path);

        await tester.tap(find.byKey(const Key('tab2')));
        await tester.pumpAndSettle();
        expect(find.text('LEAVE'), findsOneWidget);

        await tester.tap(find.byKey(const Key('tab0'))); // back: state restored
        await tester.pumpAndSettle();
        expect(router.routeInformationProvider.value.uri.path, path);

        await tester.tap(find.byKey(const Key('tab0'))); // re-tap on the current tab resets it
        await tester.pumpAndSettle();
        expect(router.routeInformationProvider.value.uri.path, path);
        expect(find.text(text), findsOneWidget);
      });
    }
  });

  group('the real router and shell', () {
    testWidgets('employee: cold start opens Home (not Profile); tabs work; More opens', (tester) async {
      await tester.pumpWidget(ProviderScope(
        overrides: [fakeAuth([attendancePunch, attendanceView], employeeId: 'e-1'), attendanceRepositoryProvider.overrideWithValue(_AttendanceRepo())],
        child: const HrmsApp(),
      ));
      await tester.pumpAndSettle();
      final container = ProviderScope.containerOf(tester.element(find.byType(MaterialApp)));
      final router = container.read(appRouterProvider);
      expect(router.routeInformationProvider.value.uri.path, '/app/home');
      expect(find.text('Not punched in'), findsOneWidget, reason: 'the real employee Home, from the today-state resolver');
      expect(find.byType(NavigationBar), findsOneWidget);
      expect(find.text('Profile'), findsOneWidget);

      await tester.tap(find.descendant(of: find.byType(NavigationBar), matching: find.text('Attendance')));
      await tester.pumpAndSettle();
      expect(router.routeInformationProvider.value.uri.path, '/app/attendance');

      await tester.tap(find.descendant(of: find.byType(NavigationBar), matching: find.text('Dashboard')));
      await tester.pumpAndSettle();
      expect(router.routeInformationProvider.value.uri.path, '/app/home');

      // On the redesigned Home the profile avatar in the header opens the More hub.
      await tester.tap(find.byIcon(Icons.person));
      await tester.pumpAndSettle();
      expect(find.byType(SettingsHubScreen), findsOneWidget);
    });
  });

  group('EmployeeThemeScope: per-route tokens for administrators only on the three tabs', () {
    Future<bool?> hasTokens(WidgetTester tester, UserProfile user, {bool scoped = true}) async {
      bool? seen;
      final child = Builder(builder: (ctx) {
        seen = Theme.of(ctx).extension<EmployeeTokens>() != null;
        return const SizedBox();
      });
      await tester.pumpWidget(ProviderScope(
        overrides: [fakeAuth(user.permissions, employeeId: user.employeeId)],
        child: MaterialApp(theme: AppTheme.light, home: scoped ? EmployeeThemeScope(child: child) : child),
      ));
      return seen;
    }

    testWidgets('an administrator with an employee record gets the tokens inside the scope', (tester) async {
      expect(await hasTokens(tester, _user([dashboardCompanyView], employeeId: 'e')), isTrue);
    });
    testWidgets('...and not outside it (every other admin screen keeps the original theme)', (tester) async {
      expect(await hasTokens(tester, _user([dashboardCompanyView], employeeId: 'e'), scoped: false), isFalse);
    });
    testWidgets('an administrator without an employee record is untouched', (tester) async {
      expect(await hasTokens(tester, _user([dashboardCompanyView])), isFalse);
    });
    testWidgets('an employee-surface session is a no-op here (the whole app already has the tokens)', (tester) async {
      expect(await hasTokens(tester, _user([attendancePunch], employeeId: 'e')), isFalse, reason: 'app theme here is the admin theme, scope must not add tokens');
    });
  });
}
