import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:go_router/go_router.dart';
import 'package:hrms_mobile/core/auth/auth_types.dart';
import 'package:hrms_mobile/core/router/app_router.dart' show ReturnPath, returnPathProvider;
import 'package:hrms_mobile/core/theme/app_theme.dart';
import 'package:hrms_mobile/features/auth/data/login_prefs.dart';
import 'package:hrms_mobile/features/auth/presentation/login_screen.dart';
import 'package:hrms_mobile/features/auth/state/auth_controller.dart';
import 'package:hrms_mobile/features/auth/state/auth_state.dart';

import 'support/test_themes.dart';

class _Prefs implements LoginPrefs {
  _Prefs({this.identifier, this.companyCode});
  String? identifier;
  String? companyCode;
  ({String identifier, String? companyCode})? remembered;

  @override
  Future<({String? identifier, String? companyCode})> read() async => (identifier: identifier, companyCode: companyCode);

  @override
  Future<void> remember({required String identifier, String? companyCode}) async => remembered = (identifier: identifier, companyCode: companyCode);

  @override
  Future<void> forget() async {}
}

class _Auth extends StateNotifier<AuthState> implements AuthController {
  _Auth(super.state, this.user);
  final UserProfile user;

  @override
  Future<UserProfile?> login({String? email, String? companyCode, String? employeeCode, required String password}) async => user;

  @override
  dynamic noSuchMethod(Invocation invocation) => super.noSuchMethod(invocation);
}

UserProfile _user(String id) => UserProfile(id: id, email: 'a@b.c', companyId: 'c', employeeId: 'e-1', permissions: const [], companyTimezone: 'Asia/Kolkata');

Future<GoRouter> _pump(WidgetTester tester, {required _Prefs prefs, AuthState state = const AuthState(status: AuthStatus.unauthenticated), String userId = 'u-1', ReturnPath? back}) async {
  tester.view.physicalSize = const Size(360, 640);
  tester.view.devicePixelRatio = 1;
  addTearDown(tester.view.reset);
  final router = GoRouter(initialLocation: '/login', routes: [
    GoRoute(path: '/login', builder: (_, __) => const LoginScreen()),
    GoRoute(path: '/app/home', builder: (_, __) => const Scaffold(body: Text('home'))),
    GoRoute(path: '/app/leave-applications/:id', builder: (_, s) => Scaffold(body: Text('leave ${s.pathParameters['id']}'))),
  ]);
  await tester.pumpWidget(ProviderScope(
    overrides: [
      loginPrefsProvider.overrideWithValue(prefs),
      authControllerProvider.overrideWith((ref) => _Auth(state, _user(userId))),
      returnPathProvider.overrideWithValue(back ?? ReturnPath()),
    ],
    child: MaterialApp.router(theme: AppTheme.light, routerConfig: router),
  ));
  await tester.pumpAndSettle();
  return router;
}

Future<void> _signIn(WidgetTester tester) async {
  await tester.enterText(find.byType(TextField).last, 'secret');
  await tester.ensureVisible(find.text('Sign in'));
  await tester.pumpAndSettle();
  await tester.tap(find.text('Sign in'));
  await tester.pumpAndSettle();
}

void main() {
  setUpAll(primeThemes);

  testWidgets('a returning employee finds their ID and company code filled in', (tester) async {
    await _pump(tester, prefs: _Prefs(identifier: 'EMP-0007', companyCode: 'ACME'));
    expect(find.text('EMP-0007'), findsOneWidget);
    expect(find.text('ACME'), findsOneWidget, reason: 'the company-code field shows for an employee ID');
  });

  testWidgets('a successful sign-in remembers the ID and company code, never the password', (tester) async {
    final prefs = _Prefs(identifier: 'EMP-0007', companyCode: 'ACME');
    await _pump(tester, prefs: prefs);
    await _signIn(tester);
    expect(prefs.remembered, (identifier: 'EMP-0007', companyCode: 'ACME'));
    expect(find.text('home'), findsOneWidget);
  });

  testWidgets('after an expired session the screen says why, and the same user goes back to where they were', (tester) async {
    final back = ReturnPath()
      ..path = '/app/leave-applications/a-1'
      ..userId = 'u-1';
    await _pump(tester, prefs: _Prefs(identifier: 'a@b.c'), state: const AuthState(status: AuthStatus.unauthenticated, sessionExpired: true, expiredUserId: 'u-1'), back: back);
    expect(find.textContaining('Your session ended'), findsOneWidget);
    await _signIn(tester);
    expect(find.text('leave a-1'), findsOneWidget);
    expect(back.path, isNull, reason: 'used once');
  });

  testWidgets('someone else signing in after an expiry goes to their own landing page', (tester) async {
    final back = ReturnPath()
      ..path = '/app/leave-applications/a-1'
      ..userId = 'u-1';
    await _pump(tester, prefs: _Prefs(identifier: 'b@b.c'), state: const AuthState(status: AuthStatus.unauthenticated, sessionExpired: true, expiredUserId: 'u-1'), userId: 'u-2', back: back);
    await _signIn(tester);
    expect(find.text('home'), findsOneWidget);
  });

  testWidgets('an ordinary signed-out start shows no session note', (tester) async {
    await _pump(tester, prefs: _Prefs());
    expect(find.textContaining('Your session ended'), findsNothing);
  });
}
