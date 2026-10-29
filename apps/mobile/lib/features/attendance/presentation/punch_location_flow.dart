import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../data/attendance_repository.dart';
import '../data/location_provider.dart';
import '../domain/punch_location.dart';

/// What a punch should send about location, decided before the request.
class PunchLocationPlan {
  const PunchLocationPlan.skip() : this._(true, null, null);
  const PunchLocationPlan.withLocation(PunchLocation location) : this._(true, location, null);
  const PunchLocationPlan.withError(LocationFailure error) : this._(true, null, error);
  const PunchLocationPlan.abort() : this._(false, null, null);
  const PunchLocationPlan._(this.proceed, this.location, this.locationError);

  /// False when the employee cancelled or a REQUIRED check could not be satisfied.
  final bool proceed;
  final PunchLocation? location;
  final LocationFailure? locationError;
}

/// Looks up the employee's own policy and, only if it asks for a location, takes ONE fresh
/// foreground fix for this employee-initiated punch.
///
/// * `DISABLED` — nothing is requested or captured.
/// * `OPTIONAL` — a fix is attempted; if it fails the punch still goes ahead (the failure is
///   reported to the server, which records it but never blocks).
/// * `REQUIRED` — a failed capture shows how to fix it and offers a retry; the punch is not sent
///   until a usable fix exists or the employee cancels.
///
/// If the policy lookup itself fails (offline) the punch is attempted without a location; the
/// server enforces regardless and answers `PUNCH_LOCATION_REQUIRED` if one was needed.
Future<PunchLocationPlan> planPunchLocation(BuildContext context, WidgetRef ref) async {
  final GeofencePolicyMe policy;
  try {
    policy = await ref.read(attendanceRepositoryProvider).getMyGeofencePolicy();
  } catch (_) {
    return const PunchLocationPlan.skip();
  }
  if (policy.isDisabled) return const PunchLocationPlan.skip();
  if (!context.mounted) return const PunchLocationPlan.abort();
  return captureForPolicy(context, ref, policy);
}

/// Captures a fix for an already-known [policy], with the retry/settings dialog on REQUIRED.
Future<PunchLocationPlan> captureForPolicy(BuildContext context, WidgetRef ref, GeofencePolicyMe policy) async {
  final capture = ref.read(locationCaptureProvider);
  while (true) {
    final result = await capture.capture(policy);
    switch (result) {
      case LocationCaptured(location: final location):
        return PunchLocationPlan.withLocation(location);
      case LocationCaptureFailed(failure: final failure):
        if (!policy.isRequired) return PunchLocationPlan.withError(failure);
        if (!context.mounted) return const PunchLocationPlan.abort();
        final retry = await showLocationProblemDialog(context, failure, capture);
        if (!retry) return const PunchLocationPlan.abort();
    }
  }
}

/// Explains why a location could not be used and how to fix it. Returns true to try again.
Future<bool> showLocationProblemDialog(BuildContext context, LocationFailure failure, LocationCapture capture) async {
  final retry = await showDialog<bool>(
    context: context,
    builder: (dialogContext) => AlertDialog(
      title: const Text('Location needed'),
      content: Text(failure.instructions),
      actions: [
        TextButton(onPressed: () => Navigator.of(dialogContext).pop(false), child: const Text('Cancel')),
        if (failure.needsSettings)
          TextButton(
            onPressed: () async {
              if (failure == LocationFailure.servicesDisabled) {
                await capture.openLocationSettings();
              } else {
                await capture.openAppSettings();
              }
            },
            child: const Text('Open settings'),
          ),
        FilledButton(onPressed: () => Navigator.of(dialogContext).pop(true), child: const Text('Try again')),
      ],
    ),
  );
  return retry ?? false;
}

/// Shown when the server refuses a geofenced punch. The message is the server's, which carries
/// no coordinates. Returns true when the employee chooses to try again.
Future<bool> showGeofenceRejectedDialog(BuildContext context, String code, String message) async {
  final canRetry = geofenceErrorIsRetryable(code);
  final retry = await showDialog<bool>(
    context: context,
    builder: (dialogContext) => AlertDialog(
      title: const Text('Punch not recorded'),
      content: Text(
        canRetry
            ? '$message\n\nIf you are at your workplace and this keeps happening, ask HR to correct your attendance.'
            : message,
      ),
      actions: [
        TextButton(onPressed: () => Navigator.of(dialogContext).pop(false), child: Text(canRetry ? 'Cancel' : 'OK')),
        if (canRetry) FilledButton(onPressed: () => Navigator.of(dialogContext).pop(true), child: const Text('Try again')),
      ],
    ),
  );
  return retry ?? false;
}
