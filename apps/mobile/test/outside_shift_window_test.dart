import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:hrms_mobile/core/api/api_error.dart';
import 'package:hrms_mobile/core/theme/app_theme.dart';
import 'package:hrms_mobile/features/attendance/domain/outside_shift_window.dart';
import 'package:hrms_mobile/features/attendance/presentation/punch_location_flow.dart';

import 'punch_controller_test.dart' show outsideShiftWindowError;

void main() {
  group('OutsideShiftWindow', () {
    test("is read from the error details, in the company's zone whatever the device's", () {
      final w = OutsideShiftWindow.fromError(outsideShiftWindowError())!;
      expect(w.shiftStart.isAtSameMomentAs(DateTime.utc(2026, 10, 30, 9, 30)), isTrue);
      expect(w.earliestPunchIn.isAtSameMomentAs(DateTime.utc(2026, 10, 30, 8, 30)), isTrue);
      // 09:30 UTC is 15:00 IST (SH-17: before, the device's own zone).
      expect((w.shiftStart.hour, w.shiftStart.minute), (15, 0));
      final utc = OutsideShiftWindow.fromError(outsideShiftWindowError(), zone: 'UTC')!;
      expect((utc.shiftStart.hour, utc.shiftStart.minute), (9, 30));
      expect((w.graceInMinutes, w.graceOutMinutes, w.earlyInAllowanceMinutes), (10, 15, 60));
    });

    test('is null for other errors, and for a refusal whose details cannot be read', () {
      expect(OutsideShiftWindow.fromError(ApiError(status: 422, code: 'PUNCH_OUTSIDE_GEOFENCE', message: 'x')), isNull);
      expect(OutsideShiftWindow.fromError(ApiError(status: 422, code: 'OUTSIDE_SHIFT_WINDOW', message: 'x')), isNull);
      expect(OutsideShiftWindow.fromError(StateError('boom')), isNull);
    });

    test('builds the sentence from the response fields', () {
      final w = OutsideShiftWindow.fromError(outsideShiftWindowError())!;
      String hm(DateTime t) => '${t.hour}:${t.minute.toString().padLeft(2, '0')}';
      expect(w.message(hm), "You can't punch in yet. Your shift starts at ${hm(w.shiftStart)}, and you can punch in from ${hm(w.earliestPunchIn)}.");
      // Always an hour apart in UTC, whatever zone the device is in.
      expect(w.shiftStart.difference(w.earliestPunchIn), const Duration(hours: 1));
    });
  });

  testWidgets('the warning shows the message in the locale format and has a single dismiss button', (tester) async {
    final host = GlobalKey();
    await tester.pumpWidget(MaterialApp(theme: AppTheme.employee, home: Scaffold(body: SizedBox(key: host))));
    final w = OutsideShiftWindow.fromError(outsideShiftWindowError())!;
    var closed = false;
    unawaited(showOutsideShiftWindowDialog(host.currentContext!, w).then((_) => closed = true));
    await tester.pumpAndSettle();

    final l = MaterialLocalizations.of(tester.element(find.byType(AlertDialog)));
    String f(DateTime t) => l.formatTimeOfDay(TimeOfDay.fromDateTime(t));
    expect(find.text("You can't punch in yet. Your shift starts at ${f(w.shiftStart)}, and you can punch in from ${f(w.earliestPunchIn)}."), findsOneWidget);
    expect(find.byIcon(Icons.warning_amber_rounded), findsOneWidget);
    expect(find.byType(TextButton), findsOneWidget);
    expect(find.byType(FilledButton), findsNothing);
    expect(find.text('Dismiss'), findsOneWidget);

    await tester.tap(find.text('Dismiss'));
    await tester.pumpAndSettle();
    expect(find.byType(AlertDialog), findsNothing);
    expect(closed, isTrue);
  });
}
