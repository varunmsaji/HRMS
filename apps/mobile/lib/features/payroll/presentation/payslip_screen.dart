import 'package:flutter/material.dart';
import 'package:printing/printing.dart';

import '../../../core/api/api_error.dart';
import '../../../core/format.dart';
import '../data/payroll_repository.dart';
import 'payslip_pdf.dart';

/// A payslip rendered natively — mirrors `apps/web/src/components/payroll/payslip-view.tsx`,
/// with "Share / save as PDF" and "Print" in place of the browser print dialog. Used for both
/// the HR view of any employee's payslip and an employee's own (`/me/payslips/{run}`).
class PayslipScreen extends StatefulWidget {
  const PayslipScreen({super.key, required this.load, this.title = 'Payslip'});

  final Future<Payslip> Function() load;
  final String title;

  @override
  State<PayslipScreen> createState() => _PayslipScreenState();
}

class _PayslipScreenState extends State<PayslipScreen> {
  bool _loading = true;
  Payslip? _payslip;
  ApiError? _error;

  @override
  void initState() {
    super.initState();
    _fetch();
  }

  Future<void> _fetch() async {
    setState(() {
      _loading = true;
      _error = null;
    });
    try {
      final p = await widget.load();
      if (mounted) setState(() => _payslip = p);
    } catch (e) {
      if (mounted) setState(() => _error = e is ApiError ? e : ApiError(status: 0, code: 'UNKNOWN_ERROR', message: 'Something went wrong.'));
    } finally {
      if (mounted) setState(() => _loading = false);
    }
  }

  String get _filename {
    final p = _payslip!;
    final who = (p.employeeCode ?? p.employeeName ?? 'employee').replaceAll(RegExp(r'[^A-Za-z0-9_-]'), '_');
    return 'payslip-${p.month}-$who.pdf';
  }

  Future<void> _share() async {
    final bytes = await buildPayslipPdf(_payslip!);
    await Printing.sharePdf(bytes: bytes, filename: _filename);
  }

  Future<void> _print() async {
    final payslip = _payslip!;
    await Printing.layoutPdf(name: _filename, onLayout: (_) => buildPayslipPdf(payslip));
  }

  @override
  Widget build(BuildContext context) {
    final p = _payslip;
    return Scaffold(
      appBar: AppBar(
        title: Text(widget.title),
        actions: [
          if (p != null) IconButton(tooltip: 'Share / save as PDF', icon: const Icon(Icons.picture_as_pdf_outlined), onPressed: _share),
          if (p != null) IconButton(tooltip: 'Print', icon: const Icon(Icons.print_outlined), onPressed: _print),
        ],
      ),
      body: _loading
          ? const Center(child: CircularProgressIndicator())
          : _error != null
              ? Center(
                  child: Padding(
                    padding: const EdgeInsets.all(24),
                    child: Column(mainAxisSize: MainAxisSize.min, children: [
                      Text(_error!.message, textAlign: TextAlign.center),
                      const SizedBox(height: 16),
                      FilledButton(onPressed: _fetch, child: const Text('Retry')),
                    ]),
                  ),
                )
              : PayslipView(payslip: p!),
    );
  }
}

class PayslipView extends StatelessWidget {
  const PayslipView({super.key, required this.payslip});
  final Payslip payslip;

  Widget _fact(BuildContext context, String label, String? value) => Padding(
        padding: const EdgeInsets.symmetric(vertical: 2),
        child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Expanded(flex: 4, child: Text(label, style: TextStyle(color: Theme.of(context).colorScheme.onSurfaceVariant))),
          Expanded(flex: 5, child: Text((value == null || value.isEmpty) ? '—' : value, textAlign: TextAlign.end)),
        ]),
      );

  Widget _lines(BuildContext context, String title, List<PayslipLine> rows, int total, {bool showFull = false}) {
    final scheme = Theme.of(context).colorScheme;
    return Container(
      margin: const EdgeInsets.only(top: 12),
      padding: const EdgeInsets.all(12),
      decoration: BoxDecoration(border: Border.all(color: scheme.outlineVariant), borderRadius: BorderRadius.circular(10)),
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Text(title, style: Theme.of(context).textTheme.titleSmall),
        const SizedBox(height: 6),
        if (rows.isEmpty) Text('None', style: TextStyle(color: scheme.onSurfaceVariant)),
        for (final r in rows)
          Padding(
            padding: const EdgeInsets.symmetric(vertical: 3),
            child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
              Expanded(
                child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                  Text(r.componentName),
                  if (r.note != null) Text(r.note!, style: TextStyle(fontSize: 12, color: scheme.onSurfaceVariant)),
                  if (showFull && r.fullMonthlyMinor != null && r.fullMonthlyMinor != r.amountMinor)
                    Text('Full month ${formatInr(r.fullMonthlyMinor!)}', style: TextStyle(fontSize: 12, color: scheme.onSurfaceVariant)),
                ]),
              ),
              Text(formatInr(r.amountMinor)),
            ]),
          ),
        const Divider(),
        Row(mainAxisAlignment: MainAxisAlignment.spaceBetween, children: [
          const Text('Total', style: TextStyle(fontWeight: FontWeight.w700)),
          Text(formatInr(total), style: const TextStyle(fontWeight: FontWeight.w700)),
        ]),
      ]),
    );
  }

  @override
  Widget build(BuildContext context) {
    final p = payslip;
    final scheme = Theme.of(context).colorScheme;
    final employerTotal = p.employerContributions.fold<int>(0, (s, l) => s + l.amountMinor);
    final paidBy = p.paymentMode == 'BANK' ? '${p.bankName ?? 'Bank'} ····${p.accountLast4 ?? ''}' : p.paymentMode;
    return ListView(
      padding: const EdgeInsets.all(16),
      children: [
        if (!p.isFinal)
          Container(
            margin: const EdgeInsets.only(bottom: 12),
            padding: const EdgeInsets.all(10),
            decoration: BoxDecoration(color: Colors.orange.withValues(alpha: 0.1), borderRadius: BorderRadius.circular(8), border: Border.all(color: Colors.orange)),
            child: const Text('Preview — this pay run is not finalised yet'),
          ),
        Center(
          child: Column(children: [
            Text(p.legalEntityName ?? p.companyName ?? '', style: Theme.of(context).textTheme.headlineSmall, textAlign: TextAlign.center),
            if (p.legalEntityAddress != null) Text(p.legalEntityAddress!, textAlign: TextAlign.center, style: TextStyle(fontSize: 12, color: scheme.onSurfaceVariant)),
            const SizedBox(height: 6),
            Text('Payslip for ${formatPayMonth(p.month)}${p.isFinal ? '' : ' (preview)'}', style: const TextStyle(fontWeight: FontWeight.w600)),
          ]),
        ),
        const SizedBox(height: 12),
        _fact(context, 'Employee', p.employeeName),
        _fact(context, 'Employee code', p.employeeCode),
        _fact(context, 'Designation', p.designation),
        _fact(context, 'Department', p.department),
        _fact(context, 'Date of joining', p.dateOfJoining),
        _fact(context, 'PAN', p.panMasked),
        _fact(context, 'UAN', p.uanNumber),
        if (p.esiIpNumber != null) _fact(context, 'ESI IP number', p.esiIpNumber),
        _fact(context, 'Paid by', paidBy),
        _fact(context, 'Days in month', '${p.daysInMonth}'),
        _fact(context, 'Paid days', p.paidDays),
        _fact(context, 'Loss of pay days', p.lopDays),
        _fact(context, 'Pay date', p.payDate),
        _lines(context, 'Earnings', p.earnings, p.grossMinor, showFull: true),
        _lines(context, 'Deductions', p.deductions, p.deductionsMinor),
        Container(
          margin: const EdgeInsets.only(top: 12),
          padding: const EdgeInsets.all(14),
          decoration: BoxDecoration(color: scheme.surfaceContainerHigh, borderRadius: BorderRadius.circular(10)),
          child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Row(mainAxisAlignment: MainAxisAlignment.spaceBetween, children: [
              const Text('Net pay', style: TextStyle(fontWeight: FontWeight.w700, fontSize: 16)),
              Text(formatInr(p.netMinor), style: const TextStyle(fontWeight: FontWeight.w700, fontSize: 18)),
            ]),
            if (p.netInWords.isNotEmpty) Text(p.netInWords, style: TextStyle(color: scheme.onSurfaceVariant)),
          ]),
        ),
        if (p.employerContributions.isNotEmpty) _lines(context, 'Employer contributions (not part of net pay)', p.employerContributions, employerTotal),
        if (p.leaveBalances.isNotEmpty) ...[
          const SizedBox(height: 12),
          Text('Leave balance on ${p.periodEnd}', style: Theme.of(context).textTheme.titleSmall),
          Wrap(spacing: 16, children: [for (final b in p.leaveBalances) Text('${b.name}: ${b.balance}')]),
        ],
        const SizedBox(height: 16),
        Center(child: Text('This is a computer-generated payslip and does not need a signature.', style: TextStyle(fontSize: 11, color: scheme.onSurfaceVariant), textAlign: TextAlign.center)),
      ],
    );
  }
}
