import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:go_router/go_router.dart';
import 'package:hrms_mobile/core/api/envelope.dart';
import 'package:hrms_mobile/features/notifications/data/notification_repository.dart';
import 'package:hrms_mobile/features/notifications/domain/app_notification.dart';
import 'package:hrms_mobile/features/notifications/presentation/notification_popup_host.dart';
import 'package:hrms_mobile/features/notifications/state/notification_popups.dart';
import 'package:hrms_mobile/features/notifications/state/unread_count.dart';

import 'support/fake_auth.dart';

Map<String, dynamic> _json(String id, {String? title, String? url = '/app/leave-applications'}) => {
      'id': id,
      'type': 'LEAVE_DECIDED',
      'title': title ?? 'Notification $id',
      'body': 'Body of $id',
      'is_read': false,
      'created_at': DateTime.now().toUtc().toIso8601String(),
      'action_url': url,
      'action_label': null,
    };

class _Repo implements NotificationRepository {
  _Repo(this.items);

  /// Newest first, like the server.
  List<Map<String, dynamic>> items;
  final read = <String>[];

  @override
  Future<ListEnvelope<AppNotification>> list({int page = 1, int perPage = 20, bool unreadOnly = false}) async {
    final rows = items.where((m) => !unreadOnly || m['is_read'] == false).toList();
    return ListEnvelope(
      data: rows.take(perPage).map(AppNotification.fromJson).toList(),
      pagination: PaginationMeta(page: 1, perPage: perPage, total: rows.length, totalPages: 1),
      meta: ResponseMeta(requestId: 'r'),
    );
  }

  @override
  Future<int> unreadCount() async => items.where((m) => m['is_read'] == false).length;

  @override
  Future<void> markRead(String id) async {
    read.add(id);
    items = [for (final m in items) m['id'] == id ? {...m, 'is_read': true} : m];
  }

  @override
  dynamic noSuchMethod(Invocation invocation) => super.noSuchMethod(invocation);
}

Widget _screen(String name) => Scaffold(body: Center(child: Text(name)));

GoRouter _router() => GoRouter(routes: [
      GoRoute(path: '/', builder: (c, s) => _screen('home')),
      GoRoute(path: '/app/notifications', builder: (c, s) => _screen('notifications screen')),
      GoRoute(path: '/app/leave-applications', builder: (c, s) => _screen('leave screen')),
    ]);

Widget _app(_Repo repo, GoRouter router) => ProviderScope(
      overrides: [
        fakeAuth(const [], employeeId: 'e-1'),
        notificationRepositoryProvider.overrideWithValue(repo),
      ],
      child: MaterialApp.router(
        routerConfig: router,
        builder: (context, child) => NotificationPopupHost(router: router, child: child!),
      ),
    );

Future<void> _poll(WidgetTester tester) async {
  await tester.pump(notificationPollInterval);
  await tester.pump();
  await tester.pump(const Duration(milliseconds: 300));
}

/// Unmount so the host's timers are cancelled before the test ends.
Future<void> _teardown(WidgetTester tester) async {
  await tester.pumpWidget(const SizedBox.shrink());
  await tester.pump(notificationBannerDuration);
}

int _badge(WidgetTester tester) =>
    ProviderScope.containerOf(tester.element(find.byType(NotificationPopupHost))).read(unreadCountProvider);

void main() {
  testWidgets('notifications already unread at start do not pop up; a new one does', (tester) async {
    final repo = _Repo([_json('old')]);
    await tester.pumpWidget(_app(repo, _router()));
    await tester.pumpAndSettle();
    expect(find.byKey(const Key('notification-popup')), findsNothing);
    expect(_badge(tester), 1);

    repo.items = [_json('new', title: 'Leave approved'), ...repo.items];
    await _poll(tester);
    expect(find.byKey(const Key('notification-popup')), findsOneWidget);
    expect(find.text('Leave approved'), findsOneWidget);
    expect(find.textContaining('more'), findsNothing);
    expect(_badge(tester), 2);

    // The same notification is never announced twice.
    await tester.tap(find.byKey(const Key('notification-popup-dismiss')));
    await tester.pumpAndSettle();
    await _poll(tester);
    expect(find.byKey(const Key('notification-popup')), findsNothing);
    await _teardown(tester);
  });

  testWidgets('tapping the banner marks it read and opens its screen', (tester) async {
    final repo = _Repo([]);
    await tester.pumpWidget(_app(repo, _router()));
    await tester.pumpAndSettle();

    repo.items = [_json('n1', title: 'Leave approved')];
    await _poll(tester);
    await tester.tap(find.text('Leave approved'));
    await tester.pumpAndSettle();
    expect(find.text('leave screen'), findsOneWidget);
    expect(repo.read, ['n1']);
    expect(find.byKey(const Key('notification-popup')), findsNothing);
    await _teardown(tester);
  });

  testWidgets('several new at once show "+N more" and open the notifications screen', (tester) async {
    final repo = _Repo([]);
    await tester.pumpWidget(_app(repo, _router()));
    await tester.pumpAndSettle();

    repo.items = [_json('c', title: 'Newest'), _json('b'), _json('a')];
    await _poll(tester);
    expect(find.text('Newest'), findsOneWidget);
    expect(find.text('+2 more'), findsOneWidget);
    await tester.tap(find.text('Newest'));
    await tester.pumpAndSettle();
    expect(find.text('notifications screen'), findsOneWidget);
    expect(repo.read, isEmpty);
    await _teardown(tester);
  });

  testWidgets('the banner hides itself after a few seconds', (tester) async {
    final repo = _Repo([]);
    await tester.pumpWidget(_app(repo, _router()));
    await tester.pumpAndSettle();

    repo.items = [_json('n1')];
    await _poll(tester);
    expect(find.byKey(const Key('notification-popup')), findsOneWidget);
    await tester.pump(notificationBannerDuration);
    await tester.pumpAndSettle();
    expect(find.byKey(const Key('notification-popup')), findsNothing);
    await _teardown(tester);
  });

  testWidgets('no banner while the notifications screen is open', (tester) async {
    final repo = _Repo([]);
    final router = _router();
    await tester.pumpWidget(_app(repo, router));
    await tester.pumpAndSettle();
    router.go('/app/notifications');
    await tester.pumpAndSettle();

    repo.items = [_json('n1')];
    await _poll(tester);
    expect(find.byKey(const Key('notification-popup')), findsNothing);
    expect(_badge(tester), 1);
    await _teardown(tester);
  });

  testWidgets('a backgrounded app is not checked; returning to it checks straight away', (tester) async {
    final repo = _Repo([]);
    await tester.pumpWidget(_app(repo, _router()));
    await tester.pumpAndSettle();

    tester.binding.handleAppLifecycleStateChanged(AppLifecycleState.paused);
    repo.items = [_json('n1', title: 'While away')];
    await tester.pump(notificationPollInterval * 2);
    expect(_badge(tester), 0);

    tester.binding.handleAppLifecycleStateChanged(AppLifecycleState.resumed);
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 300));
    expect(find.text('While away'), findsOneWidget);
    await _teardown(tester);
  });
}
