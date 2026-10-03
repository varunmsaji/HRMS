import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../state/auth_controller.dart';
import 'widgets/auth_form_field.dart';
import 'widgets/auth_scaffold.dart';

/// Mirrors `apps/web/src/app/forgot-password/page.tsx` — always shows the
/// same "check your email" message whether or not the address matches an
/// account (the API deliberately never discloses account existence here).
class ForgotPasswordScreen extends ConsumerStatefulWidget {
  const ForgotPasswordScreen({super.key});

  @override
  ConsumerState<ForgotPasswordScreen> createState() => _ForgotPasswordScreenState();
}

class _ForgotPasswordScreenState extends ConsumerState<ForgotPasswordScreen> {
  final _emailController = TextEditingController();
  String? _error;
  bool _submitting = false;
  bool _sent = false;

  @override
  void dispose() {
    _emailController.dispose();
    super.dispose();
  }

  Future<void> _submit() async {
    setState(() => _error = null);
    final email = _emailController.text.trim();
    if (email.isEmpty) {
      setState(() => _error = 'Enter your email address.');
      return;
    }

    setState(() => _submitting = true);
    try {
      await ref.read(authRepositoryProvider).forgotPassword(email);
    } finally {
      if (mounted) setState(() => _submitting = false);
      if (mounted) setState(() => _sent = true);
    }
  }

  @override
  Widget build(BuildContext context) {
    if (_sent) {
      return AuthScaffold(
        title: 'Check your email',
        child: Text(
          "If an account exists for ${_emailController.text.trim()}, we've sent a link to reset "
          'your password. It expires in 2 hours.',
          textAlign: TextAlign.center,
        ),
      );
    }

    return AuthScaffold(
      title: 'Forgot your password?',
      description: "Enter your email and we'll send you a reset link.",
      footer: Wrap(
        alignment: WrapAlignment.center,
        children: [
          const Text('Remembered it? '),
          GestureDetector(
            onTap: () => context.go('/login'),
            child: Text('Sign in', style: TextStyle(color: Theme.of(context).colorScheme.primary, fontWeight: FontWeight.w600)),
          ),
        ],
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          if (_error != null) ...[
            InlineAlert(message: _error!),
            const SizedBox(height: 16),
          ],
          AuthFormField(
            label: 'Email',
            required: true,
            child: TextField(
              controller: _emailController,
              keyboardType: TextInputType.emailAddress,
              autofillHints: const [AutofillHints.email],
              enabled: !_submitting,
              onSubmitted: (_) => _submit(),
            ),
          ),
          const SizedBox(height: 16),
          PrimaryButton(label: _submitting ? 'Sending…' : 'Send reset link', loading: _submitting, onPressed: _submit),
        ],
      ),
    );
  }
}
