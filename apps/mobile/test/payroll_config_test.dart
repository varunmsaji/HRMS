import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:hrms_mobile/core/auth/permissions.dart';
import 'package:hrms_mobile/core/providers.dart';
import 'package:hrms_mobile/core/resource/resource_screens.dart';
import 'package:hrms_mobile/features/payroll/domain/payroll_resources.dart';
import 'package:hrms_mobile/features/payroll/presentation/statutory_rates_screen.dart';

import 'support/fake_api_client.dart';
import 'support/fake_auth.dart';

Map<String, dynamic> _line(String id, String name, String type, {num? amount, String? percentage, String? baseId, String applies = 'ALWAYS'}) => {
      'id': 'l-$id',
      'salary_component_id': id,
      'component_code': name.toUpperCase(),
      'component_name': name,
      'component_type': 'EARNING',
      'calculation_type': type,
      'percentage': percentage,
      'amount_monthly_minor': amount,
      'base_salary_component_id': baseId,
      'max_monthly_minor': null,
      'applies_when': applies,
      'display_order': 0,
    };

Map<String, dynamic> _structure({List<Map<String, dynamic>> versions = const []}) => {
      'id': 's1',
      'code': 'STD',
      'name': 'Standard',
      'description': null,
      'is_active': true,
      'version': 3,
      'versions': versions,
    };

Map<String, dynamic> _version(String id, String status, {String? from = '2026-04-01', String? to, int rowVersion = 5, List<Map<String, dynamic>>? lines}) => {
      'id': id,
      'status': status,
      'effective_from': from,
      'effective_to': to,
      'version': rowVersion,
      'lines': lines ?? [_line('basic', 'Basic', 'PERCENTAGE_OF_CTC', percentage: '40'), _line('hra', 'HRA', 'PERCENTAGE_OF_COMPONENT', percentage: '50', baseId: 'basic')],
    };

Future<FakeApiClient> _pumpStructure(WidgetTester tester, Map<String, dynamic> structure, List<String> permissions, {Map<String, Map<String, dynamic>> objects = const {}}) async {
  tester.view.physicalSize = const Size(800, 9000);
  tester.view.devicePixelRatio = 1;
  addTearDown(tester.view.reset);
  final client = FakeApiClient(
    lists: {
      '/payroll/salary-components': [
        {'id': 'basic', 'name': 'Basic', 'code': 'BASIC', 'is_active': true},
        {'id': 'hra', 'name': 'HRA', 'code': 'HRA', 'is_active': true},
      ],
    },
    objects: {'/payroll/salary-structures/s1': structure, ...objects},
  );
  await tester.pumpWidget(ProviderScope(
    overrides: [apiClientProvider.overrideWithValue(client), fakeAuth(permissions)],
    child: MaterialApp(home: ResourceDetailScreen(config: salaryStructureResource, initial: structure)),
  ));
  await tester.pumpAndSettle();
  return client;
}

void main() {
  group('salary structure versions', () {
    test('lines are described the way the web editor does', () {
      final lines = [_line('basic', 'Basic', 'PERCENTAGE_OF_CTC', percentage: '40'), _line('hra', 'HRA', 'PERCENTAGE_OF_COMPONENT', percentage: '50', baseId: 'basic'), _line('conv', 'Conveyance', 'FIXED', amount: 160000, applies: 'PF_APPLICABLE'), _line('sp', 'Special', 'BALANCING')];
      expect(describeStructureLine(lines[0], lines), '40% of monthly CTC');
      expect(describeStructureLine(lines[1], lines), '50% of Basic');
      expect(describeStructureLine(lines[2], lines), '₹1,600 a month (only if pf applies)');
      expect(describeStructureLine(lines[3], lines), 'Balance of gross');
    });

    testWidgets('shows the current version, its lines, and no actions without the permission', (tester) async {
      await _pumpStructure(tester, _structure(versions: [_version('v1', 'PUBLISHED')]), const []);
      expect(find.text('Published'), findsOneWidget);
      expect(find.text('50% of Basic'), findsOneWidget);
      expect(find.text('Edit (new draft)'), findsNothing);
    });

    testWidgets('a draft can be started from the current version', (tester) async {
      final client = await _pumpStructure(tester, _structure(versions: [_version('v1', 'PUBLISHED')]), [payrollSetupManage]);
      await tester.tap(find.text('Edit (new draft)'));
      await tester.pumpAndSettle();
      final call = client.calls.first;
      expect(call.method, 'POST');
      expect(call.path, '/payroll/salary-structures/s1/versions');
      expect(call.body, isEmpty);
    });

    testWidgets('editing lines replaces them all (PUT) with money as minor units, ordered, and the draft version', (tester) async {
      final draft = _version('v2', 'DRAFT', from: null, rowVersion: 9, lines: [_line('basic', 'Basic', 'FIXED', amount: 5000000)]);
      final client = await _pumpStructure(tester, _structure(versions: [_version('v1', 'PUBLISHED', to: null), draft]), [payrollSetupManage]);
      await tester.tap(find.text('Edit lines'));
      await tester.pumpAndSettle();
      // change the fixed amount from ₹50,000 to ₹60,000
      await tester.enterText(find.widgetWithText(TextField, '50000'), '60000');
      await tester.drag(find.byType(ListView).last, const Offset(0, -20000));
      await tester.pumpAndSettle();
      await tester.tap(find.widgetWithText(FilledButton, 'Save changes'));
      await tester.pumpAndSettle();
      final call = client.calls.single;
      expect(call.method, 'PUT');
      expect(call.path, '/payroll/salary-structures/s1/versions/v2/lines');
      expect(call.ifMatch, '9');
      final lines = (call.body as Map)['lines'] as List;
      expect(lines.single['amount_monthly_minor'], 6000000);
      expect(lines.single['calculation_type'], 'FIXED');
      expect(lines.single['display_order'], 0);
    });

    testWidgets('a fixed line without an amount is rejected before anything is sent', (tester) async {
      final draft = _version('v2', 'DRAFT', from: null, lines: [_line('basic', 'Basic', 'FIXED', amount: 100)]);
      final client = await _pumpStructure(tester, _structure(versions: [draft]), [payrollSetupManage]);
      await tester.tap(find.text('Edit lines'));
      await tester.pumpAndSettle();
      await tester.enterText(find.widgetWithText(TextField, '1'), '');
      await tester.drag(find.byType(ListView).last, const Offset(0, -20000));
      await tester.pumpAndSettle();
      await tester.tap(find.widgetWithText(FilledButton, 'Save changes'));
      await tester.pumpAndSettle();
      expect(find.text('Enter the monthly amount.'), findsOneWidget);
      expect(client.calls, isEmpty);
    });

    testWidgets('publishing needs an effective date and carries the draft version', (tester) async {
      final client = await _pumpStructure(tester, _structure(versions: [_version('v1', 'PUBLISHED'), _version('v2', 'DRAFT', from: null, rowVersion: 4)]), [payrollSetupManage]);
      await tester.tap(find.widgetWithText(FilledButton, 'Publish'));
      await tester.pumpAndSettle();
      await tester.tap(find.widgetWithText(FilledButton, 'Publish').last);
      await tester.pumpAndSettle();
      expect(find.text('Choose the effective date.'), findsOneWidget);
      await tester.tap(find.byType(TextField).last);
      await tester.pumpAndSettle();
      await tester.tap(find.text('OK'));
      await tester.pumpAndSettle();
      await tester.tap(find.widgetWithText(FilledButton, 'Publish').last);
      await tester.pumpAndSettle();
      final call = client.calls.single;
      expect(call.path, '/payroll/salary-structures/s1/versions/v2/publish');
      expect(call.ifMatch, '4');
      expect((call.body as Map)['effective_from'], matches(RegExp(r'^\d{4}-\d{2}-\d{2}$')));
    });

    testWidgets('a draft can be discarded', (tester) async {
      final client = await _pumpStructure(tester, _structure(versions: [_version('v2', 'DRAFT', from: null, rowVersion: 6)]), [payrollSetupManage]);
      await tester.tap(find.widgetWithText(OutlinedButton, 'Discard draft'));
      await tester.pumpAndSettle();
      await tester.tap(find.widgetWithText(FilledButton, 'Discard'));
      await tester.pumpAndSettle();
      final call = client.calls.single;
      expect(call.method, 'DELETE');
      expect(call.path, '/payroll/salary-structures/s1/versions/v2');
      expect(call.ifMatch, '6');
    });

    testWidgets('preview posts the CTC in paise and shows the breakup', (tester) async {
      final client = await _pumpStructure(
        tester,
        _structure(versions: [_version('v1', 'PUBLISHED')]),
        const [],
        objects: {
          '/payroll/salary-structures/s1/versions/v1/preview': {
            'annual_ctc_minor': 120000000,
            'monthly_ctc_minor': 10000000,
            'gross_monthly_minor': 9000000,
            'employer_contributions_monthly_minor': 1000000,
            'lines': [
              {'component_code': 'BASIC', 'component_name': 'Basic', 'component_type': 'EARNING', 'monthly_minor': 4000000, 'annual_minor': 48000000, 'basis': '40% of CTC'},
            ],
          },
        },
      );
      await tester.tap(find.text('Preview breakup'));
      await tester.pumpAndSettle();
      final call = client.calls.single;
      expect(call.path, '/payroll/salary-structures/s1/versions/v1/preview');
      expect(call.body, {'annual_ctc_minor': 120000000, 'pf_applicable': true});
      expect(find.text('Cost to company'), findsOneWidget);
      expect(find.textContaining('₹1,00,000 / mo'), findsOneWidget);
    });
  });

  group('statutory rates', () {
    Map<String, dynamic> pf({bool verified = false, int version = 2}) => {
          'id': 'r1',
          'scheme': 'PF',
          'state_code': null,
          'effective_from': '2026-04-01',
          'effective_to': null,
          'parameters': {
            'employee_percent': '12.0000',
            'employer_percent': '12.0000',
            'eps_percent': '8.3300',
            'wage_ceiling_minor': 1500000,
            'edli_percent': '0.5000',
            'admin_percent': '0.5000',
            'eps_age_limit': 58,
          },
          'notes': null,
          'is_seeded': true,
          'verified': verified,
          'version': version,
        };

    Future<FakeApiClient> pump(WidgetTester tester, List<Map<String, dynamic>> rates, List<String> permissions) async {
      tester.view.physicalSize = const Size(800, 6000);
      tester.view.devicePixelRatio = 1;
      addTearDown(tester.view.reset);
      final client = FakeApiClient(lists: {'/payroll/statutory-rates': rates});
      await tester.pumpWidget(ProviderScope(
        overrides: [apiClientProvider.overrideWithValue(client), fakeAuth(permissions)],
        child: const MaterialApp(home: StatutoryRatesScreen()),
      ));
      await tester.pumpAndSettle();
      return client;
    }

    test('rates are summarised per scheme', () {
      expect(summariseStatutoryRate(pf()), 'Employee 12.0000% · employer 12.0000% (EPS 8.3300%) · ceiling ₹15,000');
      expect(summariseStatutoryRate({'scheme': 'PT', 'parameters': {'slabs': <dynamic>[]}}), 'No professional tax in this state');
      expect(summariseStatutoryRate({'scheme': 'LWF', 'parameters': {'months': [6, 12]}}), 'Deducted in month(s) 6, 12');
    });

    testWidgets('lists rates with their verification state, and hides actions without the permission', (tester) async {
      await pump(tester, [pf()], const []);
      expect(find.text('Provident Fund'), findsWidgets);
      expect(find.text('Unverified'), findsOneWidget);
      expect(find.text('Mark verified'), findsNothing);
      expect(find.text('New rate'), findsNothing);
    });

    testWidgets('verifying carries the rate version', (tester) async {
      final client = await pump(tester, [pf(version: 7)], [payrollStatutoryManage]);
      await tester.tap(find.text('Mark verified'));
      await tester.pumpAndSettle();
      final call = client.calls.single;
      expect(call.path, '/payroll/statutory-rates/r1/verify');
      expect(call.ifMatch, '7');
    });

    testWidgets('editing sends the whole parameter set only when a parameter changed', (tester) async {
      final client = await pump(tester, [pf(version: 4)], [payrollStatutoryManage]);
      await tester.tap(find.widgetWithText(OutlinedButton, 'Edit'));
      await tester.pumpAndSettle();
      await tester.enterText(find.widgetWithText(TextField, '15000'), '21000');
      await tester.drag(find.byType(ListView).last, const Offset(0, -20000));
      await tester.pumpAndSettle();
      await tester.tap(find.widgetWithText(FilledButton, 'Save changes'));
      await tester.pumpAndSettle();
      final call = client.calls.single;
      expect(call.method, 'PATCH');
      expect(call.ifMatch, '4');
      final params = (call.body as Map)['parameters'] as Map;
      expect(params['wage_ceiling_minor'], 2100000);
      expect(params['employee_percent'], 12);
      expect(params.keys.toSet(), {'employee_percent', 'employer_percent', 'eps_percent', 'edli_percent', 'admin_percent', 'wage_ceiling_minor', 'eps_age_limit'});
      expect((call.body as Map).containsKey('notes'), isFalse);
    });

    testWidgets('a past rate is hidden until asked for', (tester) async {
      final past = {...pf(), 'id': 'r0', 'effective_to': '2026-03-31'};
      await pump(tester, [pf(), past], const []);
      expect(find.textContaining('2026-03-31'), findsNothing);
      await tester.tap(find.text('Show past rates'));
      await tester.pumpAndSettle();
      expect(find.textContaining('2026-03-31'), findsOneWidget);
    });
  });
}
