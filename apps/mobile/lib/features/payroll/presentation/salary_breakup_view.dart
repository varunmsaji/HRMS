import 'package:flutter/material.dart';

import '../../../core/format.dart';

/// Monthly and annual amount per component, with gross, employer contributions and CTC totals
/// (payroll Phase 5.1, D2: employer contributions sit inside CTC). Mirrors
/// `apps/web/src/components/payroll/salary-breakup-table.tsx`; [breakup] is a `SalaryBreakupRead`.
class SalaryBreakupView extends StatelessWidget {
  const SalaryBreakupView({super.key, required this.breakup});
  final Map<String, dynamic> breakup;

  Widget _lineRows(BuildContext context, List<Map<String, dynamic>> lines) {
    final scheme = Theme.of(context).colorScheme;
    return Column(children: [
      for (final l in lines)
        Padding(
          padding: const EdgeInsets.symmetric(vertical: 4),
          child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Expanded(
              child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                Text(l['component_name'] as String),
                Text(l['basis'].toString(), style: TextStyle(fontSize: 12, color: scheme.onSurfaceVariant)),
              ]),
            ),
            Column(crossAxisAlignment: CrossAxisAlignment.end, children: [
              Text('${formatInr(l['monthly_minor'] as num)} / mo'),
              Text('${formatInr(l['annual_minor'] as num)} / yr', style: TextStyle(fontSize: 12, color: scheme.onSurfaceVariant)),
            ]),
          ]),
        ),
    ]);
  }

  Widget _total(String label, num monthly) => Padding(
        padding: const EdgeInsets.symmetric(vertical: 4),
        child: Row(mainAxisAlignment: MainAxisAlignment.spaceBetween, children: [
          Text(label, style: const TextStyle(fontWeight: FontWeight.w700)),
          Text('${formatInr(monthly)} / mo · ${formatInr(monthly * 12)} / yr', style: const TextStyle(fontWeight: FontWeight.w700)),
        ]),
      );

  @override
  Widget build(BuildContext context) {
    final scheme = Theme.of(context).colorScheme;
    final lines = ((breakup['lines'] as List?) ?? const []).cast<Map<String, dynamic>>();
    final earnings = lines.where((l) => l['component_type'] == 'EARNING').toList();
    final employer = lines.where((l) => l['component_type'] == 'EMPLOYER_CONTRIBUTION').toList();
    return Container(
      padding: const EdgeInsets.all(12),
      decoration: BoxDecoration(border: Border.all(color: scheme.outlineVariant), borderRadius: BorderRadius.circular(12)),
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        _lineRows(context, earnings),
        const Divider(),
        _total('Gross', breakup['gross_monthly_minor'] as num),
        if (employer.isNotEmpty) ...[
          const SizedBox(height: 8),
          Text('Employer contributions', style: Theme.of(context).textTheme.labelMedium),
          _lineRows(context, employer),
        ],
        const Divider(),
        _total('Cost to company', breakup['monthly_ctc_minor'] as num),
      ]),
    );
  }
}
