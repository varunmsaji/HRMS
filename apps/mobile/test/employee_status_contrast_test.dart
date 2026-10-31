import 'dart:math' as math;

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:hrms_mobile/core/theme/app_colors.dart';
import 'package:hrms_mobile/core/theme/employee_tokens.dart';

double _lin(double c) => c <= 0.03928 ? c / 12.92 : math.pow((c + 0.055) / 1.055, 2.4).toDouble();
double _luminance(Color c) => 0.2126 * _lin(c.r) + 0.7152 * _lin(c.g) + 0.0722 * _lin(c.b);

/// WCAG 2.x contrast ratio.
double contrast(Color a, Color b) {
  final la = _luminance(a), lb = _luminance(b);
  final hi = math.max(la, lb), lo = math.min(la, lb);
  return (hi + 0.05) / (lo + 0.05);
}

void main() {
  const t = EmployeeTokens.standard;
  const s = AppStatusColors.light;

  test('text pairs meet AA (4.5:1)', () {
    final pairs = <String, (Color, Color)>{
      'ink on sheet': (t.ink, t.sheet),
      'ink on canvas': (t.ink, t.canvas),
      'inkSecondary on sheet': (t.inkSecondary, t.sheet),
      'inkSecondary on canvas': (t.inkSecondary, t.canvas),
      'action on sheet': (t.action, t.sheet),
      'action on canvas': (t.action, t.canvas),
      'action on actionSubtle': (t.action, t.actionSubtle),
      'white on action': (Colors.white, t.action),
      'white on actionPressed': (Colors.white, t.actionPressed),
      'dangerText on sheet': (t.dangerText, t.sheet),
      'white on dangerText (filled error button)': (Colors.white, t.dangerText),
      'ink on warning banner': (t.ink, s.warningSubtle),
      'success text on subtle': (t.successText, s.successSubtle),
      'warning text on subtle': (t.warningText, s.warningSubtle),
      'danger text on subtle': (t.dangerText, s.dangerSubtle),
      'info text on subtle': (t.infoText, s.infoSubtle),
      'on-leave text on subtle': (t.onLeaveText, s.onLeaveSubtle),
      'holiday text on subtle': (t.holidayText, s.holidaySubtle),
      'wfh text on subtle': (t.wfhText, s.wfhSubtle),
    };
    for (final e in pairs.entries) {
      expect(contrast(e.value.$1, e.value.$2), greaterThanOrEqualTo(4.5), reason: e.key);
    }
  });

  test('non-text pairs meet 3:1', () {
    expect(contrast(t.inkTertiary, t.sheet), greaterThanOrEqualTo(3.0), reason: 'icons on sheet');
    expect(contrast(t.action, t.sheet), greaterThanOrEqualTo(3.0), reason: 'focus ring');
  });

  test('the raw status colours are NOT used as text (they fail AA); documents why', () {
    expect(contrast(s.warning, s.warningSubtle), lessThan(4.5));
    expect(contrast(s.info, s.infoSubtle), lessThan(4.5));
    expect(contrast(t.inkTertiary, t.sheet), lessThan(4.5), reason: 'inkTertiary is for icons/hints only');
  });
}
