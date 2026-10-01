import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../../core/api/api_error.dart';
import '../state/auth_controller.dart';
import 'widgets/auth_form_field.dart';
import 'widgets/auth_scaffold.dart';

enum _Status { verifying, success, error }

/// Mirrors `apps/web/src/app/verify-email/[token]/page.tsx` — fires the
/// single-use verification call once on entry.
class VerifyEmailScreen extends ConsumerStatefulWidget {
  const VerifyEmailScreen({super.key, required this.token});

  final String token;

  @override
  ConsumerState<VerifyEmailScreen> createState() => _VerifyEmailScreenState();
}

class _VerifyEmailScreenState extends ConsumerState<VerifyEmailScreen> {
  _Status _status = _Status.verifying;
  String? _errorMessage;

  @override
  void initState() {
    super.initState();
    _verify();
  }

  Future<void> _verify() async {
    try {
      await ref.read(authRepositoryProvider).verifyEmail(widget.token);
      if (mounted) setState(() => _status = _Status.success);
    } catch (error) {
      if (!mounted) return;
      setState(() {
        _status = _Status.error;
        _errorMessage = error is ApiError && error.status == 401
            ? 'This verification link is invalid or has expired.'
            : 'Something went wrong. Please try again.';
      });
    }
  }

  @override
  Widget build(BuildContext context) {
    switch (_status) {
      case _Status.verifying:
        return const AuthScaffold(title: 'Verifying your email', child: Text('One moment…', textAlign: TextAlign.center));
      case _Status.success:
        return AuthScaffold(
          title: 'Email verified',
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              const Text('Your email address has been confirmed. You can now sign in.', textAlign: TextAlign.center),
              const SizedBox(height: 24),
              PrimaryButton(label: 'Go to sign in', loading: false, onPressed: () => context.go('/login')),
            ],
          ),
        );
      case _Status.error:
        return AuthScaffold(
          title: 'Verification failed',
          footer: Wrap(
            alignment: WrapAlignment.center,
            children: [
              const Text('Need a new link? '),
              GestureDetector(
                onTap: () => context.go('/login'),
                child: Text(
                  'Sign in to request one',
                  style: TextStyle(color: Theme.of(context).colorScheme.primary, fontWeight: FontWeight.w600),
                ),
              ),
            ],
          ),
          child: InlineAlert(message: _errorMessage ?? 'Something went wrong.'),
        );
    }
  }
}
