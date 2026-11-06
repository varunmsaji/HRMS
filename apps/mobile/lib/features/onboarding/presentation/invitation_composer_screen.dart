import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../core/api/api_error.dart';
import '../../../core/time.dart';
import '../../../core/widgets/ui.dart';
import '../../auth/state/auth_controller.dart';
import '../domain/onboarding_invitation.dart';
import 'onboarding_cases_screen.dart' show onboardingRepositoryProvider;

/// Choose a template, edit the full message, send — mirrors the web `invitation-composer.tsx`. The
/// server fills in the candidate's details; only `{{onboarding_url}}` stays a token until sending.
/// Sending queues the email; it is not a delivery confirmation. Resolves to the send result, or null
/// if nothing was sent.
Future<Map<String, dynamic>?> openInvitationComposer(BuildContext context, {required String caseId, bool justCreated = false}) => Navigator.of(context).push<Map<String, dynamic>>(
      MaterialPageRoute(fullscreenDialog: true, builder: (_) => InvitationComposerScreen(caseId: caseId, justCreated: justCreated)),
    );

class InvitationComposerScreen extends ConsumerStatefulWidget {
  const InvitationComposerScreen({super.key, required this.caseId, this.justCreated = false});
  final String caseId;

  /// Opened straight after the case was created; says nothing has been sent yet.
  final bool justCreated;

  @override
  ConsumerState<InvitationComposerScreen> createState() => _InvitationComposerScreenState();
}

class _InvitationComposerScreenState extends ConsumerState<InvitationComposerScreen> {
  final _subject = TextEditingController();
  final _body = TextEditingController();
  final _requestId = newSendRequestId();
  InvitationCompose? _compose;
  ApiError? _loadError;
  bool _loading = true;
  bool _rendering = false;
  bool _selecting = false;
  bool _sending = false;
  String _templateKey = '';
  String? _fieldError;
  String? _sendError;

  @override
  void initState() {
    super.initState();
    _load();
  }

  @override
  void dispose() {
    _subject.dispose();
    _body.dispose();
    super.dispose();
  }

  String _describe(Object e, String denied) => e is ApiError ? (e.status == 403 ? denied : e.message) : 'Something went wrong.';

  Future<void> _load() async {
    setState(() {
      _loading = true;
      _loadError = null;
    });
    try {
      final compose = await ref.read(onboardingRepositoryProvider).getInvitationCompose(widget.caseId);
      if (!mounted) return;
      setState(() {
        _compose = compose;
        _subject.text = compose.defaultSubject;
        _body.text = compose.defaultBody;
        _templateKey = compose.templates.isEmpty ? '' : compose.templates.first.key;
        _selecting = compose.templates.length > 1;
      });
      if (compose.templates.length <= 1) await _fillIn(compose.defaultSubject, compose.defaultBody, fallback: true);
    } catch (e) {
      if (mounted) setState(() => _loadError = e is ApiError ? e : ApiError(status: 0, code: 'UNKNOWN_ERROR', message: 'Something went wrong.'));
    } finally {
      if (mounted) setState(() => _loading = false);
    }
  }

  /// Shows the template with this candidate's real details, as the text to edit.
  Future<void> _fillIn(String subject, String body, {bool fallback = false}) async {
    setState(() {
      _rendering = true;
      _fieldError = null;
    });
    try {
      final rendered = await ref.read(onboardingRepositoryProvider).previewInvitation(widget.caseId, subject: subject, body: body);
      if (!mounted) return;
      setState(() {
        _subject.text = rendered['subject'] as String;
        _body.text = rendered['editable_body'] as String? ?? body;
        _selecting = false;
      });
    } catch (e) {
      if (!mounted) return;
      setState(() {
        // With no template to go back to, edit the raw one rather than strand the user.
        if (fallback) {
          _subject.text = subject;
          _body.text = body;
          _selecting = false;
        }
        _fieldError = _describe(e, "You don't have permission to preview this invitation.");
      });
    } finally {
      if (mounted) setState(() => _rendering = false);
    }
  }

  Future<void> _send() async {
    if (_sending) return;
    setState(() {
      _sending = true;
      _sendError = null;
    });
    try {
      final result = await ref.read(onboardingRepositoryProvider).sendInvite(widget.caseId, subject: _subject.text, body: _body.text, sendRequestId: _requestId);
      if (mounted) Navigator.of(context).pop(result);
    } catch (e) {
      if (mounted) setState(() => _sendError = _describe(e, "You don't have permission to send this invitation."));
    } finally {
      if (mounted) setState(() => _sending = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final compose = _compose;
    final scheme = Theme.of(context).colorScheme;
    final zone = ref.watch(authControllerProvider).user?.companyTimezone ?? 'Asia/Kolkata';
    final muted = TextStyle(fontSize: 13, color: scheme.onSurfaceVariant);
    final busy = _loading || (_rendering && !_selecting);
    final canAct = compose != null && compose.invitable && !busy && !_rendering && !_sending;
    final templates = compose?.templates ?? const <InvitationTemplate>[];
    Widget alert(String text) => Padding(padding: const EdgeInsets.only(bottom: 10), child: Text(text, style: TextStyle(color: scheme.error)));
    return PopScope(
      canPop: !_sending,
      child: Scaffold(
        appBar: AppBar(title: Text(_selecting ? 'Choose a template' : 'Review and send invitation')),
        body: _loadError != null
            ? StateMessage(
                icon: Icons.error_outline_rounded,
                tone: Tone.danger,
                title: "Couldn't load the invitation",
                message: _loadError!.status == 403 ? "You don't have permission to send invitations." : _loadError!.message,
                actionLabel: _loadError!.status == 403 ? null : 'Retry',
                onAction: _load,
              )
            : busy || compose == null
                ? const Center(child: CircularProgressIndicator(strokeWidth: 2.5))
                : ListView(padding: const EdgeInsets.all(16), children: [
                    Padding(
                      padding: const EdgeInsets.only(bottom: 10),
                      child: Text(
                        '${widget.justCreated ? 'The onboarding case has been created. No email has been sent yet. ' : ''}${_selecting ? 'Pick the message to start from. You can edit it on the next step.' : 'Edit the message if you like. Nothing is sent until you tap Send.'}',
                        style: muted,
                      ),
                    ),
                    if (!compose.invitable) alert('This case is no longer in a status an invitation can be sent for.'),
                    if (_fieldError != null) alert(_fieldError!),
                    if (_selecting)
                      for (final t in templates)
                        RadioListTile<String>(
                          contentPadding: EdgeInsets.zero,
                          value: t.key,
                          groupValue: _templateKey,
                          onChanged: (v) => setState(() => _templateKey = v ?? _templateKey),
                          title: Text(t.name),
                          subtitle: Text(t.description),
                        )
                    else ...[
                      Text('To: ${compose.candidateName} <${compose.recipientEmail}>'),
                      const SizedBox(height: 10),
                      if (compose.hasActiveLink)
                        Padding(
                          padding: const EdgeInsets.only(bottom: 10),
                          child: AppCard(
                            child: Text(
                              'The candidate already has a live link${compose.activeLinkExpiresAt == null ? '' : ' (expires ${formatDateTime(compose.activeLinkExpiresAt, zone)})'}. Sending issues a new link and revokes the previous one.',
                            ),
                          ),
                        ),
                      TextField(controller: _subject, maxLength: compose.subjectMaxLength, decoration: const InputDecoration(labelText: 'Subject')),
                      const SizedBox(height: 6),
                      TextField(controller: _body, maxLength: compose.bodyMaxLength, minLines: 10, maxLines: 18, decoration: const InputDecoration(labelText: 'Message', alignLabelWithHint: true)),
                      Text('This is the email as the candidate will see it. Keep {{onboarding_url}} where the secure link should go; it is replaced with their personal link when you send.', style: muted),
                      if (_sendError != null) Padding(padding: const EdgeInsets.only(top: 10), child: alert(_sendError!)),
                    ],
                  ]),
        bottomNavigationBar: SafeArea(
          child: Padding(
            padding: const EdgeInsets.all(12),
            child: Row(children: [
              Expanded(
                child: OutlinedButton(
                  onPressed: _sending
                      ? null
                      : () {
                          if (!_selecting && templates.length > 1) {
                            setState(() => _selecting = true);
                          } else {
                            Navigator.of(context).pop();
                          }
                        },
                  child: Text(!_selecting && templates.length > 1 ? 'Back' : 'Cancel'),
                ),
              ),
              const SizedBox(width: 12),
              Expanded(
                child: _selecting
                    ? FilledButton(
                        onPressed: canAct && _templateKey.isNotEmpty
                            ? () {
                                final chosen = templates.firstWhere((t) => t.key == _templateKey);
                                _fillIn(chosen.subject, chosen.body);
                              }
                            : null,
                        child: Text(_rendering ? 'Preparing…' : 'Next'),
                      )
                    : FilledButton(onPressed: canAct ? _send : null, child: Text(_sending ? 'Queuing…' : 'Send invitation')),
              ),
            ]),
          ),
        ),
      ),
    );
  }
}
