import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:go_router/go_router.dart';
import 'package:hrms_mobile/core/auth/permissions.dart';
import 'package:hrms_mobile/core/theme/app_theme.dart';
import 'package:hrms_mobile/features/shell/app_shell.dart';

import 'support/fake_auth.dart';
import 'support/test_themes.dart';

/// The real [AppShell] around stub tab pages, so tab icons, selection, re-tap and Back are tested
/// without any network. `app_router.dart` supplies the real branch contents.
GoRouter _router({String start = '/app/attendance'}) => GoRouter(
      initialLocation: start,
      routes: [
        StatefulShellRoute.indexedStack(
          builder: (context, state, shell) => AppShell(navigationShell: shell),
          branches: [
            StatefulShellBranch(routes: [
              GoRoute(path: '/app/home', builder: (_, __) => const Text('HOME PAGE')),
              GoRoute(path: '/app/dashboard', builder: (_, __) => const Text('DASHBOARD PAGE')),
            ]),
            StatefulShellBranch(routes: [GoRoute(path: '/app/attendance', builder: (_, __) => const Text('ATTENDANCE PAGE'))]),
            StatefulShellBranch(routes: [GoRoute(path: '/app/leave-applications', builder: (_, __) => const Text('LEAVE PAGE'))]),
            StatefulShellBranch(routes: [GoRoute(path: '/app/me', builder: (_, __) => const Text('PROFILE PAGE'))]),
          ],
        ),
      ],
    );

Future<GoRouter> _pump(WidgetTester tester, List<String> permissions, {String? employeeId = 'e-1', String start = '/app/attendance'}) async {
  final router = _router(start: start);
  await tester.pumpWidget(ProviderScope(
    overrides: [fakeAuth(permissions, employeeId: employeeId)],
    child: MaterialApp.router(theme: AppTheme.light, routerConfig: router),
  ));
  await tester.pumpAndSettle();
  return router;
}

NavigationBar _bar(WidgetTester tester) => tester.widget<NavigationBar>(find.byType(NavigationBar));

Future<void> _tapTab(WidgetTester tester, String label) async {
  await tester.tap(find.descendant(of: find.byType(NavigationBar), matching: find.text(label)));
  await tester.pumpAndSettle();
}

String _path(GoRouter r) => r.routeInformationProvider.value.uri.path;

void main() {
  setUpAll(primeThemes);

  group('employee surface', () {
    const employee = [attendancePunch, attendanceView];

    testWidgets('has the employee tab icons: dashboard grid, fingerprint, event_available, account circle', (tester) async {
      await _pump(tester, employee);
      final icons = [for (final d in _bar(tester).destinations.cast<NavigationDestination>()) (d.icon as Icon).icon];
      expect(icons, [Icons.grid_view_outlined, Icons.fingerprint_rounded, Icons.event_available_outlined, Icons.account_circle_outlined]);
      final selected = [for (final d in _bar(tester).destinations.cast<NavigationDestination>()) (d.selectedIcon as Icon).icon];
      expect(selected, [Icons.grid_view_rounded, Icons.fingerprint_rounded, Icons.event_available_rounded, Icons.account_circle_rounded]);
    });

    testWidgets('selected tab follows the branch', (tester) async {
      await _pump(tester, employee);
      expect(_bar(tester).selectedIndex, 1);
      await _tapTab(tester, 'Leave');
      expect(_bar(tester).selectedIndex, 2);
      expect(find.text('LEAVE PAGE'), findsOneWidget);
      await _tapTab(tester, 'Profile');
      expect(_bar(tester).selectedIndex, 3);
      await _tapTab(tester, 'Dashboard');
      expect(_bar(tester).selectedIndex, 0);
    });

    testWidgets('re-tapping the current tab keeps it selected and on its root', (tester) async {
      final router = await _pump(tester, employee);
      await _tapTab(tester, 'Attendance');
      await _tapTab(tester, 'Attendance');
      expect(_bar(tester).selectedIndex, 1);
      expect(_path(router), '/app/attendance');
    });

    testWidgets('state is restored when returning to a tab', (tester) async {
      final router = await _pump(tester, employee);
      await _tapTab(tester, 'Leave');
      await _tapTab(tester, 'Attendance');
      expect(_path(router), '/app/attendance');
      expect(find.text('ATTENDANCE PAGE'), findsOneWidget);
    });

    testWidgets('Back from another tab returns to Home first, and Back on Home leaves the app', (tester) async {
      final router = await _pump(tester, employee, start: '/app/home');
      await _tapTab(tester, 'Leave');
      expect(_path(router), '/app/leave-applications');

      expect(await tester.binding.handlePopRoute(), isTrue, reason: 'handled inside the app');
      await tester.pumpAndSettle();
      expect(_path(router), '/app/home');
      expect(_bar(tester).selectedIndex, 0);

      expect(await tester.binding.handlePopRoute(), isFalse, reason: 'on Home the system gets Back');
    });

    testWidgets('the tab bar has no navy shadow on the employee surface', (tester) async {
      await _pump(tester, employee);
      final box = tester.widget<DecoratedBox>(find.ancestor(of: find.byType(NavigationBar), matching: find.byType(DecoratedBox)).first);
      expect((box.decoration as BoxDecoration).boxShadow, isNull);
    });
  });

  group('administrator is unchanged', () {
    const admin = [dashboardCompanyView];

    testWidgets('keeps the dashboard glyph and the shadow', (tester) async {
      await _pump(tester, admin);
      final first = _bar(tester).destinations.first as NavigationDestination;
      expect((first.icon as Icon).icon, Icons.space_dashboard_outlined);
      expect(((_bar(tester).destinations[2] as NavigationDestination).icon as Icon).icon, Icons.beach_access_outlined);
      final box = tester.widget<DecoratedBox>(find.ancestor(of: find.byType(NavigationBar), matching: find.byType(DecoratedBox)).first);
      expect((box.decoration as BoxDecoration).boxShadow, isNotEmpty);
    });

    testWidgets('Back does not redirect an administrator to Home (platform behaviour)', (tester) async {
      await _pump(tester, admin);
      expect(await tester.binding.handlePopRoute(), isFalse);
      expect(_bar(tester).selectedIndex, 1);
    });
  });

  group('user without an employee record', () {
    testWidgets('keeps the admin chrome and the platform Back behaviour', (tester) async {
      await _pump(tester, const [], employeeId: null);
      expect(((_bar(tester).destinations.first as NavigationDestination).icon as Icon).icon, Icons.space_dashboard_outlined);
      expect(await tester.binding.handlePopRoute(), isFalse);
    });
  });
}
