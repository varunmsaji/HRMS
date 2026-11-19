import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:go_router/go_router.dart';
import 'package:hrms_mobile/core/auth/permissions.dart';
import 'package:hrms_mobile/features/attendance/presentation/roster_view_switcher.dart';

import 'support/fake_auth.dart';

void main() {
  group('which views a user can open', () {
    test('a manager with every read sees all five, in web order', () {
      final views = rosterViewsFor(const [attendanceView, attendanceRosterManage, employeeViewAll, orgShiftManage]);
      expect(views, [RosterView.coverage, RosterView.week, RosterView.month, RosterView.day, RosterView.list]);
    });

    test('Week needs the employee directory, Day also needs the shift list', () {
      expect(rosterViewsFor(const [attendanceView]), [RosterView.coverage, RosterView.month, RosterView.list]);
      expect(rosterViewsFor(const [attendanceView, employeeViewAll]), isNot(contains(RosterView.day)));
      expect(rosterViewsFor(const [attendanceView, employeeViewAll]), contains(RosterView.week));
    });

    test('without the roster read grant there is nothing to switch to', () {
      expect(rosterViewsFor(const [attendanceRosterManage]), isEmpty);
    });

    test('every view has its own route', () {
      expect({for (final v in RosterView.values) v.route}.length, RosterView.values.length);
    });
  });

  testWidgets('choosing a view opens it in place of the current one; the current one does nothing', (tester) async {
    final router = GoRouter(initialLocation: '/start', routes: [
      GoRoute(path: '/start', builder: (_, __) => const Scaffold(body: Text('start'))),
      GoRoute(path: '/app/schedule', builder: (_, __) => Scaffold(appBar: AppBar(title: const Text('Coverage page'), bottom: const RosterViewSwitcher(current: RosterView.coverage)))),
      GoRoute(path: '/app/rosters/grid', builder: (_, __) => Scaffold(appBar: AppBar(title: const Text('Week page'), bottom: const RosterViewSwitcher(current: RosterView.week)))),
    ]);
    await tester.pumpWidget(ProviderScope(
      overrides: [fakeAuth(const [attendanceView, employeeViewAll], employeeId: 'e')],
      child: MaterialApp.router(routerConfig: router),
    ));
    router.go('/app/schedule');
    await tester.pumpAndSettle();
    expect(find.text('Coverage page'), findsOneWidget);
    // Tapping the view you are on does nothing.
    await tester.tap(find.widgetWithText(ChoiceChip, 'Coverage'));
    await tester.pumpAndSettle();
    expect(find.text('Coverage page'), findsOneWidget);

    await tester.tap(find.widgetWithText(ChoiceChip, 'Week'));
    await tester.pumpAndSettle();
    expect(find.text('Week page'), findsOneWidget);
    expect(find.text('Coverage page'), findsNothing);
  });
}
