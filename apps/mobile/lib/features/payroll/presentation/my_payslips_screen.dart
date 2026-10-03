import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../core/format.dart';
import '../../../core/widgets/async_list_screen.dart';
import '../data/payroll_repository.dart';
import 'pay_runs_screen.dart' show payrollRepositoryProvider;
import 'payslip_screen.dart';

/// The signed-in employee's finalised payslips — `GET /me/payslips`, each opening the full
/// payslip (`/me/payslips/{run_id}`) with PDF share/print.
class MyPayslipsScreen extends ConsumerWidget {
  const MyPayslipsScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    return AsyncListScreen<PayslipSummary>(
      title: 'My Payslips',
      fetch: () => ref.read(payrollRepositoryProvider).listMyPayslips(),
      emptyLabel: 'No payslips yet — they appear once a pay run is finalised.',
      itemBuilder: (context, payslip) => ListTile(
        title: Text(formatPayMonth(payslip.month)),
        subtitle: Text('Net ${formatInr(payslip.netMinor)} · paid ${payslip.payDate ?? '—'}'),
        trailing: const Icon(Icons.chevron_right, size: 20),
        onTap: () => Navigator.of(context).push(MaterialPageRoute(
          builder: (_) => PayslipScreen(
            title: 'Payslip · ${formatPayMonth(payslip.month)}',
            load: () => ref.read(payrollRepositoryProvider).getMyPayslip(payslip.payRunId),
          ),
        )),
      ),
    );
  }
}
