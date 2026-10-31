import 'package:flutter/material.dart';

import '../auth/auth_types.dart';
import '../auth/surface.dart';
import 'app_theme.dart';

/// The `MaterialApp` theme arguments for a session (docs design system §8.2).
///
/// An administrator, a user without an employee record, and every pre-authentication screen get
/// exactly the arguments the app has always used: `AppTheme.light`, `AppTheme.dark` and the
/// default `ThemeMode.system`. Only an employee-surface session gets the light employee theme.
({ThemeData theme, ThemeData darkTheme, ThemeMode themeMode}) themeSelectionFor(UserProfile? user) {
  if (usesEmployeeSurface(user)) {
    return (theme: AppTheme.employee, darkTheme: AppTheme.dark, themeMode: ThemeMode.light);
  }
  return (theme: AppTheme.light, darkTheme: AppTheme.dark, themeMode: ThemeMode.system);
}
