import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:hrms_mobile/core/auth/permissions.dart';
import 'package:hrms_mobile/core/providers.dart';
import 'package:hrms_mobile/features/payroll/presentation/employee_salary_panel.dart';
import 'package:hrms_mobile/features/payroll/presentation/salary_setup_screen.dart';

import 'support/fake_api_client.dart';
import 'support/fake_auth.dart';

Map<String, dynamic> _component(String id, String code, String name) =>
    {'id': id, 'code': code, 'name': name, 'component_type': 'EARNING', 'is_active': true};

Map<String, dynamic> _line(String componentId, String code, String calc, String? pct, {String? base}) => {
      'id': 'l-$code', 'salary_component_id': componentId, 'component_code': code, 'component_name': code,
      'component_type': 'EARNING', 'calculation_type': calc, 'percentage': pct, 'amount_monthly_minor': null,
      'base_salary_component_id': base, 'max_monthly_minor': null, 'applies_when': 'ALWAYS', 'display_order': 10,
    };

final _templateLines = [
  _line('c-basic', 'BASIC', 'PERCENTAGE_OF_GROSS', '50'),
  _line('c-hra', 'HRA', 'PERCENTAGE_OF_COMPONENT', '40', base: 'c-basic'),
  _line('c-sa', 'SPECIAL_ALLOWANCE', 'BALANCING', null),
];

final _standard = {
  'id': 'st-1', 'code': 'STANDARD', 'name': 'Standard', 'is_active': true,
  'versions': [
    {'id': 'v-1', 'status': 'PUBLISHED', 'effective_from': '2026-01-01', 'effective_to': null, 'lines': _templateLines},
  ],
};

Map<String, dynamic> _breakupLine(String code, int monthly) =>
    {'component_code': code, 'component_name': code, 'component_type': 'EARNING', 'monthly_minor': monthly, 'annual_minor': monthly * 12, 'basis': ''};

/// ₹12,00,000 a year → gross ₹1,00,000 a month; Basic 50% = ₹50,000; HRA 40% of Basic = ₹20,000.
final _preview = {
  'pf_applicable': false,
  'esi_applicable': false,
  'breakup': {
    'annual_ctc_minor': 120000000, 'monthly_ctc_minor': 10000000, 'gross_monthly_minor': 10000000,
    'employer_contributions_monthly_minor': 0,
    'lines': [_breakupLine('BASIC', 5000000), _breakupLine('HRA', 2000000), _breakupLine('SPECIAL_ALLOWANCE', 3000000)],
  },
};

FakeApiClient _api({String payBasis = 'MONTHLY'}) => FakeApiClient(
      lists: {
        '/payroll/salary-structures': [_standard],
        '/payroll/salary-components': [_component('c-basic', 'BASIC', 'Basic'), _component('c-hra', 'HRA', 'HRA'), _component('c-sa', 'SPECIAL_ALLOWANCE', 'Special Allowance')],
      },
      objects: {
        '/employees/emp-1/salary/setup': {
          'employee_id': 'emp-1', 'as_of': '2026-09-24', 'pay_basis': payBasis, 'annual_ctc_minor': 120000000,
          'pf_applicable': false, 'esi_applicable': false, 'assignment': null, 'salary_structure_id': null,
          'salary_structure_name': null, 'template_structure_id': null, 'is_customised': false, 'lines': <dynamic>[],
        },
        '/employees/emp-1/salary/setup/preview': _preview,
      },
    );

Future<void> _pump(WidgetTester tester, FakeApiClient api, Widget home, [List<String> permissions = const []]) async {
  tester.view.physicalSize = const Size(800, 4000);
  tester.view.devicePixelRatio = 1;
  addTearDown(tester.view.reset);
  await tester.pumpWidget(ProviderScope(overrides: [apiClientProvider.overrideWithValue(api), fakeAuth(permissions)], child: MaterialApp(home: home)));
  await tester.pumpAndSettle();
}

void main() {
  testWidgets('fills in each component amount and marks a changed percentage as customised', (tester) async {
    final api = _api();
    await _pump(tester, api, const SalarySetupScreen(employeeId: 'emp-1', today: '2026-09-24'));
    await tester.pump(const Duration(milliseconds: 500));
    await tester.pumpAndSettle();

    expect(find.text('₹50,000 a month · ₹6,00,000 a year'), findsOneWidget);
    expect(find.text('₹20,000 a month · ₹2,40,000 a year'), findsOneWidget);
    expect(find.text('Same as Standard'), findsOneWidget);
    final preview = api.calls.where((c) => c.path == '/employees/emp-1/salary/setup/preview').last;
    expect((preview.body as Map)['annual_ctc_minor'], 120000000);

    await tester.enterText(find.byKey(const ValueKey('pct-c-basic')), '40');
    await tester.pump(const Duration(milliseconds: 500));
    await tester.pumpAndSettle();
    expect(find.text('Customised for this employee'), findsOneWidget);
    final sent = (api.calls.where((c) => c.path == '/employees/emp-1/salary/setup/preview').last.body as Map)['lines'] as List;
    expect((sent.firstWhere((l) => l['salary_component_id'] == 'c-basic') as Map)['percentage'], '40');
  });

  testWidgets('saves the new CTC with the lines from one effective date', (tester) async {
    final api = _api();
    await _pump(tester, api, const SalarySetupScreen(employeeId: 'emp-1', today: '2026-09-24'));

    await tester.enterText(find.widgetWithText(TextField, 'Annual CTC (₹) *'), '1500000');
    await tester.enterText(find.byKey(const ValueKey('pct-c-basic')), '45');
    await tester.enterText(find.widgetWithText(TextField, 'Reason *'), 'Annual review');
    await tester.pump(const Duration(milliseconds: 500));
    await tester.pumpAndSettle();
    await tester.tap(find.text('Save salary'));
    await tester.pumpAndSettle();

    final save = api.calls.singleWhere((c) => c.path == '/employees/emp-1/salary/setup');
    final body = save.body as Map;
    expect(body['annual_ctc_minor'], 150000000);
    expect(body['revision_type'], 'ANNUAL');
    expect(body['template_structure_id'], 'st-1');
    expect(body['effective_from'], '2026-09-24');
    expect(((body['lines'] as List).firstWhere((l) => l['salary_component_id'] == 'c-basic') as Map)['percentage'], '45');
  });

  testWidgets('a daily-wage employee is pointed to the daily rate instead', (tester) async {
    await _pump(tester, _api(payBasis: 'DAILY_WAGE'), const SalarySetupScreen(employeeId: 'emp-1', today: '2026-09-24'));
    expect(find.textContaining('daily-wage employee'), findsOneWidget);
    expect(find.text('Save salary'), findsNothing);
  });

  testWidgets('the Salary tab offers the editor with both permissions', (tester) async {
    await _pump(tester, _api(), const Scaffold(body: EmployeeSalaryPanel(employeeId: 'emp-1')), const [payrollSetupManage, employeeUpdateCompensation]);
    expect(find.text('Edit salary & structure'), findsOneWidget);
  });

  testWidgets('without the compensation permission the Salary tab has no editor', (tester) async {
    await _pump(tester, _api(), const Scaffold(body: EmployeeSalaryPanel(employeeId: 'emp-1')), const [payrollSetupManage]);
    expect(find.text('Edit salary & structure'), findsNothing);
    expect(find.text('Assign'), findsOneWidget);
  });
}
