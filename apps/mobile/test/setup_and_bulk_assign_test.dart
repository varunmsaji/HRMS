import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:hrms_mobile/core/auth/permissions.dart';
import 'package:hrms_mobile/core/providers.dart';
import 'package:hrms_mobile/core/resource/resource_screens.dart';
import 'package:hrms_mobile/features/onboarding/data/onboarding_repository.dart' show SetupChecklistItem;
import 'package:hrms_mobile/features/onboarding/presentation/setup_screen.dart';
import 'package:hrms_mobile/features/payroll/domain/payroll_resources.dart';

import 'support/fake_api_client.dart';
import 'support/fake_auth.dart';

Future<void> _pump(WidgetTester tester, FakeApiClient api, List<String> permissions, Widget home) async {
  tester.view.physicalSize = const Size(800, 3000);
  tester.view.devicePixelRatio = 1;
  addTearDown(tester.view.reset);
  await tester.pumpWidget(ProviderScope(overrides: [apiClientProvider.overrideWithValue(api), fakeAuth(permissions)], child: MaterialApp(home: home)));
  await tester.pumpAndSettle();
}

void main() {
  group('setup', () {
    testWidgets('an incomplete setup shows the count, the next step and Pending', (tester) async {
      final api = FakeApiClient(objects: {
        '/companies/current/setup-progress': {
          'status': 'IN_PROGRESS',
          'current_step': 'COMPANY_PROFILE',
          'steps': [
            {'code': 'COMPANY_PROFILE', 'label': 'Company profile', 'is_complete': false}
          ],
        },
      });
      await _pump(tester, api, const [], const SetupScreen());
      expect(find.text('0 of 1 complete'), findsOneWidget);
      expect(find.text('Go to company profile'), findsOneWidget);
      expect(find.text('Pending'), findsOneWidget);
    });

    testWidgets('a complete setup has no next-step prompt', (tester) async {
      final api = FakeApiClient(objects: {
        '/companies/current/setup-progress': {
          'status': 'COMPLETE',
          'current_step': null,
          'steps': [
            {'code': 'COMPANY_PROFILE', 'label': 'Company profile', 'is_complete': true}
          ],
        },
      });
      await _pump(tester, api, const [], const SetupScreen());
      expect(find.text('Setup complete'), findsOneWidget);
      expect(find.text('Next step'), findsNothing);
      expect(find.text('Complete'), findsOneWidget);
    });
  });

  group('setup checklist', () {
    final registration = {
      'status': 'COMPLETE',
      'current_step': null,
      'steps': [
        {'code': 'COMPANY_PROFILE', 'label': 'Company profile', 'is_complete': true}
      ],
    };

    testWidgets('shows what is left from the live checklist, labelled apart from registration', (tester) async {
      final api = FakeApiClient(objects: {
        '/companies/current/setup-progress': registration,
        '/companies/current/setup-checklist': {
          'required_total': 3,
          'required_complete': 1,
          'next_code': 'SHIFT',
          'items': [
            {'code': 'SHIFT', 'label': 'Create a shift', 'description': 'A published shift.', 'required': true, 'is_complete': false, 'path': '/app/shifts'},
            {'code': 'ATTENDANCE_POLICY', 'label': 'Attendance policy', 'description': 'Whole company.', 'required': true, 'is_complete': true, 'path': '/app/attendance-policies/new'},
            {'code': 'OVERTIME_POLICY', 'label': 'Overtime policy', 'description': 'Optional.', 'required': false, 'is_complete': false, 'path': '/app/overtime-policies/new'},
          ],
        },
      });
      await _pump(tester, api, const [], const SetupScreen());
      expect(find.text('1 of 3 essentials done'), findsOneWidget);
      expect(find.text('To do'), findsOneWidget);
      expect(find.text('Done'), findsOneWidget);
      expect(find.text('Optional'), findsOneWidget);
      expect(find.text('Registration'), findsOneWidget);
    });

    test('create-page paths map to the list screens the app has', () {
      SetupChecklistItem item(String path) => SetupChecklistItem(code: 'X', label: 'x', description: 'x', required: true, isComplete: false, path: path);
      expect(item('/app/attendance-policies/new').appPath, '/app/attendance-policies');
      expect(item('/app/work-calendars/setup').appPath, '/app/work-calendars');
      expect(item('/app/shifts').appPath, '/app/shifts');
    });
  });

  group('bulk salary assignment', () {
    final structures = [
      {'id': 's1', 'code': 'STD', 'name': 'Standard', 'is_active': true, 'versions': [{'status': 'PUBLISHED', 'effective_to': null}]},
      {'id': 's2', 'code': 'DRF', 'name': 'Draft only', 'is_active': true, 'versions': [{'status': 'DRAFT', 'effective_to': null}]},
    ];

    test('only active structures with a current published version can be assigned', () {
      expect(hasCurrentVersion(structures[0]), isTrue);
      expect(hasCurrentVersion(structures[1]), isFalse);
      expect(hasCurrentVersion({...structures[0], 'is_active': false}), isFalse);
    });

    testWidgets('posts the structure and date, then reports assigned and skipped', (tester) async {
      final api = FakeApiClient(lists: {'/payroll/salary-structures': structures}, objects: {
        '/payroll/salary-assignments/bulk': {
          'assigned': ['e1', 'e2'],
          'skipped': [
            {'employee_id': 'e3', 'reason': 'No CTC on record'}
          ],
        },
      });
      await _pump(tester, api, [payrollSetupManage], ResourceListScreen(config: salaryStructureResource));
      await tester.tap(find.byTooltip('Assign to employees'));
      await tester.pumpAndSettle();
      await tester.tap(find.text('Assign'));
      await tester.pumpAndSettle();
      final call = api.calls.singleWhere((c) => c.path == '/payroll/salary-assignments/bulk');
      expect((call.body as Map)['salary_structure_id'], 's1');
      expect((call.body as Map)['effective_from'], matches(RegExp(r'^\d{4}-\d{2}-\d{2}$')));
      expect(find.text('Assigned 2 employees; skipped 1.'), findsOneWidget);
      expect(find.textContaining('No CTC on record'), findsOneWidget);
    });

    testWidgets('hidden without payroll setup permission', (tester) async {
      await _pump(tester, FakeApiClient(lists: {'/payroll/salary-structures': structures}), const [], ResourceListScreen(config: salaryStructureResource));
      expect(find.byTooltip('Assign to employees'), findsNothing);
    });
  });
}
