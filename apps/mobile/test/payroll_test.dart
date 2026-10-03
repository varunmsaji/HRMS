import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:hrms_mobile/core/auth/permissions.dart';
import 'package:hrms_mobile/core/format.dart';
import 'package:hrms_mobile/features/organisation/data/organisation_repository.dart';
import 'package:hrms_mobile/features/organisation/presentation/legal_entities_screen.dart' show organisationRepositoryProvider;
import 'package:hrms_mobile/features/payroll/data/payroll_repository.dart';
import 'package:hrms_mobile/features/payroll/presentation/pay_run_detail_screen.dart';
import 'package:hrms_mobile/features/payroll/presentation/pay_runs_screen.dart' show payrollRepositoryProvider;
import 'package:hrms_mobile/features/payroll/presentation/payslip_pdf.dart';
import 'package:hrms_mobile/features/payroll/presentation/payslip_screen.dart';

import 'support/fake_auth.dart';

Map<String, dynamic> _runJson(String status, {int version = 3}) => {
      'id': 'run-1',
      'legal_entity_id': 'le-1',
      'month': '2026-09',
      'status': status,
      'pay_date': '2026-10-01',
      'period_start': '2026-09-01',
      'period_end': '2026-09-30',
      'employee_count': 2,
      'gross_minor': 12000000,
      'deductions_minor': 1000000,
      'employer_contributions_minor': 500000,
      'net_minor': 11000000,
      'error_count': 1,
      'variance_open_count': 1,
      'version': version,
    };

Map<String, dynamic> _employeeJson(String id, String? name, {bool flagged = false, String? reason}) => {
      'id': 'pre-$id',
      'employee_id': id,
      'employee_code': 'E-$id',
      'employee_name': name,
      'paid_days': '30.00',
      'lop_days': '0.00',
      'payable_days': '30.00',
      'net_minor': 5500000,
      'gross_minor': 6000000,
      'is_computed': true,
      'has_error': false,
      'variance_flagged': flagged,
      'variance_reason': reason,
      'variance_percent': flagged ? '12.5' : null,
      'issues': const [],
    };

class _FakePayroll implements PayrollRepository {
  _FakePayroll(this.status);
  final String status;
  final calls = <String>[];

  @override
  Future<PayRun> getPayRun(String runId) async => PayRun.fromJson(_runJson(status));

  @override
  Future<List<PayRunEmployee>> listPayRunEmployees(String runId) async => [
        PayRunEmployee.fromJson(_employeeJson('a', 'Asha Rao', flagged: true)),
        PayRunEmployee.fromJson(_employeeJson('b', null)),
      ];

  @override
  Future<List<PayAdjustment>> listAdjustments({required String sourcePayRunId}) async => const [];

  @override
  Future<PayRun> compute(String runId, {required String ifMatch}) async {
    calls.add('compute:$ifMatch');
    return PayRun.fromJson(_runJson('COMPUTED'));
  }

  @override
  Future<PayRun> approve(String runId, {required String ifMatch}) async {
    calls.add('approve:$ifMatch');
    return PayRun.fromJson(_runJson('APPROVED'));
  }

  @override
  Future<PayRunEmployee> acknowledgeVariance(String runId, String employeeId, {required String reason}) async {
    calls.add('ack:$employeeId:$reason');
    return PayRunEmployee.fromJson(_employeeJson(employeeId, 'Asha Rao'));
  }

  @override
  dynamic noSuchMethod(Invocation invocation) => super.noSuchMethod(invocation);
}

class _FakeOrg implements OrganisationRepository {
  @override
  Future<List<LegalEntity>> listLegalEntities() async => [LegalEntity(id: 'le-1', name: 'Acme Pvt Ltd', isActive: true, version: 1)];

  @override
  dynamic noSuchMethod(Invocation invocation) => super.noSuchMethod(invocation);
}

Future<_FakePayroll> _pump(WidgetTester tester, String status, List<String> permissions) async {
  tester.view.physicalSize = const Size(800, 3200);
  tester.view.devicePixelRatio = 1;
  addTearDown(tester.view.reset);
  final repo = _FakePayroll(status);
  await tester.pumpWidget(ProviderScope(
    overrides: [payrollRepositoryProvider.overrideWithValue(repo), organisationRepositoryProvider.overrideWithValue(_FakeOrg()), fakeAuth(permissions)],
    child: const MaterialApp(home: PayRunDetailScreen(runId: 'run-1')),
  ));
  await tester.pumpAndSettle();
  return repo;
}

Payslip _payslip() => Payslip.fromJson({
      'month': '2026-09',
      'period_end': '2026-09-30',
      'pay_date': '2026-10-01',
      'is_final': true,
      'company_name': 'Acme',
      'legal_entity_name': 'Acme Pvt Ltd',
      'employee_name': 'Asha Rao',
      'employee_code': 'E-1',
      'days_in_month': 30,
      'paid_days': '30.00',
      'lop_days': '0.00',
      'earnings': [
        {'component_code': 'BASIC', 'component_name': 'Basic', 'full_monthly_minor': 5000000, 'amount_minor': 5000000},
        {'component_code': 'HRA', 'component_name': 'HRA', 'full_monthly_minor': 2500000, 'amount_minor': 2500000, 'note': 'Arrears Aug'},
      ],
      'deductions': [
        {'component_code': 'PF', 'component_name': 'PF', 'amount_minor': 600000}
      ],
      'employer_contributions': const [],
      'gross_minor': 7500000,
      'deductions_minor': 600000,
      'net_minor': 6900000,
      'net_in_words': 'Sixty nine thousand only',
      'leave_balances': [
        {'code': 'CL', 'name': 'Casual', 'balance': '7.50'}
      ],
    });

void main() {
  test('formatInr groups in the Indian system and shows paise only when present', () {
    expect(formatInr(0), '₹0');
    expect(formatInr(99900), '₹999');
    expect(formatInr(12345600), '₹1,23,456');
    expect(formatInr(123456789), '₹12,34,567.89');
    expect(formatInr(-150000), '-₹1,500');
    expect(formatPayMonth('2026-09'), 'September 2026');
    expect(rupeesToMinor('12,00,000.50'), 120000050);
    expect(rupeesToMinor('abc'), isNull);
  });

  test('pay run status gates mirror the web payRunActions', () {
    PayRun run(String s) => PayRun.fromJson(_runJson(s));
    expect(run('DRAFT').canLockInputs, isTrue);
    expect(run('DRAFT').canDelete, isTrue);
    expect(run('INPUTS_LOCKED').canCompute, isTrue);
    expect(run('COMPUTED').canApprove, isTrue);
    expect(run('COMPUTED').rollbackTargets, ['INPUTS_LOCKED', 'DRAFT']);
    expect(run('APPROVED').canFinalise, isTrue);
    expect(run('FINALISED').canMarkPaid, isTrue);
    expect(run('FINALISED').canEditPayDate, isFalse);
    expect(run('PAID').rollbackTargets, isEmpty);
  });

  test('employee rows tolerate a null name and string decimals', () {
    final e = PayRunEmployee.fromJson(_employeeJson('b', null));
    expect(e.displayName, 'E-b');
    expect(e.paidDays, '30.00');
  });

  test('payslip PDF is generated', () async {
    final bytes = await buildPayslipPdf(_payslip());
    expect(String.fromCharCodes(bytes.take(5)), '%PDF-');
    expect(bytes.length, greaterThan(1000));
  });

  testWidgets('payslip view shows earnings, deductions, net pay and leave balances', (tester) async {
    tester.view.physicalSize = const Size(800, 3200);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.reset);
    await tester.pumpWidget(MaterialApp(home: Scaffold(body: PayslipView(payslip: _payslip()))));
    expect(find.text('Payslip for September 2026'), findsOneWidget);
    expect(find.text('₹69,000'), findsOneWidget);
    expect(find.text('Arrears Aug'), findsOneWidget);
    expect(find.text('Casual: 7.50'), findsOneWidget);
  });

  testWidgets('a processor sees compute and recompute on a computed run, and the call carries the version', (tester) async {
    final repo = await _pump(tester, 'INPUTS_LOCKED', [payrollRunProcess]);
    await tester.tap(find.text('Compute'));
    await tester.pumpAndSettle();
    expect(repo.calls, ['compute:3']);
  });

  testWidgets('approval needs the approve permission and a computed run', (tester) async {
    await _pump(tester, 'COMPUTED', [payrollRunProcess]);
    expect(find.text('Approve'), findsNothing);
    expect(find.text('Recompute'), findsOneWidget);
    expect(find.textContaining('Before approval:'), findsOneWidget);
  });

  testWidgets('an approver can approve a computed run', (tester) async {
    final repo = await _pump(tester, 'COMPUTED', [payrollRunApprove]);
    await tester.tap(find.text('Approve'));
    await tester.pumpAndSettle();
    expect(repo.calls, ['approve:3']);
  });

  testWidgets('flagged variances can be acknowledged with a reason', (tester) async {
    final repo = await _pump(tester, 'COMPUTED', [payrollRunProcess]);
    await tester.tap(find.text('Acknowledge'));
    await tester.pumpAndSettle();
    await tester.enterText(find.byType(TextField).last, 'Bonus month');
    await tester.tap(find.text('Acknowledge').last);
    await tester.pumpAndSettle();
    expect(repo.calls, contains('ack:a:Bonus month'));
  });

  testWidgets('view-only users get no action buttons', (tester) async {
    await _pump(tester, 'COMPUTED', const []);
    expect(find.text('Recompute'), findsNothing);
    expect(find.text('Approve'), findsNothing);
    expect(find.text('Acknowledge'), findsNothing);
    expect(find.text('Asha Rao'), findsOneWidget);
  });
}
