import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../../core/api/api_error.dart';
import '../../../core/validation.dart';
import '../state/auth_controller.dart';
import '../state/auth_state.dart';
import 'widgets/auth_form_field.dart';
import 'widgets/auth_scaffold.dart';

/// Mirrors `apps/web/src/app/login/page.tsx` end to end, including the
/// SEC-09 "unverified email" branch with its resend action.
class LoginScreen extends ConsumerStatefulWidget {
  const LoginScreen({super.key});

  @override
  ConsumerState<LoginScreen> createState() => _LoginScreenState();
}

enum _ResendState { idle, sending, sent }

class _LoginScreenState extends ConsumerState<LoginScreen> {
  final _emailController = TextEditingController();
  final _passwordController = TextEditingController();

  String? _emailError;
  String? _passwordError;
  String? _formError;
  String? _unverifiedEmail;
  _ResendState _resendState = _ResendState.idle;
  bool _submitting = false;

  @override
  void dispose() {
    _emailController.dispose();
    _passwordController.dispose();
    super.dispose();
  }

  Future<void> _submit() async {
    setState(() {
      _formError = null;
      _unverifiedEmail = null;
      _resendState = _ResendState.idle;
    });

    final email = _emailController.text;
    final password = _passwordController.text;
    final nextEmailError = email.trim().isEmpty
        ? 'Email is required.'
        : (!isValidEmail(email) ? 'Enter a valid email address.' : null);
    final nextPasswordError = password.isEmpty ? 'Password is required.' : null;
    if (nextEmailError != null || nextPasswordError != null) {
      setState(() {
        _emailError = nextEmailError;
        _passwordError = nextPasswordError;
      });
      return;
    }

    setState(() => _submitting = true);
    try {
      final user =
          await ref.read(authControllerProvider.notifier).login(email: email.trim(), password: password);
      if (!mounted) return;
      context.go(landingPathFor(user));
    } catch (error) {
      if (error is ApiError) {
        if (error.code == 'EMAIL_NOT_VERIFIED') {
          setState(() => _unverifiedEmail = email.trim());
        } else if (error.status == 401) {
          setState(() => _formError = 'Invalid email or password.');
        } else if (error.status == 423) {
          setState(() => _formError = 'This account is temporarily locked. Try again later.');
        } else if (error.status == 429) {
          setState(() => _formError = 'Too many attempts. Please wait a moment and try again.');
        } else {
          setState(() => _formError = error.message);
        }
      } else {
        setState(() => _formError = 'Something went wrong. Please try again.');
      }
    } finally {
      if (mounted) setState(() => _submitting = false);
    }
  }

  Future<void> _resendVerification() async {
    final email = _unverifiedEmail;
    if (email == null) return;
    setState(() => _resendState = _ResendState.sending);
    try {
      await ref.read(authRepositoryProvider).resendVerification(email);
    } finally {
      // Anti-enumeration (matches the backend): always show the same confirmation.
      if (mounted) setState(() => _resendState = _ResendState.sent);
    }
  }

  @override
  Widget build(BuildContext context) {
    return AuthScaffold(
      title: 'Sign in',
      description: 'Welcome back — enter your details to continue.',
      footer: Wrap(
        alignment: WrapAlignment.center,
        children: [
          const Text('Setting up a new company? '),
          GestureDetector(
            onTap: () => context.go('/register'),
            child: Text('Register', style: TextStyle(color: Theme.of(context).colorScheme.primary, fontWeight: FontWeight.w600)),
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
          if (_unverifiedEmail != null) ...[
            InlineAlert(
              message: 'Please verify your email address before signing in.',
              trailing: Padding(
                padding: const EdgeInsets.only(top: 4),
                child: _resendState == _ResendState.sent
                    ? const Text('If that address has an account, a new verification email is on its way.')
                    : GestureDetector(
                        onTap: _resendState == _ResendState.sending ? null : _resendVerification,
                        child: Text(
                          _resendState == _ResendState.sending ? 'Sending…' : 'Resend verification email',
                          style: const TextStyle(fontWeight: FontWeight.w600, decoration: TextDecoration.underline),
                        ),
                      ),
              ),
            ),
            const SizedBox(height: 16),
          ],
          AuthFormField(
            label: 'Email',
            required: true,
            errorText: _emailError,
            child: TextField(
              controller: _emailController,
              keyboardType: TextInputType.emailAddress,
              autofillHints: const [AutofillHints.email],
              enabled: !_submitting,
              onChanged: (_) => setState(() => _emailError = null),
            ),
          ),
          const SizedBox(height: 16),
          AuthFormField(
            label: 'Password',
            required: true,
            errorText: _passwordError,
            child: AuthPasswordField(
              controller: _passwordController,
              enabled: !_submitting,
              autofillHints: const [AutofillHints.password],
              onChanged: (_) => setState(() => _passwordError = null),
              onSubmitted: (_) => _submit(),
            ),
          ),
          const SizedBox(height: 8),
          Align(
            alignment: Alignment.centerRight,
            child: GestureDetector(
              onTap: () => context.go('/forgot-password'),
              child: Text(
                'Forgot password?',
                style: TextStyle(color: Theme.of(context).colorScheme.primary, fontWeight: FontWeight.w600, fontSize: 13),
              ),
            ),
          ),
          const SizedBox(height: 16),
          PrimaryButton(label: _submitting ? 'Signing in…' : 'Sign in', loading: _submitting, onPressed: _submit),
        ],
      ),
    );
  }
}
