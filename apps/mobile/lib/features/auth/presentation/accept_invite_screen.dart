import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../../core/api/api_error.dart';
import '../data/auth_repository.dart';
import '../state/auth_controller.dart';
import '../state/auth_state.dart';
import 'widgets/auth_form_field.dart';
import 'widgets/auth_scaffold.dart';

/// Mirrors `apps/web/src/app/accept-invite/[token]/page.tsx` — loads the
/// public invite first (SEC-08's `existing_account` flag decides whether the
/// form asks for a *new* password or the invitee's *existing* one), then
/// accepts it.
class AcceptInviteScreen extends ConsumerStatefulWidget {
  const AcceptInviteScreen({super.key, required this.token});

  final String token;

  @override
  ConsumerState<AcceptInviteScreen> createState() => _AcceptInviteScreenState();
}

class _AcceptInviteScreenState extends ConsumerState<AcceptInviteScreen> {
  final _firstNameController = TextEditingController();
  final _lastNameController = TextEditingController();
  final _passwordController = TextEditingController();
  final _confirmController = TextEditingController();

  bool _loading = true;
  PublicAccountInvite? _invite;
  ApiError? _loadError;

  String? _passwordError;
  String? _confirmError;
  String? _formError;
  bool _submitting = false;

  @override
  void initState() {
    super.initState();
    _load();
  }

  @override
  void dispose() {
    _firstNameController.dispose();
    _lastNameController.dispose();
    _passwordController.dispose();
    _confirmController.dispose();
    super.dispose();
  }

  Future<void> _load() async {
    setState(() {
      _loading = true;
      _loadError = null;
    });
    try {
      final invite = await ref.read(authRepositoryProvider).getInvite(widget.token);
      if (mounted) setState(() => _invite = invite);
    } catch (error) {
      if (mounted) {
        setState(() {
          _invite = null;
          _loadError = error is ApiError
              ? error
              : ApiError(status: 0, code: 'UNKNOWN_ERROR', message: 'Something went wrong.');
        });
      }
    } finally {
      if (mounted) setState(() => _loading = false);
    }
  }

  Future<void> _submit() async {
    setState(() => _formError = null);
    final invite = _invite;
    if (invite == null) return;

    final password = _passwordController.text;
    final confirm = _confirmController.text;
    String? passwordError;
    String? confirmError;
    if (invite.existingAccount) {
      // SEC-08 — for an existing account, `password` authenticates it, it doesn't set a new
      // one, so the new-password strength/confirm rules don't apply — only "did you type
      // something" does.
      if (password.isEmpty) passwordError = 'Enter your password.';
    } else {
      if (password.length < 8 || !RegExp(r'[A-Za-z]').hasMatch(password) || !RegExp(r'\d').hasMatch(password)) {
        passwordError = 'At least 8 characters, with a letter and a digit.';
      }
      if (password != confirm) confirmError = 'Passwords do not match.';
    }
    if (passwordError != null || confirmError != null) {
      setState(() {
        _passwordError = passwordError;
        _confirmError = confirmError;
      });
      return;
    }

    setState(() => _submitting = true);
    try {
      final data = await ref.read(authRepositoryProvider).acceptInvite(
            token: widget.token,
            password: password,
            firstName: _firstNameController.text.trim(),
            lastName: _lastNameController.text.trim(),
          );
      final user = await ref.read(authControllerProvider.notifier).applyTokenResponse(data);
      if (!mounted) return;
      context.go(landingPathFor(user));
    } catch (error) {
      if (error is ApiError) {
        if (error.status == 401) {
          setState(() => _passwordError = 'Incorrect password.');
        } else if (error.status == 423) {
          setState(() => _formError = 'This account is temporarily locked. Try again later.');
        } else if (error.status == 409) {
          setState(() => _formError = error.message);
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

  @override
  Widget build(BuildContext context) {
    if (_loading) {
      return const AuthScaffold(title: 'Loading your invite…', child: Center(child: CircularProgressIndicator()));
    }

    final invite = _invite;
    if (invite == null) {
      return AuthScaffold(
        title: 'Invite not available',
        child: Text(
          _loadError?.status == 404
              ? 'This invite link is invalid or has expired. Please ask your admin to send a new one.'
              : (_loadError?.message ?? 'Something went wrong.'),
          textAlign: TextAlign.center,
        ),
      );
    }

    final isExisting = invite.existingAccount;
    return AuthScaffold(
      title: 'Join ${invite.companyName}',
      description: isExisting
          ? '${invite.email} already has an account. Enter its password to accept this invitation and join ${invite.companyName}.'
          : 'Set a password for ${invite.email} to finish creating your account.',
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          if (_formError != null) ...[
            InlineAlert(message: _formError!),
            const SizedBox(height: 16),
          ],
          if (!isExisting) ...[
            Row(
              children: [
                Expanded(
                  child: AuthFormField(
                    label: 'First name',
                    child: TextField(controller: _firstNameController, maxLength: 100, buildCounter: (_, {required currentLength, maxLength, required isFocused}) => null),
                  ),
                ),
                const SizedBox(width: 12),
                Expanded(
                  child: AuthFormField(
                    label: 'Last name',
                    child: TextField(controller: _lastNameController, maxLength: 100, buildCounter: (_, {required currentLength, maxLength, required isFocused}) => null),
                  ),
                ),
              ],
            ),
            const SizedBox(height: 16),
          ],
          AuthFormField(
            label: 'Password',
            required: true,
            errorText: _passwordError,
            description: isExisting ? 'Your existing account password.' : 'At least 8 characters, with a letter and a digit.',
            child: AuthPasswordField(
              controller: _passwordController,
              enabled: !_submitting,
              autofillHints: [isExisting ? AutofillHints.password : AutofillHints.newPassword],
              onChanged: (_) => setState(() => _passwordError = null),
            ),
          ),
          if (!isExisting) ...[
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
              ),
            ),
          ],
          const SizedBox(height: 16),
          PrimaryButton(
            label: _submitting
                ? (isExisting ? 'Accepting…' : 'Creating account…')
                : (isExisting ? 'Accept invitation' : 'Create account'),
            loading: _submitting,
            onPressed: _submit,
          ),
        ],
      ),
    );
  }
}
