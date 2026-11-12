import 'package:flutter_test/flutter_test.dart';
import 'package:hrms_mobile/core/auth/auth_types.dart';
import 'package:hrms_mobile/core/auth/permissions.dart';
import 'package:hrms_mobile/core/nav/nav_entries.dart';
import 'package:hrms_mobile/core/router/app_router.dart';
import 'package:hrms_mobile/features/auth/state/auth_state.dart';

/// Permission sets of the six personas, copied from what the API seeds (see
/// `apps/api/src/hrms/modules/organisation/service.py`: the COMPANY_ADMIN, HR_ADMIN,
/// REPORTING_MANAGER, BRANCH_MANAGER and EMPLOYEE role grants), so the menu and the route guard are
/// checked against the real backend authorisation, not a hand-made list. Every manager persona
/// also holds the EMPLOYEE role (a manager is an employee first).
const _employeeRole = [
  employeeView, employeeViewCompensation, employeeViewStatutory, employeeViewBanking, employeeViewSensitive, employeeViewExperience,
  employeeViewNominee, employeeViewDocuments, leaveApplicationSubmit, leaveBalanceView, attendancePunch, attendanceView,
  attendanceRegularizationRequest, payrollPayslipViewOwn,
];

const _reportingManager = [..._employeeRole, attendanceRegularizationApprove, attendanceOvertimeApprove, leaveApplicationApprove, leaveBalanceViewAll];

const _branchManager = [..._reportingManager, employeeViewAll];

const _hrAdmin = [
  ..._employeeRole, employeeViewAll, employeeCreate, employeeUpdate, attendanceViewAll, attendanceRegularizationApprove, attendanceOvertimeApprove,
  leaveApplicationApprove, leaveApplicationCancelApproved, leaveBalanceViewAll, leaveBalanceAdjust, leaveApplicationSubmitOnBehalf,
  onboardingView, onboardingCreate, onboardingReview, onboardingActivate, orgCalendarManage, orgHolidayManage,
  payrollRunView, payrollRunProcess, payrollSetupManage,
];

const _companyAdmin = [
  dashboardCompanyView, ..._hrAdmin, attendanceRosterManage, attendancePolicyManage, attendanceLock, attendanceUnlock, attendanceRecompute,
  orgCompanyManage, orgLegalEntityManage, orgBranchManage, orgDepartmentManage, orgDesignationManage, orgGradeManage, orgShiftManage,
  leaveTypeManage, leavePolicyManage, leaveCombinationRuleManage, leaveYearSettingManage, leaveStatutoryMinimumManage,
  settingsUserManage, settingsRoleManage, payrollStatutoryManage, payrollRunApprove,
];

const _employeeWithExtra = [..._employeeRole, settingsUserManage, orgDepartmentManage];

AuthState _auth(List<String> permissions, {String? employeeId = 'e-1'}) => AuthState(
      status: AuthStatus.authenticated,
      user: UserProfile(id: 'u', email: 'a@b.c', companyId: 'c', employeeId: employeeId, permissions: permissions, companyTimezone: 'Asia/Kolkata'),
    );

Set<String> _menu(List<String> permissions) => {for (final g in visibleNavGroups(permissions)) for (final e in g.items) e.route};

/// Routes that `appRedirect` lets this persona open, out of [candidates].
Set<String> _reachable(List<String> permissions, Iterable<String> candidates, {String? employeeId = 'e-1'}) {
  final auth = _auth(permissions, employeeId: employeeId);
  return {for (final r in candidates) if (appRedirect(auth, r) == null) r};
}

final _allGuarded = {for (final g in [navQuickLinks, ...navSettingsGroups]) for (final e in g.items) if (e.guarded && !isPayrollRoute(e.route)) e.route};

void main() {
  group('the menu and the route guard agree for every persona (and never open a screen the API refuses)', () {
    for (final persona in {
      'company admin': _companyAdmin,
      'HR admin': _hrAdmin,
      'branch manager': _branchManager,
      'reporting manager': _reportingManager,
      'employee': _employeeRole,
      'employee with extra management permissions': _employeeWithExtra,
    }.entries) {
      test('${persona.key}: every guarded menu entry is reachable exactly when it is in the menu', () {
        final menu = _menu(persona.value);
        final reachable = _reachable(persona.value, _allGuarded);
        expect(reachable, _allGuarded.intersection(menu), reason: 'a guarded route is open iff its entry is shown');
      });
    }
  });

  group('company admin', () {
    test('sees every administrator destination', () {
      expect(_reachable(_companyAdmin, _allGuarded), _allGuarded);
    });
    test('reaches payroll: pay runs and statutory rates', () {
      expect(_menu(_companyAdmin), containsAll(['/app/payroll/pay-runs', '/app/payroll/statutory-rates']));
      expect(appRedirect(_auth(_companyAdmin), '/app/payroll/pay-runs'), isNull);
    });
  });

  group('HR admin (seeded HR_ADMIN: company-wide employee, attendance and leave administration, no dashboard)', () {
    test('has the employee surface plus HR destinations', () {
      final menu = _menu(_hrAdmin);
      for (final r in ['/app/employees', '/app/onboarding', '/app/team-attendance', '/app/holiday-calendars', '/app/work-calendars', '/app/weekly-off-patterns', '/app/leave-balances', '/app/regularizations']) {
        expect(menu, contains(r), reason: r);
      }
    });
    test('does not get what the API keeps with COMPANY_ADMIN', () {
      final menu = _menu(_hrAdmin);
      for (final r in ['/app/users', '/app/company', '/app/shifts', '/app/attendance-policies', '/app/leave-types', '/app/branches', '/app/departments', '/app/setup']) {
        expect(menu, isNot(contains(r)), reason: r);
        expect(appRedirect(_auth(_hrAdmin), r), '/app/home', reason: r);
      }
    });
  });

  group('branch manager (EMPLOYEE.VIEW_ALL and ATTENDANCE.VIEW at branch scope, approvals)', () {
    test('keeps Employees and Team attendance and the request screens', () {
      final menu = _menu(_branchManager);
      for (final r in ['/app/employees', '/app/team-attendance', '/app/regularizations', '/app/overtime', '/app/leave-balances']) {
        expect(menu, contains(r), reason: r);
      }
      expect(menu, isNot(contains('/app/users')));
      expect(menu, isNot(contains('/app/onboarding')));
    });
  });

  group('reporting manager (reportee-tree approvals only: no company-wide read permission)', () {
    test('has the request screens (where they approve) but not the employee list or team attendance, which the API would refuse', () {
      final menu = _menu(_reportingManager);
      for (final r in ['/app/regularizations', '/app/overtime', '/app/leave-balances']) {
        expect(menu, contains(r), reason: r);
      }
      for (final r in ['/app/employees', '/app/team-attendance', '/app/users']) {
        expect(menu, isNot(contains(r)), reason: r);
        expect(appRedirect(_auth(_reportingManager), r), '/app/home', reason: r);
      }
    });
  });

  group('employee', () {
    test('menu is exactly the request destinations, My Calendar, shift swaps and My Payslips', () {
      expect([for (final e in visibleEmployeeEntries(_employeeRole)) e.route], ['/app/leave-balances', '/app/me/calendar', '/app/regularizations', '/app/overtime', '/app/shift-swaps', '/app/me/payslips']);
    });
    test('every administrator destination lands on Home', () {
      expect(_reachable(_employeeRole, _allGuarded), isEmpty);
    });
    test('tabs, Home and the employee routes are reachable', () {
      expect(_reachable(_employeeRole, ['/app/home', '/app/attendance', '/app/leave-applications', '/app/me', '/app/more', '/app/regularizations', '/app/overtime', '/app/leave-balances', '/app/shift-swaps']).length, 9);
    });
  });

  group('employee with additional management permissions', () {
    test('gets exactly the extra destinations their permissions open', () {
      final menu = _menu(_employeeWithExtra);
      expect(menu, containsAll(['/app/users', '/app/departments']));
      expect(menu, isNot(contains('/app/employees')));
      expect(appRedirect(_auth(_employeeWithExtra), '/app/users'), isNull);
      expect(appRedirect(_auth(_employeeWithExtra), '/app/shifts'), '/app/home');
    });
  });

  group('users without an employee record', () {
    test('an administrator without a record still reaches the dashboard and the destinations they hold', () {
      final auth = _auth(_companyAdmin, employeeId: null);
      expect(appRedirect(auth, '/app/dashboard'), isNull);
      expect(appRedirect(auth, '/app/users'), isNull);
      expect(appRedirect(auth, '/app/home'), '/app/dashboard');
    });
    test('a user with neither is sent to the explanatory dashboard page, not into a loop', () {
      final auth = _auth(const [], employeeId: null);
      expect(appRedirect(auth, '/app/home'), '/app/dashboard');
      expect(appRedirect(auth, '/app/dashboard'), isNull);
      expect(appRedirect(auth, '/app/users'), '/app/dashboard');
    });
  });
}
