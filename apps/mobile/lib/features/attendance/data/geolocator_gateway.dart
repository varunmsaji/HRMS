import 'dart:async';

import 'package:geolocator/geolocator.dart';

import '../domain/punch_location.dart';

/// [LocationGateway] backed by `geolocator`. One-shot, foreground-only: it calls
/// `getCurrentPosition` (a fresh fix) and never `getLastKnownPosition` or a position stream.
class GeolocatorGateway implements LocationGateway {
  const GeolocatorGateway();

  GatewayPermission _map(LocationPermission p) => switch (p) {
        LocationPermission.always || LocationPermission.whileInUse => GatewayPermission.granted,
        LocationPermission.deniedForever => GatewayPermission.deniedForever,
        LocationPermission.denied || LocationPermission.unableToDetermine => GatewayPermission.denied,
      };

  @override
  Future<bool> serviceEnabled() => Geolocator.isLocationServiceEnabled();

  @override
  Future<GatewayPermission> permission() async => _map(await Geolocator.checkPermission());

  @override
  Future<GatewayPermission> requestPermission() async => _map(await Geolocator.requestPermission());

  @override
  Future<GpsFix> currentFix({required Duration timeout}) async {
    final position = await Geolocator.getCurrentPosition(
      locationSettings: LocationSettings(accuracy: LocationAccuracy.best, timeLimit: timeout),
    );
    return GpsFix(
      latitude: position.latitude,
      longitude: position.longitude,
      accuracyM: position.accuracy,
      timestamp: position.timestamp,
      isMocked: position.isMocked,
    );
  }

  @override
  Future<void> openAppSettings() => Geolocator.openAppSettings();

  @override
  Future<void> openLocationSettings() => Geolocator.openLocationSettings();
}
