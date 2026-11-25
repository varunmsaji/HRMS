import 'dart:async';

import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../core/auth/auth_types.dart';
import '../../../core/auth/token_storage.dart';
import '../../../core/providers.dart';
import '../../notifications/push/push_registration.dart';
import '../data/auth_repository.dart';
import 'auth_state.dart';
import '../../../core/diagnostics/app_diagnostics.dart';

/// Mirrors `apps/web/src/lib/auth/auth-context.tsx`'s `AuthProvider` — loads
/// any persisted session on startup, resolves `/auth/me`, and reacts to
/// `TokenStorage`'s session-expired signal (the mobile equivalent of the web
/// client's `window.dispatchEvent(SESSION_EXPIRED_EVENT)`).
class AuthController extends StateNotifier<AuthState> {
  AuthController(this._repository, {Future<void> Function()? beforeLogout}) : _beforeLogout = beforeLogout, super(AuthState.initial) {
    _sessionExpiredSubscription = TokenStorage.instance.onSessionExpired.listen((_) {
      state = AuthState(status: AuthStatus.unauthenticated, sessionExpired: true, expiredUserId: state.user?.id);
    });
    unawaited(_init());
  }

  final AuthRepository _repository;

  /// Runs while the session is still valid, just before sign-out (e.g. to stop push to this phone).
  /// Never allowed to block or fail the sign-out.
  final Future<void> Function()? _beforeLogout;
  late final StreamSubscription<void> _sessionExpiredSubscription;

  Future<void> _init() async {
    final existing = await TokenStorage.instance.load();
    if (existing == null) {
      state = const AuthState(status: AuthStatus.unauthenticated);
      return;
    }
    await _loadCurrentUser(existing);
  }

  /// Returns the freshly-loaded profile — callers that need to redirect based
  /// on permissions right after login can't rely on `state.user`, since a
  /// state update from inside this async method isn't visible to that same
  /// call's caller until the next microtask.
  Future<UserProfile?> _loadCurrentUser(StoredSession session) async {
    try {
      final user = await _repository.me();
      state = AuthState(status: AuthStatus.authenticated, session: session, user: user);
      return user;
    } catch (_) {
      // A 401 whose refresh attempt also failed already cleared the session and notified
      // the session-expired stream (which set status "unauthenticated"). Don't clobber that
      // back to "authenticated" here — only a non-auth failure (network blip) should leave
      // the caller authenticated with no profile loaded yet.
      if (await TokenStorage.instance.load() == null) return null;
      state = AuthState(status: AuthStatus.authenticated, session: session, user: null);
      return null;
    }
  }

  /// Registration and invite-acceptance already return an authenticated
  /// session — no separate login step.
  Future<UserProfile?> applyTokenResponse(TokenResponseData data) async {
    final session = StoredSession.fromTokenResponse(data);
    await TokenStorage.instance.save(session);
    return _loadCurrentUser(session);
  }

  Future<UserProfile?> login({
    String? email,
    String? companyCode,
    String? employeeCode,
    required String password,
  }) async {
    final data = await _repository.login(
      email: email,
      companyCode: companyCode,
      employeeCode: employeeCode,
      password: password,
    );
    return applyTokenResponse(data);
  }

  Future<void> logout() async {
    try {
      await _beforeLogout?.call();
    } catch (e, s) { AppDiagnostics.instance.recordHandled(e, s); }
    try {
      await _repository.logout();
    } catch (e, s) {
      // Best-effort server-side revoke — the client-side session is cleared regardless.
      AppDiagnostics.instance.recordHandled(e, s);
    } finally {
      await TokenStorage.instance.clear();
      state = const AuthState(status: AuthStatus.unauthenticated);
    }
  }

  @override
  void dispose() {
    _sessionExpiredSubscription.cancel();
    super.dispose();
  }
}

final authRepositoryProvider = Provider<AuthRepository>(
  (ref) => AuthRepository(ref.watch(apiClientProvider)),
);

final authControllerProvider = StateNotifierProvider<AuthController, AuthState>(
  (ref) => AuthController(
    ref.watch(authRepositoryProvider),
    // Read lazily, at sign-out, so this provider does not depend on push at start-up.
    beforeLogout: () => ref.read(pushRegistrationProvider).unregister(),
  ),
);
