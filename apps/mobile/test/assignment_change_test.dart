import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:hrms_mobile/core/api/api_error.dart';
import 'package:hrms_mobile/core/auth/permissions.dart';
import 'package:hrms_mobile/core/providers.dart';
import 'package:hrms_mobile/features/profile/presentation/employee_record_sections.dart';

import 'support/fake_api_client.dart';
import 'support/fake_auth.dart';

class _Opener extends ConsumerWidget {
  const _Opener({required this.changeType, required this.result});
  final String? changeType;
  final List<bool> result;

  @override
  Widget build(BuildContext context, WidgetRef ref) => Center(
        child: ElevatedButton(
          onPressed: () async => result.add(await openAssignmentChange(context, ref, employeeId: 'e-1', changeType: changeType)),
          child: const Text('open'),
        ),
      );
}

Future<List<bool>> _open(WidgetTester tester, {required FakeApiClient api, required List<String> permissions, String? changeType}) async {
  final result = <bool>[];
  tester.view.physicalSize = const Size(800, 3000);
  tester.view.devicePixelRatio = 1;
  addTearDown(tester.view.reset);
  await tester.pumpWidget(ProviderScope(
    overrides: [apiClientProvider.overrideWithValue(api), fakeAuth(permissions)],
    child: MaterialApp(home: Scaffold(body: _Opener(changeType: changeType, result: result))),
  ));
  await tester.tap(find.text('open'));
  await tester.pumpAndSettle();
  return result;
}

final _current = {'id': 'a-1', 'effective_from': '2026-01-01', 'effective_to': null, 'version': 4, 'reporting_manager_id': 'm-1'};

void main() {
  testWidgets('preselects the change type when the viewer may record it', (tester) async {
    await _open(tester, api: FakeApiClient(lists: {'/employees/e-1/assignments': [_current]}), permissions: [employeeTransfer], changeType: 'SHIFT_CHANGE');
    expect(find.text('Shift change'), findsWidgets);
    expect(find.text('Initial placement'), findsNothing);
  });

  testWidgets('a type the viewer may not record is not preselected', (tester) async {
    await _open(tester, api: FakeApiClient(lists: {'/employees/e-1/assignments': [_current]}), permissions: [employeeTransfer], changeType: 'PROMOTION');
    expect(find.text('Promotion'), findsNothing);
  });

  testWidgets('a first placement is always an initial placement', (tester) async {
    await _open(tester, api: FakeApiClient(lists: {'/employees/e-1/assignments': const []}), permissions: [employeeTransfer], changeType: 'SHIFT_CHANGE');
    expect(find.textContaining('Initial'), findsWidgets);
    expect(find.text('Shift change'), findsNothing);
  });

  testWidgets('when the assignments cannot be read it says so and opens nothing', (tester) async {
    final result = await _open(tester, api: FakeApiClient(failing: {'/employees/e-1/assignments': ApiError(status: 403, code: 'FORBIDDEN', message: 'no')}), permissions: [employeeTransfer]);
    expect(result, [false]);
    expect(find.text("You do not have permission to view or change this employee's assignment."), findsOneWidget);
  });
}
