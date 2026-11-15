import '../../../core/auth/auth_types.dart';
import '../../../core/auth/permissions.dart';
import '../../../core/auth/token_storage.dart';

enum AuthStatus { loading, authenticated, unauthenticated }

/// Mirrors `apps/web/src/lib/auth/auth-context.tsx`'s `AuthState`.
class AuthState {
  const AuthState({required this.status, this.session, this.user, this.sessionExpired = false, this.expiredUserId});

  final AuthStatus status;
  final StoredSession? session;
  final UserProfile? user;

  /// Signed out because the session ran out (refresh failed), not because the user chose to.
  /// The login screen then says so and returns the same user to where they were (MOB-UX-031).
  final bool sessionExpired;

  /// Who was signed in when the session expired, so only that person is sent back to their screen.
  final String? expiredUserId;

  static const initial = AuthState(status: AuthStatus.loading);
}

/// Mirrors `apps/web/src/lib/auth/landing.ts::landingPathFor` — where to send
/// a user right after login/registration/invite-acceptance. A
/// `COMPANY_ADMIN`/`HR_ADMIN`-shaped user holds `DASHBOARD.COMPANY.VIEW` and
/// goes to the company dashboard; an `EMPLOYEE`/`REPORTING_MANAGER`-shaped
/// user goes to the employee Home (the workday) instead, when they have an employee record.
String landingPathFor(UserProfile? user) {
  if (user != null && user.permissions.contains(dashboardCompanyView)) return '/app/dashboard';
  if (user?.employeeId != null) return '/app/home';
  return '/app/dashboard';
}
