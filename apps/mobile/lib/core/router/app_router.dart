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
import '../../features/attendance/presentation/policy_assignments_screen.dart';
import '../../features/attendance/presentation/policy_resolution_screen.dart';
import '../../features/attendance/presentation/roster_calendar_screen.dart';
import '../../features/attendance/presentation/rosters_screen.dart';
import '../../features/auth/state/auth_controller.dart';
import '../../features/auth/state/auth_state.dart';
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

final appRouterProvider = Provider<GoRouter>((ref) {
  return GoRouter(
    initialLocation: '/splash',
    refreshListenable: ref.watch(_authRefreshProvider),
    redirect: (context, state) {
      final auth = ref.read(authControllerProvider);
      final location = state.matchedLocation;

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
      // The Home tab is hidden for them (see `showHomeTab`), so don't strand an employee on the
      // dashboard's "No access" page if something navigates there.
      if (location == '/app/dashboard' && !showHomeTab(auth.user)) return landingPathFor(auth.user);
      return null;
    },
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
      GoRoute(path: '/app/more', builder: (context, state) => const SettingsHubScreen()),
      GoRoute(path: '/app/company', builder: (context, state) => const CompanyProfileScreen()),
      GoRoute(path: '/app/branches', builder: (context, state) => ResourceListScreen(config: branchResource())),
      GoRoute(path: '/app/departments', builder: (context, state) => ResourceListScreen(config: departmentResource)),
      GoRoute(path: '/app/designations', builder: (context, state) => ResourceListScreen(config: designationResource)),
      GoRoute(path: '/app/grades', builder: (context, state) => ResourceListScreen(config: gradeResource)),
      GoRoute(path: '/app/legal-entities', builder: (context, state) => ResourceListScreen(config: legalEntityResource)),
      GoRoute(path: '/app/attendance-policies', builder: (context, state) => ResourceListScreen(config: attendancePolicyResource)),
      GoRoute(path: '/app/overtime-policies', builder: (context, state) => ResourceListScreen(config: overtimePolicyResource)),
      GoRoute(path: '/app/regularization-policies', builder: (context, state) => ResourceListScreen(config: regularizationPolicyResource)),
      GoRoute(path: '/app/shifts', builder: (context, state) => ResourceListScreen(config: shiftResource())),
      GoRoute(path: '/app/holiday-calendars', builder: (context, state) => ResourceListScreen(config: holidayCalendarResource)),
      GoRoute(path: '/app/weekly-off-patterns', builder: (context, state) => ResourceListScreen(config: weeklyOffPatternResource)),
      GoRoute(path: '/app/work-calendars', builder: (context, state) => ResourceListScreen(config: workCalendarResource)),
      GoRoute(path: '/app/regularizations', builder: (context, state) => RequestListScreen(config: regularizationConfig)),
      GoRoute(path: '/app/overtime', builder: (context, state) => RequestListScreen(config: overtimeConfig)),
      GoRoute(path: '/app/team-attendance', builder: (context, state) => const TeamAttendanceScreen()),
      GoRoute(path: '/app/attendance-insights', builder: (context, state) => const AttendanceInsightsScreen()),
      GoRoute(path: '/app/rosters', builder: (context, state) => const RostersScreen()),
      GoRoute(path: '/app/roster-calendar', builder: (context, state) => const RosterCalendarScreen()),
      GoRoute(path: '/app/attendance-periods', builder: (context, state) => const AttendancePeriodsScreen()),
      GoRoute(path: '/app/policy-assignments', builder: (context, state) => const PolicyAssignmentsScreen()),
      GoRoute(path: '/app/policy-resolution', builder: (context, state) => const PolicyResolutionScreen()),
      GoRoute(path: '/app/leave-types', builder: (context, state) => ResourceListScreen(config: leaveTypeResource)),
      GoRoute(path: '/app/leave-policies', builder: (context, state) => ResourceListScreen(config: leavePolicyResource)),
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
          ]),
          StatefulShellBranch(routes: [
            GoRoute(path: '/app/attendance', builder: (context, state) => const AttendanceSelfScreen()),
          ]),
          StatefulShellBranch(routes: [
            GoRoute(path: '/app/leave-applications', builder: (context, state) => const LeaveApplicationsScreen()),
          ]),
          StatefulShellBranch(routes: [
            GoRoute(path: '/app/me', builder: (context, state) => const ProfileScreen()),
          ]),
        ],
      ),
    ],
  );
});
