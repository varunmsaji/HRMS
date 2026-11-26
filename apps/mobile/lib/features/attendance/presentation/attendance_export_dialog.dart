import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../core/api/api_error.dart';
import '../../../core/export/file_share.dart';
import '../data/attendance_repository.dart';
import '../domain/attendance_export.dart';

/// Asks for a period and a format, then downloads the muster register or one report from the
/// server and opens the share sheet. [path] builds the request for the chosen period and format;
/// [pdfLimited] applies the register's 62-day PDF limit (web `PeriodExport`).
Future<void> showAttendanceExport(
  BuildContext context,
  WidgetRef ref, {
  required String title,
  required String filePrefix,
  required String from,
  required String to,
  required String today,
  required String Function(String from, String to, String format) path,
  bool pdfLimited = false,
}) =>
    showDialog<void>(
      context: context,
      builder: (_) => _ExportDialog(title: title, filePrefix: filePrefix, from: from, to: to, today: today, path: path, pdfLimited: pdfLimited, ref: ref),
    );

String _iso(DateTime d) => '${d.year.toString().padLeft(4, '0')}-${d.month.toString().padLeft(2, '0')}-${d.day.toString().padLeft(2, '0')}';

class _ExportDialog extends StatefulWidget {
  const _ExportDialog({required this.title, required this.filePrefix, required this.from, required this.to, required this.today, required this.path, required this.pdfLimited, required this.ref});
  final String title;
  final String filePrefix;
  final String from;
  final String to;
  final String today;
  final String Function(String from, String to, String format) path;
  final bool pdfLimited;
  final WidgetRef ref;

  @override
  State<_ExportDialog> createState() => _ExportDialogState();
}

class _ExportDialogState extends State<_ExportDialog> {
  late String _from = widget.from;
  late String _to = widget.to.compareTo(widget.today) > 0 ? widget.today : widget.to;
  String _format = 'csv';
  bool _busy = false;
  String? _failure;

  String? get _problem => exportWindowError(_from, _to, widget.today) ?? (widget.pdfLimited && _format == 'pdf' ? pdfRegisterError(_from, _to) : null);

  Future<void> _pick(bool start) async {
    final current = DateTime.tryParse(start ? _from : _to) ?? DateTime.now();
    final picked = await showDatePicker(context: context, initialDate: current, firstDate: DateTime(2020), lastDate: DateTime.parse(widget.today));
    if (picked == null) return;
    setState(() => start ? _from = _iso(picked) : _to = _iso(picked));
  }

  Future<void> _export() async {
    setState(() {
      _busy = true;
      _failure = null;
    });
    try {
      final file = await widget.ref.read(attendanceRepositoryProvider).downloadExport(widget.path(_from, _to, _format));
      await widget.ref.read(fileSharerProvider)(file.filename ?? '${widget.filePrefix}_${_from}_$_to.$_format', file.bytes, exportMimeTypes[_format]!);
      if (mounted) Navigator.of(context).pop();
    } catch (e) {
      if (mounted) setState(() => _failure = e is ApiError ? describeApiError(e) : 'Could not export.');
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final problem = _problem;
    return AlertDialog(
      title: Text(widget.title),
      content: Column(mainAxisSize: MainAxisSize.min, crossAxisAlignment: CrossAxisAlignment.start, children: [
        Row(children: [
          Expanded(child: OutlinedButton(onPressed: _busy ? null : () => _pick(true), child: Text('From $_from'))),
          const SizedBox(width: 8),
          Expanded(child: OutlinedButton(onPressed: _busy ? null : () => _pick(false), child: Text('To $_to'))),
        ]),
        const SizedBox(height: 12),
        DropdownButtonFormField<String>(
          value: _format,
          decoration: const InputDecoration(labelText: 'Format'),
          items: [for (final e in exportFormatLabels.entries) DropdownMenuItem(value: e.key, child: Text(e.value))],
          onChanged: _busy ? null : (v) => setState(() => _format = v ?? _format),
        ),
        const SizedBox(height: 8),
        Text(
          problem ?? _failure ?? 'Up to a year, for the employees you can see.',
          style: TextStyle(fontSize: 12, color: problem != null || _failure != null ? Theme.of(context).colorScheme.error : Theme.of(context).colorScheme.onSurfaceVariant),
        ),
      ]),
      actions: [
        TextButton(onPressed: _busy ? null : () => Navigator.of(context).pop(), child: const Text('Cancel')),
        FilledButton(onPressed: _busy || problem != null ? null : _export, child: Text(_busy ? 'Preparing…' : 'Export')),
      ],
    );
  }
}
