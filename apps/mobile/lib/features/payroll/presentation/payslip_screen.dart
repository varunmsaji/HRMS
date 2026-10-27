import 'package:flutter/material.dart';
import 'package:printing/printing.dart';

import '../../../core/api/api_error.dart';
import '../../../core/format.dart';
import '../../../core/theme/app_theme.dart' show AppBrand;
import '../../../core/widgets/ui.dart';
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
          ? const ListSkeleton(count: 4)
          : _error != null
              ? StateMessage(
                  icon: Icons.error_outline_rounded,
                  tone: Tone.danger,
                  title: 'Couldn\'t load payslip',
                  message: _error!.message,
                  actionLabel: 'Retry',
                  onAction: _fetch,
                )
              : PayslipView(payslip: p!),
    );
  }
}

class PayslipView extends StatelessWidget {
  const PayslipView({super.key, required this.payslip});
  final Payslip payslip;

  Widget _fact(BuildContext context, String label, String? value) => Padding(
        padding: const EdgeInsets.symmetric(vertical: 5),
        child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Expanded(flex: 4, child: Text(label, style: TextStyle(color: Theme.of(context).colorScheme.onSurfaceVariant))),
          Expanded(
            flex: 5,
            child: Text((value == null || value.isEmpty) ? '—' : value, textAlign: TextAlign.end, style: const TextStyle(fontWeight: FontWeight.w600)),
          ),
        ]),
      );

  Widget _lines(BuildContext context, String title, List<PayslipLine> rows, int total,
      {bool showFull = false, Tone tone = Tone.neutral, IconData icon = Icons.list_alt_rounded}) {
    final scheme = Theme.of(context).colorScheme;
    return Padding(
      padding: const EdgeInsets.only(top: 12),
      child: AppCard(
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Row(children: [
            IconBadge(icon: icon, tone: tone, size: 32),
            const SizedBox(width: 10),
            Expanded(child: Text(title, style: Theme.of(context).textTheme.titleMedium?.copyWith(fontWeight: FontWeight.w700))),
          ]),
          const SizedBox(height: 10),
          if (rows.isEmpty) Text('None', style: TextStyle(color: scheme.onSurfaceVariant)),
          for (final r in rows)
            Padding(
              padding: const EdgeInsets.symmetric(vertical: 5),
              child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
                Expanded(
                  child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                    Text(r.componentName),
                    if (r.note != null) Text(r.note!, style: TextStyle(fontSize: 12, color: scheme.onSurfaceVariant)),
                    if (showFull && r.fullMonthlyMinor != null && r.fullMonthlyMinor != r.amountMinor)
                      Text('Full month ${formatInr(r.fullMonthlyMinor!)}', style: TextStyle(fontSize: 12, color: scheme.onSurfaceVariant)),
                  ]),
                ),
                Text(formatInr(r.amountMinor), style: const TextStyle(fontWeight: FontWeight.w600)),
              ]),
            ),
          Divider(color: scheme.outlineVariant),
          Row(mainAxisAlignment: MainAxisAlignment.spaceBetween, children: [
            const Text('Total', style: TextStyle(fontWeight: FontWeight.w700)),
            Text(formatInr(total), style: const TextStyle(fontWeight: FontWeight.w700)),
          ]),
        ]),
      ),
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
          Padding(
            padding: const EdgeInsets.only(bottom: 12),
            child: Container(
              padding: const EdgeInsets.all(12),
              decoration: BoxDecoration(color: toneColors(context, Tone.warning).bg, borderRadius: BorderRadius.circular(12)),
              child: Row(children: [
                Icon(Icons.info_outline_rounded, size: 18, color: toneColors(context, Tone.warning).fg),
                const SizedBox(width: 8),
                const Expanded(child: Text('Preview — this pay run is not finalised yet')),
              ]),
            ),
          ),
        // Net-pay hero.
        Container(
          padding: const EdgeInsets.all(20),
          decoration: BoxDecoration(
            borderRadius: BorderRadius.circular(20),
            gradient: const LinearGradient(begin: Alignment.topLeft, end: Alignment.bottomRight, colors: [AppBrand.navy, Color(0xFF1E3A8A)]),
          ),
          child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Text(p.legalEntityName ?? p.companyName ?? '', style: const TextStyle(color: Colors.white70, fontWeight: FontWeight.w600)),
            const SizedBox(height: 4),
            Text('Payslip for ${formatPayMonth(p.month)}${p.isFinal ? '' : ' (preview)'}', style: const TextStyle(color: Colors.white, fontWeight: FontWeight.w600)),
            const SizedBox(height: 14),
            const Text('Net pay', style: TextStyle(color: Colors.white70, fontSize: 13)),
            const SizedBox(height: 2),
            Text(formatInr(p.netMinor), style: const TextStyle(color: Colors.white, fontSize: 32, fontWeight: FontWeight.w800)),
            if (p.netInWords.isNotEmpty) ...[
              const SizedBox(height: 4),
              Text(p.netInWords, style: const TextStyle(color: Colors.white70, fontSize: 12)),
            ],
            const SizedBox(height: 14),
            Row(children: [
              _heroStat('Gross', formatInr(p.grossMinor)),
              const SizedBox(width: 24),
              _heroStat('Deductions', formatInr(p.deductionsMinor)),
            ]),
          ]),
        ),
        if (p.legalEntityAddress != null)
          Padding(
            padding: const EdgeInsets.only(top: 8),
            child: Text(p.legalEntityAddress!, textAlign: TextAlign.center, style: TextStyle(fontSize: 12, color: scheme.onSurfaceVariant)),
          ),
        const SizedBox(height: 12),
        AppCard(
          child: Column(children: [
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
          ]),
        ),
        _lines(context, 'Earnings', p.earnings, p.grossMinor, showFull: true, tone: Tone.success, icon: Icons.south_west_rounded),
        _lines(context, 'Deductions', p.deductions, p.deductionsMinor, tone: Tone.danger, icon: Icons.north_east_rounded),
        if (p.employerContributions.isNotEmpty)
          _lines(context, 'Employer contributions (not part of net pay)', p.employerContributions, employerTotal, tone: Tone.info, icon: Icons.account_balance_rounded),
        if (p.leaveBalances.isNotEmpty) ...[
          const SizedBox(height: 12),
          AppCard(
            child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
              Text('Leave balance on ${p.periodEnd}', style: Theme.of(context).textTheme.titleSmall?.copyWith(fontWeight: FontWeight.w700)),
              const SizedBox(height: 8),
              Wrap(spacing: 8, runSpacing: 8, children: [
                for (final b in p.leaveBalances) StatusChip(label: '${b.name}: ${b.balance}', tone: Tone.accent, dot: false),
              ]),
            ]),
          ),
        ],
        const SizedBox(height: 16),
        Center(child: Text('This is a computer-generated payslip and does not need a signature.', style: TextStyle(fontSize: 11, color: scheme.onSurfaceVariant), textAlign: TextAlign.center)),
      ],
    );
  }

  Widget _heroStat(String label, String value) => Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Text(label, style: const TextStyle(color: Colors.white60, fontSize: 11)),
        Text(value, style: const TextStyle(color: Colors.white, fontWeight: FontWeight.w700)),
      ]);
}
