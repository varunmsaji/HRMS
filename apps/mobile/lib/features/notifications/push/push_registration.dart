import 'dart:async';

import 'package:flutter/foundation.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../auth/state/auth_controller.dart';
import '../../auth/state/auth_state.dart';
import '../data/notification_repository.dart';
import 'push_messaging.dart';
import '../../../core/diagnostics/app_diagnostics.dart';

/// Keeps the server's list of "phones to push to" in step with who is signed in on this one.
///
/// * Signed in -> ask for permission once, get the token and register it with the API, and
///   register again whenever Firebase rotates it.
/// * Signing out -> tell the API to forget this phone *before* the session is cleared, so it stops
///   receiving that user's notifications. If the session simply expires there is no valid session
///   left to make that call; the server then drops the token when Firebase reports it dead, or
///   moves it to whoever signs in next on this phone.
///
/// Every step is best-effort: push is a convenience on top of the in-app notifications and must
/// never stop sign-in, sign-out or anything else.
class PushRegistration {
  /// [repo] is a getter so nothing needs the API client until a call is actually made: with push
  /// unavailable (no Firebase config, tests) it is never touched.
  PushRegistration(this._push, this._repo);
  final PushMessaging _push;
  final NotificationRepository Function() _repo;

  String? _registered;
  StreamSubscription<String>? _refresh;

  String get _platform => defaultTargetPlatform == TargetPlatform.iOS ? 'ios' : 'android';

  /// Registers this phone for the current user. Safe to call repeatedly.
  Future<void> register() async {
    if (!_push.available) return;
    try {
      if (!await _push.requestPermission()) return;
      final token = await _push.token();
      if (token == null || token.length < 20) return;
      await _send(token);
      _refresh ??= _push.onTokenRefresh.listen((t) => unawaited(_send(t)));
    } catch (e, s) {
      // Offline or the API refused: the next sign-in or app start tries again.
      AppDiagnostics.instance.recordHandled(e, s);
    }
  }

  Future<void> _send(String token) async {
    if (token == _registered) return;
    await _repo().registerDevice(token: token, platform: _platform);
    _registered = token;
  }

  /// Stops pushes to this phone for the signed-in user. Call before the session is cleared.
  Future<void> unregister() async {
    await _refresh?.cancel();
    _refresh = null;
    final token = _registered;
    _registered = null;
    if (token == null) return;
    try {
      await _repo().unregisterDevice(token).timeout(const Duration(seconds: 4));
    } catch (e, s) { AppDiagnostics.instance.recordHandled(e, s); }
  }

  void dispose() => unawaited(_refresh?.cancel());
}

final pushRegistrationProvider = Provider<PushRegistration>((ref) {
  final registration = PushRegistration(ref.watch(pushMessagingProvider), () => ref.read(notificationRepositoryProvider));
  ref.onDispose(registration.dispose);
  return registration;
});

/// Watch this once near the root (`HrmsApp`): registers the phone when a user is signed in.
final pushLifecycleProvider = Provider<void>((ref) {
  final registration = ref.watch(pushRegistrationProvider);
  void apply(AuthState s) {
    if (s.status == AuthStatus.authenticated && s.user != null) unawaited(registration.register());
  }

  ref.listen<AuthState>(authControllerProvider, (_, next) => apply(next));
  apply(ref.read(authControllerProvider));
});
