import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../auth/state/auth_controller.dart';
import '../data/notification_repository.dart';

/// The bell's unread badge. The count always comes from the server; it is fetched when the
/// signed-in user changes (app start, login), and re-fetched by [refresh] (app resume, opening the
/// notification screen, Home pull-to-refresh). No polling. A failed read keeps the last count.
class UnreadCountNotifier extends StateNotifier<int> {
  UnreadCountNotifier(this._repo, {required bool signedIn}) : super(0) {
    if (signedIn) refresh();
  }

  /// Null when no API client has been provided (not yet initialised, or omitted in a test):
  /// the badge then simply stays at 0 instead of crashing the screen the bell sits on.
  final NotificationRepository? _repo;
  bool _disposed = false;

  Future<void> refresh() async {
    final repo = _repo;
    if (repo == null) return;
    try {
      final count = await repo.unreadCount();
      if (!_disposed) state = count;
    } catch (_) {
      // A badge read must never break the screen it sits on.
    }
  }

  void set(int count) {
    if (!_disposed) state = count < 0 ? 0 : count;
  }

  @override
  void dispose() {
    _disposed = true;
    super.dispose();
  }
}

/// Keyed on the signed-in user, so logging out/in never shows the previous user's badge.
final unreadCountProvider = StateNotifierProvider<UnreadCountNotifier, int>((ref) {
  final userId = ref.watch(authControllerProvider.select((s) => s.user?.id));
  NotificationRepository? repo;
  try {
    repo = ref.watch(notificationRepositoryProvider);
  } on UnimplementedError {
    // `apiClientProvider` is overridden in main() once the client resolves; until then (or in a
    // test that omits it) there is no notification API. Only that specific case is tolerated -
    // every other error still surfaces.
    repo = null;
  }
  return UnreadCountNotifier(repo, signedIn: userId != null);
});
