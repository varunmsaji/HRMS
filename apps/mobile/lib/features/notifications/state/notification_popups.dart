import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../auth/state/auth_controller.dart';
import '../data/notification_repository.dart';
import '../domain/app_notification.dart';
import 'unread_count.dart';

/// How often the app checks for new notifications while it is in the foreground. A backgrounded
/// app is never polled; it checks again as soon as it returns to the foreground.
const notificationPollInterval = Duration(seconds: 30);

/// How long an in-app banner stays up before it slides away on its own.
const notificationBannerDuration = Duration(seconds: 6);

/// The banner currently on screen: the newest new notification, plus how many others arrived
/// with it (shown as "+N more" and reachable from the notifications screen).
class NotificationPopup {
  const NotificationPopup(this.notification, {this.others = 0});
  final AppNotification notification;
  final int others;
}

/// Watches the signed-in user's unread notifications and raises an in-app banner for each one
/// that arrives while the app is open.
///
/// The first successful check after sign-in only records what is already unread - those are
/// already on the bell's badge, so they do not pop up on every app start. After that, any unread
/// notification not seen before is announced. The same check keeps the bell's badge current.
class NotificationPopupController extends StateNotifier<NotificationPopup?> {
  NotificationPopupController(this._repo, this._unread) : super(null);

  final NotificationRepository? _repo;
  final UnreadCountNotifier? _unread;
  final Set<String> _seen = {};
  bool _primed = false;
  bool _checking = false;
  bool _disposed = false;

  /// [announce] false records new notifications without showing a banner (used while the user is
  /// already looking at the notifications screen).
  Future<void> check({bool announce = true}) async {
    final repo = _repo;
    if (repo == null || _checking || _disposed) return;
    _checking = true;
    try {
      final env = await repo.list(perPage: 10, unreadOnly: true);
      if (_disposed) return;
      final fresh = env.data.where((n) => !_seen.contains(n.id)).toList();
      _seen.addAll(env.data.map((n) => n.id));
      final total = env.pagination?.total;
      if (total != null) {
        _unread?.set(total);
      } else {
        await _unread?.refresh();
      }
      if (_primed && announce && fresh.isNotEmpty) {
        // The server lists newest first.
        state = NotificationPopup(fresh.first, others: fresh.length - 1);
      }
      _primed = true;
    } catch (_) {
      // A background check must never surface an error; the next one retries.
    } finally {
      _checking = false;
    }
  }

  /// Hides the banner. [id] guards against an old auto-hide timer hiding a newer banner.
  void dismiss([String? id]) {
    if (_disposed) return;
    if (id == null || state?.notification.id == id) state = null;
  }

  /// Marks the banner's notification read (best effort) and hides the banner.
  Future<void> markRead(AppNotification n) async {
    dismiss(n.id);
    final repo = _repo;
    if (repo == null) return;
    try {
      await repo.markRead(n.id);
    } catch (_) {/* opening the screen must not depend on it */}
    await _unread?.refresh();
  }

  @override
  void dispose() {
    _disposed = true;
    super.dispose();
  }
}

/// Keyed on the signed-in user (through [unreadCountProvider]), so a new login starts fresh and
/// never announces the previous user's notifications.
final notificationPopupProvider = StateNotifierProvider<NotificationPopupController, NotificationPopup?>((ref) {
  final userId = ref.watch(authControllerProvider.select((s) => s.user?.id));
  if (userId == null) return NotificationPopupController(null, null);
  NotificationRepository? repo;
  try {
    repo = ref.watch(notificationRepositoryProvider);
  } on UnimplementedError {
    repo = null; // no API client yet (see unreadCountProvider)
  }
  return NotificationPopupController(repo, ref.watch(unreadCountProvider.notifier));
});
