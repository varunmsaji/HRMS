import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../../core/api/api_error.dart';
import '../../../core/validation.dart';
import '../state/auth_controller.dart';
import 'widgets/auth_form_field.dart';
import 'widgets/auth_scaffold.dart';

/// Mirrors `apps/web/src/app/reset-password/[token]/page.tsx`.
class ResetPasswordScreen extends ConsumerStatefulWidget {
  const ResetPasswordScreen({super.key, required this.token});

  final String token;

  @override
  ConsumerState<ResetPasswordScreen> createState() => _ResetPasswordScreenState();
}

class _ResetPasswordScreenState extends ConsumerState<ResetPasswordScreen> {
  final _passwordController = TextEditingController();
  final _confirmController = TextEditingController();
  String? _passwordError;
  String? _confirmError;
  String? _formError;
  bool _submitting = false;
  bool _done = false;

  @override
  void dispose() {
    _passwordController.dispose();
    _confirmController.dispose();
    super.dispose();
  }

  Future<void> _submit() async {
    setState(() => _formError = null);

    final password = _passwordController.text;
    final confirm = _confirmController.text;
    final nextPasswordError = isPasswordStrongEnough(password) ? null : passwordRequirementMessage();
    final nextConfirmError = password == confirm ? null : 'Passwords do not match.';
    if (nextPasswordError != null || nextConfirmError != null) {
      setState(() {
        _passwordError = nextPasswordError;
        _confirmError = nextConfirmError;
      });
      return;
    }

    setState(() => _submitting = true);
    try {
      await ref.read(authRepositoryProvider).resetPassword(token: widget.token, password: password);
      if (mounted) setState(() => _done = true);
    } catch (error) {
      if (error is ApiError && error.status == 401) {
        setState(() => _formError = 'This reset link is invalid or has expired. Please request a new one.');
      } else if (error is ApiError) {
        setState(() => _formError = error.message);
      } else {
        setState(() => _formError = 'Something went wrong. Please try again.');
      }
    } finally {
      if (mounted) setState(() => _submitting = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    if (_done) {
      return AuthScaffold(
        title: 'Password updated',
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            const Text(
              'Your password has been reset. You can now sign in with your new password.',
              textAlign: TextAlign.center,
            ),
            const SizedBox(height: 24),
            PrimaryButton(label: 'Go to sign in', loading: false, onPressed: () => context.go('/login')),
          ],
        ),
      );
    }

    return AuthScaffold(
      title: 'Choose a new password',
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
          if (_formError != null) ...[
            InlineAlert(message: _formError!),
            const SizedBox(height: 16),
          ],
          AuthFormField(
            label: 'New password',
            required: true,
            errorText: _passwordError,
            description: _passwordError == null ? 'At least 8 characters, with a letter and a digit.' : null,
            child: AuthPasswordField(
              controller: _passwordController,
              enabled: !_submitting,
              autofillHints: const [AutofillHints.newPassword],
              onChanged: (_) => setState(() => _passwordError = null),
            ),
          ),
          const SizedBox(height: 16),
          AuthFormField(
            label: 'Confirm password',
            required: true,
            errorText: _confirmError,
            child: AuthPasswordField(
              controller: _confirmController,
              enabled: !_submitting,
              autofillHints: const [AutofillHints.newPassword],
              onChanged: (_) => setState(() => _confirmError = null),
              onSubmitted: (_) => _submit(),
            ),
          ),
          const SizedBox(height: 16),
          PrimaryButton(label: _submitting ? 'Resetting…' : 'Reset password', loading: _submitting, onPressed: _submit),
        ],
      ),
    );
  }
}
