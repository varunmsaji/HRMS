import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../core/forms/choice_sources.dart';
import '../../../core/forms/spec_form_screen.dart';
import '../../../core/providers.dart';
import '../../../core/requests/request_screens.dart' show deniedChoiceSourcesProvider;
import '../../../core/time.dart' show formatClock24;
import '../../auth/state/auth_controller.dart';
import '../data/attendance_repository.dart' show AttendanceDay;
import '../domain/request_resources.dart';

/// What a correction for [day] most likely is, from the flags the server set on it: a missed punch
/// for a missing punch or an incomplete day, a wrong time for a late arrival or an early exit.
/// Null when the day carries no such flag; the employee then chooses.
String? suggestedCorrectionType(AttendanceDay day) {
  if (day.raw['missing_punch'] == true || day.attendanceStatus == 'INCOMPLETE') return 'MISSING_PUNCH';
  if (day.raw['is_late'] == true || day.raw['is_early_out'] == true) return 'WRONG_PUNCH';
  return null;
}

/// The form values to start a correction for [day] with: its date and the suggested type. Punch
/// times are never prefilled: a requested punch is the employee's claim, not a copy of the record.
Map<String, dynamic> correctionDefaultsFor(AttendanceDay day) => {
      'attendance_date': day.attendanceDate,
      if (suggestedCorrectionType(day) case final type?) 'request_type': type,
    };

/// "Recorded for this day: in 09:02 · out —", shown above the form so the employee can see what
/// to correct without going back (audit MOB-UX-018).
String recordedPunchesNote(AttendanceDay day, String zone) =>
    'Recorded for this day: in ${day.actualFirstIn == null ? '—' : formatClock24(day.actualFirstIn, zone)} · out ${day.actualLastOut == null ? '—' : formatClock24(day.actualLastOut, zone)}. Times use your company\'s time zone.';

/// Opens the signed-in employee's own attendance-correction form, the same request the
/// Attendance corrections screen and an attendance day raise. [day] prefills the date and the
/// likely type and shows the recorded punches. Resolves to true when a request was submitted;
/// the caller refreshes and confirms.
///
/// Used by Home's "Correction" shortcut so it opens the form, not a list (MOB-UX-007).
Future<bool> raiseOwnCorrection(BuildContext context, WidgetRef ref, {AttendanceDay? day}) {
  final client = ref.read(apiClientProvider);
  final user = ref.read(authControllerProvider).user;
  final zone = user?.companyTimezone ?? 'Asia/Kolkata';
  return openSpecForm(
    context,
    title: 'Attendance correction',
    spec: regularizationSpec(false),
    defaults: day == null ? const {} : correctionDefaultsFor(day),
    intro: day == null ? null : recordedPunchesNote(day, zone),
    submitLabel: 'Submit request',
    loadChoiceSet: () => loadCorrectionChoices(ref),
    onSubmit: (payload, _) async => client.post<Object?>('/regularizations', body: buildRegularizationBody(payload, zone), parse: (_) => null),
  );
}

/// The correction form's optional choice sources (shifts). A 403 is remembered for the session so
/// the refused endpoint is not asked again.
Future<ChoiceLoad> loadCorrectionChoices(WidgetRef ref) async {
  final client = ref.read(apiClientProvider);
  final denied = ref.read(deniedChoiceSourcesProvider(ref.read(authControllerProvider).user?.id ?? '').notifier);
  final set = await loadChoicesTolerant(client, optional: regularizationConfig.optionalChoiceKeys, knownDenied: denied.state);
  final newlyDenied = {for (final e in set.unavailable.entries) if (e.value == ChoiceUnavailable.denied) e.key};
  if (newlyDenied.difference(denied.state).isNotEmpty) denied.state = {...denied.state, ...newlyDenied};
  return set;
}
