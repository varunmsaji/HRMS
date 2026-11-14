import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../state/unread_count.dart';

/// The app-bar bell with the server's unread badge. Refreshes the count when the app returns to
/// the foreground, and every [notificationPollInterval] while the app is in the foreground, so a
/// new approval request or decision shows up without pulling to refresh. A backgrounded app is
/// never polled.
const notificationPollInterval = Duration(seconds: 60);

class NotificationBell extends ConsumerStatefulWidget {
  const NotificationBell({super.key, required this.onPressed, this.color = const Color(0xFF0B1D4D)});
  final VoidCallback onPressed;
  final Color color;

  @override
  ConsumerState<NotificationBell> createState() => _NotificationBellState();
}

class _NotificationBellState extends ConsumerState<NotificationBell> with WidgetsBindingObserver {
  Timer? _poll;

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addObserver(this);
    _startPolling();
  }

  @override
  void dispose() {
    _poll?.cancel();
    WidgetsBinding.instance.removeObserver(this);
    super.dispose();
  }

  void _startPolling() {
    _poll?.cancel();
    _poll = Timer.periodic(notificationPollInterval, (_) {
      if (mounted) ref.read(unreadCountProvider.notifier).refresh();
    });
  }

  @override
  void didChangeAppLifecycleState(AppLifecycleState state) {
    if (state == AppLifecycleState.resumed) {
      ref.read(unreadCountProvider.notifier).refresh();
      _startPolling();
    } else if (state == AppLifecycleState.paused || state == AppLifecycleState.hidden) {
      _poll?.cancel();
      _poll = null;
    }
  }

  @override
  Widget build(BuildContext context) {
    final unread = ref.watch(unreadCountProvider);
    return IconButton(
      tooltip: unread > 0 ? 'Notifications, $unread unread' : 'Notifications',
      onPressed: widget.onPressed,
      icon: Stack(clipBehavior: Clip.none, children: [
        Icon(Icons.notifications_none_rounded, size: 26, color: widget.color),
        if (unread > 0)
          Positioned(
            right: -4,
            top: -3,
            child: Container(
              key: const Key('notification-badge'),
              constraints: const BoxConstraints(minWidth: 16, minHeight: 16),
              padding: const EdgeInsets.symmetric(horizontal: 4),
              decoration: BoxDecoration(color: const Color(0xFFDC2626), borderRadius: BorderRadius.circular(8), border: Border.all(color: Colors.white, width: 1.5)),
              alignment: Alignment.center,
              child: Text(unread > 99 ? '99+' : '$unread', style: const TextStyle(color: Colors.white, fontSize: 10, fontWeight: FontWeight.w700, height: 1.1)),
            ),
          ),
      ]),
    );
  }
}
