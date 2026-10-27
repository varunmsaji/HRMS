import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../core/api/api_error.dart';
import '../../../core/format.dart';
import '../data/payroll_repository.dart';
import 'pay_runs_screen.dart' show payrollRepositoryProvider;
import '../../../core/widgets/ui.dart';

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
          ? const ListSkeleton()
          : _error != null
              ? StateMessage(icon: Icons.error_outline_rounded, tone: Tone.danger, title: 'Something went wrong', message: _error!.message, actionLabel: 'Retry', onAction: _load)
              : ListView(
                  padding: const EdgeInsets.all(16),
                  children: [
                    HeroCard(
                      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                        Row(children: [
                          InitialsAvatar(name: d!.employee.displayName, size: 44),
                          const SizedBox(width: 12),
                          Expanded(
                            child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                              Text(d.employee.displayName, style: const TextStyle(color: Colors.white, fontWeight: FontWeight.w800, fontSize: 17)),
                              Text('${d.employee.employeeCode ?? ''} · paid days ${d.employee.paidDays ?? '—'} · LOP ${d.employee.lopDays ?? '—'}', style: const TextStyle(color: Colors.white70, fontSize: 12.5)),
                            ]),
                          ),
                        ]),
                        const SizedBox(height: 14),
                        const Text('Net pay', style: TextStyle(color: Colors.white70, fontSize: 12)),
                        Text(d.lines.isEmpty ? '—' : formatInr(d.employee.netMinor ?? 0), style: const TextStyle(color: Colors.white, fontSize: 26, fontWeight: FontWeight.w800)),
                      ]),
                    ),
                    const SizedBox(height: 12),
                    for (final issue in d.employee.issues)
                      Container(
                        margin: const EdgeInsets.only(bottom: 8),
                        padding: const EdgeInsets.all(12),
                        decoration: BoxDecoration(color: toneColors(context, issue.isError ? Tone.danger : Tone.warning).bg, borderRadius: BorderRadius.circular(12)),
                        child: Text('${issue.isError ? 'Error' : 'Warning'}: ${issue.message}'),
                      ),
                    if (d.lines.isEmpty) const SizedBox(height: 240, child: StateMessage(icon: Icons.hourglass_empty_rounded, title: 'Not computed yet')),
                    for (final (type, label) in _sections)
                      if (d.lines.any((l) => l.lineType == type)) ...[
                        SectionHeader(label),
                        for (final line in d.lines.where((l) => l.lineType == type))
                          Padding(
                            padding: const EdgeInsets.only(bottom: 8),
                            child: AppCard(
                              padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 10),
                              child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
                                Expanded(
                                  child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                                    Text(line.componentName, style: const TextStyle(fontWeight: FontWeight.w600)),
                                    if (line.formula != null) Text(line.formula!, style: TextStyle(fontSize: 12, color: scheme.onSurfaceVariant)),
                                    if (line.fullMonthlyMinor != null) Text('Full month ${formatInr(line.fullMonthlyMinor!)}', style: TextStyle(fontSize: 12, color: scheme.onSurfaceVariant)),
                                  ]),
                                ),
                                Text(formatInr(line.amountMinor), style: const TextStyle(fontWeight: FontWeight.w700)),
                              ]),
                            ),
                          ),
                      ],
                  ],
                ),
    );
  }
}
