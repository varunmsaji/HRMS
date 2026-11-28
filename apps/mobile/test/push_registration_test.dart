import 'dart:async';

import 'package:flutter_test/flutter_test.dart';
import 'package:hrms_mobile/features/notifications/data/notification_repository.dart';
import 'package:hrms_mobile/features/notifications/push/push_messaging.dart';
import 'package:hrms_mobile/features/notifications/push/push_registration.dart';

class _FakePush implements PushMessaging {
  _FakePush({this.available = true, this.permission = true, this.tokenValue = 'fcm-token-0123456789-abcdef'});
  @override
  final bool available;
  final bool permission;
  String? tokenValue;
  final refresh = StreamController<String>.broadcast();

  @override
  Future<bool> requestPermission() async => permission;
  @override
  Future<String?> token() async => tokenValue;
  @override
  Stream<String> get onTokenRefresh => refresh.stream;
  @override
  Stream<PushTap> get onTap => const Stream.empty();
  @override
  Future<PushTap?> launchTap() async => null;
  @override
  Stream<void> get onForegroundMessage => const Stream.empty();
  @override
  Future<void> deleteToken() async {}
}

class _FakeRepo implements NotificationRepository {
  final registered = <String>[];
  final unregistered = <String>[];
  bool failRegister = false;

  @override
  Future<void> registerDevice({required String token, required String platform, String? appVersion}) async {
    if (failRegister) throw Exception('offline');
    registered.add(token);
  }

  @override
  Future<void> unregisterDevice(String token) async => unregistered.add(token);

  @override
  dynamic noSuchMethod(Invocation invocation) => super.noSuchMethod(invocation);
}

void main() {
  test('registers the token once, however often it is asked', () async {
    final repo = _FakeRepo();
    final reg = PushRegistration(_FakePush(), () => repo);
    await reg.register();
    await reg.register();
    expect(repo.registered, ['fcm-token-0123456789-abcdef']);
  });

  test('registers a rotated token', () async {
    final push = _FakePush();
    final repo = _FakeRepo();
    final reg = PushRegistration(push, () => repo);
    await reg.register();
    push.refresh.add('rotated-token-0123456789-xyz');
    await Future<void>.delayed(Duration.zero);
    expect(repo.registered, ['fcm-token-0123456789-abcdef', 'rotated-token-0123456789-xyz']);
  });

  test('does nothing when push is unavailable, denied, or has no token', () async {
    for (final push in [_FakePush(available: false), _FakePush(permission: false), _FakePush(tokenValue: null)]) {
      final repo = _FakeRepo();
      await PushRegistration(push, () => repo).register();
      expect(repo.registered, isEmpty);
    }
  });

  test('a failing API never throws and is retried on the next register', () async {
    final repo = _FakeRepo()..failRegister = true;
    final reg = PushRegistration(_FakePush(), () => repo);
    await reg.register();
    expect(repo.registered, isEmpty);
    repo.failRegister = false;
    await reg.register();
    expect(repo.registered, hasLength(1));
  });

  test('unregister removes the registered token, once', () async {
    final repo = _FakeRepo();
    final reg = PushRegistration(_FakePush(), () => repo);
    await reg.register();
    await reg.unregister();
    await reg.unregister();
    expect(repo.unregistered, ['fcm-token-0123456789-abcdef']);
  });

  test('unregister without a registration calls nothing', () async {
    final repo = _FakeRepo();
    await PushRegistration(_FakePush(), () => repo).unregister();
    expect(repo.unregistered, isEmpty);
  });

  test('DisabledPushMessaging is a safe no-op', () async {
    const push = DisabledPushMessaging();
    expect(push.available, isFalse);
    expect(await push.requestPermission(), isFalse);
    expect(await push.token(), isNull);
    expect(await push.launchTap(), isNull);
    await push.deleteToken();
  });

  test('PushTap reads the notification id and action url, ignoring blanks', () {
    final tap = PushTap.fromData({'notification_id': 'n1', 'action_url': '/app/leave-applications/abc', 'type': 'LEAVE_DECIDED'});
    expect(tap.notificationId, 'n1');
    expect(tap.actionUrl, '/app/leave-applications/abc');
    final blank = PushTap.fromData({'notification_id': '', 'action_url': '  '});
    expect(blank.notificationId, isNull);
    expect(blank.actionUrl, isNull);
  });
}
