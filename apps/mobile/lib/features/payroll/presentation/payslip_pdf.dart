import 'dart:typed_data';

import 'package:pdf/pdf.dart';
import 'package:pdf/widgets.dart' as pw;

import '../../../core/format.dart';
import '../data/payroll_repository.dart';

// The bundled PDF fonts have no ₹ glyph, so amounts are printed as "Rs".
String _money(int minor) => formatInr(minor).replaceAll('₹', 'Rs ');

/// A printable payslip (FR-PAY-017) — the same content as the web `PayslipView`, rendered to a
/// PDF so it can be shared, saved or printed from the phone.
Future<Uint8List> buildPayslipPdf(Payslip p) async {
  final doc = pw.Document(title: 'Payslip ${p.month}', author: p.legalEntityName ?? p.companyName);

  pw.Widget fact(String label, String? value) => pw.Padding(
        padding: const pw.EdgeInsets.symmetric(vertical: 1.5),
        child: pw.Row(mainAxisAlignment: pw.MainAxisAlignment.spaceBetween, children: [
          pw.Text(label, style: const pw.TextStyle(fontSize: 9, color: PdfColors.grey700)),
          pw.Text((value == null || value.isEmpty) ? '-' : value, style: const pw.TextStyle(fontSize: 9)),
        ]),
      );

  pw.Widget lines(String title, List<PayslipLine> rows, int total, {bool showFull = false}) {
    final style = pw.TextStyle(fontSize: 9, fontWeight: pw.FontWeight.bold);
    return pw.Table(
      columnWidths: {0: const pw.FlexColumnWidth(3), if (showFull) 1: const pw.FlexColumnWidth(2), (showFull ? 2 : 1): const pw.FlexColumnWidth(2)},
      children: [
        pw.TableRow(
          decoration: const pw.BoxDecoration(border: pw.Border(bottom: pw.BorderSide(color: PdfColors.grey500))),
          children: [
            pw.Text(title, style: style),
            if (showFull) pw.Align(alignment: pw.Alignment.centerRight, child: pw.Text('Full month', style: style)),
            pw.Align(alignment: pw.Alignment.centerRight, child: pw.Text('Amount', style: style)),
          ],
        ),
        if (rows.isEmpty)
          pw.TableRow(children: [pw.Text('None', style: const pw.TextStyle(fontSize: 9)), if (showFull) pw.SizedBox(), pw.SizedBox()]),
        for (final r in rows)
          pw.TableRow(children: [
            pw.Text('${r.componentName}${r.note != null ? '\n${r.note}' : ''}', style: const pw.TextStyle(fontSize: 9)),
            if (showFull)
              pw.Align(alignment: pw.Alignment.centerRight, child: pw.Text(r.fullMonthlyMinor == null ? '' : _money(r.fullMonthlyMinor!), style: const pw.TextStyle(fontSize: 9))),
            pw.Align(alignment: pw.Alignment.centerRight, child: pw.Text(_money(r.amountMinor), style: const pw.TextStyle(fontSize: 9))),
          ]),
        pw.TableRow(children: [
          pw.Text('Total', style: style),
          if (showFull) pw.SizedBox(),
          pw.Align(alignment: pw.Alignment.centerRight, child: pw.Text(_money(total), style: style)),
        ]),
      ],
    );
  }

  final employerTotal = p.employerContributions.fold<int>(0, (s, l) => s + l.amountMinor);
  final bank = p.paymentMode == 'BANK' ? '${p.bankName ?? 'Bank'} ....${p.accountLast4 ?? ''}' : p.paymentMode;

  doc.addPage(pw.MultiPage(
    pageFormat: PdfPageFormat.a4,
    margin: const pw.EdgeInsets.all(32),
    build: (ctx) => [
      pw.Center(
        child: pw.Column(children: [
          pw.Text(p.legalEntityName ?? p.companyName ?? '', style: pw.TextStyle(fontSize: 16, fontWeight: pw.FontWeight.bold)),
          if (p.legalEntityAddress != null) pw.Text(p.legalEntityAddress!, style: const pw.TextStyle(fontSize: 8, color: PdfColors.grey700)),
          pw.SizedBox(height: 6),
          pw.Text('Payslip for ${formatPayMonth(p.month)}${p.isFinal ? '' : ' (preview)'}', style: pw.TextStyle(fontSize: 11, fontWeight: pw.FontWeight.bold)),
        ]),
      ),
      pw.Divider(),
      fact('Employee', p.employeeName),
      fact('Employee code', p.employeeCode),
      fact('Designation', p.designation),
      fact('Department', p.department),
      fact('Date of joining', p.dateOfJoining),
      fact('PAN', p.panMasked),
      fact('UAN', p.uanNumber),
      if (p.esiIpNumber != null) fact('ESI IP number', p.esiIpNumber),
      fact('Paid by', bank),
      fact('Days in month', '${p.daysInMonth}'),
      fact('Paid days', p.paidDays),
      fact('Loss of pay days', p.lopDays),
      fact('Pay date', p.payDate),
      pw.SizedBox(height: 14),
      lines('Earnings', p.earnings, p.grossMinor, showFull: true),
      pw.SizedBox(height: 10),
      lines('Deductions', p.deductions, p.deductionsMinor),
      pw.SizedBox(height: 14),
      pw.Container(
        padding: const pw.EdgeInsets.all(8),
        color: PdfColors.grey200,
        child: pw.Column(crossAxisAlignment: pw.CrossAxisAlignment.start, children: [
          pw.Row(mainAxisAlignment: pw.MainAxisAlignment.spaceBetween, children: [
            pw.Text('Net pay', style: pw.TextStyle(fontSize: 12, fontWeight: pw.FontWeight.bold)),
            pw.Text(_money(p.netMinor), style: pw.TextStyle(fontSize: 12, fontWeight: pw.FontWeight.bold)),
          ]),
          if (p.netInWords.isNotEmpty) pw.Text(p.netInWords, style: const pw.TextStyle(fontSize: 9)),
        ]),
      ),
      if (p.employerContributions.isNotEmpty) ...[
        pw.SizedBox(height: 14),
        lines('Employer contributions (not part of net pay)', p.employerContributions, employerTotal),
      ],
      if (p.leaveBalances.isNotEmpty) ...[
        pw.SizedBox(height: 14),
        pw.Text('Leave balance on ${p.periodEnd}', style: pw.TextStyle(fontSize: 9, fontWeight: pw.FontWeight.bold)),
        pw.Text(p.leaveBalances.map((b) => '${b.name}: ${b.balance}').join('    '), style: const pw.TextStyle(fontSize: 9)),
      ],
      pw.SizedBox(height: 18),
      pw.Center(child: pw.Text('This is a computer-generated payslip and does not need a signature.', style: const pw.TextStyle(fontSize: 8, color: PdfColors.grey700))),
    ],
  ));
  return doc.save();
}
