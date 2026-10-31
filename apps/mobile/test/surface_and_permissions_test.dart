import 'package:flutter_test/flutter_test.dart';
import 'package:hrms_mobile/core/auth/auth_types.dart';
import 'package:hrms_mobile/core/auth/permissions.dart';
import 'package:hrms_mobile/core/auth/surface.dart';

UserProfile _u({List<String> permissions = const [], String? employeeId}) => UserProfile(
      id: 'u',
      email: 'a@b.c',
      companyId: 'c',
      employeeId: employeeId,
      permissions: permissions,
      companyTimezone: 'Asia/Kolkata',
    );

void main() {
  group('usesEmployeeSurface (D-03)', () {
    test('employee with a record and no dashboard grant', () => expect(usesEmployeeSurface(_u(employeeId: 'e')), isTrue));
    test('manager with approve permissions is still an employee surface', () {
      expect(usesEmployeeSurface(_u(employeeId: 'e', permissions: [leaveApplicationApprove, leaveBalanceViewAll])), isTrue);
    });
    test('administrator with the dashboard grant is not', () {
      expect(usesEmployeeSurface(_u(employeeId: 'e', permissions: [dashboardCompanyView])), isFalse);
    });
    test('no employee record is not', () => expect(usesEmployeeSurface(_u()), isFalse));
    test('no profile yet is not', () => expect(usesEmployeeSurface(null), isFalse));
  });

  test('permission constants equal the backend permission codes', () {
    // Copied from apps/api/src/hrms/modules/*/permissions.py.
    expect(employeeView, 'EMPLOYEE.VIEW');
    expect(employeeViewAll, 'EMPLOYEE.VIEW_ALL');
    expect(employeeViewDocuments, 'EMPLOYEE.VIEW_DOCUMENTS');
    expect(leaveBalanceView, 'LEAVE.BALANCE_VIEW');
    expect(payrollPayslipViewOwn, 'PAYROLL.PAYSLIP_VIEW_OWN');
    expect(payrollRunView, 'PAYROLL.RUN_VIEW');
    expect(onboardingView, 'ONBOARDING.VIEW');
    expect(leaveCombinationRuleManage, 'LEAVE.COMBINATION_RULE_MANAGE');
    expect(leaveYearSettingManage, 'LEAVE.YEAR_SETTING_MANAGE');
    expect(leaveStatutoryMinimumManage, 'LEAVE.STATUTORY_MINIMUM_MANAGE');
  });
}
