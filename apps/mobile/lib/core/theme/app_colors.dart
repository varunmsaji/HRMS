import 'package:flutter/material.dart';

/// HRMS status-state colors that don't map onto Flutter's [ColorScheme]
/// (success/warning/on-leave/holiday/half-day/wfh, each with a `subtle`
/// background pair). Mirrors the `--color-*` custom properties in
/// `apps/web/src/app/globals.css` §9 (light) / §10 (dark) — the Stitch
/// "Staff Spectrum HRMS" (technobeala) design system — so the mobile app
/// reads as the same product, not a reskin.
@immutable
class AppStatusColors extends ThemeExtension<AppStatusColors> {
  const AppStatusColors({
    required this.success,
    required this.successSubtle,
    required this.warning,
    required this.warningSubtle,
    required this.danger,
    required this.dangerSubtle,
    required this.info,
    required this.infoSubtle,
    required this.onLeave,
    required this.onLeaveSubtle,
    required this.holiday,
    required this.holidaySubtle,
    required this.halfDay,
    required this.halfDaySubtle,
    required this.wfh,
    required this.wfhSubtle,
  });

  final Color success;
  final Color successSubtle;
  final Color warning;
  final Color warningSubtle;
  final Color danger;
  final Color dangerSubtle;
  final Color info;
  final Color infoSubtle;
  final Color onLeave;
  final Color onLeaveSubtle;
  final Color holiday;
  final Color holidaySubtle;
  final Color halfDay;
  final Color halfDaySubtle;
  final Color wfh;
  final Color wfhSubtle;

  static const light = AppStatusColors(
    success: Color(0xFF16A34A),
    successSubtle: Color(0xFFF0FDF4),
    warning: Color(0xFFF59E0B),
    warningSubtle: Color(0xFFFFFBEB),
    danger: Color(0xFFEF4444),
    dangerSubtle: Color(0xFFFEE2E2),
    info: Color(0xFF0EA5E9),
    infoSubtle: Color(0xFFE0F2FE),
    onLeave: Color(0xFF8B5CF6),
    onLeaveSubtle: Color(0xFFF5F3FF),
    holiday: Color(0xFF64748B),
    holidaySubtle: Color(0xFFF1F5F9),
    halfDay: Color(0xFFF59E0B),
    halfDaySubtle: Color(0xFFFFFBEB),
    wfh: Color(0xFF0D9488),
    wfhSubtle: Color(0xFFF0FDFA),
  );

  static const dark = AppStatusColors(
    success: Color(0xFF4ADE80),
    successSubtle: Color(0xFF052E16),
    warning: Color(0xFFFBBF24),
    warningSubtle: Color(0xFF451A03),
    danger: Color(0xFFF87171),
    dangerSubtle: Color(0xFF450A0A),
    info: Color(0xFF38BDF8),
    infoSubtle: Color(0xFF0C4A6E),
    onLeave: Color(0xFFA78BFA),
    onLeaveSubtle: Color(0xFF2E1065),
    holiday: Color(0xFF94A3B8),
    holidaySubtle: Color(0xFF1E293B),
    halfDay: Color(0xFFFBBF24),
    halfDaySubtle: Color(0xFF451A03),
    wfh: Color(0xFF2DD4BF),
    wfhSubtle: Color(0xFF042F2E),
  );

  @override
  AppStatusColors copyWith({
    Color? success,
    Color? successSubtle,
    Color? warning,
    Color? warningSubtle,
    Color? danger,
    Color? dangerSubtle,
    Color? info,
    Color? infoSubtle,
    Color? onLeave,
    Color? onLeaveSubtle,
    Color? holiday,
    Color? holidaySubtle,
    Color? halfDay,
    Color? halfDaySubtle,
    Color? wfh,
    Color? wfhSubtle,
  }) {
    return AppStatusColors(
      success: success ?? this.success,
      successSubtle: successSubtle ?? this.successSubtle,
      warning: warning ?? this.warning,
      warningSubtle: warningSubtle ?? this.warningSubtle,
      danger: danger ?? this.danger,
      dangerSubtle: dangerSubtle ?? this.dangerSubtle,
      info: info ?? this.info,
      infoSubtle: infoSubtle ?? this.infoSubtle,
      onLeave: onLeave ?? this.onLeave,
      onLeaveSubtle: onLeaveSubtle ?? this.onLeaveSubtle,
      holiday: holiday ?? this.holiday,
      holidaySubtle: holidaySubtle ?? this.holidaySubtle,
      halfDay: halfDay ?? this.halfDay,
      halfDaySubtle: halfDaySubtle ?? this.halfDaySubtle,
      wfh: wfh ?? this.wfh,
      wfhSubtle: wfhSubtle ?? this.wfhSubtle,
    );
  }

  @override
  AppStatusColors lerp(ThemeExtension<AppStatusColors>? other, double t) {
    if (other is! AppStatusColors) return this;
    return AppStatusColors(
      success: Color.lerp(success, other.success, t)!,
      successSubtle: Color.lerp(successSubtle, other.successSubtle, t)!,
      warning: Color.lerp(warning, other.warning, t)!,
      warningSubtle: Color.lerp(warningSubtle, other.warningSubtle, t)!,
      danger: Color.lerp(danger, other.danger, t)!,
      dangerSubtle: Color.lerp(dangerSubtle, other.dangerSubtle, t)!,
      info: Color.lerp(info, other.info, t)!,
      infoSubtle: Color.lerp(infoSubtle, other.infoSubtle, t)!,
      onLeave: Color.lerp(onLeave, other.onLeave, t)!,
      onLeaveSubtle: Color.lerp(onLeaveSubtle, other.onLeaveSubtle, t)!,
      holiday: Color.lerp(holiday, other.holiday, t)!,
      holidaySubtle: Color.lerp(holidaySubtle, other.holidaySubtle, t)!,
      halfDay: Color.lerp(halfDay, other.halfDay, t)!,
      halfDaySubtle: Color.lerp(halfDaySubtle, other.halfDaySubtle, t)!,
      wfh: Color.lerp(wfh, other.wfh, t)!,
      wfhSubtle: Color.lerp(wfhSubtle, other.wfhSubtle, t)!,
    );
  }
}
