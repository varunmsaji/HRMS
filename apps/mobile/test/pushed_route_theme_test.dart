import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:hrms_mobile/core/auth/permissions.dart';
import 'package:hrms_mobile/core/theme/app_theme.dart';
import 'package:hrms_mobile/core/theme/employee_theme_scope.dart';
import 'package:hrms_mobile/core/theme/employee_tokens.dart';

import 'support/fake_auth.dart';
import 'support/test_themes.dart';

/// Detail routes are pushed with `Navigator.push`, above the per-route [EmployeeThemeScope]. A
/// screen that opens one with [pushKeepingTheme] must give it the screen's own theme: the employee
/// treatment for an administrator inside Attendance/Leave/Profile, and the untouched administrator
/// theme from every administrator screen.
class _Opener extends StatelessWidget {
  const _Opener({required this.seen});
  final void Function(bool hasTokens) seen;

  @override
  Widget build(BuildContext context) => Scaffold(
        body: TextButton(
          onPressed: () => pushKeepingTheme<void>(context, (_) => Builder(builder: (ctx) {
                seen(Theme.of(ctx).extension<EmployeeTokens>() != null);
                return const Scaffold(body: Text('DETAIL'));
              })),
          child: const Text('open'),
        ),
      );
}

Future<bool?> _openFrom(WidgetTester tester, List<String> permissions, {required bool inScope}) async {
  bool? detailHasTokens;
  final opener = _Opener(seen: (v) => detailHasTokens = v);
  await tester.pumpWidget(ProviderScope(
    overrides: [fakeAuth(permissions, employeeId: 'e-1')],
    child: MaterialApp(theme: AppTheme.light, home: inScope ? EmployeeThemeScope(child: opener) : opener),
  ));
  await tester.tap(find.text('open'));
  await tester.pumpAndSettle();
  expect(find.text('DETAIL'), findsOneWidget);
  return detailHasTokens;
}

void main() {
  setUpAll(primeThemes);

  testWidgets('an HR administrator opening a detail from their Attendance/Leave/Profile tab keeps the employee treatment', (tester) async {
    expect(await _openFrom(tester, [dashboardCompanyView], inScope: true), isTrue);
  });

  testWidgets('the same administrator opening a detail from an administrator screen keeps the administrator theme', (tester) async {
    expect(await _openFrom(tester, [dashboardCompanyView], inScope: false), isFalse);
  });

  testWidgets('an administrator without an employee record is untouched', (tester) async {
    bool? seen;
    await tester.pumpWidget(ProviderScope(
      overrides: [fakeAuth([dashboardCompanyView])],
      child: MaterialApp(theme: AppTheme.light, home: EmployeeThemeScope(child: _Opener(seen: (v) => seen = v))),
    ));
    await tester.tap(find.text('open'));
    await tester.pumpAndSettle();
    expect(seen, isFalse);
  });
}
