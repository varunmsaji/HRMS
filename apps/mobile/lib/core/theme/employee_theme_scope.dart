import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../features/auth/state/auth_controller.dart';
import '../auth/surface.dart';
import 'app_theme.dart';
import 'employee_tokens.dart';

/// Gives the three self-service tabs (Attendance, Leave, Profile) the employee design tokens when
/// the signed-in user is an administrator who also has an employee record.
///
/// Employee-surface sessions already have the employee theme app-wide, and sessions without an
/// employee record have nothing to show here, so for them this is a no-op. Everything outside the
/// three wrapped routes keeps the unchanged administrator theme. Dialogs and sheets opened from
/// inside capture this theme; screens pushed with `Navigator.push` sit above it and keep the
/// administrator theme (a documented limit of the per-route scope).
class EmployeeThemeScope extends ConsumerWidget {
  const EmployeeThemeScope({super.key, required this.child});

  final Widget child;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final scoped = ref.watch(authControllerProvider.select((s) {
      final user = s.user;
      return user != null && user.employeeId != null && !usesEmployeeSurface(user);
    }));
    return scoped ? Theme(data: AppTheme.employee, child: child) : child;
  }
}

/// Pushes a screen from one that may be inside an [EmployeeThemeScope], keeping that screen's
/// theme. `Navigator.push` routes sit above the scope, so without this an administrator who opens
/// a leave application, a day or a form from their own Attendance/Leave/Profile tab would drop
/// back to the administrator theme mid-flow. A push from an administrator screen (no employee
/// tokens) is left exactly as it was, so the global administrator theme is untouched.
Future<T?> pushKeepingTheme<T>(BuildContext context, WidgetBuilder builder) {
  final theme = Theme.of(context);
  final scoped = theme.extension<EmployeeTokens>() != null;
  return Navigator.of(context).push<T>(MaterialPageRoute<T>(builder: (ctx) => scoped ? Theme(data: theme, child: builder(ctx)) : builder(ctx)));
}
