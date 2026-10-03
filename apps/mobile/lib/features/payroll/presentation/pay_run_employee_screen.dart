import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../core/api/api_error.dart';
import '../../../core/format.dart';
import '../data/payroll_repository.dart';
import 'pay_runs_screen.dart' show payrollRepositoryProvider;

/// One employee's pay in a run, line by line with the formula behind each amount — mirrors
/// `apps/web/src/components/payroll/pay-run-employee-dialog.tsx`.
class PayRunEmployeeScreen extends ConsumerStatefulWidget {
  const PayRunEmployeeScreen({super.key, required this.runId, required this.employeeId, this.title});

  final String runId;
  final String employeeId;
  final String? title;

  @override
  ConsumerState<PayRunEmployeeScreen> createState() => _PayRunEmployeeScreenState();
}

const _sections = [
  ('EARNING', 'Earnings'),
  ('DEDUCTION', 'Deductions'),
  ('EMPLOYER_CONTRIBUTION', 'Employer contributions'),
  ('ROUNDING', 'Rounding'),
];

class _PayRunEmployeeScreenState extends ConsumerState<PayRunEmployeeScreen> {
  bool _loading = true;
  ApiError? _error;
  PayRunEmployeeDetail? _detail;

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
      final d = await ref.read(payrollRepositoryProvider).getPayRunEmployee(widget.runId, widget.employeeId);
      if (mounted) setState(() => _detail = d);
    } catch (e) {
      if (mounted) setState(() => _error = e is ApiError ? e : ApiError(status: 0, code: 'UNKNOWN_ERROR', message: 'Something went wrong.'));
    } finally {
      if (mounted) setState(() => _loading = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final scheme = Theme.of(context).colorScheme;
    final d = _detail;
    return Scaffold(
      appBar: AppBar(title: Text(d?.employee.displayName ?? widget.title ?? 'Employee pay')),
      body: _loading
          ? const Center(child: CircularProgressIndicator())
          : _error != null
              ? Center(
                  child: Padding(
                    padding: const EdgeInsets.all(24),
                    child: Column(mainAxisSize: MainAxisSize.min, children: [
                      Text(_error!.message, textAlign: TextAlign.center),
                      const SizedBox(height: 16),
                      FilledButton(onPressed: _load, child: const Text('Retry')),
                    ]),
                  ),
                )
              : ListView(
                  padding: const EdgeInsets.all(16),
                  children: [
                    Text('${d!.employee.employeeCode ?? ''} · paid days ${d.employee.paidDays ?? '—'} · LOP ${d.employee.lopDays ?? '—'}', style: TextStyle(color: scheme.onSurfaceVariant)),
                    const SizedBox(height: 12),
                    for (final issue in d.employee.issues)
                      Container(
                        margin: const EdgeInsets.only(bottom: 6),
                        padding: const EdgeInsets.all(10),
                        decoration: BoxDecoration(
                          color: (issue.isError ? scheme.error : Colors.orange).withValues(alpha: 0.08),
                          border: Border.all(color: issue.isError ? scheme.error : Colors.orange),
                          borderRadius: BorderRadius.circular(8),
                        ),
                        child: Text('${issue.isError ? 'Error' : 'Warning'}: ${issue.message}'),
                      ),
                    if (d.lines.isEmpty) const Padding(padding: EdgeInsets.all(24), child: Center(child: Text('Not computed yet.'))),
                    for (final (type, label) in _sections)
                      if (d.lines.any((l) => l.lineType == type)) ...[
                        const SizedBox(height: 12),
                        Text(label, style: Theme.of(context).textTheme.titleSmall),
                        const SizedBox(height: 6),
                        for (final line in d.lines.where((l) => l.lineType == type))
                          Container(
                            margin: const EdgeInsets.only(bottom: 6),
                            padding: const EdgeInsets.all(10),
                            decoration: BoxDecoration(border: Border.all(color: scheme.outlineVariant), borderRadius: BorderRadius.circular(8)),
                            child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
                              Expanded(
                                child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                                  Text(line.componentName),
                                  if (line.formula != null) Text(line.formula!, style: TextStyle(fontSize: 12, color: scheme.onSurfaceVariant)),
                                  if (line.fullMonthlyMinor != null) Text('Full month ${formatInr(line.fullMonthlyMinor!)}', style: TextStyle(fontSize: 12, color: scheme.onSurfaceVariant)),
                                ]),
                              ),
                              Text(formatInr(line.amountMinor), style: const TextStyle(fontWeight: FontWeight.w600)),
                            ]),
                          ),
                      ],
                    if (d.lines.isNotEmpty) ...[
                      const Divider(height: 28),
                      Row(mainAxisAlignment: MainAxisAlignment.spaceBetween, children: [
                        const Text('Net pay', style: TextStyle(fontWeight: FontWeight.w700, fontSize: 16)),
                        Text(formatInr(d.employee.netMinor ?? 0), style: const TextStyle(fontWeight: FontWeight.w700, fontSize: 18)),
                      ]),
                    ],
                  ],
                ),
    );
  }
}
