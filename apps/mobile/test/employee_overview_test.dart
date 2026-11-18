import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:hrms_mobile/core/api/api_error.dart';
import 'package:hrms_mobile/core/api/envelope.dart';
import 'package:hrms_mobile/features/leave/data/leave_repository.dart';
import 'package:hrms_mobile/features/profile/data/employee_repository.dart';
import 'package:hrms_mobile/features/profile/presentation/employee_overview.dart';
import 'package:hrms_mobile/features/profile/presentation/profile_screen.dart' show employeeRepositoryProvider;

import 'support/fake_auth.dart';

Employee _employee() => Employee.fromJson({
      'id': 'e-1',
      'employee_code': 'EMP001',
      'first_name': 'Asha',
      'middle_name': 'K',
      'last_name': 'Rao',
      'display_name': 'Ash',
      'date_of_birth': '1990-11-20',
      'status': 'ACTIVE',
      'is_active': true,
      'version': 1,
    });

class _FakeEmployees implements EmployeeRepository {
  _FakeEmployees({this.work, this.workError, this.documents});
  final EmployeeWorkSummary? work;
  final ApiError? workError;
  final List<EmployeeDocumentRow>? documents;

  @override
  Future<EmployeeWorkSummary> workSummary(String employeeId) async {
    if (workError != null) throw workError!;
    return work!;
  }

  @override
  Future<List<EmployeeDocumentRow>> listDocuments(String employeeId) async {
    if (documents == null) throw ApiError(status: 403, code: 'FORBIDDEN', message: 'no');
    return documents!;
  }

  @override
  dynamic noSuchMethod(Invocation invocation) => super.noSuchMethod(invocation);
}

class _FakeLeave implements LeaveRepository {
  _FakeLeave({this.balances, this.next});
  final List<LeaveBalance>? balances;
  final LeaveApplication? next;

  @override
  Future<List<LeaveBalance>> listLeaveBalances(String employeeId) async {
    if (balances == null) throw ApiError(status: 403, code: 'FORBIDDEN', message: 'no');
    return balances!;
  }

  @override
  Future<ListEnvelope<LeaveApplication>> listLeaveApplicationsPage({String? employeeId, String? dateFrom, String? dateTo, String? status, int page = 1}) async =>
      ListEnvelope(data: [if (next != null) next!], pagination: null, meta: ResponseMeta(requestId: 'r'));

  @override
  dynamic noSuchMethod(Invocation invocation) => super.noSuchMethod(invocation);
}

final _now = DateTime.utc(2026, 11, 18, 6);

Future<void> _pump(WidgetTester tester, {required _FakeEmployees employees, required _FakeLeave leave}) async {
  tester.view.physicalSize = const Size(800, 4000);
  tester.view.devicePixelRatio = 1;
  addTearDown(tester.view.reset);
  await tester.pumpWidget(ProviderScope(
    overrides: [
      employeeRepositoryProvider.overrideWithValue(employees),
      leaveRepositoryProvider.overrideWithValue(leave),
      fakeAuth(const []),
    ],
    child: MaterialApp(home: Scaffold(body: EmployeeOverview(employee: _employee(), now: _now))),
  ));
  await tester.pumpAndSettle();
}

EmployeeWorkSummary _work({bool employed = true}) => EmployeeWorkSummary(
      employment: employed ? {'joining_date': '2024-04-01', 'probation_end_date': '2024-10-01', 'pay_basis': 'DAILY_WAGE', 'status': 'ACTIVE'} : null,
      assignment: {'work_location_type': 'WFH'},
      company: 'Acme Pvt Ltd',
      department: 'Finance',
      designation: 'Accountant',
      branch: 'Pune',
      shift: 'General',
      manager: (id: 'm-1', name: 'Meera Shah'),
    );

LeaveBalance _balance(String code, num balance, [num reserved = 0]) =>
    LeaveBalance(employeeId: 'e-1', leaveTypeId: 't-$code', leaveTypeCode: code, leaveTypeName: 'Leave $code', balance: balance, reservedBalance: reserved);

void main() {
  testWidgets('shows names, age, the Current work card and the hero facts', (tester) async {
    await _pump(tester, employees: _FakeEmployees(work: _work(), documents: const []), leave: _FakeLeave(balances: const []));
    expect(find.text('Asha K Rao'), findsOneWidget);
    expect(find.text('Ash'), findsWidgets);
    expect(find.text('1990-11-20 (35 yrs)'), findsOneWidget);
    expect(find.byKey(const Key('overview-work')), findsOneWidget);
    for (final v in ['Acme Pvt Ltd', 'Accountant', 'Finance', 'Pune', 'Meera Shah', 'General', 'Work from home', '1 Apr 2024', '1 Oct 2024', 'Daily wage']) {
      expect(find.text(v), findsWidgets, reason: v);
    }
    expect(find.text('EMP001 · Accountant · Finance'), findsOneWidget);
    expect(find.text('Reports to Meera Shah'), findsOneWidget);
    expect(find.text('Joined 1 Apr 2024'), findsOneWidget);
  });

  testWidgets('no employment record shows the hint under the card', (tester) async {
    await _pump(tester, employees: _FakeEmployees(work: _work(employed: false), documents: const []), leave: _FakeLeave(balances: const []));
    expect(find.byKey(const Key('overview-no-employment')), findsOneWidget);
  });

  testWidgets('a 403 on work information explains it and the side cards stay out', (tester) async {
    await _pump(tester, employees: _FakeEmployees(workError: ApiError(status: 403, code: 'FORBIDDEN', message: 'no')), leave: _FakeLeave());
    expect(find.text("You do not have permission to view this employee's work information."), findsOneWidget);
    expect(find.byKey(const Key('overview-leave-balances')), findsNothing);
    expect(find.byKey(const Key('overview-documents')), findsNothing);
  });

  testWidgets('leave balances show pending and the next approved leave; documents count verified', (tester) async {
    final next = LeaveApplication.fromJson({
      'id': 'a-1', 'employee_id': 'e-1', 'leave_type_id': 't-CL', 'start_date': '2026-12-01', 'end_date': '2026-12-02',
      'total_days': '2', 'status': 'APPROVED', 'version': 1,
    });
    await _pump(
      tester,
      employees: _FakeEmployees(work: _work(), documents: const [
        EmployeeDocumentRow(id: 'd1', documentType: 'PAN_CARD', originalFilename: 'pan.pdf', status: 'VERIFIED'),
        EmployeeDocumentRow(id: 'd2', documentType: 'AADHAAR', originalFilename: 'aadhaar.pdf', status: 'PENDING'),
      ]),
      leave: _FakeLeave(balances: [_balance('CL', 7.5, 1)], next: next),
    );
    expect(find.text('Leave CL (CL)'), findsOneWidget);
    expect(find.text('7.5 days'), findsOneWidget);
    expect(find.text(' (1 pending)'), findsOneWidget);
    expect(find.byKey(const Key('overview-next-leave')), findsOneWidget);
    expect(find.text('1 Dec 2026 – 2 Dec 2026 (2 days)'), findsOneWidget);
    expect(find.text('Documents (1 of 2 verified)'), findsOneWidget);
    expect(find.text('pan card'), findsOneWidget);
  });

  testWidgets('a viewer who cannot read balances or documents sees neither card', (tester) async {
    await _pump(tester, employees: _FakeEmployees(work: _work()), leave: _FakeLeave());
    expect(find.byKey(const Key('overview-leave-balances')), findsNothing);
    expect(find.byKey(const Key('overview-documents')), findsNothing);
    expect(find.byKey(const Key('overview-work')), findsOneWidget);
  });
}
