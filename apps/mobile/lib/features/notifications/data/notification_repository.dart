import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../core/api/api_client.dart';
import '../../../core/api/envelope.dart';
import '../../../core/providers.dart';
import '../domain/app_notification.dart';

/// Thin wrapper over the same `/notifications` API the web uses; every call acts on the signed-in
/// user's own notifications (the server derives the recipient from the token).
class NotificationRepository {
  NotificationRepository(this._client);
  final ApiClient _client;

  Future<ListEnvelope<AppNotification>> list({int page = 1, int perPage = 20, bool unreadOnly = false}) => _client.getList<AppNotification>(
        '/notifications',
        parseItem: AppNotification.fromJson,
        query: PageQuery(page: page, perPage: perPage),
        filters: {if (unreadOnly) 'unread_only': 'true'},
      );

  Future<int> unreadCount() => _client.get<int>('/notifications/unread-count', parse: (d) => (d as Map<String, dynamic>)['unread_count'] as int);

  Future<void> markRead(String id) => _client.patch<void>('/notifications/$id/read', parse: (_) {});

  /// Returns the unread count after the update.
  Future<int> markAllRead() => _client.post<int>('/notifications/read-all', body: const {}, parse: (d) => (d as Map<String, dynamic>)['unread_count'] as int);
}

final notificationRepositoryProvider = Provider<NotificationRepository>((ref) => NotificationRepository(ref.watch(apiClientProvider)));
