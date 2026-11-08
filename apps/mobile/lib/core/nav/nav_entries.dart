import 'package:flutter/material.dart';

import '../auth/auth_types.dart';
import '../auth/permissions.dart';
import '../auth/surface.dart';

/// One destination in the More menu, and — for admin-only destinations — the permission the
/// route guard enforces for the same path. A single table, so the menu and the guard cannot
/// disagree (redesign spec §3.4–3.5, decision D-08/D-09).
///
/// **Hiding is not security.** The API enforces every permission below; the menu and the guard
/// only stop an employee from landing on screens that can only answer 403. `anyOf` mirrors the
/// permission the screen's own list endpoint checks (verified against the API routers).
/// Payroll is outside the attendance-only release: its menu entries and routes are hidden and
/// its deep links land on the user's landing page. The screens, API client and models stay in the
/// code base untouched; flipping this switches everything back on. UX only, the API still
/// enforces every payroll permission.
const kPayrollInRelease = false;

/// Whether [route] belongs to payroll (pay runs, salary setup, statutory rates, own payslips).
bool isPayrollRoute(String route) => route == '/app/payroll' || route.startsWith('/app/payroll/') || route == '/app/me/payslips' || route.startsWith('/app/me/payslips/');

class NavEntry {
  const NavEntry(this.label, this.icon, this.route, {this.anyOf = const [], this.allOf = const [], this.employeeLabel, this.guarded = true, this.requiresEmployee = false});

  final String label;
  final IconData icon;
  final String route;

  /// The user needs at least one of these. Empty means anyone signed in.
  final List<String> anyOf;

  /// The user also needs every one of these: the read grants the screen's other API calls
  /// check, so a user who passes [anyOf] is not sent to a screen that can only answer 403.
  final List<String> allOf;

  /// Label for the employee menu when it differs from the administrator's.
  final String? employeeLabel;

  /// Whether the route guard redirects a user lacking [anyOf]. False for the employee destinations
  /// (their screens already answer the API's 403 with the normal error state).
  final bool guarded;

  /// A personal view: hidden from an account with no linked employee record.
  final bool requiresEmployee;

  bool allowedFor(Iterable<String> permissions) =>
      (anyOf.isEmpty || anyOf.any(permissions.contains)) && allOf.every(permissions.contains);
}

class NavGroup {
  const NavGroup(this.label, this.items);
  final String label;
  final List<NavEntry> items;
}

const _teamView = [attendanceViewAll, employeeViewAll];

/// What the attendance calendar reads besides [attendanceViewAll]: the employee list and the days.
const attendanceCalendarReads = [attendanceView, employeeViewAll];

/// The employee destinations (the entire employee menu besides Sign out).
const employeeNavEntries = [
  NavEntry('Leave Balances', Icons.account_balance_wallet_outlined, '/app/leave-balances',
      anyOf: [leaveBalanceView, leaveBalanceViewAll], employeeLabel: 'Leave balances', guarded: false),
  NavEntry('My Calendar', Icons.calendar_month_outlined, '/app/me/calendar', anyOf: [attendanceView], employeeLabel: 'My calendar', guarded: false, requiresEmployee: true),
  NavEntry('Regularizations', Icons.edit_note, '/app/regularizations', anyOf: [attendanceView], employeeLabel: 'Corrections', guarded: false),
  NavEntry('Overtime', Icons.alarm_on_outlined, '/app/overtime', anyOf: [attendanceView], guarded: false),
  NavEntry('Shift swaps', Icons.swap_horiz_rounded, '/app/shift-swaps', anyOf: [attendanceView], guarded: false),
  NavEntry('My Payslips', Icons.description_outlined, '/app/me/payslips', anyOf: [payrollPayslipViewOwn], employeeLabel: 'Payslips', guarded: false),
];

/// Mirrors `apps/web/src/components/layout/nav-items.ts`'s `NAV_ITEMS` (the items not already in
/// the bottom nav). Order is the existing hub order.
const navQuickLinks = NavGroup('Quick links', [
  NavEntry('My Calendar', Icons.calendar_month_outlined, '/app/me/calendar', anyOf: [attendanceView], guarded: false, requiresEmployee: true),
  NavEntry('Employees', Icons.people_outline, '/app/employees', anyOf: [employeeViewAll]),
  NavEntry('Onboarding', Icons.person_add_alt, '/app/onboarding', anyOf: [onboardingView, onboardingCreate, onboardingReview, onboardingActivate]),
  NavEntry('Team Attendance', Icons.groups_outlined, '/app/team-attendance', anyOf: _teamView),
  // Also reads /employees (EMPLOYEE.VIEW_ALL) and /attendance/days (ATTENDANCE.VIEW).
  NavEntry('Attendance Calendar', Icons.calendar_view_month_outlined, '/app/attendance/calendar', anyOf: [attendanceViewAll], allOf: attendanceCalendarReads),
  NavEntry('Attendance Insights', Icons.insights_outlined, '/app/attendance-insights', anyOf: _teamView),
  // Roster reads (/rosters, /rosters/weekly-schedule) check ATTENDANCE.VIEW, not ROSTER_MANAGE.
  NavEntry('Shift Rosters', Icons.event_available, '/app/rosters', anyOf: [attendanceRosterManage, ..._teamView], allOf: [attendanceView]),
  NavEntry('Schedule Coverage', Icons.stacked_bar_chart_outlined, '/app/schedule', anyOf: [attendanceRosterManage, ..._teamView], allOf: [attendanceView]),
  NavEntry('Shift Swaps', Icons.swap_horiz_rounded, '/app/shift-swaps', anyOf: [attendanceView], guarded: false),
  NavEntry('Regularizations', Icons.edit_note, '/app/regularizations', anyOf: [attendanceView], guarded: false),
  NavEntry('Overtime', Icons.alarm_on_outlined, '/app/overtime', anyOf: [attendanceView], guarded: false),
  NavEntry('Leave Balances', Icons.account_balance_wallet_outlined, '/app/leave-balances', anyOf: [leaveBalanceView, leaveBalanceViewAll], guarded: false),
  NavEntry('Payroll', Icons.payments_outlined, '/app/payroll/pay-runs', anyOf: [payrollRunView, payrollRunProcess]),
  NavEntry('My Payslips', Icons.description_outlined, '/app/me/payslips', anyOf: [payrollPayslipViewOwn], guarded: false),
]);

/// Mirrors `SETTINGS_NAV_GROUPS` in full: web's Settings sections in setup order, area by area
/// (Company & structure, Attendance, Leave, Payroll, Access & setup), then the shared
/// "Who follows what" screens.
const navSettingsGroups = [
  NavGroup('Company', [
    NavEntry('Company Profile', Icons.apartment_outlined, '/app/company', anyOf: [orgCompanyManage]),
    NavEntry('Legal Entities', Icons.gavel_outlined, '/app/legal-entities', anyOf: [orgLegalEntityManage]),
    NavEntry('Branches', Icons.business_outlined, '/app/branches', anyOf: [orgBranchManage]),
  ]),
  NavGroup('People structure', [
    NavEntry('Departments', Icons.account_tree_outlined, '/app/departments', anyOf: [orgDepartmentManage]),
    NavEntry('Designations', Icons.work_outline, '/app/designations', anyOf: [orgDesignationManage]),
    NavEntry('Grades', Icons.layers_outlined, '/app/grades', anyOf: [orgGradeManage]),
  ]),
  NavGroup('When people work', [
    NavEntry('Shifts', Icons.schedule_outlined, '/app/shifts', anyOf: [orgShiftManage]),
    NavEntry('Work Calendars', Icons.date_range_outlined, '/app/work-calendars', anyOf: [orgCalendarManage]),
    NavEntry('Holiday Calendars', Icons.calendar_month_outlined, '/app/holiday-calendars', anyOf: [orgHolidayManage]),
    NavEntry('Weekly-Off Patterns', Icons.event_busy_outlined, '/app/weekly-off-patterns', anyOf: [orgCalendarManage]),
    // Mobile only: web shows the roster calendar as a tab of Shift Rosters.
    NavEntry('Roster Calendar', Icons.calendar_view_month_outlined, '/app/roster-calendar', anyOf: [attendanceRosterManage, ..._teamView], allOf: [attendanceView]),
  ]),
  NavGroup('Where people punch', [
    NavEntry('Workplace Geofences', Icons.location_on_outlined, '/app/attendance-geofences', anyOf: [attendancePolicyManage, attendanceViewAll]),
  ]),
  NavGroup('Attendance rules', [
    NavEntry('Attendance Policies', Icons.assignment_outlined, '/app/attendance-policies', anyOf: [attendancePolicyManage]),
    NavEntry('Overtime Policies', Icons.timer_outlined, '/app/overtime-policies', anyOf: [attendancePolicyManage]),
    NavEntry('Correction Policies', Icons.history_edu_outlined, '/app/regularization-policies', anyOf: [attendancePolicyManage]),
  ]),
  NavGroup('Closing the month', [
    NavEntry('Attendance Periods', Icons.lock_clock_outlined, '/app/attendance-periods', anyOf: [attendanceLock, attendanceUnlock, ..._teamView]),
  ]),
  NavGroup('Leave types and rules', [
    NavEntry('Leave Types', Icons.sell_outlined, '/app/leave-types', anyOf: [leaveTypeManage]),
    NavEntry('Leave Policies', Icons.assignment_turned_in_outlined, '/app/leave-policies', anyOf: [leavePolicyManage]),
    NavEntry('Leave Year', Icons.event_repeat_outlined, '/app/leave-year-setting', anyOf: [leaveYearSettingManage]),
    NavEntry('Leave Combination Rules', Icons.merge_type_outlined, '/app/leave-combination-rules', anyOf: [leaveCombinationRuleManage]),
    NavEntry('Statutory Minimums', Icons.balance_outlined, '/app/statutory-leave-minimums', anyOf: [leaveStatutoryMinimumManage]),
  ]),
  NavGroup('Pay setup', [
    NavEntry('Salary Components', Icons.attach_money_outlined, '/app/payroll/salary-components', anyOf: [payrollSetupManage]),
    NavEntry('Salary Structures', Icons.view_list_outlined, '/app/payroll/salary-structures', anyOf: [payrollSetupManage]),
    NavEntry('Statutory Rates', Icons.account_balance_outlined, '/app/payroll/statutory-rates', anyOf: [payrollStatutoryManage]),
  ]),
  NavGroup('Access & setup', [
    NavEntry('Users', Icons.manage_accounts_outlined, '/app/users', anyOf: [settingsUserManage, settingsRoleManage]),
    NavEntry('Setup', Icons.checklist_outlined, '/app/setup', anyOf: [orgCompanyManage]),
  ]),
  NavGroup('Who follows what', [
    NavEntry('Rules by Group', Icons.link_outlined, '/app/policy-assignments', anyOf: [orgCalendarManage, attendancePolicyManage]),
    NavEntry("Check a Person's Rules", Icons.search_outlined, '/app/policy-resolution', anyOf: [orgCalendarManage, attendancePolicyManage]),
  ]),
];

List<NavEntry> _visible(List<NavEntry> items, Iterable<String> permissions, bool payroll, {bool hasEmployee = true}) =>
    [for (final e in items) if (e.allowedFor(permissions) && (payroll || !isPayrollRoute(e.route)) && (hasEmployee || !e.requiresEmployee)) e];

/// The administrator/manager menu filtered to what [permissions] allow; groups with no visible
/// entry are dropped.
List<NavGroup> visibleNavGroups(Iterable<String> permissions, {bool payroll = kPayrollInRelease, bool hasEmployee = true}) => [
      for (final g in [navQuickLinks, ...navSettingsGroups])
        if (_visible(g.items, permissions, payroll, hasEmployee: hasEmployee).isNotEmpty) NavGroup(g.label, _visible(g.items, permissions, payroll, hasEmployee: hasEmployee)),
    ];

/// The employee menu: the destinations the user may open, with employee wording.
List<NavEntry> visibleEmployeeEntries(Iterable<String> permissions, {bool payroll = kPayrollInRelease}) => _visible(employeeNavEntries, permissions, payroll);

/// Route → entry, for every guarded destination (built from the same entries).
final Map<String, NavEntry> _guardTable = {
  for (final g in [navQuickLinks, ...navSettingsGroups])
    for (final e in g.items)
      if (e.guarded) e.route: e,
};

/// Where to send [user] instead of [location], or null to let them through. Applies only to the
/// administrator destinations in the menu table; tabs, `/app/more`, and the employee screens are
/// never redirected. UX only: the API answers 403 regardless.
String? guardRedirect(String location, UserProfile? user, {required String landing, bool payroll = kPayrollInRelease}) {
  if (user == null) return null;
  if (!payroll && isPayrollRoute(location)) return landing;
  for (final entry in _guardTable.entries) {
    if (location == entry.key || location.startsWith('${entry.key}/')) {
      return entry.value.allowedFor(user.permissions) ? null : landing;
    }
  }
  return null;
}

/// Convenience used by the router.
bool isGuardedRoute(String location) => _guardTable.keys.any((r) => location == r || location.startsWith('$r/'));

/// For tests and docs: whether the user sees the employee menu rather than the full one.
bool showsEmployeeMenu(UserProfile? user) => usesEmployeeSurface(user);
