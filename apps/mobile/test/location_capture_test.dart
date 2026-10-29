import 'dart:async';

import 'package:flutter_test/flutter_test.dart';
import 'package:hrms_mobile/features/attendance/domain/punch_location.dart';

final _now = DateTime.utc(2026, 10, 28, 9, 0, 0);

class FakeGateway implements LocationGateway {
  FakeGateway({
    this.enabled = true,
    this.perm = GatewayPermission.granted,
    this.afterRequest,
    this.fix,
    this.fixError,
  });

  bool enabled;
  GatewayPermission perm;

  /// What `requestPermission` yields; defaults to [perm] unchanged.
  GatewayPermission? afterRequest;
  GpsFix? fix;
  Object? fixError;

  int fixCalls = 0;
  int requestCalls = 0;
  int appSettingsOpened = 0;
  int locationSettingsOpened = 0;

  @override
  Future<bool> serviceEnabled() async => enabled;

  @override
  Future<GatewayPermission> permission() async => perm;

  @override
  Future<GatewayPermission> requestPermission() async {
    requestCalls++;
    perm = afterRequest ?? perm;
    return perm;
  }

  @override
  Future<GpsFix> currentFix({required Duration timeout}) async {
    fixCalls++;
    if (fixError != null) throw fixError!;
    return fix!;
  }

  @override
  Future<void> openAppSettings() async => appSettingsOpened++;

  @override
  Future<void> openLocationSettings() async => locationSettingsOpened++;
}

GpsFix _fix({double accuracy = 10, int ageSeconds = 3, bool mocked = false, DateTime? at}) => GpsFix(
      latitude: 9.9312,
      longitude: 76.2673,
      accuracyM: accuracy,
      timestamp: at ?? _now.subtract(Duration(seconds: ageSeconds)),
      isMocked: mocked,
    );

const _policy = GeofencePolicyMe(mode: 'REQUIRED', maxAccuracyM: 50, maxAgeSeconds: 30);

LocationCapture _capture(FakeGateway g) => LocationCapture(g, now: () => _now);

void main() {
  group('LocationCapture', () {
    test('takes a fresh fix and reports where and when the platform got it', () async {
      final g = FakeGateway(fix: _fix(accuracy: 12, ageSeconds: 4));
      final result = await _capture(g).capture(_policy);

      expect(result, isA<LocationCaptured>());
      final loc = (result as LocationCaptured).location;
      expect(loc.accuracyM, 12);
      expect(loc.capturedAt, _now.subtract(const Duration(seconds: 4)));
      expect(loc.toJson()['captured_at'], '2026-10-28T08:59:56.000Z');
      expect(loc.toJson().keys, {'latitude', 'longitude', 'accuracy_m', 'captured_at'});
      expect(g.fixCalls, 1);
      expect(g.requestCalls, 0, reason: 'permission already granted: never prompt again');
    });

    test('asks for permission only when it is merely undecided, then proceeds if granted', () async {
      final g = FakeGateway(perm: GatewayPermission.denied, afterRequest: GatewayPermission.granted, fix: _fix());
      expect(await _capture(g).capture(_policy), isA<LocationCaptured>());
      expect(g.requestCalls, 1);
    });

    test('permission refused at the prompt', () async {
      final g = FakeGateway(perm: GatewayPermission.denied, afterRequest: GatewayPermission.denied);
      final result = await _capture(g).capture(_policy) as LocationCaptureFailed;
      expect(result.failure, LocationFailure.permissionDenied);
      expect(g.fixCalls, 0);
    });

    test('permanently denied is reported without prompting and points to settings', () async {
      final g = FakeGateway(perm: GatewayPermission.deniedForever);
      final result = await _capture(g).capture(_policy) as LocationCaptureFailed;
      expect(result.failure, LocationFailure.permissionDeniedForever);
      expect(result.failure.needsSettings, isTrue);
      expect(g.requestCalls, 0);
      expect(g.fixCalls, 0);
    });

    test('location services off: no permission prompt, no fix', () async {
      final g = FakeGateway(enabled: false);
      final result = await _capture(g).capture(_policy) as LocationCaptureFailed;
      expect(result.failure, LocationFailure.servicesDisabled);
      expect(result.failure.needsSettings, isTrue);
      expect(g.requestCalls, 0);
      expect(g.fixCalls, 0);
    });

    test('GPS timeout and a platform error are different, non-settings failures', () async {
      final slow = await _capture(FakeGateway(fixError: TimeoutException('gps'))).capture(_policy);
      expect((slow as LocationCaptureFailed).failure, LocationFailure.timeout);
      final broken = await _capture(FakeGateway(fixError: StateError('boom'))).capture(_policy);
      expect((broken as LocationCaptureFailed).failure, LocationFailure.unavailable);
      expect(LocationFailure.timeout.needsSettings, isFalse);
    });

    test('a stale fix is refused, never substituted', () async {
      final g = FakeGateway(fix: _fix(ageSeconds: 31));
      final result = await _capture(g).capture(_policy) as LocationCaptureFailed;
      expect(result.failure, LocationFailure.stale);
      expect(result.failure.serverCode, isNull);
    });

    test('age exactly at the policy limit is accepted', () async {
      expect(await _capture(FakeGateway(fix: _fix(ageSeconds: 30))).capture(_policy), isA<LocationCaptured>());
    });

    test('poor accuracy is reported with the reading, at the policy ceiling it passes', () async {
      final bad = await _capture(FakeGateway(fix: _fix(accuracy: 80))).capture(_policy) as LocationCaptureFailed;
      expect(bad.failure, LocationFailure.poorAccuracy);
      expect(bad.accuracyM, 80);
      expect(await _capture(FakeGateway(fix: _fix(accuracy: 50))).capture(_policy), isA<LocationCaptured>());
    });

    test('a platform without a usable timestamp is not trusted', () async {
      final g = FakeGateway(fix: _fix(at: DateTime.fromMillisecondsSinceEpoch(0, isUtc: true)));
      final result = await _capture(g).capture(_policy) as LocationCaptureFailed;
      expect(result.failure, LocationFailure.unavailable);
    });

    test('a position flagged as mock is refused client-side (convenience only)', () async {
      final result = await _capture(FakeGateway(fix: _fix(mocked: true))).capture(_policy) as LocationCaptureFailed;
      expect(result.failure, LocationFailure.mockLocation);
    });

    test('preflight reports a blocker without taking a fix', () async {
      final g = FakeGateway(enabled: false);
      expect(await _capture(g).preflight(), LocationFailure.servicesDisabled);
      expect(g.fixCalls, 0);
      expect(await _capture(FakeGateway()).preflight(), isNull);
    });

    test('settings shortcuts are forwarded', () async {
      final g = FakeGateway();
      await _capture(g).openAppSettings();
      await _capture(g).openLocationSettings();
      expect((g.appSettingsOpened, g.locationSettingsOpened), (1, 1));
    });
  });

  group('LocationFailure', () {
    test('only client-side capture failures map to a server location_error code', () {
      expect(LocationFailure.permissionDenied.serverCode, 'PERMISSION_DENIED');
      expect(LocationFailure.permissionDeniedForever.serverCode, 'PERMISSION_DENIED_FOREVER');
      expect(LocationFailure.servicesDisabled.serverCode, 'SERVICES_DISABLED');
      expect(LocationFailure.timeout.serverCode, 'TIMEOUT');
      expect(LocationFailure.unavailable.serverCode, 'UNAVAILABLE');
      expect(LocationFailure.poorAccuracy.serverCode, isNull);
    });

    test('every failure tells the employee what to do', () {
      for (final f in LocationFailure.values) {
        expect(f.instructions, isNotEmpty);
      }
    });
  });

  group('GeofencePolicyMe', () {
    test('parses the server answer', () {
      final p = GeofencePolicyMe.fromJson({'mode': 'REQUIRED', 'max_accuracy_m': 40, 'max_age_seconds': 20});
      expect((p.mode, p.maxAccuracyM, p.maxAgeSeconds, p.isRequired, p.isDisabled), ('REQUIRED', 40, 20, true, false));
      expect(GeofencePolicyMe.disabled.isDisabled, isTrue);
    });
  });
}
