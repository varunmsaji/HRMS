import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../core/api/api_client.dart';
import '../../../core/api/api_error.dart';
import '../../../core/auth/permissions.dart';
import '../../../core/forms/choice_sources.dart';
import '../../../core/forms/form_spec.dart';
import '../../../core/providers.dart';
import '../../../core/time.dart';
import '../../auth/presentation/widgets/auth_form_field.dart';
import '../../auth/state/auth_controller.dart';

typedef Rec = Map<String, dynamic>;

const periodBlockingReasonLabels = {
  'EMPLOYEES_WITHOUT_ATTENDANCE': 'Employees missing calculated attendance',
  'CONFIG_ERROR': 'Unresolved configuration errors',
  'INCOMPLETE_ATTENDANCE': 'Incomplete attendance requiring manual resolution',
  'PENDING_REGULARIZATION': 'Pending regularization requests',
  'PENDING_OVERTIME_APPROVAL': 'Pending overtime approvals',
  'UNPUBLISHED_ROSTER': 'Unpublished (DRAFT) roster entries',
  'PAID_LOP_MISMATCH': 'Days whose paid, loss-of-pay and unpaid-off shares do not add up to one day',
  'WORK_ON_LEAVE_UNRESOLVED': 'Punches on approved full-day leave awaiting an HR decision',
};

const periodActionLabels = {
  'OPENED': 'Period opened',
  'VALIDATED': 'Validated — ready to finalize',
  'VALIDATION_FAILED': 'Validation blocked',
  'CLOSED': 'Finalized and locked',
  'REOPENED': 'Reopened',
};

const periodSummaryColumns = [
  ('paid_days', 'Paid days'),
  ('lop_days', 'LOP'),
  ('unpaid_off_days', 'Unpaid off'),
  ('payable_days', 'Payable'),
  ('present_days', 'Present'),
  ('half_days', 'Half day'),
  ('absent_days', 'Absent'),
  ('leave_days', 'Leave'),
  ('on_duty_days', 'On duty'),
  ('holiday_days', 'Holiday'),
  ('weekly_off_days', 'Weekly off'),
  ('incomplete_days', 'Incomplete'),
  ('not_employed_days', 'Not employed'),
  ('late_count', 'Late count'),
];

/// One attendance period — mirrors `apps/web/src/app/app/attendance-periods/[id]/page.tsx`:
/// details, finalization readiness (Validate), queueing the day calculation, Finalize (with the
/// blocking reasons a refusal carries), Reopen, the per-employee summary and the timeline.
class AttendancePeriodDetailScreen extends ConsumerStatefulWidget {
  const AttendancePeriodDetailScreen({super.key, required this.periodId, this.initial});
  final String periodId;
  final Rec? initial;

  @override
  ConsumerState<AttendancePeriodDetailScreen> createState() => _AttendancePeriodDetailScreenState();
}

class _AttendancePeriodDetailScreenState extends ConsumerState<AttendancePeriodDetailScreen> {
  Rec? _period;
  List<Rec> _summary = const [];
  Rec? _validation;
  String? _validationError;
  ApiError? _error;
  bool _loading = true;
  bool _busy = false;
  Map<String, String> _employees = const {};
  String? _entityName;

  ApiClient get _client => ref.read(apiClientProvider);
  String get _url => '/attendance-periods/${widget.periodId}';
  String get _zone => ref.read(authControllerProvider).user?.companyTimezone ?? 'Asia/Kolkata';

  @override
  void initState() {
    super.initState();
    _period = widget.initial;
    _load();
  }

  Future<void> _load() async {
    setState(() {
      _loading = true;
      _error = null;
    });
    try {
      final period = await _client.get<Rec>(_url, parse: (d) => d as Rec);
      var summary = const <Rec>[];
      try {
        summary = (await _client.getList<Rec>('$_url/summary', query: PageQuery(perPage: 100), parseItem: (d) => d as Rec)).data;
      } catch (_) {}
      var employees = const <String, String>{};
      String? entity;
      try {
        final c = await loadChoices(_client, const ['employees', 'legal_entities']);
        employees = {for (final e in c['employees'] ?? const <Choice>[]) e.value: e.label};
        for (final e in c['legal_entities'] ?? const <Choice>[]) {
          if (e.value == period['legal_entity_id']) entity = e.label;
        }
      } catch (_) {}
      if (mounted) {
        setState(() {
          _period = period;
          _summary = summary;
          _employees = employees;
          _entityName = entity;
        });
      }
    } catch (e) {
      if (mounted) setState(() => _error = e is ApiError ? e : ApiError(status: 0, code: 'UNKNOWN_ERROR', message: 'Something went wrong.'));
    } finally {
      if (mounted) setState(() => _loading = false);
    }
  }

  void _toast(String m) => ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(m)));

  Future<void> _validate() async {
    setState(() {
      _busy = true;
      _validationError = null;
    });
    try {
      final v = await _client.post<Rec>('$_url/validate', body: const {}, parse: (d) => d as Rec);
      if (mounted) setState(() => _validation = v);
    } catch (e) {
      if (mounted) setState(() => _validationError = e is ApiError ? e.message : 'Something went wrong.');
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  /// PAY-001 — queues calculation of every employed day in the period (up to the *business*
  /// today, in the company's zone) for the period's legal entity; Validate shows when it caught up.
  Future<void> _calculateRange(Rec p) async {
    final today = businessToday(_zone);
    final dateTo = (p['period_end'] as String).compareTo(today) < 0 ? p['period_end'] as String : today;
    setState(() => _busy = true);
    try {
      await _client.post<Object?>('/attendance/days/calculate-range', body: {'date_from': p['period_start'], 'date_to': dateTo, 'legal_entity_id': p['legal_entity_id']}, parse: (_) => null);
      _toast('Attendance calculation queued for ${p['period_start']} – $dateTo. Run Validate in a few minutes to check progress.');
    } catch (e) {
      _toast(e is ApiError ? e.message : 'Something went wrong.');
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  Future<void> _finalize(Rec p) async {
    List<Rec>? reasons;
    final ok = await showDialog<bool>(
      context: context,
      builder: (ctx) => StatefulBuilder(
        builder: (ctx, setLocal) => AlertDialog(
          title: const Text('Finalize this period?'),
          content: SingleChildScrollView(
            child: Column(mainAxisSize: MainAxisSize.min, crossAxisAlignment: CrossAxisAlignment.start, children: [
              const Text('Finalizing locks every attendance day in the period and freezes the payroll summary. It can only be undone by reopening with a reason.'),
              if (reasons != null && reasons!.isNotEmpty) ...[
                const SizedBox(height: 12),
                Text('This period is not ready:', style: TextStyle(color: Theme.of(ctx).colorScheme.error, fontWeight: FontWeight.w600)),
                for (final r in reasons!) Padding(padding: const EdgeInsets.only(top: 6), child: Text('${periodBlockingReasonLabels[r['code']] ?? r['code']} — ${r['count']}\n${r['message']}')),
              ],
            ]),
          ),
          actions: [
            TextButton(onPressed: () => Navigator.of(ctx).pop(false), child: const Text('Cancel')),
            FilledButton(
              onPressed: () async {
                try {
                  final updated = await _client.post<Rec>('$_url/finalize', body: const {}, ifMatch: p['version'].toString(), parse: (d) => d as Rec);
                  if (mounted) setState(() => _period = updated);
                  if (ctx.mounted) Navigator.of(ctx).pop(true);
                } on ApiError catch (e) {
                  final ctxMap = e.details.isNotEmpty ? e.details.first.context : null;
                  final found = ((ctxMap?['reasons'] as List?) ?? const []).cast<Rec>();
                  setLocal(() => reasons = found.isEmpty ? [{'code': e.code, 'count': '', 'message': e.message}] : found);
                }
              },
              child: const Text('Finalize'),
            ),
          ],
        ),
      ),
    );
    if (ok == true && mounted) {
      _toast('Period finalized and locked.');
      _load();
    }
  }

  Future<void> _reopen(Rec p) async {
    final reason = TextEditingController();
    String? error;
    final ok = await showDialog<bool>(
      context: context,
      builder: (ctx) => StatefulBuilder(
        builder: (ctx, setLocal) => AlertDialog(
          title: const Text('Reopen this period?'),
          content: Column(mainAxisSize: MainAxisSize.min, crossAxisAlignment: CrossAxisAlignment.start, children: [
            const Text('Unlocks the period so attendance can be corrected. A finalized pay run for this month blocks reopening.'),
            const SizedBox(height: 12),
            if (error != null) Padding(padding: const EdgeInsets.only(bottom: 8), child: Text(error!, style: TextStyle(color: Theme.of(ctx).colorScheme.error))),
            AuthFormField(label: 'Reason', required: true, child: TextField(controller: reason)),
          ]),
          actions: [
            TextButton(onPressed: () => Navigator.of(ctx).pop(false), child: const Text('Cancel')),
            FilledButton(
              style: FilledButton.styleFrom(backgroundColor: Theme.of(ctx).colorScheme.error),
              onPressed: () async {
                if (reason.text.trim().isEmpty) return setLocal(() => error = 'A reason is required.');
                try {
                  final updated = await _client.post<Rec>('$_url/reopen', body: {'reason': reason.text.trim()}, ifMatch: p['version'].toString(), parse: (d) => d as Rec);
                  if (mounted) setState(() => _period = updated);
                  if (ctx.mounted) Navigator.of(ctx).pop(true);
                } catch (e) {
                  setLocal(() => error = e is ApiError ? e.message : 'Something went wrong.');
                }
              },
              child: const Text('Reopen'),
            ),
          ],
        ),
      ),
    );
    if (ok == true && mounted) {
      _toast('Period reopened.');
      _load();
    }
  }

  Widget _section(String title, List<Widget> children) {
    final scheme = Theme.of(context).colorScheme;
    return Container(
      margin: const EdgeInsets.only(top: 14),
      padding: const EdgeInsets.all(14),
      decoration: BoxDecoration(border: Border.all(color: scheme.outlineVariant), borderRadius: BorderRadius.circular(12)),
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [Text(title, style: Theme.of(context).textTheme.titleSmall), const SizedBox(height: 8), ...children]),
    );
  }

  Widget _kv(String k, String v) => Padding(
        padding: const EdgeInsets.symmetric(vertical: 3),
        child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Expanded(flex: 4, child: Text(k, style: TextStyle(color: Theme.of(context).colorScheme.onSurfaceVariant))),
          Expanded(flex: 5, child: Text(v, textAlign: TextAlign.end)),
        ]),
      );

  @override
  Widget build(BuildContext context) {
    final permissions = ref.watch(authControllerProvider).user?.permissions ?? const <String>[];
    final canLock = permissions.contains(attendanceLock);
    final canRecompute = permissions.contains(attendanceRecompute);
    final canUnlock = permissions.contains(attendanceUnlock);
    final tz = _zone;
    final scheme = Theme.of(context).colorScheme;
    final p = _period;
    Widget body;
    if (p == null && _loading) {
      body = const Center(child: CircularProgressIndicator());
    } else if (p == null) {
      body = Center(
        child: Padding(
          padding: const EdgeInsets.all(24),
          child: Column(mainAxisSize: MainAxisSize.min, children: [
            Text(_error?.status == 404 ? "This attendance period was not found, or you don't have access to it." : (_error?.message ?? 'Something went wrong.'), textAlign: TextAlign.center),
            const SizedBox(height: 16),
            FilledButton(onPressed: _load, child: const Text('Retry')),
          ]),
        ),
      );
    } else {
      final open = p['status'] == 'OPEN';
      final actions = ((p['actions'] as List?) ?? const []).cast<Rec>();
      final reasons = ((_validation?['reasons'] as List?) ?? const []).cast<Rec>();
      final frozen = _summary.isNotEmpty && _summary.first['frozen'] == true;
      body = RefreshIndicator(
        onRefresh: _load,
        child: ListView(
          padding: const EdgeInsets.all(16),
          children: [
            Row(children: [
              Expanded(child: Text(p['label'] as String? ?? '${p['period_start']} → ${p['period_end']}', style: Theme.of(context).textTheme.headlineSmall)),
              Chip(label: Text(open ? 'Open' : 'Closed & locked'), visualDensity: VisualDensity.compact, backgroundColor: (open ? Colors.orange : Colors.green).withValues(alpha: 0.15)),
            ]),
            Wrap(spacing: 8, runSpacing: 8, children: [
              if (open && canRecompute) OutlinedButton(onPressed: _busy ? null : () => _calculateRange(p), child: const Text('Calculate attendance')),
              if (open && canLock) OutlinedButton(onPressed: _busy ? null : _validate, child: const Text('Validate')),
              if (open && canLock) FilledButton(onPressed: _busy ? null : () => _finalize(p), child: const Text('Finalize')),
              if (!open && canUnlock) OutlinedButton(style: OutlinedButton.styleFrom(foregroundColor: scheme.error), onPressed: _busy ? null : () => _reopen(p), child: const Text('Reopen')),
            ]),
            _section('Period', [
              _kv('Label', '${p['label'] ?? '—'}'),
              _kv('Legal entity', _entityName ?? '—'),
              _kv('Period start', '${p['period_start']}'),
              _kv('Period end', '${p['period_end']}'),
              _kv('Opened at', formatDateTime(p['opened_at'] as String?, tz)),
              _kv('Closed at', formatDateTime(p['closed_at'] as String?, tz)),
              _kv('Reopen reason', '${p['reopen_reason'] ?? '—'}'),
            ]),
            if (_validationError != null) Padding(padding: const EdgeInsets.only(top: 12), child: Text(_validationError!, style: TextStyle(color: scheme.error))),
            if (_validation != null)
              _section('Finalization readiness', [
                Align(
                  alignment: Alignment.centerLeft,
                  child: Chip(
                    label: Text('${_validation!['status']}'),
                    visualDensity: VisualDensity.compact,
                    backgroundColor: (_validation!['status'] == 'READY' ? Colors.green : Colors.orange).withValues(alpha: 0.15),
                  ),
                ),
                if (_validation!['status'] == 'BLOCKED')
                  for (final r in reasons)
                    Container(
                      margin: const EdgeInsets.only(top: 8),
                      padding: const EdgeInsets.all(10),
                      decoration: BoxDecoration(border: Border.all(color: scheme.outlineVariant), borderRadius: BorderRadius.circular(8)),
                      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                        Text('${periodBlockingReasonLabels[r['code']] ?? r['code']} — ${r['count']}', style: const TextStyle(fontWeight: FontWeight.w600)),
                        Text('${r['message']}', style: TextStyle(color: scheme.onSurfaceVariant)),
                      ]),
                    )
                else
                  const Text('Every check passed — this period can be finalized.'),
              ]),
            _section('Summary ${_summary.isNotEmpty ? (frozen ? '(frozen)' : '(live preview)') : ''}'.trim(), [
              if (_summary.isEmpty) Text('No calculated attendance in this range yet.', style: TextStyle(color: scheme.onSurfaceVariant)),
              for (final row in _summary)
                ExpansionTile(
                  tilePadding: EdgeInsets.zero,
                  title: Text(_employees[row['employee_id']] ?? '${row['employee_id']}'),
                  subtitle: Text('Paid ${row['paid_days'] ?? '—'} · LOP ${row['lop_days'] ?? '—'} · Present ${row['present_days'] ?? '—'}'),
                  children: [for (final (key, label) in periodSummaryColumns) _kv(label, '${row[key] ?? '—'}')],
                ),
            ]),
            if (actions.isNotEmpty)
              _section('Timeline', [
                for (final a in actions)
                  Padding(
                    padding: const EdgeInsets.symmetric(vertical: 4),
                    child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                      Text(periodActionLabels[a['action']] ?? '${a['action']}', style: const TextStyle(fontWeight: FontWeight.w600)),
                      Text(formatDateTime(a['created_at'] as String?, tz), style: TextStyle(fontSize: 12, color: scheme.onSurfaceVariant)),
                      if (a['comment'] != null) Text('${a['comment']}'),
                    ]),
                  ),
              ]),
          ],
        ),
      );
    }
    return Scaffold(appBar: AppBar(title: const Text('Attendance period')), body: body);
  }
}
