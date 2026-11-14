/// One row of `GET /notifications`. The server owns recipient, tenant and read state; the
/// notification only says where to go - screens it links to re-read the canonical state.
class AppNotification {
  const AppNotification({
    required this.id,
    required this.type,
    required this.title,
    required this.body,
    required this.isRead,
    required this.createdAt,
    this.actionUrl,
    this.actionLabel,
  });

  final String id;
  final String type;
  final String title;
  final String body;
  final bool isRead;
  final String createdAt;
  final String? actionUrl;
  final String? actionLabel;

  factory AppNotification.fromJson(dynamic json) {
    final m = json as Map<String, dynamic>;
    return AppNotification(
      id: m['id'] as String,
      type: m['type'] as String,
      title: m['title'] as String,
      body: m['body'] as String,
      isRead: m['is_read'] as bool,
      createdAt: m['created_at'] as String,
      actionUrl: m['action_url'] as String?,
      actionLabel: m['action_label'] as String?,
    );
  }

  AppNotification asRead() => AppNotification(
        id: id,
        type: type,
        title: title,
        body: body,
        isRead: true,
        createdAt: createdAt,
        actionUrl: actionUrl,
        actionLabel: actionLabel,
      );
}

/// The server only stores app-relative paths; refuse anything else before navigating. Mobile
/// additionally restricts to the app's own `/app/...` routes.
String? safeNotificationPath(String? url) {
  if (url == null || !url.startsWith('/app/') || url.startsWith('//') || url.contains('://')) return null;
  return mobileRouteFor(url);
}

/// Web paths whose screen lives at a different path in this app.
const _mobileAliases = {'/app/rosters/schedule': '/app/shift-swaps'};

/// List screens that have a web detail page (`<list>/<id>`) but no detail route here: a
/// notification about one item opens the list it sits in.
const _listOnlyOnMobile = [
  '/app/leave-applications',
  '/app/regularizations',
  '/app/overtime',
  '/app/onboarding',
  '/app/me/payslips',
];

/// A notification's `action_url` is the web path; this maps it onto a route this app has.
String mobileRouteFor(String path) {
  final alias = _mobileAliases[path];
  if (alias != null) return alias;
  for (final list in _listOnlyOnMobile) {
    if (path.startsWith('$list/') && !path.substring(list.length + 1).contains('/')) return list;
  }
  return path;
}

/// "just now", "5m ago", "3h ago", "2d ago", then a short date.
String notificationAge(String iso, {DateTime? now}) {
  final t = DateTime.tryParse(iso);
  if (t == null) return '';
  final d = (now ?? DateTime.now()).toUtc().difference(t.toUtc());
  if (d.isNegative || d.inMinutes < 1) return 'just now';
  if (d.inHours < 1) return '${d.inMinutes}m ago';
  if (d.inDays < 1) return '${d.inHours}h ago';
  if (d.inDays < 7) return '${d.inDays}d ago';
  const months = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
  final l = t.toLocal();
  return '${l.day} ${months[l.month - 1]} ${l.year}';
}
