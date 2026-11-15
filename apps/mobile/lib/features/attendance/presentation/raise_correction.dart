import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../core/forms/choice_sources.dart';
import '../../../core/forms/spec_form_screen.dart';
import '../../../core/providers.dart';
import '../../../core/requests/request_screens.dart' show deniedChoiceSourcesProvider;
import '../../auth/state/auth_controller.dart';
import '../domain/request_resources.dart';

/// Opens the signed-in employee's own attendance-correction form, the same request the
/// Regularizations screen and an attendance day raise. [date] (ISO) prefills the day. Resolves to
/// true when a request was submitted; the caller refreshes and confirms.
///
/// Used by Home's "Correction" shortcut so it opens the form, not a list (MOB-UX-007).
Future<bool> raiseOwnCorrection(BuildContext context, WidgetRef ref, {String? date}) {
  final client = ref.read(apiClientProvider);
  final user = ref.read(authControllerProvider).user;
  final zone = user?.companyTimezone ?? 'Asia/Kolkata';
  final denied = ref.read(deniedChoiceSourcesProvider(user?.id ?? '').notifier);
  return openSpecForm(
    context,
    title: 'Attendance correction',
    spec: regularizationSpec(false),
    defaults: {if (date != null) 'attendance_date': date},
    submitLabel: 'Submit request',
    loadChoiceSet: () async {
      final set = await loadChoicesTolerant(client, optional: regularizationConfig.optionalChoiceKeys, knownDenied: denied.state);
      // A 403 is remembered for the session so the refused endpoint is not asked again.
      final newlyDenied = {for (final e in set.unavailable.entries) if (e.value == ChoiceUnavailable.denied) e.key};
      if (newlyDenied.difference(denied.state).isNotEmpty) denied.state = {...denied.state, ...newlyDenied};
      return set;
    },
    onSubmit: (payload, _) async => client.post<Object?>('/regularizations', body: buildRegularizationBody(payload, zone), parse: (_) => null),
  );
}
