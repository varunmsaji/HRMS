import 'package:flutter/material.dart';
import 'package:flutter/services.dart' show SystemUiOverlayStyle;
import 'package:google_fonts/google_fonts.dart';

import 'app_colors.dart';
import 'employee_tokens.dart';

/// Corner radii from the Stitch "Staff Spectrum HRMS" design system (`ROUND_FOUR`
/// token set: `sm` 2px … `xl` 12px), applied to buttons/inputs/cards below.
class AppRadii {
  const AppRadii._();

  static const sm = 2.0;
  static const md = 6.0;
  static const lg = 8.0;
  static const xl = 12.0;
  static const full = 999.0;

  /// Modern, softer radii used by the shared widgets and the theme.
  static const input = 12.0;
  static const button = 12.0;
  static const card = 16.0;
}

/// Krewoxa brand colours from the landing page (`apps/web/src/components/landing`),
/// used for the navy hero surfaces on the auth screens and the dashboard header.
class AppBrand {
  const AppBrand._();

  static const navy = Color(0xFF102A43);
  static const navyDeep = Color(0xFF0B1E33);
  static const blue = Color(0xFF2563EB);
}

/// Builds the light/dark [ThemeData] from the Stitch "technobeala" design
/// system tokens — the same palette as `apps/web/src/app/globals.css` §9/10,
/// so the mobile app reads as the same product (see `AppStatusColors`'s own
/// doc comment). `colorScheme` values below are copied from the Stitch
/// project's resolved `namedColors`, not re-derived, so a future design pass
/// updates both here and on the Stitch project together rather than drifting.
class AppTheme {
  const AppTheme._();

  static const _lightScheme = ColorScheme(
    brightness: Brightness.light,
    primary: Color(0xFF004AC6),
    onPrimary: Color(0xFFFFFFFF),
    primaryContainer: Color(0xFF2563EB),
    onPrimaryContainer: Color(0xFFEEEFFF),
    secondary: Color(0xFF505F76),
    onSecondary: Color(0xFFFFFFFF),
    secondaryContainer: Color(0xFFD0E1FB),
    onSecondaryContainer: Color(0xFF54647A),
    tertiary: Color(0xFF0EA5E9),
    onTertiary: Color(0xFFFFFFFF),
    tertiaryContainer: Color(0xFFBC4800),
    onTertiaryContainer: Color(0xFFFFEDE6),
    error: Color(0xFFEF4444),
    onError: Color(0xFFFFFFFF),
    errorContainer: Color(0xFFFFDAD6),
    onErrorContainer: Color(0xFF93000A),
    surface: Color(0xFFFAF8FF),
    onSurface: Color(0xFF191B23),
    onSurfaceVariant: Color(0xFF434655),
    outline: Color(0xFFCBD5E1),
    outlineVariant: Color(0xFFC3C6D7),
    inverseSurface: Color(0xFF2E3039),
    onInverseSurface: Color(0xFFF0F0FB),
    inversePrimary: Color(0xFFB4C5FF),
    surfaceTint: Color(0xFF0053DB),
    surfaceContainerLowest: Color(0xFFFFFFFF),
    surfaceContainerLow: Color(0xFFF3F3FE),
    surfaceContainer: Color(0xFFEDEDF9),
    surfaceContainerHigh: Color(0xFFE7E7F3),
    surfaceContainerHighest: Color(0xFFE1E2ED),
  );

  static const _darkScheme = ColorScheme(
    brightness: Brightness.dark,
    primary: Color(0xFFB4C5FF),
    onPrimary: Color(0xFF00174B),
    primaryContainer: Color(0xFF003EA8),
    onPrimaryContainer: Color(0xFFDBE1FF),
    secondary: Color(0xFFB7C8E1),
    onSecondary: Color(0xFF0B1C30),
    secondaryContainer: Color(0xFF38485D),
    onSecondaryContainer: Color(0xFFD3E4FE),
    tertiary: Color(0xFFFFB596),
    onTertiary: Color(0xFF360F00),
    tertiaryContainer: Color(0xFF7D2D00),
    onTertiaryContainer: Color(0xFFFFDBCD),
    error: Color(0xFFF87171),
    onError: Color(0xFF450A0A),
    errorContainer: Color(0xFF93000A),
    onErrorContainer: Color(0xFFFFDAD6),
    surface: Color(0xFF191B23),
    onSurface: Color(0xFFE1E2ED),
    onSurfaceVariant: Color(0xFFC3C6D7),
    outline: Color(0xFF8D909F),
    outlineVariant: Color(0xFF434655),
    inverseSurface: Color(0xFFE1E2ED),
    onInverseSurface: Color(0xFF2E3039),
    inversePrimary: Color(0xFF004AC6),
    surfaceTint: Color(0xFFB4C5FF),
    surfaceContainerLowest: Color(0xFF11131A),
    surfaceContainerLow: Color(0xFF191B23),
    surfaceContainer: Color(0xFF1D1F28),
    surfaceContainerHigh: Color(0xFF282A33),
    surfaceContainerHighest: Color(0xFF33353E),
  );

  static TextTheme _textTheme(ColorScheme scheme) {
    final base = GoogleFonts.interTextTheme();
    TextStyle style(double size, double height, FontWeight weight, double tracking) =>
        base.bodyMedium!.copyWith(
          fontSize: size,
          height: height / size,
          fontWeight: weight,
          letterSpacing: tracking * size,
          color: scheme.onSurface,
        );
    return TextTheme(
      headlineLarge: style(24, 32, FontWeight.w600, -0.02),
      headlineMedium: style(20, 28, FontWeight.w600, -0.015),
      headlineSmall: style(16, 24, FontWeight.w600, -0.01),
      bodyLarge: style(14, 20, FontWeight.w400, 0),
      bodyMedium: style(13, 18, FontWeight.w400, 0),
      bodySmall: style(12, 16, FontWeight.w400, 0),
      labelMedium: style(12, 16, FontWeight.w500, 0.01),
      labelSmall: style(11, 14, FontWeight.w600, 0.02),
    );
  }

  static ThemeData _build(ColorScheme scheme) {
    final textTheme = _textTheme(scheme);
    final dark = scheme.brightness == Brightness.dark;
    final inputRadius = BorderRadius.circular(AppRadii.input);
    final softBorder = scheme.outlineVariant.withValues(alpha: dark ? 0.7 : 0.9);
    OutlineInputBorder border(Color color, [double width = 1]) =>
        OutlineInputBorder(borderRadius: inputRadius, borderSide: BorderSide(color: color, width: width));
    final buttonShape = RoundedRectangleBorder(borderRadius: BorderRadius.circular(AppRadii.button));
    final buttonText = textTheme.bodyLarge?.copyWith(fontWeight: FontWeight.w600, letterSpacing: 0.1);
    return ThemeData(
      useMaterial3: true,
      colorScheme: scheme,
      scaffoldBackgroundColor: scheme.surfaceContainerLow,
      textTheme: textTheme,
      splashFactory: InkSparkle.splashFactory,
      extensions: [dark ? AppStatusColors.dark : AppStatusColors.light],
      appBarTheme: AppBarTheme(
        backgroundColor: scheme.surfaceContainerLow,
        foregroundColor: scheme.onSurface,
        elevation: 0,
        scrolledUnderElevation: 0,
        surfaceTintColor: Colors.transparent,
        centerTitle: false,
        titleSpacing: 16,
        titleTextStyle: textTheme.headlineMedium?.copyWith(fontWeight: FontWeight.w700),
      ),
      cardTheme: CardThemeData(
        color: scheme.surfaceContainerLowest,
        surfaceTintColor: Colors.transparent,
        elevation: 0,
        margin: EdgeInsets.zero,
        shape: RoundedRectangleBorder(
          borderRadius: BorderRadius.circular(AppRadii.card),
          side: BorderSide(color: softBorder.withValues(alpha: 0.6)),
        ),
      ),
      listTileTheme: ListTileThemeData(
        iconColor: scheme.onSurfaceVariant,
        contentPadding: const EdgeInsets.symmetric(horizontal: 16, vertical: 2),
        titleTextStyle: textTheme.bodyLarge?.copyWith(fontWeight: FontWeight.w600),
        subtitleTextStyle: textTheme.bodyMedium?.copyWith(color: scheme.onSurfaceVariant),
        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(AppRadii.lg)),
      ),
      inputDecorationTheme: InputDecorationTheme(
        filled: true,
        fillColor: dark ? scheme.surfaceContainer : scheme.surfaceContainerLowest,
        contentPadding: const EdgeInsets.symmetric(horizontal: 16, vertical: 14),
        border: border(softBorder),
        enabledBorder: border(softBorder),
        focusedBorder: border(scheme.primary, 1.75),
        errorBorder: border(scheme.error),
        focusedErrorBorder: border(scheme.error, 1.75),
        disabledBorder: border(softBorder.withValues(alpha: 0.5)),
        labelStyle: textTheme.bodyLarge?.copyWith(color: scheme.onSurfaceVariant),
        hintStyle: textTheme.bodyLarge?.copyWith(color: scheme.onSurfaceVariant.withValues(alpha: 0.7)),
        prefixIconColor: scheme.onSurfaceVariant,
        suffixIconColor: scheme.onSurfaceVariant,
      ),
      elevatedButtonTheme: ElevatedButtonThemeData(
        style: ElevatedButton.styleFrom(
          backgroundColor: scheme.primary,
          foregroundColor: scheme.onPrimary,
          disabledBackgroundColor: scheme.primary.withValues(alpha: 0.4),
          elevation: 0,
          minimumSize: const Size.fromHeight(50),
          padding: const EdgeInsets.symmetric(horizontal: 20, vertical: 14),
          shape: buttonShape,
          textStyle: buttonText,
        ),
      ),
      filledButtonTheme: FilledButtonThemeData(
        style: FilledButton.styleFrom(
          minimumSize: const Size(64, 48),
          padding: const EdgeInsets.symmetric(horizontal: 20, vertical: 12),
          shape: buttonShape,
          textStyle: buttonText,
        ),
      ),
      outlinedButtonTheme: OutlinedButtonThemeData(
        style: OutlinedButton.styleFrom(
          minimumSize: const Size(64, 48),
          padding: const EdgeInsets.symmetric(horizontal: 20, vertical: 12),
          side: BorderSide(color: scheme.outline),
          shape: buttonShape,
          textStyle: buttonText,
        ),
      ),
      textButtonTheme: TextButtonThemeData(
        style: TextButton.styleFrom(
          foregroundColor: scheme.primary,
          shape: buttonShape,
          textStyle: buttonText,
        ),
      ),
      floatingActionButtonTheme: FloatingActionButtonThemeData(
        elevation: 3,
        highlightElevation: 4,
        backgroundColor: scheme.primary,
        foregroundColor: scheme.onPrimary,
        extendedTextStyle: buttonText,
        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(AppRadii.card)),
      ),
      navigationBarTheme: NavigationBarThemeData(
        height: 68,
        elevation: 0,
        backgroundColor: scheme.surfaceContainerLowest,
        surfaceTintColor: Colors.transparent,
        indicatorColor: scheme.primary.withValues(alpha: dark ? 0.22 : 0.10),
        indicatorShape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(AppRadii.full)),
        labelTextStyle: WidgetStateProperty.resolveWith((states) {
          final selected = states.contains(WidgetState.selected);
          return textTheme.labelMedium?.copyWith(
            fontSize: 11.5,
            fontWeight: selected ? FontWeight.w700 : FontWeight.w500,
            color: selected ? scheme.primary : scheme.onSurfaceVariant,
          );
        }),
        iconTheme: WidgetStateProperty.resolveWith((states) {
          final selected = states.contains(WidgetState.selected);
          return IconThemeData(size: 24, color: selected ? scheme.primary : scheme.onSurfaceVariant);
        }),
      ),
      chipTheme: ChipThemeData(
        backgroundColor: scheme.surfaceContainerLowest,
        selectedColor: scheme.primary.withValues(alpha: 0.12),
        side: BorderSide(color: softBorder),
        shape: const StadiumBorder(),
        labelStyle: textTheme.labelMedium,
        showCheckmark: false,
      ),
      dialogTheme: DialogThemeData(
        backgroundColor: scheme.surfaceContainerLowest,
        surfaceTintColor: Colors.transparent,
        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(24)),
        titleTextStyle: textTheme.headlineMedium?.copyWith(fontWeight: FontWeight.w700),
      ),
      bottomSheetTheme: BottomSheetThemeData(
        backgroundColor: scheme.surfaceContainerLowest,
        surfaceTintColor: Colors.transparent,
        showDragHandle: true,
        shape: const RoundedRectangleBorder(borderRadius: BorderRadius.vertical(top: Radius.circular(28))),
      ),
      snackBarTheme: SnackBarThemeData(
        behavior: SnackBarBehavior.floating,
        backgroundColor: scheme.inverseSurface,
        contentTextStyle: textTheme.bodyLarge?.copyWith(color: scheme.onInverseSurface),
        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(AppRadii.lg)),
      ),
      tabBarTheme: TabBarThemeData(
        dividerColor: Colors.transparent,
        labelStyle: textTheme.bodyLarge?.copyWith(fontWeight: FontWeight.w700),
        unselectedLabelStyle: textTheme.bodyLarge,
        indicatorSize: TabBarIndicatorSize.label,
      ),
      progressIndicatorTheme: ProgressIndicatorThemeData(
        color: scheme.primary,
        linearTrackColor: scheme.surfaceContainerHigh,
        linearMinHeight: 6,
        borderRadius: BorderRadius.circular(AppRadii.full),
      ),
      dividerTheme: DividerThemeData(color: scheme.outlineVariant.withValues(alpha: 0.6), space: 1, thickness: 1),
      pageTransitionsTheme: const PageTransitionsTheme(builders: {
        TargetPlatform.android: FadeForwardsPageTransitionsBuilder(),
        TargetPlatform.iOS: CupertinoPageTransitionsBuilder(),
      }),
    );
  }


  // ---------------------------------------------------------------------------------------
  // Employee experience (docs/design/employee-mobile, design system §8).
  //
  // Layered on top of the unchanged administrator build: `_build(_lightScheme)` and
  // `_build(_darkScheme)` are not touched, so `AppTheme.light` / `AppTheme.dark` are identical to
  // before (proved by test/theme_isolation_test.dart). The employee theme starts from the same
  // builder with an employee scheme, then replaces only the component themes below.
  // ---------------------------------------------------------------------------------------

  static final _employeeScheme = _lightScheme.copyWith(
    surface: const Color(0xFFFFFFFF),
    onSurface: EmployeeTokens.standard.ink,
    onSurfaceVariant: EmployeeTokens.standard.inkSecondary,
    surfaceContainerLowest: EmployeeTokens.standard.sheet,
    surfaceContainerLow: EmployeeTokens.standard.canvas,
    surfaceContainer: EmployeeTokens.standard.inset,
    surfaceContainerHigh: const Color(0xFFECEFF3),
    outline: EmployeeTokens.standard.lineStrong,
    outlineVariant: EmployeeTokens.standard.line,
    error: EmployeeTokens.standard.dangerText,
    errorContainer: const Color(0xFFFEE2E2),
    onErrorContainer: const Color(0xFF7F1D1D),
    // Read only by the company read-only banner: recolours it without touching its code.
    tertiaryContainer: const Color(0xFFFFFBEB),
    onTertiaryContainer: EmployeeTokens.standard.ink,
  );

  static TextTheme _employeeTextTheme(ColorScheme scheme) {
    final base = GoogleFonts.interTextTheme();
    TextStyle style(double size, double height, FontWeight weight, double tracking, [Color? color]) => base.bodyMedium!.copyWith(
          fontSize: size,
          height: height / size,
          fontWeight: weight,
          letterSpacing: tracking,
          color: color ?? scheme.onSurface,
          fontFeatures: const [FontFeature.tabularFigures()],
        );
    return TextTheme(
      headlineLarge: style(28, 34, FontWeight.w600, -0.2),
      headlineMedium: style(22, 28, FontWeight.w600, -0.2),
      headlineSmall: style(18, 24, FontWeight.w600, -0.2),
      titleLarge: style(18, 24, FontWeight.w600, -0.2),
      titleMedium: style(16, 22, FontWeight.w600, 0),
      titleSmall: style(14, 20, FontWeight.w600, 0),
      bodyLarge: style(16, 22, FontWeight.w400, 0),
      bodyMedium: style(14, 20, FontWeight.w400, 0),
      bodySmall: style(13, 18, FontWeight.w400, 0, scheme.onSurfaceVariant),
      labelLarge: style(14, 20, FontWeight.w600, 0),
      labelMedium: style(13, 18, FontWeight.w600, 0.4),
      labelSmall: style(12, 16, FontWeight.w500, 0),
    );
  }

  static ThemeData _employeeTheme() {
    const t = EmployeeTokens.standard;
    final scheme = _employeeScheme;
    final base = _build(scheme);
    final text = _employeeTextTheme(scheme);
    final control = BorderRadius.circular(EmployeeTokens.radiusControl);
    OutlineInputBorder border(Color color, [double width = 1]) =>
        OutlineInputBorder(borderRadius: control, borderSide: BorderSide(color: color, width: width));
    final buttonShape = RoundedRectangleBorder(borderRadius: control);
    final buttonText = text.bodyLarge!.copyWith(fontWeight: FontWeight.w600);
    return base.copyWith(
      scaffoldBackgroundColor: t.canvas,
      textTheme: text,
      primaryTextTheme: text,
      extensions: [AppStatusColors.light, t],
      // A dark navy bar with light text and status-bar icons, so the top of every employee screen
      // reads as a bar instead of blending into the pale page.
      appBarTheme: AppBarTheme(
        backgroundColor: const Color(0xFF0A1F5C),
        foregroundColor: Colors.white,
        elevation: 0,
        scrolledUnderElevation: 0,
        surfaceTintColor: Colors.transparent,
        systemOverlayStyle: SystemUiOverlayStyle.light,
        centerTitle: false,
        titleSpacing: 16,
        titleTextStyle: text.headlineSmall?.copyWith(color: Colors.white),
      ),
      cardTheme: CardThemeData(
        color: t.sheet,
        surfaceTintColor: Colors.transparent,
        elevation: 0,
        margin: EdgeInsets.zero,
        shape: RoundedRectangleBorder(
          borderRadius: BorderRadius.circular(EmployeeTokens.radiusSurface),
          side: BorderSide(color: t.line),
        ),
      ),
      listTileTheme: ListTileThemeData(
        iconColor: t.inkSecondary,
        contentPadding: const EdgeInsets.symmetric(horizontal: 16, vertical: 4),
        minVerticalPadding: 8,
        titleTextStyle: text.bodyLarge?.copyWith(fontWeight: FontWeight.w600),
        subtitleTextStyle: text.bodySmall,
      ),
      inputDecorationTheme: InputDecorationTheme(
        filled: true,
        fillColor: t.sheet,
        contentPadding: const EdgeInsets.symmetric(horizontal: 16, vertical: 14),
        border: border(t.lineStrong),
        enabledBorder: border(t.lineStrong),
        focusedBorder: border(t.action, 1.5),
        errorBorder: border(t.danger, 1.5),
        focusedErrorBorder: border(t.danger, 1.5),
        disabledBorder: border(t.line),
        labelStyle: text.bodyLarge?.copyWith(color: t.inkSecondary),
        hintStyle: text.bodyLarge?.copyWith(color: t.inkTertiary),
        errorStyle: text.bodySmall?.copyWith(color: t.dangerText),
      ),
      elevatedButtonTheme: ElevatedButtonThemeData(
        style: ElevatedButton.styleFrom(
          backgroundColor: t.action,
          foregroundColor: Colors.white,
          disabledBackgroundColor: t.action.withValues(alpha: 0.4),
          elevation: 0,
          minimumSize: const Size.fromHeight(EmployeeTokens.minTarget),
          shape: buttonShape,
          textStyle: buttonText,
        ),
      ),
      filledButtonTheme: FilledButtonThemeData(
        style: FilledButton.styleFrom(
          backgroundColor: t.action,
          foregroundColor: Colors.white,
          minimumSize: const Size(64, EmployeeTokens.minTarget),
          padding: const EdgeInsets.symmetric(horizontal: 20, vertical: 12),
          shape: buttonShape,
          textStyle: buttonText,
        ),
      ),
      outlinedButtonTheme: OutlinedButtonThemeData(
        style: OutlinedButton.styleFrom(
          foregroundColor: t.ink,
          minimumSize: const Size(64, EmployeeTokens.minTarget),
          padding: const EdgeInsets.symmetric(horizontal: 20, vertical: 12),
          side: BorderSide(color: t.lineStrong),
          shape: buttonShape,
          textStyle: buttonText,
        ),
      ),
      textButtonTheme: TextButtonThemeData(
        style: TextButton.styleFrom(
          foregroundColor: t.action,
          minimumSize: const Size(64, EmployeeTokens.minTarget),
          shape: buttonShape,
          textStyle: buttonText,
        ),
      ),
      navigationBarTheme: NavigationBarThemeData(
        height: 64,
        elevation: 0,
        backgroundColor: t.sheet,
        surfaceTintColor: Colors.transparent,
        indicatorColor: t.actionSubtle,
        indicatorShape: const StadiumBorder(),
        labelTextStyle: WidgetStateProperty.resolveWith((states) {
          final selected = states.contains(WidgetState.selected);
          return text.labelSmall?.copyWith(
            fontWeight: selected ? FontWeight.w600 : FontWeight.w500,
            color: selected ? t.action : t.inkSecondary,
          );
        }),
        iconTheme: WidgetStateProperty.resolveWith((states) {
          final selected = states.contains(WidgetState.selected);
          return IconThemeData(size: 24, color: selected ? t.action : t.inkSecondary);
        }),
      ),
      chipTheme: ChipThemeData(
        backgroundColor: t.sheet,
        selectedColor: t.actionSubtle,
        side: BorderSide(color: t.lineStrong),
        shape: const StadiumBorder(),
        labelStyle: text.labelSmall?.copyWith(fontWeight: FontWeight.w500),
        showCheckmark: false,
      ),
      dialogTheme: DialogThemeData(
        backgroundColor: t.sheet,
        surfaceTintColor: Colors.transparent,
        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(EmployeeTokens.radiusSheet)),
        titleTextStyle: text.headlineSmall,
        contentTextStyle: text.bodyMedium,
      ),
      bottomSheetTheme: BottomSheetThemeData(
        backgroundColor: t.sheet,
        surfaceTintColor: Colors.transparent,
        showDragHandle: true,
        shape: const RoundedRectangleBorder(borderRadius: BorderRadius.vertical(top: Radius.circular(EmployeeTokens.radiusSheet))),
      ),
      tabBarTheme: TabBarThemeData(
        dividerColor: Colors.transparent,
        labelColor: t.action,
        unselectedLabelColor: t.inkSecondary,
        indicatorColor: t.action,
        labelStyle: text.labelMedium?.copyWith(letterSpacing: 0),
        unselectedLabelStyle: text.labelMedium?.copyWith(letterSpacing: 0, fontWeight: FontWeight.w500),
        indicatorSize: TabBarIndicatorSize.label,
      ),
      progressIndicatorTheme: ProgressIndicatorThemeData(
        color: t.action,
        linearTrackColor: t.line,
        linearMinHeight: 4,
        borderRadius: BorderRadius.circular(EmployeeTokens.radiusPill),
      ),
      dividerTheme: DividerThemeData(color: t.line, space: 1, thickness: 1),
    );
  }

  /// The employee-surface theme (light only). Built once; `usesEmployeeSurface` selects it.
  static final ThemeData employee = _employeeTheme();

  // Built once (the values are identical to the former per-call getters; `theme_isolation_test`
  // compares them with a pre-change baseline).
  static final ThemeData light = _build(_lightScheme);
  static final ThemeData dark = _build(_darkScheme);
}
