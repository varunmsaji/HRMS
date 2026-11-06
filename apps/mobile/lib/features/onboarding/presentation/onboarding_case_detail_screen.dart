import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:url_launcher/url_launcher.dart';

import '../../../core/api/api_error.dart';
import '../../../core/auth/permissions.dart';
import '../../../core/widgets/ui.dart';
import '../../auth/presentation/widgets/auth_form_field.dart';
import '../../auth/state/auth_controller.dart';
import '../../employees/presentation/employees_screen.dart' show EmployeeDetailScreen;
import '../../profile/presentation/profile_screen.dart' show employeeRepositoryProvider;
import '../data/onboarding_repository.dart';
import '../data/public_onboarding_repository.dart' show OnboardingDocument;
import '../../../core/forms/form_spec.dart';
import '../domain/onboarding_form_spec.dart';
import 'onboarding_cases_screen.dart' show onboardingRepositoryProvider;
import '../domain/onboarding_invitation.dart';
import 'invitation_composer_screen.dart';
import 'invitation_history.dart';

/// Mirrors the web `apps/web/src/app/app/onboarding/[id]/page.tsx`: case status and invite
/// link, every candidate-entered section with verify/reject, uploaded documents with
/// verify/reject, and request-changes / activate.
class OnboardingCaseDetailScreen extends ConsumerStatefulWidget {
  const OnboardingCaseDetailScreen({super.key, required this.caseSummary, this.composeOnOpen = false});
  final OnboardingCase caseSummary;

  /// Opened straight after the case was created: goes on to writing the invitation.
  final bool composeOnOpen;

  @override
  ConsumerState<OnboardingCaseDetailScreen> createState() => _OnboardingCaseDetailScreenState();
}

const _invitableStatuses = ['DRAFT', 'EXPIRED', 'INVITED', 'IN_PROGRESS', 'ACTIVATED'];
const _reviewableStatuses = ['SUBMITTED', 'UNDER_REVIEW'];

class _OnboardingCaseDetailScreenState extends ConsumerState<OnboardingCaseDetailScreen> {
  bool _loading = true;
  ApiError? _error;
  OnboardingCaseDetail? _detail;
  List<OnboardingDocument>? _documents;
  bool _busy = false;
  String? _inviteUrl;
  int _historyKey = 0;

  OnboardingRepository get _repo => ref.read(onboardingRepositoryProvider);
  String get _id => widget.caseSummary.id;

  @override
  void initState() {
    super.initState();
    _load();
    if (widget.composeOnOpen) WidgetsBinding.instance.addPostFrameCallback((_) => _compose(justCreated: true));
  }

  Future<void> _load() async {
    setState(() {
      _loading = true;
      _error = null;
    });
    try {
      final detail = await _repo.getCase(_id);
      List<OnboardingDocument>? docs;
      try {
        docs = await _repo.listCaseDocuments(_id);
      } catch (_) {
        docs = null; // no permission, or none uploaded
      }
      if (mounted) {
        setState(() {
          _detail = detail;
          _documents = docs;
        });
      }
    } catch (e) {
      if (mounted) setState(() => _error = e is ApiError ? e : ApiError(status: 0, code: 'UNKNOWN_ERROR', message: 'Something went wrong.'));
    } finally {
      if (mounted) setState(() => _loading = false);
    }
  }

  void _toast(String m) => ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(m)));

  Future<void> _run(Future<void> Function() action, {String? success}) async {
    setState(() => _busy = true);
    try {
      await action();
      if (success != null) _toast(success);
      await _load();
    } catch (e) {
      _toast(e is ApiError ? (e.status == 403 ? "You don't have permission to do that." : e.message) : 'Something went wrong.');
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  Future<String?> _askReason(String title) async {
    final controller = TextEditingController();
    final result = await showDialog<String>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: Text(title),
        content: AuthFormField(label: 'Reason', required: true, child: TextField(controller: controller, autofocus: true)),
        actions: [
          TextButton(onPressed: () => Navigator.of(ctx).pop(), child: const Text('Cancel')),
          FilledButton(
            style: FilledButton.styleFrom(backgroundColor: Theme.of(ctx).colorScheme.error),
            onPressed: () => Navigator.of(ctx).pop(controller.text.trim()),
            child: const Text('Reject'),
          ),
        ],
      ),
    );
    if (result == null) return null;
    if (result.isEmpty) {
      _toast('A rejection reason is required.');
      return null;
    }
    return result;
  }

  Future<void> _sendInvite() => _run(() async {
        final result = await _repo.sendInvite(_id);
        setState(() => _inviteUrl = result['invite_url'] as String?);
      }, success: 'Invite ready.');

  /// "Queued" is all the API can say at this point, never "sent" or "delivered".
  Future<void> _compose({bool justCreated = false}) async {
    final result = await openInvitationComposer(context, caseId: _id, justCreated: justCreated);
    if (result == null || !mounted) return;
    final queued = result['email_queued'] != false;
    setState(() {
      _inviteUrl = result['invite_url'] as String?;
      _historyKey++;
    });
    _toast(queued ? 'Invitation queued. Track its status below.' : 'The link is ready to copy, but no email was queued. Send a new invitation to retry.');
    await _load();
  }

  Future<void> _cancelCase(OnboardingCaseDetail detail) async {
    final reason = TextEditingController();
    String? error;
    var saving = false;
    final cancelled = await showDialog<bool>(
      context: context,
      builder: (ctx) => StatefulBuilder(
        builder: (ctx, setLocal) => AlertDialog(
          title: Text('Cancel onboarding for ${detail.candidateName.isEmpty ? 'this candidate' : detail.candidateName}?'),
          content: SingleChildScrollView(
            child: Column(mainAxisSize: MainAxisSize.min, crossAxisAlignment: CrossAxisAlignment.start, children: [
              Text('The case is closed and cannot be reopened.${detail.tokenStatus == 'ACTIVE' ? ' Their onboarding link stops working immediately.' : ''} The candidate is not emailed, and the case and its history stay on record. You can start a new onboarding for the same email afterwards.'),
              const SizedBox(height: 12),
              TextField(controller: reason, maxLength: 500, decoration: const InputDecoration(labelText: 'Reason (optional, kept in the audit trail)')),
              if (error != null) Text(error!, style: TextStyle(color: Theme.of(ctx).colorScheme.error)),
            ]),
          ),
          actions: [
            TextButton(onPressed: saving ? null : () => Navigator.of(ctx).pop(false), child: const Text('Keep case')),
            FilledButton(
              style: FilledButton.styleFrom(backgroundColor: Theme.of(ctx).colorScheme.error),
              onPressed: saving
                  ? null
                  : () async {
                      setLocal(() {
                        saving = true;
                        error = null;
                      });
                      try {
                        final text = reason.text.trim();
                        await _repo.cancelCase(_id, reason: text.isEmpty ? null : text);
                        if (ctx.mounted) Navigator.of(ctx).pop(true);
                      } on ApiError catch (e) {
                        setLocal(() {
                          saving = false;
                          error = e.status == 403
                              ? "You don't have permission to cancel onboarding."
                              : e.status == 409
                                  ? 'This onboarding case can no longer be cancelled. Refresh to see its latest status.'
                                  : e.message;
                        });
                      } catch (_) {
                        setLocal(() {
                          saving = false;
                          error = 'Something went wrong.';
                        });
                      }
                    },
              child: const Text('Cancel onboarding'),
            ),
          ],
        ),
      ),
    );
    if (cancelled != true || !mounted) return;
    _toast('Onboarding cancelled.');
    setState(() {
      _inviteUrl = null;
      _historyKey++;
    });
    await _load();
  }

  Future<void> _activate() async {
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: const Text('Activate employee'),
        content: const Text('This creates a real employee record from this case. This cannot be undone.'),
        actions: [
          TextButton(onPressed: () => Navigator.of(ctx).pop(false), child: const Text('Cancel')),
          FilledButton(onPressed: () => Navigator.of(ctx).pop(true), child: const Text('Activate')),
        ],
      ),
    );
    if (confirmed != true) return;
    await _run(() => _repo.activate(_id), success: 'Employee activated.');
  }

  Future<void> _rejectSection(String section, String label) async {
    final reason = await _askReason('Reject $label');
    if (reason == null) return;
    await _run(() => _repo.reviewSection(_id, section, verified: false, reason: reason), success: 'Section rejected.');
  }

  Future<void> _rejectDocument(OnboardingDocument d) async {
    final reason = await _askReason('Reject document');
    if (reason == null) return;
    await _run(() => _repo.reviewDocument(_id, d.id, verified: false, reason: reason), success: 'Document rejected.');
  }

  Future<void> _openDocument(OnboardingDocument d) async {
    final url = d.downloadUrl;
    if (url == null) return;
    final ok = await launchUrl(Uri.parse(url), mode: LaunchMode.externalApplication);
    if (!ok) _toast('Could not open the document.');
  }

  Future<void> _openEmployee(String employeeId) async {
    try {
      final employee = await ref.read(employeeRepositoryProvider).getEmployee(employeeId);
      if (!mounted) return;
      await Navigator.of(context).push(MaterialPageRoute(builder: (_) => EmployeeDetailScreen(employee: employee)));
    } catch (e) {
      _toast(e is ApiError ? e.message : 'Something went wrong.');
    }
  }

  Widget _statusChip(String status) => switch (status) {
        'VERIFIED' => const StatusChip(label: 'Verified', tone: Tone.success),
        'REJECTED' => const StatusChip(label: 'Rejected', tone: Tone.danger),
        _ => const StatusChip(label: 'Pending', tone: Tone.warning),
      };

  Widget _kv(String k, String v) => KeyValueRow(k, v);

  Widget _sectionBody(FormSpec spec, Map<String, dynamic> wire) {
    if (spec.repeatable) {
      final items = (wire['items'] as List?) ?? const [];
      if (items.isEmpty) return const Text('None added.');
      return Column(children: [
        for (var i = 0; i < items.length; i++)
          Container(
            width: double.infinity,
            margin: const EdgeInsets.only(bottom: 8),
            padding: const EdgeInsets.all(10),
            decoration: BoxDecoration(color: Theme.of(context).colorScheme.surfaceContainerLow, borderRadius: BorderRadius.circular(12)),
            child: Column(children: [for (final (k, v) in displayRows(spec, Map<String, dynamic>.from(items[i] as Map))) _kv(k, v)]),
          ),
      ]);
    }
    final rows = displayRows(spec, wire);
    if (rows.isEmpty) return const Text('Not filled in yet.');
    return Column(children: [for (final (k, v) in rows) _kv(k, v)]);
  }

  @override
  Widget build(BuildContext context) {
    final permissions = ref.watch(authControllerProvider).user?.permissions ?? const <String>[];
    final canInvite = permissions.contains(onboardingCreate);
    final canReview = permissions.contains(onboardingReview);
    final canActivate = permissions.contains(onboardingActivate);
    final detail = _detail;
    final scheme = Theme.of(context).colorScheme;

    Widget body;
    if (_loading && detail == null) {
      body = const ListSkeleton(count: 4);
    } else if (_error != null || detail == null) {
      body = StateMessage(
        icon: _error?.status == 403 ? Icons.lock_outline_rounded : Icons.error_outline_rounded,
        tone: Tone.danger,
        title: _error?.status == 403 ? 'No access' : 'Couldn\'t load case',
        message: _error?.status == 403 ? 'You do not have permission to view this onboarding case.' : (_error?.message ?? 'Something went wrong.'),
        actionLabel: 'Retry',
        onAction: _load,
      );
    } else {
      final status = detail.status;
      final reviewable = _reviewableStatuses.contains(status);
      final hasRejection = detail.sectionReviews.any((r) => r['status'] == 'REJECTED') || (_documents ?? const []).any((d) => d.status == 'REJECTED');
      body = RefreshIndicator(
        onRefresh: _load,
        child: ListView(
          padding: const EdgeInsets.all(16),
          children: [
            HeroCard(
              child: Row(children: [
                InitialsAvatar(name: detail.candidateName, size: 52),
                const SizedBox(width: 14),
                Expanded(
                  child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                    Text(detail.candidateName, style: const TextStyle(color: Colors.white, fontWeight: FontWeight.w800, fontSize: 18)),
                    const SizedBox(height: 2),
                    Text(detail.personalEmail, style: const TextStyle(color: Colors.white70, fontSize: 12.5), overflow: TextOverflow.ellipsis),
                    const SizedBox(height: 8),
                    StatusChip.status(status),
                  ]),
                ),
              ]),
            ),
            DetailSection(title: 'Candidate', icon: Icons.person_outline_rounded, children: [
              _kv('Email', detail.personalEmail),
              if (detail.personalMobile != null) _kv('Mobile', detail.personalMobile!),
              if (detail.proposedJoiningDate != null) _kv('Proposed joining', detail.proposedJoiningDate!),
              if (detail.tokenStatus != null) _kv('Invite link', '${detail.tokenStatus}${detail.tokenExpiresAt != null ? ' · expires ${detail.tokenExpiresAt}' : ''}'),
            ]),
            const SizedBox(height: 12),
            Wrap(spacing: 8, runSpacing: 8, children: [
              if (canInvite && _invitableStatuses.contains(status))
                FilledButton(onPressed: _busy ? null : (status == 'ACTIVATED' ? _sendInvite : _compose), child: Text(status == 'DRAFT' ? 'Send invite' : status == 'ACTIVATED' ? 'Get link' : 'Resend invite')),
              if (canReview && status == 'UNDER_REVIEW' && hasRejection)
                OutlinedButton(onPressed: _busy ? null : () => _run(() => _repo.requestChanges(_id), success: 'Changes requested.'), child: const Text('Request changes')),
              if (canActivate && status == 'VERIFIED') FilledButton(onPressed: _busy ? null : _activate, child: const Text('Activate employee')),
              if (status == 'ACTIVATED' && detail.employeeId != null)
                OutlinedButton(onPressed: () => _openEmployee(detail.employeeId!), child: const Text('View employee')),
              if (permissions.contains(onboardingCancel) && onboardingCancellableStatuses.contains(status))
                OutlinedButton(onPressed: _busy ? null : () => _cancelCase(detail), child: const Text('Cancel onboarding')),
            ]),
            if (_inviteUrl != null) ...[
              const SizedBox(height: 12),
              Container(
                padding: const EdgeInsets.all(10),
                decoration: BoxDecoration(color: scheme.surfaceContainerHigh, borderRadius: BorderRadius.circular(12)),
                child: Row(children: [
                  Expanded(child: SelectableText(_inviteUrl!, style: const TextStyle(fontSize: 12))),
                  IconButton(
                    tooltip: 'Copy link',
                    icon: const Icon(Icons.copy, size: 18),
                    onPressed: () async {
                      await Clipboard.setData(ClipboardData(text: _inviteUrl!));
                      _toast('Link copied.');
                    },
                  ),
                ]),
              ),
            ],
            const SizedBox(height: 12),
            InvitationHistory(caseId: _id, refreshKey: _historyKey, canResend: canInvite && _invitableStatuses.contains(status) && status != 'ACTIVATED', onResend: _compose),
            const SizedBox(height: 20),
            for (final spec in onboardingSections) ...[
              Padding(
                padding: const EdgeInsets.only(bottom: 12),
                child: AppCard(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Row(children: [
                        Expanded(child: Text(spec.label, style: Theme.of(context).textTheme.titleMedium?.copyWith(fontWeight: FontWeight.w700))),
                        _statusChip(detail.reviewStatus(spec.name)),
                      ]),
                      const SizedBox(height: 8),
                      _sectionBody(spec, detail.sections[spec.name] ?? const {}),
                      if (detail.reviewStatus(spec.name) == 'REJECTED' && detail.rejectionReason(spec.name) != null)
                        Padding(padding: const EdgeInsets.only(top: 6), child: Text('Rejected: ${detail.rejectionReason(spec.name)}', style: TextStyle(color: scheme.error))),
                      if (canReview && reviewable && detail.reviewStatus(spec.name) != 'VERIFIED')
                        Padding(
                          padding: const EdgeInsets.only(top: 8),
                          child: Row(children: [
                            OutlinedButton(
                              onPressed: _busy ? null : () => _run(() => _repo.reviewSection(_id, spec.name, verified: true), success: 'Section verified.'),
                              child: const Text('Verify'),
                            ),
                            const SizedBox(width: 8),
                            OutlinedButton(onPressed: _busy ? null : () => _rejectSection(spec.name, spec.label), child: const Text('Reject')),
                          ]),
                        ),
                    ],
                  ),
                ),
              ),
            ],
            const SectionHeader('Documents'),
            if (_documents == null)
              Text('You do not have permission to view documents, or none have been uploaded yet.', style: TextStyle(color: scheme.onSurfaceVariant))
            else if (_documents!.isEmpty)
              Text('No documents uploaded yet.', style: TextStyle(color: scheme.onSurfaceVariant))
            else
              for (final d in _documents!)
                Padding(
                  padding: const EdgeInsets.only(bottom: 10),
                  child: AppCard(
                    child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                      Row(children: [
                        const IconBadge(icon: Icons.description_outlined, size: 34),
                        const SizedBox(width: 10),
                        Expanded(child: Text(onboardingDocumentTypes[d.documentType] ?? d.documentType, style: Theme.of(context).textTheme.titleSmall?.copyWith(fontWeight: FontWeight.w700))),
                        _statusChip(d.status),
                      ]),
                      TextButton.icon(
                        style: TextButton.styleFrom(padding: EdgeInsets.zero, alignment: Alignment.centerLeft),
                        icon: const Icon(Icons.open_in_new, size: 16),
                        label: Text(d.originalFilename),
                        onPressed: d.downloadUrl == null ? null : () => _openDocument(d),
                      ),
                      if (d.status == 'REJECTED' && d.rejectionReason != null) Text(d.rejectionReason!, style: TextStyle(color: scheme.error)),
                      if (canReview)
                        Row(children: [
                          OutlinedButton(
                            onPressed: _busy ? null : () => _run(() => _repo.reviewDocument(_id, d.id, verified: true), success: 'Document verified.'),
                            child: const Text('Verify'),
                          ),
                          const SizedBox(width: 8),
                          OutlinedButton(onPressed: _busy ? null : () => _rejectDocument(d), child: const Text('Reject')),
                        ]),
                    ]),
                  ),
                ),
          ],
        ),
      );
    }
    return Scaffold(appBar: AppBar(title: Text(widget.caseSummary.candidateName)), body: body);
  }
}
