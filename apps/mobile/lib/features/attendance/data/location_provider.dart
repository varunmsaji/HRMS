import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../domain/punch_location.dart';
import 'geolocator_gateway.dart';

/// The one-shot location capture used by punches. Overridden with a fake in tests.
final locationCaptureProvider = Provider<LocationCapture>((ref) => LocationCapture(const GeolocatorGateway()));
