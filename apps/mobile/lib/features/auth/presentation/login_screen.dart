import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../../core/api/api_error.dart';
import '../../../core/validation.dart';
import '../../../core/router/app_router.dart' show returnPathProvider;
import '../../../core/widgets/ui.dart' show Tone, toneColors;
import '../data/login_prefs.dart';
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
  final _companyCodeController = TextEditingController();
  final _passwordController = TextEditingController();

  String? _emailError;
  String? _companyCodeError;
  String? _passwordError;
  String? _formError;
  String? _unverifiedEmail;
  _ResendState _resendState = _ResendState.idle;
  bool _submitting = false;

  @override
  void initState() {
    super.initState();
    _prefill();
  }

  /// Fills in the identifier and company code from the last successful sign-in on this device, so
  /// a returning employee types only their password (MOB-UX-030). Never overwrites typing.
  Future<void> _prefill() async {
    final saved = await ref.read(loginPrefsProvider).read();
    if (!mounted) return;
    setState(() {
      if (_emailController.text.isEmpty && saved.identifier != null) _emailController.text = saved.identifier!;
      if (_companyCodeController.text.isEmpty && saved.companyCode != null) _companyCodeController.text = saved.companyCode!;
    });
  }

  @override
  void dispose() {
    _emailController.dispose();
    _companyCodeController.dispose();
    _passwordController.dispose();
    super.dispose();
  }

  Future<void> _submit() async {
    setState(() {
      _formError = null;
      _unverifiedEmail = null;
      _resendState = _ResendState.idle;
    });

    final identifier = _emailController.text.trim();
    final companyCode = _companyCodeController.text.trim();
    final password = _passwordController.text;
    final byEmail = _isEmail(identifier);
    final nextEmailError = identifier.isEmpty
        ? 'Email or employee ID is required.'
        : (byEmail && !isValidEmail(identifier) ? 'Enter a valid email address.' : null);
    final nextCompanyCodeError = identifier.isNotEmpty && !byEmail && companyCode.isEmpty
        ? 'Company code is required to sign in with an employee ID.'
        : null;
    final nextPasswordError = password.isEmpty ? 'Password is required.' : null;
    if (nextEmailError != null || nextCompanyCodeError != null || nextPasswordError != null) {
      setState(() {
        _emailError = nextEmailError;
        _companyCodeError = nextCompanyCodeError;
        _passwordError = nextPasswordError;
      });
      return;
    }

    setState(() => _submitting = true);
    try {
      final auth = ref.read(authControllerProvider.notifier);
      final user = byEmail
          ? await auth.login(email: identifier, password: password)
          : await auth.login(companyCode: companyCode, employeeCode: identifier, password: password);
      if (!mounted) return;
      await ref.read(loginPrefsProvider).remember(identifier: identifier, companyCode: byEmail ? null : companyCode);
      if (!mounted) return;
      // Back to where an expired session interrupted this same user; otherwise the landing page.
      context.go(ref.read(returnPathProvider).takeFor(user?.id) ?? landingPathFor(user));
    } catch (error) {
      if (error is ApiError) {
        if (error.code == 'EMAIL_NOT_VERIFIED') {
          setState(() {
            if (byEmail) {
              _unverifiedEmail = identifier;
            } else {
              _formError = 'Please verify your email address before signing in. '
                  'Check your inbox for the verification link.';
            }
          });
        } else if (error.status == 401) {
          setState(() => _formError =
              byEmail ? 'Invalid email or password.' : 'Invalid company code, employee ID or password.');
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

  /// Anything with an `@` is an email; otherwise it is an employee ID, which
  /// needs the company code too.
  static bool _isEmail(String identifier) => identifier.contains('@');

  bool get _showCompanyCode {
    final identifier = _emailController.text.trim();
    return identifier.isNotEmpty && !_isEmail(identifier);
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
          // Most people on this screen are employees signing in; registering a company is the rare
          // case, so it is a link rather than a second large button competing with Sign in.
          TextButton.icon(
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
            if (ref.watch(authControllerProvider.select((a) => a.sessionExpired)) && _formError == null) ...[
              const _SessionEndedNote(),
              const SizedBox(height: 16),
            ],
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
                      : Align(
                          alignment: Alignment.centerLeft,
                          child: TextButton(
                            onPressed: _resendState == _ResendState.sending ? null : _resendVerification,
                            style: TextButton.styleFrom(minimumSize: const Size(48, 48), padding: EdgeInsets.zero, foregroundColor: Theme.of(context).colorScheme.onErrorContainer),
                            child: Text(
                              _resendState == _ResendState.sending ? 'Sending…' : 'Resend verification email',
                              style: const TextStyle(fontWeight: FontWeight.w600, decoration: TextDecoration.underline),
                            ),
                          ),
                        ),
                ),
              ),
              const SizedBox(height: 16),
            ],
            AuthFormField(
              label: 'Email or employee ID',
              errorText: _emailError,
              child: TextField(
                controller: _emailController,
                keyboardType: TextInputType.emailAddress,
                textInputAction: TextInputAction.next,
                autocorrect: false,
                autofillHints: const [AutofillHints.username],
                enabled: !_submitting,
                onChanged: (_) => setState(() => _emailError = null),
                decoration: const InputDecoration(
                  hintText: 'you@company.com or EMP-0007',
                  prefixIcon: Icon(Icons.person_outline_rounded),
                ),
              ),
            ),
            if (_showCompanyCode) ...[
              const SizedBox(height: 18),
              AuthFormField(
                label: 'Company code',
                errorText: _companyCodeError,
                child: TextField(
                  controller: _companyCodeController,
                  textCapitalization: TextCapitalization.characters,
                  textInputAction: TextInputAction.next,
                  autocorrect: false,
                  enabled: !_submitting,
                  onChanged: (_) => setState(() => _companyCodeError = null),
                  decoration: const InputDecoration(
                    hintText: 'e.g. ACME — it\'s in your welcome email',
                    prefixIcon: Icon(Icons.business_outlined),
                  ),
                ),
              ),
            ],
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

/// Shown when the app signed the user out because their session ran out, so the login screen is
/// not a mystery (MOB-UX-031). Informational, not an error.
class _SessionEndedNote extends StatelessWidget {
  const _SessionEndedNote();

  @override
  Widget build(BuildContext context) {
    final c = toneColors(context, Tone.info);
    return Semantics(
      liveRegion: true,
      child: Container(
        padding: const EdgeInsets.all(12),
        decoration: BoxDecoration(color: c.bg, borderRadius: BorderRadius.circular(12)),
        child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Icon(Icons.info_outline_rounded, size: 18, color: c.fg),
          const SizedBox(width: 10),
          Expanded(child: Text('Your session ended. Sign in again to continue where you left off.', style: TextStyle(color: c.fg, fontSize: 13, height: 1.35))),
        ]),
      ),
    );
  }
}
