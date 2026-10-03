import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:hrms_mobile/core/auth/permissions.dart';
import 'package:hrms_mobile/core/providers.dart';
import 'package:hrms_mobile/features/profile/presentation/employee_record_sections.dart';

import 'support/fake_api_client.dart';
import 'support/fake_auth.dart';

RecordSection _section(String title) => employeeRecordSections.firstWhere((s) => s.title == title);

Future<FakeApiClient> _pump(WidgetTester tester, String section, List<String> permissions, Map<String, List<Map<String, dynamic>>> lists, {Map<String, Map<String, dynamic>> objects = const {}}) async {
  tester.view.physicalSize = const Size(800, 3000);
  tester.view.devicePixelRatio = 1;
  addTearDown(tester.view.reset);
  final client = FakeApiClient(lists: {'/legal-entities': [{'id': 'le-1', 'name': 'Acme Pvt Ltd', 'is_active': true}], ...lists}, objects: objects);
  await tester.pumpWidget(ProviderScope(
    overrides: [apiClientProvider.overrideWithValue(client), fakeAuth(permissions)],
    child: MaterialApp(home: Scaffold(body: EmployeeRecordPanel(employeeId: 'emp-1', section: _section(section)))),
  ));
  await tester.pumpAndSettle();
  return client;
}

void main() {
  testWidgets('with no permission there are no write buttons', (tester) async {
    await _pump(tester, 'Employment', const [], {'/employees/emp-1/employments': []});
    expect(find.text('Create first employment'), findsNothing);
  });

  testWidgets('an employee with no employment can be hired with the legal entity chosen from a list', (tester) async {
    final client = await _pump(tester, 'Employment', [employeeCreate], {'/employees/emp-1/employments': []});
    await tester.tap(find.text('Create first employment'));
    await tester.pumpAndSettle();
    // required fields block submit
    await tester.tap(find.widgetWithText(FilledButton, 'Create'));
    await tester.pumpAndSettle();
    expect(find.text('Legal entity is required.'), findsOneWidget);
    expect(find.text('Joining date is required.'), findsOneWidget);
    expect(client.calls, isEmpty);

    await tester.tap(find.byType(DropdownButtonFormField<String>).first);
    await tester.pumpAndSettle();
    await tester.tap(find.text('Acme Pvt Ltd').last);
    await tester.pumpAndSettle();
    // joining date via the date picker
    await tester.tap(find.widgetWithText(TextField, '').first);
    await tester.pumpAndSettle();
    await tester.tap(find.text('OK'));
    await tester.pumpAndSettle();
    await tester.tap(find.widgetWithText(FilledButton, 'Create'));
    await tester.pumpAndSettle();

    final call = client.calls.single;
    expect(call.method, 'POST');
    expect(call.path, '/employees/emp-1/employments');
    expect(call.ifMatch, isNull);
    final body = call.body as Map<String, dynamic>;
    expect(body['legal_entity_id'], 'le-1');
    expect(body['pay_basis'], 'MONTHLY');
    expect(body['joining_date'], matches(RegExp(r'^\d{4}-\d{2}-\d{2}$')));
  });

  testWidgets('a current employment offers edit and terminate, terminate carries the row version', (tester) async {
    final client = await _pump(
      tester,
      'Employment',
      [employeeUpdate, employeeTerminate],
      {
        '/employees/emp-1/employments': [
          {'id': 'em-1', 'status': 'ACTIVE', 'joining_date': '2024-04-01', 'legal_entity_id': 'le-1', 'pay_basis': 'MONTHLY', 'version': 5},
        ],
      },
    );
    expect(find.text('Edit employment'), findsOneWidget);
    expect(find.text('Terminate'), findsOneWidget);
    expect(find.text('Rehire'), findsNothing);

    await tester.tap(find.text('Terminate'));
    await tester.pumpAndSettle();
    expect(find.textContaining('This cannot be undone'), findsOneWidget);
    // validation: date required
    await tester.tap(find.widgetWithText(FilledButton, 'Terminate'));
    await tester.pumpAndSettle();
    expect(find.text('Last working day is required.'), findsOneWidget);
    expect(client.calls, isEmpty);

    await tester.tap(find.widgetWithText(TextField, '').first);
    await tester.pumpAndSettle();
    await tester.tap(find.text('OK'));
    await tester.pumpAndSettle();
    await tester.tap(find.widgetWithText(FilledButton, 'Terminate'));
    await tester.pumpAndSettle();
    final call = client.calls.single;
    expect(call.path, '/employees/emp-1/employments/em-1/terminate');
    expect(call.ifMatch, '5');
    expect((call.body as Map)['last_working_day'], isNotNull);
  });

  testWidgets('a terminated employee can be rehired, not terminated again', (tester) async {
    await _pump(tester, 'Employment', [employeeCreate, employeeTerminate, employeeUpdate], {
      '/employees/emp-1/employments': [
        {'id': 'em-1', 'status': 'TERMINATED', 'joining_date': '2022-01-01', 'last_working_day': '2023-01-01', 'legal_entity_id': 'le-1', 'pay_basis': 'MONTHLY', 'version': 2},
      ],
    });
    expect(find.text('Rehire'), findsOneWidget);
    expect(find.text('Terminate'), findsNothing);
    expect(find.text('Edit employment'), findsNothing);
  });

  testWidgets('compensation actions need the compensation permission and read "Revise" once a row exists', (tester) async {
    await _pump(tester, 'Compensation', [employeeViewCompensation], {'/employees/emp-1/compensation': []});
    expect(find.text('Set compensation'), findsNothing);
  });

  testWidgets('compensation offers Set when empty and Revise when a row exists', (tester) async {
    await _pump(tester, 'Compensation', [employeeUpdateCompensation], {'/employees/emp-1/compensation': []});
    expect(find.text('Set compensation'), findsOneWidget);
  });

  testWidgets('compensation offers Revise when a current row exists', (tester) async {
    await _pump(tester, 'Compensation', [employeeUpdateCompensation], {
      '/employees/emp-1/compensation': [
        {'id': 'c-1', 'effective_from': '2024-04-01', 'effective_to': null, 'annual_ctc_minor': 1200000, 'currency': 'INR', 'revision_type': 'JOINING', 'version': 4},
      ],
    });
    expect(find.text('Revise compensation'), findsOneWidget);
  });

  test('openRow finds the effective-dated row that is still in force', () {
    expect(openRow([]), isNull);
    expect(
      openRow([
        {'id': 'old', 'effective_to': '2024-01-01'},
        {'id': 'now', 'effective_to': null},
      ])?['id'],
      'now',
    );
  });

  testWidgets('dependents can be deleted with the row version after confirming', (tester) async {
    final client = await _pump(tester, 'Dependents', [employeeUpdateSensitive], {
      '/employees/emp-1/dependents': [
        {'id': 'd-1', 'full_name': 'Ravi', 'relationship': 'Son', 'is_minor': true, 'is_pf_nominee': false, 'is_gratuity_nominee': false, 'is_esi_dependent': false, 'version': 3},
      ],
    });
    await tester.tap(find.text('Delete'));
    await tester.pumpAndSettle();
    expect(find.text('Delete this dependent?'), findsOneWidget);
    await tester.tap(find.text('Delete').last);
    await tester.pumpAndSettle();
    expect(client.calls.single.method, 'DELETE');
    expect(client.calls.single.path, '/employees/emp-1/dependents/d-1');
    expect(client.calls.single.ifMatch, '3');
  });

  testWidgets('delete is hidden without the sensitive-update permission', (tester) async {
    await _pump(tester, 'Dependents', [employeeViewNominee], {
      '/employees/emp-1/dependents': [
        {'id': 'd-1', 'full_name': 'Ravi', 'relationship': 'Son', 'is_minor': false, 'is_pf_nominee': false, 'is_gratuity_nominee': false, 'is_esi_dependent': false, 'version': 3},
      ],
    });
    expect(find.text('Delete'), findsNothing);
    expect(find.text('Add dependent / nominee'), findsNothing);
  });
}
