import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:hrms_mobile/core/auth/auth_types.dart';
import 'package:hrms_mobile/features/auth/state/auth_controller.dart';
import 'package:hrms_mobile/features/auth/state/auth_state.dart';

class _FakeAuthController extends StateNotifier<AuthState> implements AuthController {
  _FakeAuthController(super.state);

  @override
  dynamic noSuchMethod(Invocation invocation) => super.noSuchMethod(invocation);
}

/// Overrides [authControllerProvider] with a signed-in user holding [permissions] — no secure
/// storage or network, so permission-gated screens can be widget-tested.
Override fakeAuth(List<String> permissions, {String? employeeId}) => authControllerProvider.overrideWith(
      (ref) => _FakeAuthController(AuthState(
        status: AuthStatus.authenticated,
        user: UserProfile(
          id: 'u-1',
          email: 'hr@example.com',
          companyId: 'c-1',
          employeeId: employeeId,
          permissions: permissions,
          companyTimezone: 'Asia/Kolkata',
        ),
      )),
    );
