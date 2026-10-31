import 'dart:io';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:go_router/go_router.dart';
import 'package:hrms_mobile/core/auth/auth_types.dart';
import 'package:hrms_mobile/core/auth/permissions.dart';
import 'package:hrms_mobile/core/router/app_router.dart';
import 'package:hrms_mobile/core/theme/app_theme.dart';
import 'package:hrms_mobile/core/theme/employee_tokens.dart';
import 'package:hrms_mobile/core/theme/theme_selection.dart';
import 'package:hrms_mobile/core/widgets/employee/employee_status_chip.dart';
import 'package:hrms_mobile/core/widgets/employee/status_map.dart';
import 'package:hrms_mobile/core/widgets/ui.dart';
import 'package:hrms_mobile/main.dart';

import 'support/fake_auth.dart';
import 'support/test_themes.dart';
import 'support/theme_fingerprint.dart';

/// T0-07: the employee theme must never leak into administrator (or signed-out) sessions.
/// `test/fixtures/admin_theme_*.txt` were generated from `AppTheme.light` / `AppTheme.dark`
/// BEFORE any employee-theme code existed; they must keep matching byte for byte.
UserProfile _user(List<String> permissions, {String? employeeId}) => UserProfile(
      id: 'u',
      email: 'a@b.c',
      companyId: 'c',
      employeeId: employeeId,
      permissions: permissions,
      companyTimezone: 'Asia/Kolkata',
    );

void main() {
  setUpAll(primeThemes);

  final baselineLight = File('test/fixtures/admin_theme_light.txt').readAsStringSync();
  final baselineDark = File('test/fixtures/admin_theme_dark.txt').readAsStringSync();

  test('AppTheme.light and AppTheme.dark are byte-identical to the pre-change baseline', () {
    expect(themeFingerprint(AppTheme.light), baselineLight);
    expect(themeFingerprint(AppTheme.dark), baselineDark);
  });

  group('theme selection', () {
    final admin = _user([dashboardCompanyView], employeeId: 'e');
    final noRecord = _user([]);
    final employee = _user([leaveBalanceView, attendancePunch], employeeId: 'e');
    final manager = _user([leaveApplicationApprove, leaveBalanceViewAll], employeeId: 'e');

    for (final entry in {'administrator': admin, 'no employee record': noRecord, 'signed out': null}.entries) {
      test('${entry.key} gets exactly the original arguments', () {
        final s = themeSelectionFor(entry.value);
        expect(themeFingerprint(s.theme), baselineLight);
        expect(themeFingerprint(s.darkTheme), baselineDark);
        expect(s.themeMode, ThemeMode.system);
        expect(s.theme.extension<EmployeeTokens>(), isNull);
      });
    }

    for (final entry in {'employee': employee, 'manager': manager}.entries) {
      test('${entry.key} gets the light employee theme', () {
        final s = themeSelectionFor(entry.value);
        expect(s.themeMode, ThemeMode.light);
        expect(s.theme.extension<EmployeeTokens>(), isNotNull);
        expect(s.theme.scaffoldBackgroundColor, const Color(0xFFF4F6F8));
        expect(themeFingerprint(s.darkTheme), baselineDark, reason: 'dark theme stays untouched');
      });
    }
  });

  group('MaterialApp wiring', () {
    Future<MaterialApp> pumpApp(WidgetTester tester, List<String> perms, {String? employeeId, bool signedIn = true}) async {
      final router = GoRouter(routes: [GoRoute(path: '/', builder: (_, __) => const Text('x'))]);
      await tester.pumpWidget(ProviderScope(
        overrides: [appRouterProvider.overrideWithValue(router), if (signedIn) fakeAuth(perms, employeeId: employeeId)],
        child: const HrmsApp(),
      ));
      return tester.widget<MaterialApp>(find.byType(MaterialApp));
    }

    testWidgets('administrator session: system mode, original themes', (tester) async {
      final app = await pumpApp(tester, [dashboardCompanyView], employeeId: 'e');
      expect(app.themeMode, ThemeMode.system);
      expect(themeFingerprint(app.theme!), baselineLight);
      expect(themeFingerprint(app.darkTheme!), baselineDark);
    });

    testWidgets('employee session: light mode regardless of a dark device', (tester) async {
      tester.platformDispatcher.platformBrightnessTestValue = Brightness.dark;
      addTearDown(tester.platformDispatcher.clearPlatformBrightnessTestValue);
      final app = await pumpApp(tester, [attendancePunch], employeeId: 'e');
      expect(app.themeMode, ThemeMode.light);
      expect(app.theme!.extension<EmployeeTokens>(), isNotNull);
      final ctx = tester.element(find.text('x'));
      expect(Theme.of(ctx).brightness, Brightness.light);
    });

    testWidgets('administrator on a dark device still gets dark', (tester) async {
      tester.platformDispatcher.platformBrightnessTestValue = Brightness.dark;
      addTearDown(tester.platformDispatcher.clearPlatformBrightnessTestValue);
      await pumpApp(tester, [dashboardCompanyView], employeeId: 'e');
      expect(Theme.of(tester.element(find.text('x'))).brightness, Brightness.dark);
    });
  });

  group('employee theme', () {
    test('minimum control size is 48 and body text is at least 16', () {
      final t = AppTheme.employee;
      expect(t.filledButtonTheme.style!.minimumSize!.resolve({})!.height, 48);
      expect(t.textTheme.bodyLarge!.fontSize, 16);
      expect(t.textTheme.labelSmall!.fontSize, greaterThanOrEqualTo(12));
      expect(t.colorScheme.primary, const Color(0xFF004AC6));
    });

    test('the read-only banner colour comes from the scheme', () {
      expect(AppTheme.employee.colorScheme.tertiaryContainer, const Color(0xFFFFFBEB));
      expect(AppTheme.light.colorScheme.tertiaryContainer, const Color(0xFFBC4800));
    });
  });

  group('shared widgets render under every theme', () {
    for (final entry in <String, ThemeData Function()>{'admin light': () => AppTheme.light, 'admin dark': () => AppTheme.dark, 'employee': () => AppTheme.employee}.entries) {
      testWidgets(entry.key, (tester) async {
        await tester.pumpWidget(employeeHarness(
          Column(children: [
            const AppCard(child: Text('card')),
            const StatusChip(label: 'Approved', tone: Tone.success),
            EmployeeStatusChip(status: statusForRequest('APPROVED')),
          ]),
          theme: entry.value(),
        ));
        expect(tester.takeException(), isNull);
        expect(find.text('Approved'), findsNWidgets(2));
      });
    }
  });
}
