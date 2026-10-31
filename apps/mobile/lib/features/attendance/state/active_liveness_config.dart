import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../domain/active_liveness.dart';

/// Rollout switch for on-device active liveness: build with `--dart-define=FACE_ACTIVE_LIVENESS=true`
/// or override this provider. Off by default so existing deployments behave exactly as before
/// until the stage has been verified on real devices.
const _enabled = bool.fromEnvironment('FACE_ACTIVE_LIVENESS');

final activeLivenessConfigProvider = Provider<ActiveLivenessConfig>((ref) => const ActiveLivenessConfig(enabled: _enabled));
