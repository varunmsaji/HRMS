import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:hrms_mobile/core/auth/permissions.dart';
import 'package:hrms_mobile/core/providers.dart';
import 'package:hrms_mobile/features/payroll/presentation/pay_runs_screen.dart';

import 'support/fake_api_client.dart';
import 'support/fake_auth.dart';

Map<String, dynamic> _entity(String id, String name) => {'id': id, 'company_id': 'c-1', 'name': name, 'legal_name': name, 'is_active': true, 'version': 1};

Future<void> _pump(WidgetTester tester, List<String> permissions, {List<Map<String, dynamic>> entities = const []}) async {
  tester.view.physicalSize = const Size(800, 2400);
  tester.view.devicePixelRatio = 1;
  addTearDown(tester.view.reset);
  final api = FakeApiClient(lists: {'/payroll/pay-runs': const <Map<String, dynamic>>[], '/legal-entities': entities});
  await tester.pumpWidget(ProviderScope(
    overrides: [apiClientProvider.overrideWithValue(api), fakeAuth(permissions)],
    child: const MaterialApp(home: PayRunsScreen()),
  ));
  await tester.pumpAndSettle();
}

void main() {
  testWidgets("uses web's title and empty state", (tester) async {
    await _pump(tester, const [payrollRunView]);
    expect(find.text('Pay Runs'), findsOneWidget);
    expect(find.text('No pay runs yet.'), findsOneWidget);
    expect(find.text("Close the month's attendance period for a company, then create its pay run."), findsOneWidget);
  });

  testWidgets('payroll settings follow PAYROLL.SETUP_MANAGE, as the API does', (tester) async {
    await _pump(tester, const [payrollRunProcess]);
    expect(find.byTooltip('Payroll settings'), findsNothing, reason: 'processing pay runs does not open the settings');
    expect(find.text('New pay run'), findsOneWidget);
  });

  testWidgets('a setup manager sees payroll settings', (tester) async {
    await _pump(tester, const [payrollRunView, payrollSetupManage]);
    expect(find.byTooltip('Payroll settings'), findsOneWidget);
    expect(find.text('New pay run'), findsNothing);
  });

  testWidgets('the filter and the new pay run dialog say company', (tester) async {
    await _pump(tester, const [payrollRunProcess], entities: [_entity('le-1', 'Acme India'), _entity('le-2', 'Acme Services')]);
    expect(find.text('All companies'), findsOneWidget);
    await tester.tap(find.text('New pay run'));
    await tester.pumpAndSettle();
    expect(find.text('Company'), findsWidgets);
    expect(find.text('Create pay run'), findsOneWidget);
    expect(find.textContaining('Legal entity'), findsNothing);
  });
}
