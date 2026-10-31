import 'dart:async';

import 'package:flutter/material.dart';
import 'package:google_fonts/google_fonts.dart';
import 'package:hrms_mobile/core/theme/app_theme.dart';

/// `AppTheme` builds its text theme with `google_fonts`, which tries to download Inter and fails
/// asynchronously in a test sandbox (the fallback font is used). Build the themes once here with
/// that failure absorbed so tests can use them.
Future<void> primeThemes() async {
  GoogleFonts.config.allowRuntimeFetching = false;
  await runZonedGuarded(() async {
    AppTheme.employee;
    AppTheme.light;
    AppTheme.dark;
    await Future<void>.delayed(const Duration(milliseconds: 200));
  }, (_, __) {});
}

/// Pumps [child] in the employee theme at a given logical size and text scale.
Widget employeeHarness(Widget child, {double textScale = 1.0, ThemeData? theme}) => MaterialApp(
      debugShowCheckedModeBanner: false,
      theme: theme ?? AppTheme.employee,
      home: MediaQuery(
        data: MediaQueryData(textScaler: TextScaler.linear(textScale)),
        child: Scaffold(body: child),
      ),
    );
