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
  int workLoads = 0;

  @override
  Future<EmployeeWorkSummary> workSummary(String employeeId) async {
    workLoads += 1;
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

Future<void> _pump(WidgetTester tester, {required _FakeEmployees employees, required _FakeLeave leave, OverviewActions? overview}) async {
  tester.view.physicalSize = const Size(800, 4000);
  tester.view.devicePixelRatio = 1;
  addTearDown(tester.view.reset);
  await tester.pumpWidget(ProviderScope(
    overrides: [
      employeeRepositoryProvider.overrideWithValue(employees),
      leaveRepositoryProvider.overrideWithValue(leave),
      fakeAuth(const []),
    ],
    child: MaterialApp(home: Scaffold(body: EmployeeOverview(employee: _employee(), overview: overview, now: _now))),
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

  group('edit controls', () {
    final changes = <String?>[];
    final opened = <String>[];
    var editedDetails = 0;
    var saved = true;

    OverviewActions actions({bool update = true, bool change = true, List<String> sections = const ['Employment', 'Compensation', 'Banking', 'Documents']}) => OverviewActions(
          canEditDetails: update,
          canChangeWork: change,
          onEditDetails: () => editedDetails += 1,
          onChangeWork: (t) async {
            changes.add(t);
            return saved;
          },
          onOpenSection: opened.add,
          openableSections: sections,
        );

    setUp(() {
      changes.clear();
      opened.clear();
      editedDetails = 0;
      saved = true;
    });

    testWidgets('Change shift and Change assignment open the assignment form, and a save reloads the work card', (tester) async {
      final employees = _FakeEmployees(work: _work(), documents: const []);
      await _pump(tester, employees: employees, leave: _FakeLeave(balances: const []), overview: actions());
      expect(employees.workLoads, 1);
      await tester.tap(find.byKey(const Key('overview-change-shift')));
      await tester.pumpAndSettle();
      await tester.tap(find.byKey(const Key('overview-change-assignment')));
      await tester.pumpAndSettle();
      expect(changes, ['SHIFT_CHANGE', null]);
      expect(employees.workLoads, 3);
    });

    testWidgets('a cancelled change does not reload', (tester) async {
      saved = false;
      final employees = _FakeEmployees(work: _work(), documents: const []);
      await _pump(tester, employees: employees, leave: _FakeLeave(balances: const []), overview: actions());
      await tester.tap(find.byKey(const Key('overview-change-shift')));
      await tester.pumpAndSettle();
      expect(employees.workLoads, 1);
    });

    testWidgets('each row pencil preselects the fitting change type', (tester) async {
      await _pump(tester, employees: _FakeEmployees(work: _work(), documents: const []), leave: _FakeLeave(balances: const []), overview: actions());
      for (final label in ['designation', 'department', 'reporting manager', 'branch', 'work location', 'shift']) {
        await tester.tap(find.byTooltip('Edit $label'));
        await tester.pumpAndSettle();
      }
      expect(changes, ['PROMOTION', 'TRANSFER', 'MANAGER_CHANGE', 'TRANSFER', 'TRANSFER', 'SHIFT_CHANGE']);
    });

    testWidgets('without transfer or promote there are no work controls, but employment still opens its section', (tester) async {
      await _pump(tester, employees: _FakeEmployees(work: _work(), documents: const []), leave: _FakeLeave(balances: const []), overview: actions(change: false));
      expect(find.byKey(const Key('overview-change-shift')), findsNothing);
      expect(find.byTooltip('Edit department'), findsNothing);
      await tester.tap(find.byKey(const Key('overview-edit-employment')));
      await tester.pumpAndSettle();
      expect(opened, ['Employment']);
      await tester.tap(find.byTooltip('Edit pay basis'));
      expect(opened, ['Employment', 'Employment']);
    });

    testWidgets('personal details show only what is filled, list what is missing once, and Add details edits', (tester) async {
      await _pump(tester, employees: _FakeEmployees(work: _work(), documents: const []), leave: _FakeLeave(balances: const []), overview: actions());
      final personal = find.byKey(const Key('overview-personal'));
      expect(find.descendant(of: personal, matching: find.text('Legal name')), findsOneWidget);
      expect(find.descendant(of: personal, matching: find.text('Gender')), findsNothing);
      final missing = tester.widget<Text>(find.descendant(of: find.byKey(const Key('overview-not-added')), matching: find.byType(Text)).first);
      expect(missing.textSpan!.toPlainText(), startsWith('Not added yet: Gender, Marital status, Blood group, Nationality, Personal email, Personal mobile'));
      await tester.tap(find.text('Add details'));
      await tester.tap(find.text('Edit'));
      expect(editedDetails, 2);
    });

    testWidgets('without update access there is no Edit or Add details', (tester) async {
      await _pump(tester, employees: _FakeEmployees(work: _work(), documents: const []), leave: _FakeLeave(balances: const []), overview: actions(update: false));
      expect(find.text('Add details'), findsNothing);
      expect(find.byKey(const Key('overview-not-added')), findsOneWidget);
    });

    testWidgets('More to edit links only the sections the viewer can open', (tester) async {
      await _pump(tester, employees: _FakeEmployees(work: _work(), documents: const []), leave: _FakeLeave(balances: const []), overview: actions());
      final more = find.byKey(const Key('overview-more-to-edit'));
      expect(find.descendant(of: more, matching: find.text('Banking')), findsOneWidget);
      expect(find.descendant(of: more, matching: find.text('Statutory')), findsNothing);
      await tester.tap(find.descendant(of: more, matching: find.text('Banking')));
      expect(opened, ['Banking']);
    });

    testWidgets('My Profile (no actions) has no edit controls, no More to edit and no attendance analytics', (tester) async {
      await _pump(tester, employees: _FakeEmployees(work: _work(), documents: const []), leave: _FakeLeave(balances: const []));
      expect(find.byKey(const Key('overview-change-shift')), findsNothing);
      expect(find.byKey(const Key('overview-edit-employment')), findsNothing);
      expect(find.byKey(const Key('overview-more-to-edit')), findsNothing);
      expect(find.byKey(const Key('employee-insights')), findsNothing);
      expect(find.byTooltip('Edit shift'), findsNothing);
    });

    testWidgets('the header shows the shift and the time with the company', (tester) async {
      await _pump(tester, employees: _FakeEmployees(work: _work(), documents: const []), leave: _FakeLeave(balances: const []));
      expect(find.text('Shift General'), findsOneWidget);
      expect(find.text('Time with company 2 yrs 7 mos'), findsOneWidget);
    });
  });
}
