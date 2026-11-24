import 'dart:async';

import 'package:firebase_core/firebase_core.dart';
import 'package:firebase_messaging/firebase_messaging.dart';
import 'package:flutter/foundation.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

/// A push the user tapped (from the system tray, with the app in the background or closed).
class PushTap {
  const PushTap({this.notificationId, this.actionUrl});
  final String? notificationId;

  /// The web-style path the server put in the notification (`/app/leave-applications/<id>`).
  /// Always run it through `safeNotificationPath` before navigating.
  final String? actionUrl;

  static PushTap fromData(Map<String, dynamic> data) {
    String? clean(Object? v) {
      final s = v?.toString().trim();
      return s == null || s.isEmpty ? null : s;
    }

    return PushTap(notificationId: clean(data['notification_id']), actionUrl: clean(data['action_url']));
  }
}

/// The app's whole view of push. One small interface so the rest of the app never touches
/// Firebase directly, and so everything works, silently without push, when Firebase is not set up
/// (no config files in the build) or the user turned notifications off.
abstract class PushMessaging {
  /// False when push can't work in this build (see [DisabledPushMessaging]).
  bool get available;

  /// Asks the OS for notification permission if needed. True when pushes may be shown.
  Future<bool> requestPermission();

  /// This install's registration token, or null if there isn't one.
  Future<String?> token();

  /// A fresh token whenever Firebase rotates it.
  Stream<String> get onTokenRefresh;

  /// Taps on a push while the app is running in the background.
  Stream<PushTap> get onTap;

  /// The push that launched the app from closed, if any (read once).
  Future<PushTap?> launchTap();

  /// A push that arrived while the app is open (the OS shows nothing then).
  Stream<void> get onForegroundMessage;

  /// Forget this install's token (the next [token] call issues a new one).
  Future<void> deleteToken();
}

/// Used when Firebase isn't configured, in tests, and on any platform without push. Every call is
/// a harmless no-op, so callers never need to check.
class DisabledPushMessaging implements PushMessaging {
  const DisabledPushMessaging();
  @override
  bool get available => false;
  @override
  Future<bool> requestPermission() async => false;
  @override
  Future<String?> token() async => null;
  @override
  Stream<String> get onTokenRefresh => const Stream.empty();
  @override
  Stream<PushTap> get onTap => const Stream.empty();
  @override
  Future<PushTap?> launchTap() async => null;
  @override
  Stream<void> get onForegroundMessage => const Stream.empty();
  @override
  Future<void> deleteToken() async {}
}

/// Firebase Cloud Messaging.
class FirebasePushMessaging implements PushMessaging {
  FirebasePushMessaging._(this._fm);
  final FirebaseMessaging _fm;

  /// Initializes Firebase and returns a working instance, or a [DisabledPushMessaging] when that
  /// isn't possible: the build has no `google-services.json` / `GoogleService-Info.plist`, the
  /// platform has no push, or anything throws. The app must start either way.
  static Future<PushMessaging> tryCreate() async {
    if (kIsWeb || (defaultTargetPlatform != TargetPlatform.android && defaultTargetPlatform != TargetPlatform.iOS)) {
      return const DisabledPushMessaging();
    }
    try {
      await Firebase.initializeApp();
      return FirebasePushMessaging._(FirebaseMessaging.instance);
    } catch (e) {
      debugPrint('Push disabled: Firebase is not configured for this build ($e)');
      return const DisabledPushMessaging();
    }
  }

  @override
  bool get available => true;

  @override
  Future<bool> requestPermission() async {
    try {
      final settings = await _fm.requestPermission();
      final status = settings.authorizationStatus;
      return status == AuthorizationStatus.authorized || status == AuthorizationStatus.provisional;
    } catch (_) {
      return false;
    }
  }

  @override
  Future<String?> token() async {
    try {
      return await _fm.getToken();
    } catch (_) {
      return null;
    }
  }

  @override
  Stream<String> get onTokenRefresh => _fm.onTokenRefresh;

  @override
  Stream<PushTap> get onTap => FirebaseMessaging.onMessageOpenedApp.map((m) => PushTap.fromData(m.data));

  @override
  Future<PushTap?> launchTap() async {
    try {
      final m = await _fm.getInitialMessage();
      return m == null ? null : PushTap.fromData(m.data);
    } catch (_) {
      return null;
    }
  }

  @override
  Stream<void> get onForegroundMessage => FirebaseMessaging.onMessage.map((_) {});

  @override
  Future<void> deleteToken() async {
    try {
      await _fm.deleteToken();
    } catch (_) {}
  }
}

/// Overridden in `main()` with the result of [FirebasePushMessaging.tryCreate]. Everything else
/// (including every test) gets the disabled no-op.
final pushMessagingProvider = Provider<PushMessaging>((ref) => const DisabledPushMessaging());
