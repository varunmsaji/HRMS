import '../../features/attendance/domain/attendance_setup_configs.dart';
import '../../features/attendance/presentation/policy_setup_screen.dart';
import '../../features/leave/domain/leave_setup_config.dart';
import 'package:flutter/foundation.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../features/auth/presentation/accept_invite_screen.dart';
import '../../features/auth/presentation/forgot_password_screen.dart';
import '../../features/auth/presentation/login_screen.dart';
import '../../features/auth/presentation/register_screen.dart';
import '../../features/auth/presentation/reset_password_screen.dart';
import '../../features/auth/presentation/verify_email_screen.dart';
import '../../features/attendance/presentation/attendance_periods_screen.dart';
import '../../features/attendance/presentation/attendance_insights_screen.dart';
import '../../features/attendance/presentation/attendance_self_screen.dart';
import '../../features/attendance/presentation/face_setup_screen.dart';
import '../../features/notifications/presentation/notifications_screen.dart';
import '../../features/attendance/presentation/policy_assignments_screen.dart';
import '../../features/attendance/presentation/policy_resolution_screen.dart';
import '../../features/attendance/presentation/roster_calendar_screen.dart';
import '../../features/attendance/presentation/rosters_screen.dart';
import '../../features/attendance/presentation/shift_swaps_screen.dart';
import '../../features/attendance/presentation/geofences_screen.dart';
import '../../features/attendance/presentation/regularization_decision_center_screen.dart';
import '../../features/leave/presentation/leave_decision_center_screen.dart';
import '../../features/attendance/presentation/shift_board_screen.dart';
import '../../features/attendance/presentation/workforce_roster_screen.dart';
import '../../features/attendance/presentation/my_calendar_screen.dart';
import '../../features/attendance/presentation/weekly_schedule_screen.dart';
import '../../features/auth/state/auth_controller.dart';
import '../../features/auth/state/auth_state.dart';
import '../../features/home/presentation/employee_home_screen.dart';
import '../auth/surface.dart';
import '../nav/nav_entries.dart';
import '../theme/employee_theme_scope.dart';
import '../../features/dashboard/presentation/dashboard_screen.dart';
import '../../features/employees/presentation/employees_screen.dart';
import '../../features/leave/presentation/leave_applications_screen.dart';
import '../../features/leave/presentation/leave_balances_screen.dart';
import '../../features/leave/presentation/leave_year_setting_screen.dart';
import '../../features/onboarding/presentation/onboarding_cases_screen.dart';
import '../../features/onboarding/presentation/setup_screen.dart';
import '../../features/onboarding/presentation/users_screen.dart';
import '../../features/payroll/presentation/my_payslips_screen.dart';
import '../../features/payroll/presentation/pay_runs_screen.dart';
import '../../features/payroll/presentation/statutory_rates_screen.dart';
import '../../features/organisation/presentation/company_profile_screen.dart';
import '../../features/profile/presentation/profile_screen.dart';
import '../../features/attendance/presentation/team_attendance_screen.dart';
import '../../features/onboarding/presentation/public_onboarding_screen.dart';
import '../../features/attendance/domain/policy_resources.dart';
import '../../features/attendance/domain/request_resources.dart';
import '../requests/request_screens.dart';
import '../../features/leave/domain/leave_resources.dart';
import '../../features/organisation/domain/org_resources.dart';
import '../../features/payroll/domain/payroll_resources.dart';
import '../resource/resource_screens.dart';
import '../../features/shell/app_shell.dart';
import '../../features/shell/settings_hub_screen.dart';
import '../../features/splash/splash_screen.dart';

/// Redirected away from once authenticated (there's no reason to see a
/// sign-in/sign-up form with a live session).
const _authOnlyPaths = ['/login', '/register', '/forgot-password'];

/// Standalone token-driven flows that mirror the web app's pages outside its
/// `/app` layout guard entirely — accessible regardless of auth status (a
/// signed-in user can still open a password-reset or invite link from email).
const _alwaysPublicPaths = ['/reset-password', '/verify-email', '/accept-invite', '/onboarding'];

/// Bridges Riverpod's [authControllerProvider] to go_router's
/// `refreshListenable` so a login/logout re-runs the redirect below without
/// the router itself being rebuilt.
class _AuthRefreshNotifier extends ChangeNotifier {
  _AuthRefreshNotifier(Ref ref) {
    ref.listen(authControllerProvider, (_, __) => notifyListeners());
  }
}

final _authRefreshProvider = Provider<_AuthRefreshNotifier>((ref) => _AuthRefreshNotifier(ref));

/// The router's redirect rules as a pure function (so every user type can be tested without
/// building screens). Returns the location to go to instead, or null to stay.
String? appRedirect(AuthState auth, String location) {
  if (_alwaysPublicPaths.any((p) => location.startsWith(p))) return null;

  if (auth.status == AuthStatus.loading) {
    return location == '/splash' ? null : '/splash';
  }

  final isAuthOnly = _authOnlyPaths.any((p) => location.startsWith(p));
  if (auth.status == AuthStatus.unauthenticated) {
    return isAuthOnly ? null : '/login';
  }

  // Authenticated.
  if (location == '/splash' || isAuthOnly) return landingPathFor(auth.user);
  // Branch 0 holds both the company dashboard and the employee Home; each user only gets their
  // own, so a link or a tab re-tap to the other one lands on the right one.
  final employee = usesEmployeeSurface(auth.user);
  if (location == '/app/dashboard' && employee) return '/app/home';
  if (location == '/app/home' && !employee) return '/app/dashboard';
  // Administrator destinations: an employee following a stale link or a deep link lands on their
  // landing page instead of a screen that can only answer 403. UX only; the API is the authority.
  return guardRedirect(location, auth.user, landing: landingPathFor(auth.user));
}

final appRouterProvider = Provider<GoRouter>((ref) {
  return GoRouter(
    initialLocation: '/splash',
    refreshListenable: ref.watch(_authRefreshProvider),
    redirect: (context, state) => appRedirect(ref.read(authControllerProvider), state.matchedLocation),
    routes: [
      GoRoute(path: '/splash', builder: (context, state) => const SplashScreen()),
      GoRoute(path: '/login', builder: (context, state) => const LoginScreen()),
      GoRoute(path: '/register', builder: (context, state) => const RegisterScreen()),
      GoRoute(path: '/forgot-password', builder: (context, state) => const ForgotPasswordScreen()),
      GoRoute(
        path: '/reset-password/:token',
        builder: (context, state) => ResetPasswordScreen(token: state.pathParameters['token']!),
      ),
      GoRoute(
        path: '/verify-email/:token',
        builder: (context, state) => VerifyEmailScreen(token: state.pathParameters['token']!),
      ),
      GoRoute(
        path: '/accept-invite/:token',
        builder: (context, state) => AcceptInviteScreen(token: state.pathParameters['token']!),
      ),
      GoRoute(
        path: '/onboarding/:token',
        builder: (context, state) => PublicOnboardingScreen(token: state.pathParameters['token']!),
      ),
      GoRoute(path: '/app/notifications', builder: (context, state) => const EmployeeThemeScope(child: NotificationsScreen())),
      GoRoute(path: '/app/me/calendar', builder: (context, state) => const EmployeeThemeScope(child: MyCalendarScreen())),
      GoRoute(path: '/app/attendance/face-setup', builder: (context, state) => const EmployeeThemeScope(child: FaceSetupScreen())),
      GoRoute(path: '/app/more', builder: (context, state) => const SettingsHubScreen()),
      GoRoute(path: '/app/company', builder: (context, state) => const CompanyProfileScreen()),
      GoRoute(path: '/app/branches', builder: (context, state) => ResourceListScreen(config: branchResource())),
      GoRoute(path: '/app/departments', builder: (context, state) => ResourceListScreen(config: departmentResource)),
      GoRoute(path: '/app/designations', builder: (context, state) => ResourceListScreen(config: designationResource)),
      GoRoute(path: '/app/grades', builder: (context, state) => ResourceListScreen(config: gradeResource)),
      GoRoute(path: '/app/legal-entities', builder: (context, state) => ResourceListScreen(config: legalEntityResource)),
      GoRoute(path: '/app/attendance-policies', builder: (context, state) => ResourceListScreen(config: attendancePolicyResource, createScreen: () => PolicySetupScreen(config: attendancePolicySetup))),
      GoRoute(path: '/app/overtime-policies', builder: (context, state) => ResourceListScreen(config: overtimePolicyResource, createScreen: () => PolicySetupScreen(config: overtimePolicySetup))),
      GoRoute(path: '/app/regularization-policies', builder: (context, state) => ResourceListScreen(config: regularizationPolicyResource, createScreen: () => PolicySetupScreen(config: regularizationPolicySetup))),
      GoRoute(path: '/app/shifts', builder: (context, state) => ResourceListScreen(config: shiftResource(), createScreen: () => PolicySetupScreen(config: shiftSetup))),
      GoRoute(path: '/app/holiday-calendars', builder: (context, state) => ResourceListScreen(config: holidayCalendarResource)),
      GoRoute(path: '/app/weekly-off-patterns', builder: (context, state) => ResourceListScreen(config: weeklyOffPatternResource)),
      GoRoute(path: '/app/work-calendars', builder: (context, state) => ResourceListScreen(config: workCalendarResource)),
      GoRoute(path: '/app/regularizations', builder: (context, state) => RequestListScreen(config: regularizationConfig, decisionCenter: const RegularizationDecisionCenterPanel())),
      GoRoute(path: '/app/overtime', builder: (context, state) => RequestListScreen(config: overtimeConfig)),
      GoRoute(path: '/app/team-attendance', builder: (context, state) => const TeamAttendanceScreen()),
      GoRoute(path: '/app/attendance-geofences', builder: (context, state) => const GeofencesScreen()),
      GoRoute(path: '/app/attendance-insights', builder: (context, state) => const AttendanceInsightsScreen()),
      GoRoute(path: '/app/rosters', builder: (context, state) => const RostersScreen()),
      GoRoute(path: '/app/rosters/board', builder: (context, state) => const ShiftBoardScreen()),
      GoRoute(path: '/app/rosters/grid', builder: (context, state) => const WorkforceRosterScreen()),
      GoRoute(path: '/app/schedule', builder: (context, state) => const WeeklyScheduleScreen()),
      GoRoute(path: '/app/shift-swaps', builder: (context, state) => const ShiftSwapsScreen()),
      GoRoute(path: '/app/roster-calendar', builder: (context, state) => const RosterCalendarScreen()),
      GoRoute(path: '/app/attendance-periods', builder: (context, state) => const AttendancePeriodsScreen()),
      GoRoute(path: '/app/policy-assignments', builder: (context, state) => const PolicyAssignmentsScreen()),
      GoRoute(path: '/app/policy-resolution', builder: (context, state) => const PolicyResolutionScreen()),
      GoRoute(path: '/app/leave-types', builder: (context, state) => ResourceListScreen(config: leaveTypeResource)),
      GoRoute(path: '/app/leave-policies', builder: (context, state) => ResourceListScreen(config: leavePolicyResource, createScreen: () => PolicySetupScreen(config: leavePolicySetup))),
      GoRoute(path: '/app/leave-combination-rules', builder: (context, state) => ResourceListScreen(config: leaveCombinationRuleResource)),
      GoRoute(path: '/app/leave-year-setting', builder: (context, state) => const LeaveYearSettingScreen()),
      GoRoute(path: '/app/statutory-leave-minimums', builder: (context, state) => ResourceListScreen(config: statutoryLeaveMinimumResource)),
      GoRoute(path: '/app/leave-balances', builder: (context, state) => const LeaveBalancesScreen()),
      GoRoute(path: '/app/payroll/pay-runs', builder: (context, state) => const PayRunsScreen()),
      GoRoute(path: '/app/payroll/salary-components', builder: (context, state) => ResourceListScreen(config: salaryComponentResource)),
      GoRoute(path: '/app/payroll/salary-structures', builder: (context, state) => ResourceListScreen(config: salaryStructureResource)),
      GoRoute(path: '/app/payroll/statutory-rates', builder: (context, state) => const StatutoryRatesScreen()),
      GoRoute(path: '/app/me/payslips', builder: (context, state) => const MyPayslipsScreen()),
      GoRoute(path: '/app/employees', builder: (context, state) => const EmployeesScreen()),
      GoRoute(path: '/app/onboarding', builder: (context, state) => const OnboardingCasesScreen()),
      GoRoute(path: '/app/setup', builder: (context, state) => const SetupScreen()),
      GoRoute(path: '/app/users', builder: (context, state) => const UsersScreen()),
      StatefulShellRoute.indexedStack(
        builder: (context, state, navigationShell) => AppShell(navigationShell: navigationShell),
        branches: [
          StatefulShellBranch(routes: [
            GoRoute(path: '/app/dashboard', builder: (context, state) => const DashboardScreen()),
            GoRoute(path: '/app/home', builder: (context, state) => const EmployeeHomeScreen()),
          ]),
          StatefulShellBranch(routes: [
            GoRoute(path: '/app/attendance', builder: (context, state) => const EmployeeThemeScope(child: AttendanceSelfScreen())),
          ]),
          StatefulShellBranch(routes: [
            GoRoute(path: '/app/leave-applications', builder: (context, state) => const EmployeeThemeScope(child: LeaveApplicationsScreen(decisionCenter: LeaveDecisionCenterPanel()))),
          ]),
          StatefulShellBranch(routes: [
            GoRoute(path: '/app/me', builder: (context, state) => const EmployeeThemeScope(child: ProfileScreen())),
          ]),
        ],
      ),
    ],
  );
});
