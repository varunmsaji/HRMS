import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../auth/state/auth_controller.dart';
import '../../auth/state/auth_state.dart';
import '../data/notification_repository.dart';
import '../domain/app_notification.dart';
import '../push/push_messaging.dart';
import '../state/notification_popups.dart';

const _notificationsPath = '/app/notifications';

/// Sits above the app's navigator (via `MaterialApp.router`'s `builder`) and owns the
/// notification check: every [notificationPollInterval] while the app is in the foreground, and
/// straight away when it returns to the foreground. A new notification slides a banner in from the
/// top; tapping it opens the linked screen (or the notifications screen), swiping it up or waiting
/// [notificationBannerDuration] hides it.
class NotificationPopupHost extends ConsumerStatefulWidget {
  const NotificationPopupHost({super.key, required this.router, required this.child});
  final GoRouter router;
  final Widget child;

  @override
  ConsumerState<NotificationPopupHost> createState() => _NotificationPopupHostState();
}

class _NotificationPopupHostState extends ConsumerState<NotificationPopupHost> with WidgetsBindingObserver {
  Timer? _poll;
  Timer? _autoHide;
  StreamSubscription<PushTap>? _tapSub;
  StreamSubscription<void>? _foregroundSub;

  /// A tapped push waiting for sign-in to finish (a cold start from a push lands here first).
  PushTap? _pendingTap;

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addObserver(this);
    _startPolling();
    WidgetsBinding.instance.addPostFrameCallback((_) => _check());
    final push = ref.read(pushMessagingProvider);
    _tapSub = push.onTap.listen(_onPushTap);
    // A push while the app is open shows no system alert: refresh now rather than at the next poll.
    _foregroundSub = push.onForegroundMessage.listen((_) => _check());
    unawaited(push.launchTap().then((t) {
      if (t != null) _onPushTap(t);
    }));
  }

  void _onPushTap(PushTap tap) {
    if (!mounted) return;
    _pendingTap = tap;
    _openPendingTap();
  }

  /// Opens the tapped push's screen once the user is signed in; until then it waits.
  void _openPendingTap() {
    final tap = _pendingTap;
    if (tap == null || ref.read(authControllerProvider).status != AuthStatus.authenticated) return;
    _pendingTap = null;
    final id = tap.notificationId;
    if (id != null) unawaited(ref.read(notificationRepositoryProvider).markRead(id).catchError((_) {}));
    widget.router.push(safeNotificationPath(tap.actionUrl) ?? _notificationsPath);
    _check();
  }

  @override
  void dispose() {
    _poll?.cancel();
    _autoHide?.cancel();
    _tapSub?.cancel();
    _foregroundSub?.cancel();
    WidgetsBinding.instance.removeObserver(this);
    super.dispose();
  }

  void _startPolling() {
    _poll?.cancel();
    _poll = Timer.periodic(notificationPollInterval, (_) => _check());
  }

  String? get _currentPath {
    try {
      return widget.router.routerDelegate.currentConfiguration.uri.path;
    } catch (_) {
      return null;
    }
  }

  void _check() {
    if (!mounted) return;
    // Someone already reading the notifications screen does not need a banner on top of it.
    ref.read(notificationPopupProvider.notifier).check(announce: _currentPath != _notificationsPath);
  }

  @override
  void didChangeAppLifecycleState(AppLifecycleState state) {
    if (state == AppLifecycleState.resumed) {
      _check();
      _startPolling();
    } else if (state == AppLifecycleState.paused || state == AppLifecycleState.hidden) {
      _poll?.cancel();
      _poll = null;
    }
  }

  Future<void> _open(NotificationPopup popup) async {
    final n = popup.notification;
    final controller = ref.read(notificationPopupProvider.notifier);
    if (popup.others > 0) {
      controller.dismiss(n.id);
      widget.router.push(_notificationsPath);
      return;
    }
    final path = safeNotificationPath(n.actionUrl) ?? _notificationsPath;
    unawaited(controller.markRead(n));
    widget.router.push(path);
  }

  @override
  Widget build(BuildContext context) {
    ref.listen<AuthState>(authControllerProvider, (_, __) => _openPendingTap());
    // A new user (login/logout) gets a new controller; check for them straight away.
    ref.listen(notificationPopupProvider.notifier, (_, __) => WidgetsBinding.instance.addPostFrameCallback((_) => _check()));
    ref.listen<NotificationPopup?>(notificationPopupProvider, (_, next) {
      _autoHide?.cancel();
      if (next != null) {
        final id = next.notification.id;
        _autoHide = Timer(notificationBannerDuration, () {
          if (mounted) ref.read(notificationPopupProvider.notifier).dismiss(id);
        });
      }
    });
    final popup = ref.watch(notificationPopupProvider);
    return Stack(children: [
      widget.child,
      Positioned(
        top: 0,
        left: 0,
        right: 0,
        child: SafeArea(
          bottom: false,
          child: AnimatedSwitcher(
            duration: const Duration(milliseconds: 250),
            transitionBuilder: (child, animation) => SlideTransition(
              position: Tween(begin: const Offset(0, -1.2), end: Offset.zero).animate(CurvedAnimation(parent: animation, curve: Curves.easeOutCubic)),
              child: FadeTransition(opacity: animation, child: child),
            ),
            child: popup == null
                ? const SizedBox.shrink(key: ValueKey('no-popup'))
                : _Banner(
                    key: ValueKey(popup.notification.id),
                    popup: popup,
                    onTap: () => _open(popup),
                    onDismiss: () => ref.read(notificationPopupProvider.notifier).dismiss(popup.notification.id),
                  ),
          ),
        ),
      ),
    ]);
  }
}

class _Banner extends StatelessWidget {
  const _Banner({super.key, required this.popup, required this.onTap, required this.onDismiss});
  final NotificationPopup popup;
  final VoidCallback onTap;
  final VoidCallback onDismiss;

  @override
  Widget build(BuildContext context) {
    final scheme = Theme.of(context).colorScheme;
    final n = popup.notification;
    return Dismissible(
      key: ValueKey('popup-${n.id}'),
      direction: DismissDirection.up,
      onDismissed: (_) => onDismiss(),
      child: Padding(
        padding: const EdgeInsets.fromLTRB(12, 8, 12, 0),
        child: Semantics(
          liveRegion: true,
          label: 'New notification',
          child: Material(
            key: const Key('notification-popup'),
            elevation: 6,
            color: scheme.surface,
            surfaceTintColor: scheme.surfaceTint,
            borderRadius: BorderRadius.circular(16),
            clipBehavior: Clip.antiAlias,
            child: InkWell(
              onTap: onTap,
              child: Padding(
                padding: const EdgeInsets.fromLTRB(14, 12, 4, 12),
                child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
                  Container(
                    width: 36,
                    height: 36,
                    decoration: BoxDecoration(color: scheme.primaryContainer, shape: BoxShape.circle),
                    child: Icon(Icons.notifications_active_rounded, size: 20, color: scheme.onPrimaryContainer),
                  ),
                  const SizedBox(width: 12),
                  Expanded(
                    child: Column(crossAxisAlignment: CrossAxisAlignment.start, mainAxisSize: MainAxisSize.min, children: [
                      Text(n.title, maxLines: 1, overflow: TextOverflow.ellipsis, style: TextStyle(fontWeight: FontWeight.w700, fontSize: 14, color: scheme.onSurface)),
                      const SizedBox(height: 2),
                      Text(n.body, maxLines: 2, overflow: TextOverflow.ellipsis, style: TextStyle(fontSize: 13, color: scheme.onSurfaceVariant)),
                      if (popup.others > 0) ...[
                        const SizedBox(height: 4),
                        Text('+${popup.others} more', style: TextStyle(fontSize: 12, fontWeight: FontWeight.w600, color: scheme.primary)),
                      ],
                    ]),
                  ),
                  // No tooltip: the banner sits above the navigator, where there is no Overlay.
                  Semantics(
                    label: 'Dismiss',
                    button: true,
                    child: IconButton(
                      key: const Key('notification-popup-dismiss'),
                      visualDensity: VisualDensity.compact,
                      icon: Icon(Icons.close_rounded, size: 18, color: scheme.onSurfaceVariant),
                      onPressed: onDismiss,
                    ),
                  ),
                ]),
              ),
            ),
          ),
        ),
      ),
    );
  }
}
