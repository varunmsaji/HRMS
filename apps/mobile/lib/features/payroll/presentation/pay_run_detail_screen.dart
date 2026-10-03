import 'dart:io';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:path_provider/path_provider.dart';
import 'package:share_plus/share_plus.dart';

import '../../../core/api/api_error.dart';
import '../../../core/auth/permissions.dart';
import '../../../core/format.dart';
import '../../auth/presentation/widgets/auth_form_field.dart';
import '../../auth/state/auth_controller.dart';
import '../../organisation/data/organisation_repository.dart' show organisationRepositoryProvider;
import '../data/payroll_repository.dart';
import 'pay_run_employee_screen.dart';
import 'pay_runs_screen.dart' show payrollRepositoryProvider;
import 'payslip_screen.dart';

/// Mirrors `apps/web/src/app/app/payroll/pay-runs/[id]/page.tsx` — one pay run: lock inputs from
/// the closed attendance period, compute, resolve errors and acknowledge variances, approve (a
/// different user — D9), finalise and mark paid; plus rollback, pay date, bank advice, day
/// corrections and each employee's pay and payslip. The backend decides every transition; this
/// screen only offers the plausible ones.
class PayRunDetailScreen extends ConsumerStatefulWidget {
  const PayRunDetailScreen({super.key, required this.runId});
  final String runId;

  @override
  ConsumerState<PayRunDetailScreen> createState() => _PayRunDetailScreenState();
}

enum _Filter { all, issues, variance }

class _PayRunDetailScreenState extends ConsumerState<PayRunDetailScreen> {
  bool _loading = true;
  bool _busy = false;
  ApiError? _error;
  PayRun? _run;
  List<PayRunEmployee> _employees = const [];
  List<PayAdjustment> _corrections = const [];
  String? _entityName;
  _Filter _filter = _Filter.all;

  PayrollRepository get _repo => ref.read(payrollRepositoryProvider);

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    setState(() {
      _loading = true;
      _error = null;
    });
    try {
      final run = await _repo.getPayRun(widget.runId);
      final employees = await _repo.listPayRunEmployees(widget.runId);
      List<PayAdjustment> corrections = const [];
      if (run.isClosed) {
        try {
          corrections = await _repo.listAdjustments(sourcePayRunId: run.id);
        } catch (_) {}
      }
      String? entity;
      try {
        final entities = await ref.read(organisationRepositoryProvider).listLegalEntities();
        for (final e in entities) {
          if (e.id == run.legalEntityId) entity = e.name;
        }
      } catch (_) {}
      if (mounted) {
        setState(() {
          _run = run;
          _employees = employees;
          _corrections = corrections;
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

  /// `PAY_RUN_BLOCKED` carries the list of reasons in its first detail's context.
  String _explain(Object e) {
    if (e is ApiError) {
      if (e.code == 'PAY_RUN_BLOCKED' && e.details.isNotEmpty) {
        final reasons = e.details.first.context?['reasons'];
        if (reasons is List && reasons.isNotEmpty) {
          return reasons.map((r) => (r as Map)['message']).join('; ');
        }
      }
      return e.message;
    }
    return 'Something went wrong.';
  }

  Future<bool> _guard(Future<void> Function() action, {String? success}) async {
    setState(() => _busy = true);
    try {
      await action();
      if (success != null) _toast(success);
      await _load();
      return true;
    } catch (e) {
      _toast(_explain(e));
      return false;
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  Future<void> _transition(Future<PayRun> Function(String ifMatch) call, String done) =>
      _guard(() async => call(_run!.version.toString()), success: done);

  Future<void> _confirm(String title, String body, String label, Future<void> Function() onYes) async {
    final yes = await showDialog<bool>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: Text(title),
        content: Text(body),
        actions: [
          TextButton(onPressed: () => Navigator.of(ctx).pop(false), child: const Text('Cancel')),
          FilledButton(onPressed: () => Navigator.of(ctx).pop(true), child: Text(label)),
        ],
      ),
    );
    if (yes == true) await onYes();
  }

  /// Small dialog with one or two text inputs; returns the trimmed values, or null if cancelled.
  Future<List<String>?> _prompt({
    required String title,
    String? message,
    required List<(String label, String? hint, TextInputType type)> inputs,
    required String action,
    String? Function(List<String>)? validate,
    List<String>? initial,
  }) async {
    final controllers = [for (var i = 0; i < inputs.length; i++) TextEditingController(text: initial != null && i < initial.length ? initial[i] : '')];
    String? error;
    final result = await showDialog<List<String>>(
      context: context,
      builder: (ctx) => StatefulBuilder(
        builder: (ctx, setLocal) => AlertDialog(
          title: Text(title),
          content: SingleChildScrollView(
            child: Column(mainAxisSize: MainAxisSize.min, crossAxisAlignment: CrossAxisAlignment.start, children: [
              if (message != null) Padding(padding: const EdgeInsets.only(bottom: 12), child: Text(message)),
              if (error != null) Padding(padding: const EdgeInsets.only(bottom: 8), child: Text(error!, style: TextStyle(color: Theme.of(ctx).colorScheme.error))),
              for (var i = 0; i < inputs.length; i++) ...[
                AuthFormField(label: inputs[i].$1, required: true, description: inputs[i].$2, child: TextField(controller: controllers[i], keyboardType: inputs[i].$3)),
                const SizedBox(height: 12),
              ],
            ]),
          ),
          actions: [
            TextButton(onPressed: () => Navigator.of(ctx).pop(), child: const Text('Cancel')),
            FilledButton(
              onPressed: () {
                final values = [for (final c in controllers) c.text.trim()];
                final problem = values.any((v) => v.isEmpty) ? 'All fields are required.' : validate?.call(values);
                if (problem != null) return setLocal(() => error = problem);
                Navigator.of(ctx).pop(values);
              },
              child: Text(action),
            ),
          ],
        ),
      ),
    );
    return result;
  }

  Future<void> _rollback() async {
    final run = _run!;
    var target = run.rollbackTargets.first;
    final reason = TextEditingController();
    final ok = await showDialog<bool>(
      context: context,
      builder: (ctx) => StatefulBuilder(
        builder: (ctx, setLocal) => AlertDialog(
          title: const Text('Roll back pay run'),
          content: Column(mainAxisSize: MainAxisSize.min, children: [
            DropdownButtonFormField<String>(
              value: target,
              decoration: const InputDecoration(labelText: 'Roll back to'),
              items: [for (final t in run.rollbackTargets) DropdownMenuItem(value: t, child: Text(t == 'DRAFT' ? 'Draft (drops the snapshot)' : 'Inputs locked (drops computed pay)'))],
              onChanged: (v) => setLocal(() => target = v ?? target),
            ),
            const SizedBox(height: 12),
            AuthFormField(label: 'Reason', required: true, child: TextField(controller: reason)),
          ]),
          actions: [
            TextButton(onPressed: () => Navigator.of(ctx).pop(false), child: const Text('Cancel')),
            FilledButton(onPressed: () => reason.text.trim().isEmpty ? null : Navigator.of(ctx).pop(true), child: const Text('Roll back')),
          ],
        ),
      ),
    );
    final text = reason.text.trim();
    if (ok == true && text.isNotEmpty) {
      await _guard(() async => _repo.rollback(run.id, toStatus: target, reason: text, ifMatch: run.version.toString()), success: 'Rolled back.');
    }
  }

  Future<void> _changePayDate() async {
    final run = _run!;
    final v = await _prompt(
      title: 'Change pay date',
      inputs: const [('Pay date', 'YYYY-MM-DD', TextInputType.datetime)],
      initial: [run.payDate ?? ''],
      action: 'Save',
      validate: (v) => DateTime.tryParse(v.first) == null ? 'Enter a valid date.' : null,
    );
    if (v == null) return;
    await _guard(() async => _repo.updatePayDate(run.id, payDate: v.first, ifMatch: run.version.toString()), success: 'Pay date updated.');
  }

  Future<void> _acknowledge(PayRunEmployee e) async {
    final prev = e.previousNetMinor != null ? formatInr(e.previousNetMinor!) : '—';
    final v = await _prompt(
      title: 'Acknowledge variance',
      message: '${e.displayName}: net pay $prev last run → ${formatInr(e.netMinor ?? 0)} now. Say why.',
      inputs: const [('Reason', null, TextInputType.text)],
      action: 'Acknowledge',
    );
    if (v == null) return;
    await _guard(() async => _repo.acknowledgeVariance(widget.runId, e.employeeId, reason: v.first), success: 'Variance acknowledged.');
  }

  Future<void> _correctDays(PayRunEmployee e) async {
    final v = await _prompt(
      title: 'Correct paid days',
      message: '${e.displayName} was paid for ${e.paidDays} of ${e.payableDays} days. This month is finalised — the difference is paid (or recovered) as arrears in the next pay run.',
      inputs: const [('Change in paid days', 'e.g. 1, 0.5 or -1', TextInputType.numberWithOptions(decimal: true, signed: true)), ('Reason', null, TextInputType.text)],
      action: 'Record correction',
      validate: (v) => RegExp(r'^-?\d+(\.5|\.0)?$').hasMatch(v.first) ? null : 'Use whole or half days, e.g. 1, 0.5 or -1.',
    );
    if (v == null) return;
    await _guard(
      () async => _repo.createAdjustment(sourcePayRunId: widget.runId, employeeId: e.employeeId, paidDaysDelta: v[0], reason: v[1]),
      success: 'Correction recorded — it is paid in the next pay run.',
    );
  }

  Future<void> _bankAdvice() async {
    await _guard(() async {
      final file = await _repo.downloadBankAdvice(widget.runId);
      final dir = await getTemporaryDirectory();
      final name = file.filename ?? 'bank-advice-${_run!.month}.csv';
      final out = File('${dir.path}/$name');
      await out.writeAsBytes(file.bytes);
      await SharePlus.instance.share(ShareParams(files: [XFile(out.path, mimeType: 'text/csv')], subject: name));
    });
  }

  Future<void> _delete() => _confirm('Delete pay run?', 'This draft pay run will be removed.', 'Delete', () async {
        final ok = await _guard(() async => _repo.deletePayRun(widget.runId));
        if (ok && mounted) Navigator.of(context).pop();
      });

  Widget _stat(String label, String value) {
    final scheme = Theme.of(context).colorScheme;
    return Container(
      padding: const EdgeInsets.all(12),
      decoration: BoxDecoration(border: Border.all(color: scheme.outlineVariant), borderRadius: BorderRadius.circular(10)),
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Text(label.toUpperCase(), style: TextStyle(fontSize: 11, fontWeight: FontWeight.w600, color: scheme.onSurfaceVariant)),
        const SizedBox(height: 4),
        Text(value, style: const TextStyle(fontSize: 16, fontWeight: FontWeight.w700)),
      ]),
    );
  }

  @override
  Widget build(BuildContext context) {
    final permissions = ref.watch(authControllerProvider).user?.permissions ?? const <String>[];
    final canProcess = permissions.contains(payrollRunProcess);
    final canApprove = permissions.contains(payrollRunApprove);
    final canBank = permissions.contains(payrollBankAdviceDownload);
    final run = _run;
    final scheme = Theme.of(context).colorScheme;

    Widget body;
    if (_loading && run == null) {
      body = const Center(child: CircularProgressIndicator());
    } else if (_error != null || run == null) {
      body = Center(
        child: Padding(
          padding: const EdgeInsets.all(24),
          child: Column(mainAxisSize: MainAxisSize.min, children: [
            Text(_error?.status == 403 ? 'You do not have permission to view pay runs.' : (_error?.message ?? 'Pay run not found.'), textAlign: TextAlign.center),
            const SizedBox(height: 16),
            FilledButton(onPressed: _load, child: const Text('Retry')),
          ]),
        ),
      );
    } else {
      final visible = _employees.where((e) => switch (_filter) {
            _Filter.all => true,
            _Filter.issues => e.issues.isNotEmpty,
            _Filter.variance => e.varianceFlagged,
          }).toList();
      final repo = _repo;
      body = RefreshIndicator(
        onRefresh: _load,
        child: ListView(
          padding: const EdgeInsets.all(16),
          children: [
            Text('${_entityName ?? 'Legal entity'} · ${run.periodStart ?? ''} to ${run.periodEnd ?? ''}', style: TextStyle(color: scheme.onSurfaceVariant)),
            const SizedBox(height: 4),
            Text(run.status.replaceAll('_', ' '), style: TextStyle(color: scheme.primary, fontWeight: FontWeight.w700)),
            const SizedBox(height: 12),
            Wrap(spacing: 8, runSpacing: 8, children: [
              if (canProcess && run.canLockInputs) FilledButton(onPressed: _busy ? null : () => _transition((m) => repo.lockInputs(run.id, ifMatch: m), 'Inputs locked.'), child: const Text('Lock inputs')),
              if (canProcess && run.canCompute)
                (run.status == 'COMPUTED' ? OutlinedButton.new : FilledButton.new)(
                  onPressed: _busy ? null : () => _transition((m) => repo.compute(run.id, ifMatch: m), 'Computed.'),
                  child: Text(run.status == 'COMPUTED' ? 'Recompute' : 'Compute'),
                ),
              if (canApprove && run.canApprove) FilledButton(onPressed: _busy ? null : () => _transition((m) => repo.approve(run.id, ifMatch: m), 'Approved.'), child: const Text('Approve')),
              if (canApprove && run.canFinalise)
                FilledButton(
                  onPressed: _busy
                      ? null
                      : () => _confirm(
                            'Finalise this pay run?',
                            'A finalised pay run can never change, and the month\'s attendance period can no longer be reopened. Later corrections are paid as arrears in a future run.',
                            'Finalise',
                            () => _transition((m) => repo.finalise(run.id, ifMatch: m), 'Finalised.'),
                          ),
                  child: const Text('Finalise'),
                ),
              if (canApprove && run.canMarkPaid)
                FilledButton(
                  onPressed: _busy ? null : () => _confirm('Mark this pay run as paid?', 'Records that salaries have been transferred.', 'Mark paid', () => _transition((m) => repo.markPaid(run.id, ifMatch: m), 'Marked paid.')),
                  child: const Text('Mark paid'),
                ),
              if (canProcess && run.rollbackTargets.isNotEmpty) OutlinedButton(onPressed: _busy ? null : _rollback, child: const Text('Roll back')),
              if (canBank && run.isClosed) OutlinedButton(onPressed: _busy ? null : _bankAdvice, child: const Text('Bank advice (CSV)')),
              if (canProcess && run.canDelete) OutlinedButton(onPressed: _busy ? null : _delete, child: const Text('Delete')),
            ]),
            const SizedBox(height: 16),
            GridView.count(
              crossAxisCount: 2,
              shrinkWrap: true,
              physics: const NeverScrollableScrollPhysics(),
              mainAxisSpacing: 8,
              crossAxisSpacing: 8,
              childAspectRatio: 2.4,
              children: [
                _stat('Employees', '${run.employeeCount ?? 0}'),
                _stat('Gross', run.isComputed ? formatInr(run.grossMinor ?? 0) : '—'),
                _stat('Deductions', run.isComputed ? formatInr(run.deductionsMinor ?? 0) : '—'),
                _stat('Net pay', run.isComputed ? formatInr(run.netMinor ?? 0) : '—'),
                _stat('Employer contributions', run.isComputed ? formatInr(run.employerContributionsMinor ?? 0) : '—'),
              ],
            ),
            const SizedBox(height: 12),
            Row(children: [
              Expanded(child: Text('Pay date ${run.payDate ?? '—'}')),
              if (canProcess && run.canEditPayDate) TextButton(onPressed: _busy ? null : _changePayDate, child: const Text('Change')),
            ]),
            if (run.varianceThresholdPercent != null) Text('Variance threshold ${run.varianceThresholdPercent}%', style: TextStyle(color: scheme.onSurfaceVariant)),
            if (run.lastRollbackReason != null) Text('Last rolled back: ${run.lastRollbackReason}', style: TextStyle(color: scheme.onSurfaceVariant)),
            if (run.status == 'DRAFT')
              Padding(
                padding: const EdgeInsets.only(top: 8),
                child: Text('Lock the inputs once this month\'s attendance period for the legal entity is closed. Everything the pay is computed from is copied into the run at that moment.', style: TextStyle(color: scheme.onSurfaceVariant)),
              ),
            if (run.status == 'COMPUTED' && (run.errorCount > 0 || run.varianceOpenCount > 0))
              Container(
                margin: const EdgeInsets.only(top: 12),
                padding: const EdgeInsets.all(12),
                decoration: BoxDecoration(color: Colors.orange.withValues(alpha: 0.1), border: Border.all(color: Colors.orange), borderRadius: BorderRadius.circular(8)),
                child: Text(
                  'Before approval: ${[
                    if (run.errorCount > 0) '${run.errorCount} employee(s) with errors to fix',
                    if (run.varianceOpenCount > 0) '${run.varianceOpenCount} flagged variance(s) to acknowledge',
                  ].join(', ')}. The user who computed the run cannot approve it.',
                ),
              ),
            if (_employees.isNotEmpty) ...[
              const SizedBox(height: 20),
              DropdownButtonFormField<_Filter>(
                value: _filter,
                decoration: const InputDecoration(labelText: 'Show'),
                items: [
                  DropdownMenuItem(value: _Filter.all, child: Text('All employees (${_employees.length})')),
                  const DropdownMenuItem(value: _Filter.issues, child: Text('With issues')),
                  const DropdownMenuItem(value: _Filter.variance, child: Text('Flagged variance')),
                ],
                onChanged: (v) => setState(() => _filter = v ?? _Filter.all),
              ),
              const SizedBox(height: 8),
              for (final e in visible) _employeeCard(e, run, canProcess),
            ],
            if (_corrections.isNotEmpty) ...[
              const SizedBox(height: 20),
              Text('Day corrections for this month', style: Theme.of(context).textTheme.titleSmall),
              const SizedBox(height: 6),
              for (final c in _corrections)
                Card(
                  child: ListTile(
                    title: Text('${_employees.where((x) => x.employeeId == c.employeeId).map((x) => x.displayName).firstOrNull ?? 'Employee'} ${(num.tryParse(c.paidDaysDelta) ?? 0) > 0 ? '+' : ''}${c.paidDaysDelta} day(s)'),
                    subtitle: Text('${c.reason}\n${c.status == 'APPLIED' ? 'Paid as arrears' : 'Pending — next run'}'),
                    isThreeLine: true,
                    trailing: canProcess && c.status == 'PENDING'
                        ? TextButton(onPressed: _busy ? null : () => _guard(() async => _repo.deleteAdjustment(c.id), success: 'Correction withdrawn.'), child: const Text('Withdraw'))
                        : null,
                  ),
                ),
            ],
          ],
        ),
      );
    }

    return Scaffold(appBar: AppBar(title: Text(run == null ? 'Pay run' : 'Pay run — ${formatPayMonth(run.month)}')), body: body);
  }

  Widget _employeeCard(PayRunEmployee e, PayRun run, bool canProcess) {
    final scheme = Theme.of(context).colorScheme;
    return Card(
      margin: const EdgeInsets.only(top: 8),
      child: Padding(
        padding: const EdgeInsets.all(12),
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Row(children: [
            Expanded(
              child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                Text(e.displayName, style: const TextStyle(fontWeight: FontWeight.w600)),
                Text('${e.employeeCode ?? ''}${e.payBasis == 'DAILY_WAGE' ? ' · daily-wage' : ''}', style: TextStyle(fontSize: 12, color: scheme.onSurfaceVariant)),
              ]),
            ),
            if (e.isComputed) Text(formatInr(e.netMinor ?? 0), style: const TextStyle(fontWeight: FontWeight.w700)),
          ]),
          const SizedBox(height: 6),
          Text('Paid days ${e.paidDays ?? '—'} · LOP ${e.lopDays ?? '—'}${e.isComputed ? ' · gross ${formatInr(e.grossMinor ?? 0)}' : ''}', style: TextStyle(color: scheme.onSurfaceVariant)),
          if (e.varianceFlagged || e.variancePercent != null)
            Padding(
              padding: const EdgeInsets.only(top: 4),
              child: Text(
                'Variance ${e.variancePercent != null ? '${e.variancePercent}%' : 'changed'}${e.varianceReason != null ? ' — ${e.varianceReason}' : ''}',
                style: TextStyle(color: e.varianceFlagged && e.varianceReason == null ? Colors.orange.shade800 : scheme.onSurfaceVariant),
              ),
            ),
          if (e.issues.isNotEmpty)
            Padding(
              padding: const EdgeInsets.only(top: 6),
              child: Wrap(spacing: 6, runSpacing: 4, children: [
                for (final i in e.issues)
                  Tooltip(
                    message: i.message,
                    child: Chip(
                      visualDensity: VisualDensity.compact,
                      label: Text(i.code.replaceAll('_', ' ').toLowerCase(), style: const TextStyle(fontSize: 11)),
                      backgroundColor: (i.isError ? scheme.error : Colors.orange).withValues(alpha: 0.12),
                    ),
                  ),
              ]),
            ),
          Wrap(spacing: 4, children: [
            TextButton(
              onPressed: () => Navigator.of(context).push(MaterialPageRoute(builder: (_) => PayRunEmployeeScreen(runId: run.id, employeeId: e.employeeId, title: e.displayName))),
              child: const Text('View pay'),
            ),
            if (run.isComputed && e.isComputed)
              TextButton(
                onPressed: () => Navigator.of(context).push(MaterialPageRoute(
                  builder: (_) => PayslipScreen(title: e.displayName, load: () => _repo.getPayRunPayslip(run.id, e.employeeId)),
                )),
                child: const Text('Payslip'),
              ),
            if (canProcess && run.status == 'COMPUTED' && e.varianceFlagged && e.varianceReason == null)
              TextButton(onPressed: _busy ? null : () => _acknowledge(e), child: const Text('Acknowledge')),
            if (canProcess && run.isClosed && e.paidDays != null) TextButton(onPressed: _busy ? null : () => _correctDays(e), child: const Text('Correct days')),
          ]),
        ]),
      ),
    );
  }
}
