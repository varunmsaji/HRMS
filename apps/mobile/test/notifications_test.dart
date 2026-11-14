import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:go_router/go_router.dart';
import 'package:hrms_mobile/core/api/envelope.dart';
import 'support/fake_auth.dart';
import 'package:hrms_mobile/features/attendance/data/attendance_repository.dart';
import 'package:hrms_mobile/features/attendance/presentation/face_setup_screen.dart';
import 'package:hrms_mobile/features/notifications/data/notification_repository.dart';
import 'package:hrms_mobile/features/notifications/domain/app_notification.dart';
import 'package:hrms_mobile/features/notifications/presentation/notification_bell.dart';
import 'package:hrms_mobile/features/notifications/presentation/notifications_screen.dart';
import 'package:hrms_mobile/features/notifications/state/unread_count.dart';

Map<String, dynamic> _json({String id = 'n1', bool read = false, String title = 'Face Enrollment Requested', String? url = '/app/attendance/face-setup'}) => {
      'id': id,
      'type': 'FACE_ENROLLMENT_REQUESTED',
      'title': title,
      'body': 'Your HR team has requested you to complete face enrollment for attendance.',
      'is_read': read,
      'created_at': DateTime.now().toUtc().toIso8601String(),
      'action_url': url,
      'action_label': 'Complete Face Enrollment',
    };

class _Repo implements NotificationRepository {
  _Repo({List<Map<String, dynamic>>? items, this.failList = false, this.gate}) : items = items ?? [_json()];
  List<Map<String, dynamic>> items;
  bool failList;
  Completer<void>? gate;
  int unread = 1;
  int listCalls = 0;
  int countCalls = 0;
  final read = <String>[];
  bool readAllCalled = false;
  bool lastUnreadOnly = false;

  @override
  Future<ListEnvelope<AppNotification>> list({int page = 1, int perPage = 20, bool unreadOnly = false}) async {
    listCalls++;
    lastUnreadOnly = unreadOnly;
    if (gate != null) await gate!.future;
    if (failList) throw Exception('boom');
    final rows = unreadOnly ? items.where((m) => m['is_read'] == false).toList() : items;
    return ListEnvelope(data: rows.map(AppNotification.fromJson).toList(), pagination: null, meta: ResponseMeta(requestId: 'r'));
  }

  @override
  Future<int> unreadCount() async {
    countCalls++;
    return unread;
  }

  @override
  Future<void> markRead(String id) async {
    read.add(id);
    unread = unread > 0 ? unread - 1 : 0;
    items = [for (final m in items) m['id'] == id ? {...m, 'is_read': true} : m];
  }

  @override
  Future<int> markAllRead() async {
    readAllCalled = true;
    unread = 0;
    items = [for (final m in items) {...m, 'is_read': true}];
    return 0;
  }

  @override
  dynamic noSuchMethod(Invocation invocation) => super.noSuchMethod(invocation);
}

class _AttRepo implements AttendanceRepository {
  _AttRepo({Map<String, dynamic>? status}) : status = status ?? availableStatus;

  /// What the server says *now*; a test changes it after the notification was created.
  Map<String, dynamic> status;
  int statusCalls = 0;
  int startCalls = 0;

  static const availableStatus = {
    'profile': null,
    'open_window': {'id': 'w1', 'expires_at': '2099-01-01T00:00:00Z'},
    'enrollment_state': 'ENROLLMENT_AVAILABLE',
  };

  @override
  Future<FaceEnrollmentStatus> getMyFaceEnrollment() async {
    statusCalls++;
    return FaceEnrollmentStatus.fromJson(status);
  }

  @override
  Future<void> startMyFaceEnrollment() async {
    startCalls++;
  }

  @override
  dynamic noSuchMethod(Invocation invocation) => super.noSuchMethod(invocation);
}

Widget _app(_Repo repo, {_AttRepo? att, Widget? home}) {
  final router = GoRouter(routes: [
    GoRoute(path: '/', builder: (c, s) => home ?? const NotificationsScreen()),
    GoRoute(path: '/app/attendance/face-setup', builder: (c, s) => const FaceSetupScreen()),
  ]);
  return ProviderScope(
    overrides: [
      notificationRepositoryProvider.overrideWithValue(repo),
      unreadCountProvider.overrideWith((ref) => UnreadCountNotifier(repo, signedIn: true)),
      if (att != null) attendanceRepositoryProvider.overrideWithValue(att),
    ],
    child: MaterialApp.router(routerConfig: router),
  );
}

void main() {
  test('safeNotificationPath only allows in-app routes', () {
    expect(safeNotificationPath('/app/attendance/face-setup'), '/app/attendance/face-setup');
    expect(safeNotificationPath('https://evil.example'), isNull);
    expect(safeNotificationPath('//evil.example'), isNull);
    expect(safeNotificationPath('/other'), isNull);
    expect(safeNotificationPath(null), isNull);
  });

  test('web detail paths open the matching mobile screen', () {
    expect(safeNotificationPath('/app/leave-applications/abc'), '/app/leave-applications');
    expect(safeNotificationPath('/app/regularizations/abc'), '/app/regularizations');
    expect(safeNotificationPath('/app/overtime/abc'), '/app/overtime');
    expect(safeNotificationPath('/app/onboarding/abc'), '/app/onboarding');
    expect(safeNotificationPath('/app/me/payslips/run-1'), '/app/me/payslips');
    expect(safeNotificationPath('/app/rosters/schedule'), '/app/shift-swaps');
    // Paths the app already has are left alone, as are deeper ones it does not know about.
    expect(safeNotificationPath('/app/leave-applications'), '/app/leave-applications');
    expect(safeNotificationPath('/app/overtime-policies/abc'), '/app/overtime-policies/abc');
  });

  test('notificationAge', () {
    final now = DateTime.utc(2026, 11, 1, 12);
    expect(notificationAge('2026-11-01T11:59:50Z', now: now), 'just now');
    expect(notificationAge('2026-11-01T11:30:00Z', now: now), '30m ago');
    expect(notificationAge('2026-11-01T09:00:00Z', now: now), '3h ago');
    expect(notificationAge('2026-10-30T12:00:00Z', now: now), '2d ago');
  });

  testWidgets('bell shows the server unread count and refreshes on app resume', (tester) async {
    final repo = _Repo()..unread = 3;
    await tester.pumpWidget(_app(repo, home: Scaffold(body: Center(child: Consumer(builder: (c, r, _) => NotificationBell(onPressed: () {}))))));
    await tester.pumpAndSettle();
    expect(find.byKey(const Key('notification-badge')), findsOneWidget);
    expect(find.text('3'), findsOneWidget);

    final before = repo.countCalls;
    repo.unread = 0;
    tester.binding.handleAppLifecycleStateChanged(AppLifecycleState.resumed);
    await tester.pumpAndSettle();
    expect(repo.countCalls, greaterThan(before));
    expect(find.byKey(const Key('notification-badge')), findsNothing);
  });

  testWidgets('list: loading, then unread notification is visually distinct', (tester) async {
    final gate = Completer<void>();
    final repo = _Repo(items: [_json(), _json(id: 'n2', read: true, title: 'Older')], gate: gate);
    await tester.pumpWidget(_app(repo));
    await tester.pump();
    expect(find.byType(CircularProgressIndicator), findsOneWidget);
    gate.complete();
    await tester.pumpAndSettle();
    expect(find.text('Face Enrollment Requested'), findsOneWidget);
    expect(find.text('Older'), findsOneWidget);
    expect(find.byKey(const Key('unread-dot')), findsOneWidget); // only the unread one
    expect(find.text('Complete Face Enrollment →'), findsOneWidget);
  });

  testWidgets('empty and error states; error can retry', (tester) async {
    final empty = _Repo(items: []);
    await tester.pumpWidget(_app(empty));
    await tester.pumpAndSettle();
    expect(find.text('No notifications yet'), findsOneWidget);

    final failing = _Repo(failList: true);
    await tester.pumpWidget(_app(failing));
    await tester.pumpAndSettle();
    expect(find.text('Try again'), findsOneWidget);
    failing.failList = false;
    await tester.tap(find.text('Try again'));
    await tester.pumpAndSettle();
    expect(find.text('Face Enrollment Requested'), findsOneWidget);
  });

  testWidgets('tapping the face-enrollment notification marks it read and opens Face Attendance Setup', (tester) async {
    final repo = _Repo();
    final att = _AttRepo();
    await tester.pumpWidget(_app(repo, att: att));
    await tester.pumpAndSettle();
    await tester.tap(find.text('Face Enrollment Requested'));
    await tester.pumpAndSettle();
    expect(repo.read, ['n1']);
    // Landed on the setup screen, which read the canonical server status itself.
    expect(find.text('Face Attendance Setup'), findsWidgets);
    expect(att.statusCalls, 1);
    expect(find.text('Continue Enrollment'), findsOneWidget);
  });

  // The notification only says where to go. Each case: the notification (written when HR opened
  // the window) is still unread, the server state has since changed, the employee taps it.
  Future<_AttRepo> tapStale(WidgetTester tester, Map<String, dynamic> serverNow) async {
    final repo = _Repo();
    final att = _AttRepo(); // server state when the notification was created: window open
    await tester.pumpWidget(_app(repo, att: att));
    await tester.pumpAndSettle();
    att.status = serverNow; // ...then the server state changes before the employee taps
    await tester.tap(find.text('Face Enrollment Requested'));
    await tester.pumpAndSettle();
    expect(repo.read, ['n1']);
    expect(att.statusCalls, 1, reason: 'the destination re-reads the canonical state');
    expect(find.text('Face Attendance Setup'), findsWidgets);
    expect(find.text('Continue Enrollment'), findsNothing, reason: 'no stale open window is offered');
    expect(att.startCalls, 0, reason: 'opening the screen never starts anything');
    return att;
  }

  testWidgets('stale: HR cancelled the window - no enrollment is resumed from the old notification', (tester) async {
    await tapStale(tester, {'profile': null, 'open_window': null, 'enrollment_state': 'NOT_ENROLLED'});
    expect(find.text('Start Enrollment'), findsOneWidget); // current state: no window; the server decides on start
  });

  testWidgets('stale: the window expired - current state shown, no enrollment flow started', (tester) async {
    await tapStale(tester, {'profile': null, 'open_window': null, 'enrollment_state': 'NOT_ENROLLED'});
    expect(find.byType(CircularProgressIndicator), findsNothing);
    expect(find.text('Start Enrollment'), findsOneWidget);
  });

  testWidgets('stale: already enrolled - the enrolled state is shown, no enroll button', (tester) async {
    await tapStale(tester, {
      'profile': {'status': 'ENROLLED'},
      'open_window': null,
      'enrollment_state': 'ENROLLED',
    });
    expect(find.textContaining('Your face is enrolled'), findsOneWidget);
    expect(find.text('Start Enrollment'), findsNothing);
  });

  testWidgets('stale: submitted and pending HR approval - the pending state is shown', (tester) async {
    await tapStale(tester, {
      'profile': {'status': 'PENDING_APPROVAL'},
      'open_window': null,
      'enrollment_state': 'PENDING_APPROVAL',
    });
    expect(find.text('Face enrollment submitted'), findsOneWidget);
    expect(find.text('Start Enrollment'), findsNothing);
  });

  testWidgets('bell never crashes when no API client is provided', (tester) async {
    // Signed in (fake auth) but no api client override: apiClientProvider throws UnimplementedError.
    await tester.pumpWidget(ProviderScope(
      overrides: [fakeAuth(const [], employeeId: 'e-1')],
      child: MaterialApp(home: Scaffold(body: NotificationBell(onPressed: () {}))),
    ));
    await tester.pumpAndSettle();
    expect(tester.takeException(), isNull);
    expect(find.byIcon(Icons.notifications_none_rounded), findsOneWidget);
    expect(find.byKey(const Key('notification-badge')), findsNothing);
  });

  testWidgets('mark all as read, unread filter and pull to refresh', (tester) async {
    final repo = _Repo(items: [_json(), _json(id: 'n2', title: 'Second')]);
    repo.unread = 2;
    await tester.pumpWidget(_app(repo));
    await tester.pumpAndSettle();

    await tester.tap(find.text('Unread'));
    await tester.pumpAndSettle();
    expect(repo.lastUnreadOnly, isTrue);

    final calls = repo.listCalls;
    await tester.fling(find.byType(ListView).first, const Offset(0, 400), 1000);
    await tester.pumpAndSettle();
    expect(repo.listCalls, greaterThan(calls));

    await tester.tap(find.text('Mark all as read'));
    await tester.pumpAndSettle();
    expect(repo.readAllCalled, isTrue);
    expect(find.byKey(const Key('unread-dot')), findsNothing);
  });
}
