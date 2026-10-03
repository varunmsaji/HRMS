import 'dart:async';
import 'dart:convert';

import 'package:flutter_secure_storage/flutter_secure_storage.dart';

import 'auth_types.dart';

/// Mirrors `apps/web/src/lib/auth/token-storage.ts`.
///
/// SEC-06 parity: the refresh token never passes through this class. On the
/// web app it's an HttpOnly cookie the browser handles automatically; here
/// it lives in the `Dio` client's persisted `PersistCookieJar` (see
/// `api_client.dart`), which behaves the same way for a native HTTP client —
/// this app's own code never reads or writes it. Only the short-lived access
/// token and non-sensitive session metadata are kept here, in secure storage
/// (the mobile equivalent of the web client's `localStorage` use, but backed
/// by Keychain/Keystore rather than plain prefs since there's no HttpOnly
/// cookie boundary protecting it on this side).
class StoredSession {
  StoredSession({
    required this.accessToken,
    required this.companyId,
    required this.companies,
    required this.expiresAt,
  });

  final String accessToken;
  final String companyId;
  final List<CompanySummary> companies;

  /// Epoch ms.
  final int expiresAt;

  factory StoredSession.fromTokenResponse(TokenResponseData data) => StoredSession(
        accessToken: data.accessToken,
        companyId: data.companyId,
        companies: data.companies,
        expiresAt: DateTime.now().millisecondsSinceEpoch + data.expiresInMinutes * 60000,
      );

  factory StoredSession.fromJson(Map<String, dynamic> json) => StoredSession(
        accessToken: json['accessToken'] as String,
        companyId: json['companyId'] as String,
        companies: (json['companies'] as List)
            .map((e) => CompanySummary.fromJson(e as Map<String, dynamic>))
            .toList(),
        expiresAt: json['expiresAt'] as int,
      );

  Map<String, dynamic> toJson() => {
        'accessToken': accessToken,
        'companyId': companyId,
        'companies': companies
            .map((c) => {'id': c.id, 'name': c.name, 'is_primary': c.isPrimary})
            .toList(),
        'expiresAt': expiresAt,
      };
}

class TokenStorage {
  TokenStorage._();
  static final TokenStorage instance = TokenStorage._();

  static const _storageKey = 'hrms.session';
  final _storage = const FlutterSecureStorage();

  /// Lets the API client (a plain class, not a widget) tell the auth layer the
  /// session died mid-request (refresh failed) without an import cycle —
  /// mirrors the web client's `window.dispatchEvent(SESSION_EXPIRED_EVENT)`.
  final _sessionExpiredController = StreamController<void>.broadcast();
  Stream<void> get onSessionExpired => _sessionExpiredController.stream;

  Future<StoredSession?> load() async {
    final raw = await _storage.read(key: _storageKey);
    if (raw == null) return null;
    try {
      return StoredSession.fromJson(jsonDecode(raw) as Map<String, dynamic>);
    } catch (_) {
      return null;
    }
  }

  Future<void> save(StoredSession session) async {
    await _storage.write(key: _storageKey, value: jsonEncode(session.toJson()));
  }

  Future<void> clear() async {
    await _storage.delete(key: _storageKey);
  }

  void notifySessionExpired() {
    _sessionExpiredController.add(null);
  }
}
