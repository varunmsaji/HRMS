import 'package:flutter_test/flutter_test.dart';
import 'package:hrms_mobile/core/auth/auth_types.dart';
import 'package:hrms_mobile/core/auth/permissions.dart';
import 'package:hrms_mobile/features/shell/app_shell.dart';

UserProfile _user({List<String> permissions = const [], String? employeeId}) => UserProfile(
      id: 'u-1',
      email: 'a@example.com',
      companyId: 'c-1',
      employeeId: employeeId,
      permissions: permissions,
      companyTimezone: 'Asia/Kolkata',
    );

void main() {
  test('an admin with the dashboard permission sees all four tabs', () {
    final user = _user(permissions: [dashboardCompanyView], employeeId: 'e-1');
    expect(visibleShellBranches(user), [0, 1, 2, 3]);
  });

  test('an employee without the dashboard permission does not get a Home tab', () {
    final user = _user(employeeId: 'e-1');
    expect(showHomeTab(user), isFalse);
    expect(visibleShellBranches(user), [1, 2, 3]);
  });

  test('a user with neither the permission nor an employee record keeps Home (it explains why)', () {
    expect(visibleShellBranches(_user()), [0, 1, 2, 3]);
  });

  test('before the profile loads, every tab is shown', () {
    expect(visibleShellBranches(null), [0, 1, 2, 3]);
  });
}
