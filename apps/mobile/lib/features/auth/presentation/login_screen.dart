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

  /// The invite email links to the web app; a new joiner pastes that link (or just its token)
  /// here to continue the same onboarding on mobile.
  Future<void> _openOnboardingLink() async {
    final controller = TextEditingController();
    final pasted = await showDialog<String>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: const Text('Onboarding link'),
        content: TextField(
          controller: controller,
          autofocus: true,
          decoration: const InputDecoration(hintText: 'Paste the link from your invite email'),
        ),
        actions: [
          TextButton(onPressed: () => Navigator.of(ctx).pop(), child: const Text('Cancel')),
          FilledButton(onPressed: () => Navigator.of(ctx).pop(controller.text), child: const Text('Continue')),
        ],
      ),
    );
    final token = (pasted ?? '').trim().split('?').first.split('/').where((s) => s.isNotEmpty).lastOrNull;
    if (token == null || !mounted) return;
    context.go('/onboarding/$token');
  }

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final scheme = theme.colorScheme;
    return AuthScaffold(
      title: 'Welcome back',
      description: 'Sign in to your company workspace.',
      footer: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          Row(
            children: [
              const Expanded(child: Divider()),
              Padding(
                padding: const EdgeInsets.symmetric(horizontal: 12),
                child: Text('New to Krewoxa?', style: theme.textTheme.bodyMedium?.copyWith(color: scheme.onSurfaceVariant)),
              ),
              const Expanded(child: Divider()),
            ],
          ),
          const SizedBox(height: 16),
          OutlinedButton.icon(
            onPressed: _submitting ? null : () => context.go('/register'),
            icon: const Icon(Icons.domain_add_outlined, size: 20),
            label: const Text('Register your company'),
          ),
          const SizedBox(height: 4),
          TextButton.icon(
            onPressed: _submitting ? null : _openOnboardingLink,
            icon: const Icon(Icons.link_rounded, size: 20),
            label: const Text('New joiner? Open onboarding link'),
          ),
        ],
      ),
      child: AutofillGroup(
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
              label: 'Work email',
              errorText: _emailError,
              child: TextField(
                controller: _emailController,
                keyboardType: TextInputType.emailAddress,
                textInputAction: TextInputAction.next,
                autocorrect: false,
                autofillHints: const [AutofillHints.email],
                enabled: !_submitting,
                onChanged: (_) => setState(() => _emailError = null),
                decoration: const InputDecoration(
                  hintText: 'you@company.com',
                  prefixIcon: Icon(Icons.mail_outline_rounded),
                ),
              ),
            ),
            const SizedBox(height: 18),
            AuthFormField(
              label: 'Password',
              errorText: _passwordError,
              child: AuthPasswordField(
                controller: _passwordController,
                enabled: !_submitting,
                hintText: 'Enter your password',
                prefixIcon: const Icon(Icons.lock_outline_rounded),
                textInputAction: TextInputAction.done,
                autofillHints: const [AutofillHints.password],
                onChanged: (_) => setState(() => _passwordError = null),
                onSubmitted: (_) => _submit(),
              ),
            ),
            Align(
              alignment: Alignment.centerRight,
              child: TextButton(
                onPressed: _submitting ? null : () => context.go('/forgot-password'),
                style: TextButton.styleFrom(padding: const EdgeInsets.symmetric(horizontal: 4, vertical: 12)),
                child: const Text('Forgot password?'),
              ),
            ),
            const SizedBox(height: 8),
            PrimaryButton(label: _submitting ? 'Signing in…' : 'Sign in', loading: _submitting, onPressed: _submit),
          ],
        ),
      ),
    );
  }
}
