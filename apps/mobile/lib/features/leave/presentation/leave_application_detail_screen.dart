import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../core/api/api_error.dart';
import '../../../core/auth/permissions.dart';
import '../../../core/forms/choice_sources.dart';
import '../../../core/forms/form_spec.dart' show Choice, prettyEnum;
import '../../../core/providers.dart';
import '../../../core/time.dart';
import '../../../core/widgets/ui.dart';
import '../../auth/presentation/widgets/auth_form_field.dart';
import '../../auth/state/auth_controller.dart';
import '../data/leave_repository.dart';
import 'leave_applications_screen.dart' show LeaveStatusChip;

/// One leave application — mirrors `apps/web/src/app/app/leave-applications/[id]/page.tsx`: the
/// request, its day-by-day breakdown and action history, and the review (approve / reject) and
/// cancel flows with the same permission and timing rules.
class LeaveApplicationDetailScreen extends ConsumerStatefulWidget {
  const LeaveApplicationDetailScreen({super.key, required this.applicationId, this.initial, this.reviewOnOpen});

  /// Opens straight on the approve (true) or reject (false) step, and leaves when it is done.
  final bool? reviewOnOpen;

  final String applicationId;
  final LeaveApplication? initial;

  @override
  ConsumerState<LeaveApplicationDetailScreen> createState() => _LeaveApplicationDetailScreenState();
}

class _LeaveApplicationDetailScreenState extends ConsumerState<LeaveApplicationDetailScreen> {
  LeaveApplication? _app;
  ApiError? _error;
  bool _loading = true;
  bool _busy = false;
  Map<String, String> _typeNames = const {};

  LeaveRepository get _repo => ref.read(leaveRepositoryProvider);

  @override
  void initState() {
    super.initState();
    _app = widget.initial;
    _load();
    _loadTypes();
  }

  Future<void> _loadTypes() async {
    try {
      final c = await loadChoices(ref.read(apiClientProvider), const ['leave_types']);
      if (mounted) setState(() => _typeNames = {for (final t in c['leave_types'] ?? const <Choice>[]) t.value: t.label});
    } catch (_) {}
  }

  Future<void> _load() async {
    setState(() {
      _loading = true;
      _error = null;
    });
    try {
      final a = await _repo.getLeaveApplication(widget.applicationId);
      if (mounted) setState(() => _app = a);
      _reviewOnce(a);
    } catch (e) {
      if (mounted) setState(() => _error = e is ApiError ? e : ApiError(status: 0, code: 'UNKNOWN_ERROR', message: 'Something went wrong.'));
    } finally {
      if (mounted) setState(() => _loading = false);
    }
  }

  bool _reviewStarted = false;

  Future<void> _reviewOnce(LeaveApplication a) async {
    final approve = widget.reviewOnOpen;
    if (approve == null || _reviewStarted || !mounted) return;
    _reviewStarted = true;
    await _review(a, approve: approve);
    if (mounted) Navigator.of(context).pop();
  }

  void _toast(String m) => ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(m)));

  Future<void> _cancel(LeaveApplication a, {required bool reasonRequired}) async {
    final reason = TextEditingController();
    String? error;
    final ok = await showDialog<bool>(
      context: context,
      builder: (ctx) => StatefulBuilder(
        builder: (ctx, setLocal) => AlertDialog(
          title: const Text('Cancel this application?'),
          content: Column(mainAxisSize: MainAxisSize.min, crossAxisAlignment: CrossAxisAlignment.start, children: [
            Text(a.status == 'APPROVED' ? 'The leave balance and attendance are reversed.' : 'The application is withdrawn.'),
            const SizedBox(height: 12),
            if (error != null) Padding(padding: const EdgeInsets.only(bottom: 8), child: Text(error!, style: TextStyle(color: Theme.of(ctx).colorScheme.error))),
            AuthFormField(label: 'Reason', required: reasonRequired, description: reasonRequired ? 'Required — the leave has already started.' : 'Optional', child: TextField(controller: reason)),
          ]),
          actions: [
            TextButton(onPressed: () => Navigator.of(ctx).pop(false), child: const Text('Keep it')),
            FilledButton(
              style: FilledButton.styleFrom(backgroundColor: Theme.of(ctx).colorScheme.error),
              onPressed: () {
                if (reasonRequired && reason.text.trim().isEmpty) return setLocal(() => error = 'A reason is required.');
                Navigator.of(ctx).pop(true);
              },
              child: const Text('Cancel application'),
            ),
          ],
        ),
      ),
    );
    if (ok != true) return;
    setState(() => _busy = true);
    try {
      final updated = await _repo.cancelLeaveApplication(a.id, ifMatch: a.version.toString(), reason: reason.text.trim());
      if (mounted) setState(() => _app = updated);
      _toast(a.status == 'APPROVED' ? 'Application cancelled — balance and attendance reversed.' : 'Application cancelled.');
      _load();
    } catch (e) {
      _toast(e is ApiError ? e.message : 'Something went wrong.');
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  /// Approve or reject. A balance shortfall on approve offers approving the uncovered days as
  /// loss of pay (the web dialog's second step).
  Future<void> _review(LeaveApplication a, {required bool approve}) async {
    final comment = TextEditingController();
    final rejection = TextEditingController();
    String? formError;
    Map<String, dynamic>? shortfall;
    final done = await showDialog<bool>(
      context: context,
      builder: (ctx) => StatefulBuilder(
        builder: (ctx, setLocal) {
          Future<void> submit({bool lop = false}) async {
            try {
              final updated = approve
                  ? await _repo.approveLeaveApplication(a.id, ifMatch: a.version.toString(), comment: comment.text.trim(), excessAsLop: lop)
                  : await _repo.rejectLeaveApplication(a.id, ifMatch: a.version.toString(), comment: comment.text.trim(), reason: rejection.text.trim());
              if (mounted) setState(() => _app = updated);
              if (ctx.mounted) Navigator.of(ctx).pop(true);
            } on ApiError catch (e) {
              if (e.status == 403) {
                setLocal(() => formError = e.code == 'LEAVE_APPLICATION_SELF_APPROVAL_NOT_ALLOWED'
                    ? 'You cannot approve or reject your own application.'
                    : e.code == 'LEAVE_APPLICATION_APPROVER_MISMATCH'
                        ? "You are not the resolved approver for this application's current stage."
                        : e.message);
              } else if (e.code == 'LEAVE_APPLICATION_BALANCE_SHORTFALL') {
                final ctxMap = e.details.isNotEmpty ? (e.details.first.context ?? const {}) : const <String, dynamic>{};
                setLocal(() => shortfall = {'available': '${ctxMap['available'] ?? '0.00'}', 'shortfall': '${ctxMap['shortfall'] ?? ''}'});
              } else if (e.status == 409) {
                setLocal(() => formError = "This application has already moved on (approved, rejected, or cancelled by someone else), or one of its dates falls in an attendance period that's now closed. Refresh to see its current state.");
              } else {
                setLocal(() => formError = e.message);
              }
            } catch (_) {
              setLocal(() => formError = 'Something went wrong.');
            }
          }

          return AlertDialog(
            title: Text(approve ? 'Approve leave application' : 'Reject leave application'),
            content: SingleChildScrollView(
              child: Column(mainAxisSize: MainAxisSize.min, crossAxisAlignment: CrossAxisAlignment.start, children: [
                Text(approve ? 'Approving a stage moves the application on; the final approval books the leave.' : 'No balance or attendance change is made when an application is rejected.'),
                const SizedBox(height: 12),
                AuthFormField(label: 'Comment', description: 'Optional, visible to the employee.', child: TextField(controller: comment)),
                if (!approve) ...[const SizedBox(height: 12), AuthFormField(label: 'Rejection reason', child: TextField(controller: rejection))],
                if (formError != null) Padding(padding: const EdgeInsets.only(top: 12), child: Text(formError!, style: TextStyle(color: Theme.of(ctx).colorScheme.error))),
                if (shortfall != null)
                  Container(
                    margin: const EdgeInsets.only(top: 12),
                    padding: const EdgeInsets.all(10),
                    decoration: BoxDecoration(color: Colors.orange.withValues(alpha: 0.1), borderRadius: BorderRadius.circular(8), border: Border.all(color: Colors.orange)),
                    child: Text(
                      'Not enough leave balance. The balance now covers ${(num.tryParse(shortfall!['available']!) ?? 0) > 0 ? shortfall!['available'] : '0'} of ${a.totalDays} days — ${shortfall!['shortfall']} short. Reject it, or approve it with the uncovered days as loss of pay (unpaid leave); the latest days become loss of pay, whole days only.',
                    ),
                  ),
              ]),
            ),
            actions: [
              TextButton(onPressed: () => Navigator.of(ctx).pop(false), child: const Text('Cancel')),
              if (shortfall != null)
                FilledButton(onPressed: () => submit(lop: true), child: const Text('Approve, uncovered days as loss of pay'))
              else
                FilledButton(
                  style: approve ? null : FilledButton.styleFrom(backgroundColor: Theme.of(ctx).colorScheme.error),
                  onPressed: () => submit(),
                  child: Text(approve ? 'Approve' : 'Reject'),
                ),
            ],
          );
        },
      ),
    );
    if (done == true && mounted) {
      _toast(approve ? 'Leave application approved.' : 'Leave application rejected.');
      _load();
    }
  }

  Widget _section(String title, List<Widget> children, {IconData? icon}) => DetailSection(title: title, icon: icon, children: children);

  Widget _kv(String k, String v) => KeyValueRow(k, v == '—' ? null : v);

  @override
  Widget build(BuildContext context) {
    final user = ref.watch(authControllerProvider).user;
    final permissions = user?.permissions ?? const <String>[];
    final tz = user?.companyTimezone ?? 'Asia/Kolkata';
    final a = _app;

    Widget body;
    if (a == null && _loading) {
      body = const ListSkeleton(count: 3);
    } else if (a == null) {
      body = StateMessage(
        icon: _error?.status == 404 ? Icons.search_off_rounded : Icons.error_outline_rounded,
        tone: _error?.status == 404 ? Tone.neutral : Tone.danger,
        title: _error?.status == 404 ? 'Not found' : 'Couldn\'t load application',
        message: _error?.status == 404 ? "This leave application was not found, or you don't have access to it." : (_error?.message ?? 'Something went wrong.'),
        actionLabel: 'Retry',
        onAction: _load,
      );
    } else {
      final r = a.raw;
      String s(String k) => (r[k] ?? '—').toString();
      final isOwn = user?.employeeId != null && a.employeeId == user!.employeeId;
      final isPending = a.status == 'SUBMITTED' && a.approvalStage != null;
      final canReview = permissions.contains(leaveApplicationApprove) && isPending && !isOwn;
      final hasStarted = businessToday(tz).compareTo(a.startDate) >= 0;
      final canCancel = a.status == 'SUBMITTED'
          ? (r['submitted_by_user_id'] == user?.id || isOwn)
          : a.status == 'APPROVED'
              ? (permissions.contains(leaveApplicationCancelApproved) || (isOwn && !hasStarted))
              : false;
      final reasonRequired = a.status == 'APPROVED' && hasStarted;
      final days = ((r['days'] as List?) ?? const []).cast<Map<String, dynamic>>();
      final actions = ((r['actions'] as List?) ?? const []).cast<Map<String, dynamic>>();
      final lop = num.tryParse('${r['lop_days'] ?? 0}') ?? 0;
      body = RefreshIndicator(
        onRefresh: _load,
        child: ListView(
          padding: const EdgeInsets.all(16),
          children: [
            HeroCard(
              child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                Row(children: [
                  Expanded(child: Text(_typeNames[a.leaveTypeId] ?? 'Leave', style: const TextStyle(color: Colors.white, fontWeight: FontWeight.w800, fontSize: 20))),
                  LeaveStatusChip(status: a.status),
                ]),
                const SizedBox(height: 8),
                Row(children: [
                  const Icon(Icons.event_rounded, size: 16, color: Colors.white70),
                  const SizedBox(width: 6),
                  Text('${a.startDate} → ${a.endDate}', style: const TextStyle(color: Colors.white70)),
                ]),
                const SizedBox(height: 4),
                Text('${s('total_days')} day(s)', style: const TextStyle(color: Colors.white, fontWeight: FontWeight.w700)),
              ]),
            ),
            if (canCancel || canReview)
              Padding(
                padding: const EdgeInsets.only(top: 10),
                child: Wrap(spacing: 8, runSpacing: 8, children: [
                  if (canReview) FilledButton(onPressed: _busy ? null : () => _review(a, approve: true), child: const Text('Approve')),
                  if (canReview) OutlinedButton(onPressed: _busy ? null : () => _review(a, approve: false), child: const Text('Reject')),
                  if (canCancel) OutlinedButton(onPressed: _busy ? null : () => _cancel(a, reasonRequired: reasonRequired), child: const Text('Cancel application')),
                ]),
              ),
            _section('Request', [
              _kv('Total days', s('total_days')),
              if (lop > 0) _kv('Loss of pay days', s('lop_days')),
              _kv('Reason', s('reason')),
              _kv('Attachment reference', s('attachment_reference')),
              if (r['expected_delivery_date'] != null) _kv('Expected delivery', s('expected_delivery_date')),
              _kv('Approval chain', prettyEnum(s('approval_chain'))),
              _kv('Approval stage', prettyEnum(s('approval_stage'))),
              _kv('Submitted at', formatDateTime(r['submitted_at'] as String?, tz)),
            ]),
            if (a.status != 'SUBMITTED')
              _section('Outcome', [
                _kv('Reviewed at', formatDateTime(r['reviewed_at'] as String?, tz)),
                _kv('Reviewer comment', s('reviewer_comment')),
                _kv('Rejection reason', s('rejection_reason')),
                _kv('Cancelled at', formatDateTime(r['cancelled_at'] as String?, tz)),
                if (r['cancellation_reason'] != null) _kv('Cancellation reason', s('cancellation_reason')),
              ]),
            if (days.isNotEmpty)
              _section('Days', [
                for (final d in days)
                  _kv(
                    '${d['calendar_date']}',
                    [
                      '${d['fraction']}',
                      if (d['half'] != null) prettyEnum('${d['half']}'),
                      if (d['is_lop'] == true) 'loss of pay',
                      if (d['is_sandwich_generated'] == true) 'sandwich',
                    ].join(' · '),
                  ),
              ]),
            if (actions.isNotEmpty)
              _section('History', [
                for (var i = 0; i < actions.length; i++)
                  TimelineEntry(
                    title: '${prettyEnum('${actions[i]['action']}')}${actions[i]['stage'] != null ? ' · ${actions[i]['stage']}' : ''}',
                    subtitle: formatDateTime(actions[i]['created_at'] as String?, tz),
                    body: actions[i]['comment'] == null ? null : '${actions[i]['comment']}',
                    last: i == actions.length - 1,
                  ),
              ]),
          ],
        ),
      );
    }
    return Scaffold(appBar: AppBar(title: const Text('Leave application')), body: body);
  }
}
