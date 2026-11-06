import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../core/api/api_error.dart';
import '../../../core/time.dart';
import '../../../core/widgets/ui.dart';
import '../../auth/state/auth_controller.dart';
import '../domain/onboarding_invitation.dart';
import 'onboarding_cases_screen.dart' show onboardingRepositoryProvider;

/// The emails sent for a case and what became of them — mirrors the web `invitation-history.tsx`.
class InvitationHistory extends ConsumerStatefulWidget {
  const InvitationHistory({super.key, required this.caseId, required this.refreshKey, required this.canResend, required this.onResend});
  final String caseId;

  /// Change to re-fetch (after a send, say).
  final int refreshKey;
  final bool canResend;
  final VoidCallback onResend;

  @override
  ConsumerState<InvitationHistory> createState() => _InvitationHistoryState();
}

class _InvitationHistoryState extends ConsumerState<InvitationHistory> {
  List<OnboardingMessage>? _messages;
  String? _error;

  @override
  void initState() {
    super.initState();
    _load();
  }

  @override
  void didUpdateWidget(covariant InvitationHistory old) {
    super.didUpdateWidget(old);
    if (old.refreshKey != widget.refreshKey) _load();
  }

  Future<void> _load() async {
    try {
      final messages = await ref.read(onboardingRepositoryProvider).listMessages(widget.caseId);
      if (mounted) {
        setState(() {
          _messages = messages;
          _error = null;
        });
      }
    } catch (e) {
      if (mounted) {
        setState(() {
          _messages = null;
          _error = e is ApiError && e.status == 403 ? "You don't have permission to view invitation history." : 'Could not load invitation history: ${e is ApiError ? e.message : 'something went wrong.'}';
        });
      }
    }
  }

  @override
  Widget build(BuildContext context) {
    final user = ref.watch(authControllerProvider).user;
    final zone = user?.companyTimezone ?? 'Asia/Kolkata';
    final scheme = Theme.of(context).colorScheme;
    final muted = TextStyle(fontSize: 12, color: scheme.onSurfaceVariant);
    final messages = _messages;
    return DetailSection(title: 'Invitation emails', icon: Icons.mail_outline_rounded, children: [
      if (_error != null)
        Text(_error!, style: TextStyle(color: scheme.error))
      else if (messages == null)
        const Padding(padding: EdgeInsets.all(12), child: Center(child: CircularProgressIndicator(strokeWidth: 2.5)))
      else if (messages.isEmpty)
        Text('No invitation has been sent yet.', style: TextStyle(color: scheme.onSurfaceVariant))
      else
        for (final m in messages) ...[
          Builder(builder: (context) {
            final info = describeMessageStatus(m.status);
            return Padding(
              padding: const EdgeInsets.only(bottom: 12),
              child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                Text(m.subject, style: const TextStyle(fontWeight: FontWeight.w600)),
                Text(info.label, style: TextStyle(fontWeight: FontWeight.w600, color: info.needsResend ? scheme.error : null)),
                Text('To ${m.recipientEmail} · by ${m.createdByUserId == user?.id ? 'you' : 'another HR user'} · ${formatDateTime(m.createdAt, zone)}', style: muted),
                Text(
                  '${info.description}${m.lastAttemptAt == null ? '' : ' Last attempt: ${formatDateTime(m.lastAttemptAt, zone)}.'}${m.providerAcceptedAt == null ? '' : ' Accepted: ${formatDateTime(m.providerAcceptedAt, zone)}.'}',
                  style: muted,
                ),
                if (info.needsResend && widget.canResend) OutlinedButton(onPressed: widget.onResend, child: const Text('Send new invitation')),
              ]),
            );
          }),
        ],
    ]);
  }
}
