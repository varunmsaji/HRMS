import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../core/widgets/async_list_screen.dart';
import '../data/payroll_repository.dart';
import 'pay_runs_screen.dart' show payrollRepositoryProvider;

class MyPayslipsScreen extends ConsumerStatefulWidget {
  const MyPayslipsScreen({super.key});

  @override
  ConsumerState<MyPayslipsScreen> createState() => _MyPayslipsScreenState();
}

class _MyPayslipsScreenState extends ConsumerState<MyPayslipsScreen> {
  @override
  Widget build(BuildContext context) {
    return AsyncListScreen<PayslipSummary>(
      title: 'My Payslips',
      fetch: () => ref.read(payrollRepositoryProvider).listMyPayslips(),
      emptyLabel: 'No payslips yet — they appear once a pay run is finalised.',
      itemBuilder: (context, payslip) => ListTile(
        title: Text(payslip.month),
        subtitle: Text('Net ${(payslip.netMinor / 100).toStringAsFixed(2)}${payslip.payDate != null ? ' · paid ${payslip.payDate}' : ''}'),
        trailing: const Icon(Icons.chevron_right, size: 20),
        onTap: () => Navigator.of(context).push(MaterialPageRoute(builder: (_) => PayslipDetailScreen(payRunId: payslip.payRunId))),
      ),
    );
  }
}

class PayslipDetailScreen extends ConsumerStatefulWidget {
  const PayslipDetailScreen({super.key, required this.payRunId});
  final String payRunId;

  @override
  ConsumerState<PayslipDetailScreen> createState() => _PayslipDetailScreenState();
}

class _PayslipDetailScreenState extends ConsumerState<PayslipDetailScreen> {
  bool _loading = true;
  Map<String, dynamic>? _payslip;
  String? _error;

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    try {
      final payslip = await ref.read(payrollRepositoryProvider).getMyPayslip(widget.payRunId);
      if (mounted) setState(() => _payslip = payslip);
    } catch (error) {
      if (mounted) setState(() => _error = 'Something went wrong.');
    } finally {
      if (mounted) setState(() => _loading = false);
    }
  }

  Widget _lineList(String title, List<dynamic>? lines) {
    if (lines == null || lines.isEmpty) return const SizedBox.shrink();
    return Padding(
      padding: const EdgeInsets.only(top: 16),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(title, style: Theme.of(context).textTheme.labelMedium),
          const SizedBox(height: 8),
          for (final line in lines)
            Padding(
              padding: const EdgeInsets.symmetric(vertical: 4),
              child: Row(
                mainAxisAlignment: MainAxisAlignment.spaceBetween,
                children: [
                  Expanded(child: Text(line['component_name'] as String? ?? '')),
                  Text(((line['amount_minor'] as num? ?? 0) / 100).toStringAsFixed(2)),
                ],
              ),
            ),
        ],
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    final scheme = Theme.of(context).colorScheme;
    final payslip = _payslip;
    return Scaffold(
      appBar: AppBar(title: Text(payslip?['month'] as String? ?? 'Payslip')),
      body: _loading
          ? const Center(child: CircularProgressIndicator())
          : _error != null
              ? Center(child: Text(_error!))
              : ListView(
                  padding: const EdgeInsets.all(16),
                  children: [
                    Container(
                      padding: const EdgeInsets.all(16),
                      decoration: BoxDecoration(color: scheme.surfaceContainerLowest, borderRadius: BorderRadius.circular(12), border: Border.all(color: scheme.outlineVariant)),
                      child: Column(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          Text(payslip!['employee_name'] as String? ?? '', style: Theme.of(context).textTheme.headlineSmall),
                          Text('${payslip['designation'] ?? ''} · ${payslip['department'] ?? ''}', style: TextStyle(color: scheme.onSurfaceVariant)),
                          const Divider(height: 20),
                          Text('Paid days: ${payslip['paid_days']} · LOP days: ${payslip['lop_days']}'),
                          const SizedBox(height: 8),
                          Text('Net pay: ${((payslip['net_minor'] as num? ?? 0) / 100).toStringAsFixed(2)}', style: const TextStyle(fontWeight: FontWeight.w700, fontSize: 18)),
                          if (payslip['net_in_words'] != null) Text(payslip['net_in_words'] as String, style: TextStyle(fontSize: 12, color: scheme.onSurfaceVariant)),
                        ],
                      ),
                    ),
                    _lineList('Earnings', payslip['earnings'] as List?),
                    _lineList('Deductions', payslip['deductions'] as List?),
                    _lineList('Employer contributions', payslip['employer_contributions'] as List?),
                  ],
                ),
    );
  }
}
