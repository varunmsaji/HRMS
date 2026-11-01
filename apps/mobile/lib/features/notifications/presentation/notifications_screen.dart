import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../../core/api/api_error.dart';
import '../data/notification_repository.dart';
import '../domain/app_notification.dart';
import '../state/unread_count.dart';

/// The full notification list: newest first, All/Unread, pull to refresh, load more on scroll.
class NotificationsScreen extends ConsumerStatefulWidget {
  const NotificationsScreen({super.key});

  @override
  ConsumerState<NotificationsScreen> createState() => _NotificationsScreenState();
}

class _NotificationsScreenState extends ConsumerState<NotificationsScreen> {
  static const _perPage = 20;
  final _scroll = ScrollController();
  final _items = <AppNotification>[];
  bool _unreadOnly = false;
  bool _loading = true;
  bool _loadingMore = false;
  bool _hasMore = false;
  int _page = 1;
  String? _error;

  @override
  void initState() {
    super.initState();
    _scroll.addListener(() {
      if (_scroll.position.pixels > _scroll.position.maxScrollExtent - 200) _loadMore();
    });
    _reload();
  }

  @override
  void dispose() {
    _scroll.dispose();
    super.dispose();
  }

  Future<void> _reload() async {
    setState(() {
      _loading = _items.isEmpty;
      _error = null;
    });
    try {
      final env = await ref.read(notificationRepositoryProvider).list(page: 1, perPage: _perPage, unreadOnly: _unreadOnly);
      if (!mounted) return;
      setState(() {
        _items
          ..clear()
          ..addAll(env.data);
        _page = 1;
        _hasMore = env.pagination != null && env.pagination!.page < env.pagination!.totalPages;
      });
      ref.read(unreadCountProvider.notifier).refresh();
    } catch (e) {
      if (mounted) setState(() => _error = describeApiError(e));
    } finally {
      if (mounted) setState(() => _loading = false);
    }
  }

  Future<void> _loadMore() async {
    if (_loadingMore || !_hasMore || _loading) return;
    setState(() => _loadingMore = true);
    try {
      final env = await ref.read(notificationRepositoryProvider).list(page: _page + 1, perPage: _perPage, unreadOnly: _unreadOnly);
      if (!mounted) return;
      final known = _items.map((n) => n.id).toSet();
      setState(() {
        _items.addAll(env.data.where((n) => !known.contains(n.id)));
        _page += 1;
        _hasMore = env.pagination != null && env.pagination!.page < env.pagination!.totalPages;
      });
    } catch (_) {
      // Keep what is shown; the next scroll retries.
    } finally {
      if (mounted) setState(() => _loadingMore = false);
    }
  }

  Future<void> _open(AppNotification n) async {
    final path = safeNotificationPath(n.actionUrl);
    final repo = ref.read(notificationRepositoryProvider);
    if (!n.isRead) {
      // Persist "read" first (best effort) so the badge is right when the user comes back.
      try {
        await repo.markRead(n.id);
        if (mounted) {
          setState(() {
            final i = _items.indexWhere((x) => x.id == n.id);
            if (i >= 0) _items[i] = n.asRead();
          });
        }
      } catch (_) {/* navigation must not depend on it */}
      ref.read(unreadCountProvider.notifier).refresh();
    }
    if (path != null && mounted) {
      await context.push(path);
      if (mounted) ref.read(unreadCountProvider.notifier).refresh();
    }
  }

  Future<void> _markAll() async {
    try {
      final unread = await ref.read(notificationRepositoryProvider).markAllRead();
      ref.read(unreadCountProvider.notifier).set(unread);
      await _reload();
    } catch (e) {
      if (mounted) ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(describeApiError(e))));
    }
  }

  @override
  Widget build(BuildContext context) {
    final unread = ref.watch(unreadCountProvider);
    return Scaffold(
      appBar: AppBar(
        title: const Text('Notifications'),
        actions: [TextButton(onPressed: unread > 0 ? _markAll : null, child: const Text('Mark all as read'))],
      ),
      body: Column(children: [
        Padding(
          padding: const EdgeInsets.fromLTRB(16, 8, 16, 4),
          child: SegmentedButton<bool>(
            segments: const [ButtonSegment(value: false, label: Text('All')), ButtonSegment(value: true, label: Text('Unread'))],
            selected: {_unreadOnly},
            onSelectionChanged: (s) {
              setState(() => _unreadOnly = s.first);
              _reload();
            },
          ),
        ),
        Expanded(child: _body()),
      ]),
    );
  }

  Widget _body() {
    if (_loading) return const Center(child: CircularProgressIndicator());
    if (_error != null) {
      return Center(
        child: Padding(
          padding: const EdgeInsets.all(24),
          child: Column(mainAxisSize: MainAxisSize.min, children: [
            Text(_error!, textAlign: TextAlign.center),
            const SizedBox(height: 12),
            OutlinedButton(onPressed: _reload, child: const Text('Try again')),
          ]),
        ),
      );
    }
    return RefreshIndicator(
      onRefresh: _reload,
      child: _items.isEmpty
          ? ListView(controller: _scroll, physics: const AlwaysScrollableScrollPhysics(), children: [
              const SizedBox(height: 120),
              Icon(Icons.notifications_none_rounded, size: 48, color: Theme.of(context).disabledColor),
              const SizedBox(height: 12),
              Center(child: Text(_unreadOnly ? 'No unread notifications' : 'No notifications yet')),
            ])
          : ListView.separated(
              controller: _scroll,
              physics: const AlwaysScrollableScrollPhysics(),
              itemCount: _items.length + (_loadingMore ? 1 : 0),
              separatorBuilder: (_, __) => const Divider(height: 1),
              itemBuilder: (context, i) => i == _items.length
                  ? const Padding(padding: EdgeInsets.all(16), child: Center(child: CircularProgressIndicator()))
                  : _NotificationTile(notification: _items[i], onTap: () => _open(_items[i])),
            ),
    );
  }
}

class _NotificationTile extends StatelessWidget {
  const _NotificationTile({required this.notification, required this.onTap});
  final AppNotification notification;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    final n = notification;
    final scheme = Theme.of(context).colorScheme;
    return Material(
      color: n.isRead ? Colors.transparent : scheme.primary.withValues(alpha: 0.06),
      child: InkWell(
        onTap: onTap,
        child: Padding(
          padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 12),
          child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
            CircleAvatar(
              radius: 18,
              backgroundColor: n.isRead ? scheme.surfaceContainerHighest : scheme.primary.withValues(alpha: 0.12),
              child: Icon(n.type == 'FACE_ENROLLMENT_REQUESTED' ? Icons.face_retouching_natural : Icons.notifications_none_rounded, size: 20, color: n.isRead ? scheme.onSurfaceVariant : scheme.primary),
            ),
            const SizedBox(width: 12),
            Expanded(
              child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
                  Expanded(child: Text(n.title, style: TextStyle(fontWeight: n.isRead ? FontWeight.w500 : FontWeight.w700))),
                  if (!n.isRead) Container(key: const Key('unread-dot'), margin: const EdgeInsets.only(top: 6, left: 8), width: 8, height: 8, decoration: BoxDecoration(color: scheme.primary, shape: BoxShape.circle)),
                ]),
                const SizedBox(height: 2),
                Text(n.body, style: TextStyle(fontSize: 13, color: scheme.onSurfaceVariant)),
                const SizedBox(height: 4),
                Row(children: [
                  Text(notificationAge(n.createdAt), style: TextStyle(fontSize: 11, color: scheme.onSurfaceVariant)),
                  if (!n.isRead && n.actionLabel != null) ...[
                    const SizedBox(width: 8),
                    Flexible(child: Text('${n.actionLabel} →', overflow: TextOverflow.ellipsis, style: TextStyle(fontSize: 11, fontWeight: FontWeight.w600, color: scheme.primary))),
                  ],
                ]),
              ]),
            ),
          ]),
        ),
      ),
    );
  }
}
