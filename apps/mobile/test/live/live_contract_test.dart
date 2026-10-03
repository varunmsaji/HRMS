@Tags(['live'])
library;

// Drives the app's real repositories over real HTTP against a running backend, so contract
// drift (a field typed differently, a missing header, a renamed key) fails here instead of on a
// device. Skipped unless HRMS_LIVE_API is set:
//
//   HRMS_LIVE_API=1 flutter test test/live            # backend on http://localhost:8000
//   HRMS_LIVE_API=1 HRMS_LIVE_EMAIL=… HRMS_LIVE_PASSWORD=… flutter test test/live
//
// Read-only: it only issues GETs (plus the login).

import 'dart:io';

import 'package:flutter/services.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:hrms_mobile/core/api/api_client.dart';
import 'package:hrms_mobile/core/api/api_error.dart';
import 'package:hrms_mobile/core/auth/token_storage.dart';
import 'package:hrms_mobile/features/attendance/data/attendance_repository.dart';
import 'package:hrms_mobile/features/attendance/data/policy_repository.dart';
import 'package:hrms_mobile/features/auth/data/auth_repository.dart';
import 'package:hrms_mobile/features/dashboard/data/dashboard_repository.dart';
import 'package:hrms_mobile/features/leave/data/leave_repository.dart';
import 'package:hrms_mobile/features/onboarding/data/onboarding_repository.dart';
import 'package:hrms_mobile/features/organisation/data/organisation_repository.dart';
import 'package:hrms_mobile/features/payroll/data/payroll_repository.dart';
import 'package:hrms_mobile/features/profile/data/employee_repository.dart';
import 'package:hrms_mobile/features/profile/presentation/employee_record_sections.dart';

final _failures = <String>[];
final _dataDependent = <String>[];
var _passed = 0;

Future<T?> _check<T>(String name, Future<T> Function() call) async {
  try {
    final result = await call();
    _passed++;
    return result;
  } on ApiError catch (e) {
    // The call reached the server and got a well-formed envelope back. A 4xx (no subscription
    // row, account has no linked employee, missing permission) is about the demo data, not the
    // contract. 401 (auth broke), 5xx and 422 (we sent something the server rejected) still fail.
    final noEmployee = e.message.contains('no linked employee');
    if (noEmployee || e.status == 403 || e.status == 404 || e.status == 409) {
      _dataDependent.add('$name -> ${e.status} ${e.message}');
    } else {
      _failures.add('$name -> ${e.status} ${e.code} ${e.message}');
    }
    return null;
  } catch (e, st) {
    final where = st.toString().split('\n').firstWhere((l) => l.contains('hrms_mobile'), orElse: () => '');
    _failures.add('$name -> $e ${where.trim()}');
    return null;
  }
}

void main() {
  final live = Platform.environment['HRMS_LIVE_API'] != null;

  test('every read the app makes parses against the live API', () async {
    TestWidgetsFlutterBinding.ensureInitialized();
    HttpOverrides.global = null; // the test binding blocks real HTTP by default
    FlutterSecureStorage.setMockInitialValues({});
    final tmp = Directory.systemTemp.createTempSync('hrms_live_');
    TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger.setMockMethodCallHandler(
      const MethodChannel('plugins.flutter.io/path_provider'),
      (call) async => tmp.path,
    );

    final client = await ApiClient.getInstance();
    final auth = AuthRepository(client);
    final login = await auth.login(
      email: Platform.environment['HRMS_LIVE_EMAIL'] ?? 'admin@example.com',
      password: Platform.environment['HRMS_LIVE_PASSWORD'] ?? 'DemoPass123!',
    );
    await TokenStorage.instance.save(StoredSession.fromTokenResponse(login));

    await _check('auth /me', auth.me);

    final dashboard = DashboardRepository(client);
    await _check('dashboard company', dashboard.getCompanyDashboard);
    await _check('dashboard subscription', dashboard.getSubscription);
    await _check('dashboard company profile', dashboard.getCompanyProfile);

    final org = OrganisationRepository(client);
    await _check('company profile', org.getCompanyProfile);
    await _check('legal entities', org.listLegalEntities);
    await _check('branches', org.listBranches);
    await _check('departments', org.listDepartments);
    await _check('designations', org.listDesignations);
    await _check('grades', org.listGrades);

    final employees = EmployeeRepository(client);
    final list = await _check('employees list', employees.listEmployees) ?? const <Employee>[];
    if (list.isNotEmpty) {
      await _check('employee detail', () => employees.getEmployee(list.first.id));
      for (final section in employeeRecordSections) {
        await _check('employee ${section.title}', () async {
          final path = '/employees/${list.first.id}${section.path}';
          if (section.single) {
            return client.get<Map<String, dynamic>>(path, parse: (d) => d as Map<String, dynamic>);
          }
          return client.getList<Map<String, dynamic>>(path, parseItem: (d) => d as Map<String, dynamic>);
        });
      }
    }

    final att = AttendanceRepository(client);
    await _check('shifts', att.listShifts);
    final calendars = await _check('holiday calendars', att.listHolidayCalendars) ?? const <HolidayCalendar>[];
    if (calendars.isNotEmpty) await _check('holidays', () => att.listHolidays(calendars.first.id));
    await _check('weekly-off patterns', att.listWeeklyOffPatterns);
    await _check('work calendars', att.listWorkCalendars);
    for (final path in ['/regularizations', '/overtime']) {
      await _check(path, () => client.getList<Map<String, dynamic>>(path, parseItem: (d) => d as Map<String, dynamic>));
    }
    await _check('rosters', () => client.getList<Map<String, dynamic>>('/rosters', parseItem: (d) => d as Map<String, dynamic>));
    await _check('attendance periods', () => client.getList<Map<String, dynamic>>('/attendance-periods', parseItem: (d) => d as Map<String, dynamic>));
    await _check('policy assignments', att.listPolicyAssignments);
    await _check('face enrollment (me)', att.getMyFaceEnrollment);
    for (final base in ['attendance-policies', 'overtime-policies', 'regularization-policies']) {
      final policies = PolicyRepository(client, base);
      final identities = await _check('$base list', policies.listPolicies) ?? const <PolicyIdentity>[];
      if (identities.isNotEmpty) await _check('$base versions', () => policies.listVersions(identities.first.id));
    }

    final leave = LeaveRepository(client);
    await _check('leave types', leave.listLeaveTypes);
    await _check('leave combination rules', leave.listCombinationRules);
    await _check('statutory leave minimums', leave.listStatutoryMinimums);
    await _check('leave year setting', leave.getLeaveYearSetting);
    await _check('leave applications', leave.listLeaveApplications);
    if (list.isNotEmpty) {
      await _check('leave balances', () => leave.listLeaveBalances(list.first.id));
      await _check('leave ledger', () => leave.listLeaveLedger(list.first.id));
    }

    final payroll = PayrollRepository(client);
    final runs = await _check('pay runs', payroll.listPayRuns) ?? const <PayRun>[];
    if (runs.isNotEmpty) await _check('pay run employees', () => payroll.listPayRunEmployees(runs.first.id));
    await _check('salary components', payroll.listSalaryComponents);
    await _check('salary structures', payroll.listSalaryStructures);
    await _check('statutory rates', payroll.listStatutoryRates);
    await _check('my payslips', payroll.listMyPayslips);

    final onboarding = OnboardingRepository(client);
    final cases = await _check('onboarding cases', onboarding.listCases) ?? const <OnboardingCase>[];
    if (cases.isNotEmpty) {
      await _check('onboarding case detail', () => onboarding.getCase(cases.first.id));
      await _check('onboarding case documents', () => onboarding.listCaseDocuments(cases.first.id));
    }
    await _check('setup progress', onboarding.getSetupProgress);
    await _check('users', onboarding.listUsers);

    // ignore: avoid_print
    print('live contract: $_passed passed, ${_dataDependent.length} data-dependent, ${_failures.length} failed');
    for (final d in _dataDependent) {
      // ignore: avoid_print
      print('  (data) $d');
    }
    for (final f in _failures) {
      // ignore: avoid_print
      print('  FAIL $f');
    }
    expect(_failures, isEmpty);
  }, skip: live ? false : 'set HRMS_LIVE_API=1 to run against a live backend', timeout: const Timeout(Duration(minutes: 3)));
}
