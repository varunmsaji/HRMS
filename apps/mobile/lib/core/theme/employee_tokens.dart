import 'package:flutter/material.dart';

import 'app_colors.dart';

/// Design tokens of the employee experience (docs/design/employee-mobile, design system §2-§4).
///
/// Present on the theme only for employee-surface sessions (`AppTheme.employee`). Components read
/// them through [EmployeeTokens.of], which falls back to values derived from the active
/// [ColorScheme] so the same widgets also render correctly under the administrator theme (light
/// or dark) when a screen is shared.
@immutable
class EmployeeTokens extends ThemeExtension<EmployeeTokens> {
  const EmployeeTokens({
    required this.ink,
    required this.inkSecondary,
    required this.inkTertiary,
    required this.action,
    required this.actionPressed,
    required this.actionSubtle,
    required this.canvas,
    required this.sheet,
    required this.inset,
    required this.line,
    required this.lineStrong,
    required this.danger,
    required this.successText,
    required this.warningText,
    required this.dangerText,
    required this.infoText,
    required this.onLeaveText,
    required this.holidayText,
    required this.wfhText,
  });

  final Color ink;
  final Color inkSecondary;

  /// Icons and non-essential hints only: 3.66:1 on white, below AA for text.
  final Color inkTertiary;
  final Color action;
  final Color actionPressed;
  final Color actionSubtle;
  final Color canvas;
  final Color sheet;
  final Color inset;
  final Color line;
  final Color lineStrong;

  /// Danger as a fill/glyph. Text uses [dangerText].
  final Color danger;

  /// Darker status colours for text on the matching subtle fill (the raw status colours fail AA).
  final Color successText;
  final Color warningText;
  final Color dangerText;
  final Color infoText;
  final Color onLeaveText;
  final Color holidayText;
  final Color wfhText;

  static const radiusControl = 8.0;
  static const radiusSurface = 10.0;
  static const radiusSheet = 16.0;
  static const radiusPill = 999.0;
  static const minTarget = 48.0;

  static const standard = EmployeeTokens(
    ink: Color(0xFF102A43),
    inkSecondary: Color(0xFF52606D),
    inkTertiary: Color(0xFF7B8794),
    action: Color(0xFF004AC6),
    actionPressed: Color(0xFF003A9E),
    actionSubtle: Color(0xFFE8F0FE),
    canvas: Color(0xFFF4F6F8),
    sheet: Color(0xFFFFFFFF),
    inset: Color(0xFFF7F8FA),
    line: Color(0xFFE4E7EB),
    lineStrong: Color(0xFFCBD2D9),
    danger: Color(0xFFEF4444),
    successText: Color(0xFF15803D),
    warningText: Color(0xFFB45309),
    dangerText: Color(0xFFB91C1C),
    infoText: Color(0xFF0369A1),
    onLeaveText: Color(0xFF6D28D9),
    holidayText: Color(0xFF475569),
    wfhText: Color(0xFF0F766E),
  );

  /// The tokens in effect: the theme's extension, else derived from the active scheme.
  static EmployeeTokens of(BuildContext context) {
    final theme = Theme.of(context);
    final ext = theme.extension<EmployeeTokens>();
    if (ext != null) return ext;
    final s = theme.colorScheme;
    final status = theme.extension<AppStatusColors>() ?? AppStatusColors.light;
    return EmployeeTokens(
      ink: s.onSurface,
      inkSecondary: s.onSurfaceVariant,
      inkTertiary: s.onSurfaceVariant.withValues(alpha: 0.7),
      action: s.primary,
      actionPressed: s.primary,
      actionSubtle: s.primary.withValues(alpha: 0.10),
      canvas: s.surfaceContainerLow,
      sheet: s.surfaceContainerLowest,
      inset: s.surfaceContainer,
      line: s.outlineVariant,
      lineStrong: s.outline,
      danger: status.danger,
      successText: status.success,
      warningText: status.warning,
      dangerText: s.error,
      infoText: status.info,
      onLeaveText: status.onLeave,
      holidayText: status.holiday,
      wfhText: status.wfh,
    );
  }

  @override
  EmployeeTokens copyWith({Color? ink, Color? canvas, Color? sheet}) => EmployeeTokens(
        ink: ink ?? this.ink,
        inkSecondary: inkSecondary,
        inkTertiary: inkTertiary,
        action: action,
        actionPressed: actionPressed,
        actionSubtle: actionSubtle,
        canvas: canvas ?? this.canvas,
        sheet: sheet ?? this.sheet,
        inset: inset,
        line: line,
        lineStrong: lineStrong,
        danger: danger,
        successText: successText,
        warningText: warningText,
        dangerText: dangerText,
        infoText: infoText,
        onLeaveText: onLeaveText,
        holidayText: holidayText,
        wfhText: wfhText,
      );

  /// The employee theme is never animated between two token sets.
  @override
  EmployeeTokens lerp(ThemeExtension<EmployeeTokens>? other, double t) => other is EmployeeTokens && t >= 0.5 ? other : this;
}
