import 'dart:async';

import '../../../core/api/api_error.dart';

/// A device-reported position sent with a geofenced punch. Every field is a claim by the phone;
/// the server decides what it means, and the app never decides whether the employee is inside.
class PunchLocation {
  const PunchLocation({
    required this.latitude,
    required this.longitude,
    required this.accuracyM,
    required this.capturedAt,
  });

  final double latitude;
  final double longitude;

  /// Horizontal accuracy radius in metres, as reported by the platform.
  final double accuracyM;

  /// When the platform obtained the fix (UTC) — not when the request is sent.
  final DateTime capturedAt;

  Map<String, dynamic> toJson() => {
        'latitude': latitude,
        'longitude': longitude,
        'accuracy_m': accuracyM,
        'captured_at': capturedAt.toUtc().toIso8601String(),
      };
}

/// Why no usable fix could be taken.
enum LocationFailure {
  permissionDenied,
  permissionDeniedForever,
  servicesDisabled,
  timeout,
  unavailable,

  /// The fix is older than the policy allows. Never silently replaced by a cached position.
  stale,

  /// The platform reports a worse accuracy than the policy accepts.
  poorAccuracy,

  /// The platform flagged the position as coming from a mock-location provider. A convenience
  /// check only — the server never relies on it, and a modified app can skip it.
  mockLocation;

  /// The `location_error` value the server understands, or null when the failure is one the
  /// server would judge itself from a real fix (stale / poor accuracy / mock).
  String? get serverCode => switch (this) {
        permissionDenied => 'PERMISSION_DENIED',
        permissionDeniedForever => 'PERMISSION_DENIED_FOREVER',
        servicesDisabled => 'SERVICES_DISABLED',
        timeout => 'TIMEOUT',
        unavailable => 'UNAVAILABLE',
        stale || poorAccuracy || mockLocation => null,
      };

  /// What to tell the employee, including how to fix it.
  String get instructions => switch (this) {
        permissionDenied =>
          'Location permission is needed to confirm you are at your workplace. Allow location access when asked.',
        permissionDeniedForever =>
          'Location access is blocked for this app. Open the app settings, allow Location, then try again.',
        servicesDisabled =>
          'Location services are turned off. Turn on Location in your phone settings, then try again.',
        timeout =>
          'Could not get your location in time. Move to an open area, check that Location is on, and try again.',
        unavailable =>
          'Your phone could not provide a location. Check that Location is on and try again.',
        stale => 'The location reading was too old. Try again to get a fresh reading.',
        poorAccuracy =>
          'The GPS signal is too weak. Turn on precise location, move to an open area or near a window, wait a few seconds and try again.',
        mockLocation =>
          'Your phone is using a mock location. Turn off mock-location apps and try again.',
      };

  /// True when the settings screens can help (as opposed to just waiting for a better signal).
  bool get needsSettings =>
      this == permissionDeniedForever || this == servicesDisabled;
}

/// The caller's own location requirement (`GET /attendance/geofence-policy/me`).
class GeofencePolicyMe {
  const GeofencePolicyMe({required this.mode, required this.maxAccuracyM, required this.maxAgeSeconds});

  /// `DISABLED`, `OPTIONAL` or `REQUIRED`.
  final String mode;
  final int maxAccuracyM;
  final int maxAgeSeconds;

  static const disabled = GeofencePolicyMe(mode: 'DISABLED', maxAccuracyM: 100, maxAgeSeconds: 60);

  bool get isDisabled => mode == 'DISABLED';
  bool get isRequired => mode == 'REQUIRED';

  factory GeofencePolicyMe.fromJson(Map<String, dynamic> json) => GeofencePolicyMe(
        mode: json['mode'] as String,
        maxAccuracyM: (json['max_accuracy_m'] as num).toInt(),
        maxAgeSeconds: (json['max_age_seconds'] as num).toInt(),
      );
}

enum GatewayPermission { granted, denied, deniedForever }

/// A raw platform fix.
class GpsFix {
  const GpsFix({
    required this.latitude,
    required this.longitude,
    required this.accuracyM,
    required this.timestamp,
    this.isMocked = false,
  });

  final double latitude;
  final double longitude;
  final double accuracyM;
  final DateTime timestamp;
  final bool isMocked;
}

/// The platform surface the capture logic needs; faked in tests, `geolocator` in the app.
abstract class LocationGateway {
  Future<bool> serviceEnabled();
  Future<GatewayPermission> permission();
  Future<GatewayPermission> requestPermission();

  /// A FRESH fix. Implementations must not return a cached last-known position. Throws
  /// [TimeoutException] when none arrives within [timeout].
  Future<GpsFix> currentFix({required Duration timeout});

  Future<void> openAppSettings();
  Future<void> openLocationSettings();
}

sealed class LocationCaptureResult {
  const LocationCaptureResult();
}

class LocationCaptured extends LocationCaptureResult {
  const LocationCaptured(this.location);
  final PunchLocation location;
}

class LocationCaptureFailed extends LocationCaptureResult {
  const LocationCaptureFailed(this.failure, {this.accuracyM});
  final LocationFailure failure;
  final double? accuracyM;
}

/// Takes one fresh foreground location for an employee-initiated punch. Nothing here runs in the
/// background or keeps a subscription open; permission is requested only when a capture needs it.
class LocationCapture {
  LocationCapture(this._gateway, {DateTime Function()? now, this.timeout = const Duration(seconds: 15)})
      : _now = now ?? DateTime.now;

  final LocationGateway _gateway;
  final DateTime Function() _now;
  final Duration timeout;

  /// Services on + permission granted (asking once if it is merely not yet decided). Cheap, so a
  /// slow flow (face capture) can learn about a blocker before the user does the slow part.
  Future<LocationFailure?> preflight() async {
    if (!await _gateway.serviceEnabled()) return LocationFailure.servicesDisabled;
    var permission = await _gateway.permission();
    if (permission == GatewayPermission.denied) permission = await _gateway.requestPermission();
    return switch (permission) {
      GatewayPermission.granted => null,
      GatewayPermission.deniedForever => LocationFailure.permissionDeniedForever,
      GatewayPermission.denied => LocationFailure.permissionDenied,
    };
  }

  Future<LocationCaptureResult> capture(GeofencePolicyMe policy) async {
    final blocked = await preflight();
    if (blocked != null) return LocationCaptureFailed(blocked);

    final GpsFix fix;
    try {
      fix = await _gateway.currentFix(timeout: timeout);
    } on TimeoutException {
      return const LocationCaptureFailed(LocationFailure.timeout);
    } catch (_) {
      return const LocationCaptureFailed(LocationFailure.unavailable);
    }

    // A platform that cannot say when the fix was taken gives us nothing to judge freshness by;
    // never invent a timestamp for it.
    if (fix.timestamp.year < 2020) return const LocationCaptureFailed(LocationFailure.unavailable);
    if (_now().difference(fix.timestamp) > Duration(seconds: policy.maxAgeSeconds)) {
      return const LocationCaptureFailed(LocationFailure.stale);
    }
    if (fix.isMocked) return const LocationCaptureFailed(LocationFailure.mockLocation);
    if (fix.accuracyM > policy.maxAccuracyM) {
      return LocationCaptureFailed(LocationFailure.poorAccuracy, accuracyM: fix.accuracyM);
    }
    return LocationCaptured(PunchLocation(
      latitude: fix.latitude,
      longitude: fix.longitude,
      accuracyM: fix.accuracyM,
      capturedAt: fix.timestamp.toUtc(),
    ));
  }

  Future<void> openAppSettings() => _gateway.openAppSettings();
  Future<void> openLocationSettings() => _gateway.openLocationSettings();
}

/// Server refusals of a geofenced punch (`PUNCH_<outcome>`), with whether retrying can help.
const geofenceErrorCodes = {
  'PUNCH_OUTSIDE_GEOFENCE',
  'PUNCH_OUTSIDE_GEOFENCE_UNCERTAIN',
  'PUNCH_LOCATION_TOO_INACCURATE',
  'PUNCH_LOCATION_STALE',
  'PUNCH_LOCATION_INVALID',
  'PUNCH_LOCATION_REQUIRED',
  'PUNCH_LOCATION_UNAVAILABLE_CLIENT',
  'PUNCH_NO_APPLICABLE_WORKPLACE',
};

bool isGeofenceError(Object error, [String? code]) {
  if (error is! ApiError) return false;
  return code == null ? geofenceErrorCodes.contains(error.code) : error.code == code;
}

/// True when retrying (after improving the signal / moving) may succeed; false when only HR can
/// fix it (no workplace configured).
bool geofenceErrorIsRetryable(String code) => code != 'PUNCH_NO_APPLICABLE_WORKPLACE';
