import 'auth_types.dart';
import 'permissions.dart';

/// Whether this session gets the employee experience: it has an employee record and is not an
/// administrator (`DASHBOARD.COMPANY.VIEW`). This is the inverse of the old "no Home tab" rule,
/// kept in one place so landing, tabs and theme can never disagree (decision D-03).
///
/// Managers (reporting/branch) are employee-surface sessions that carry extra permissions; the
/// screens they share with the employee keep every permission branch.
bool usesEmployeeSurface(UserProfile? user) =>
    user != null && user.employeeId != null && !user.permissions.contains(dashboardCompanyView);
