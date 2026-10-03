import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../core/api/api_error.dart';
import '../../../core/providers.dart';
import '../../../core/time.dart';
import '../../auth/state/auth_controller.dart';

typedef Rec = Map<String, dynamic>;

/// "Assign to employees" — mirrors the bulk dialog on the web salary-structures page
/// (`POST /payroll/salary-assignments/bulk`): every monthly-paid employee employed on the date who
/// has no salary structure yet gets the chosen one; the rest come back as skipped with a reason.
Future<void> showBulkAssignSalaryDialog(BuildContext context, List<Rec> structures) {
  if (structures.isEmpty) {
    ScaffoldMessenger.of(context).showSnackBar(const SnackBar(content: Text('Publish a salary structure first.')));
    return Future.value();
  }
  return showDialog<void>(context: context, builder: (_) => BulkAssignSalaryDialog(structures: structures));
}

class BulkAssignSalaryDialog extends ConsumerStatefulWidget {
  const BulkAssignSalaryDialog({super.key, required this.structures});

  final List<Rec> structures;

  @override
  ConsumerState<BulkAssignSalaryDialog> createState() => _BulkAssignSalaryDialogState();
}

class _BulkAssignSalaryDialogState extends ConsumerState<BulkAssignSalaryDialog> {
  late String _structureId = widget.structures.first['id'] as String;
  late String _date = businessToday(ref.read(authControllerProvider).user?.companyTimezone ?? 'Asia/Kolkata');
  bool _saving = false;
  String? _error;
  Rec? _result;

  Future<void> _pickDate() async {
    final p = await showDatePicker(context: context, initialDate: DateTime.tryParse(_date) ?? DateTime.now(), firstDate: DateTime(2000), lastDate: DateTime(2100));
    if (p != null) setState(() => _date = '${p.year.toString().padLeft(4, '0')}-${p.month.toString().padLeft(2, '0')}-${p.day.toString().padLeft(2, '0')}');
  }

  Future<void> _assign() async {
    setState(() {
      _saving = true;
      _error = null;
    });
    try {
      final r = await ref.read(apiClientProvider).post<Rec>('/payroll/salary-assignments/bulk', body: {'salary_structure_id': _structureId, 'effective_from': _date}, parse: (d) => d as Rec);
      if (mounted) setState(() => _result = r);
    } catch (e) {
      if (mounted) setState(() => _error = e is ApiError ? e.message : 'Could not assign the structure.');
    } finally {
      if (mounted) setState(() => _saving = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final r = _result;
    final assigned = (r?['assigned'] as List?)?.length ?? 0;
    final skipped = ((r?['skipped'] as List?) ?? const []).cast<Rec>();
    return AlertDialog(
      title: const Text('Assign a structure to employees'),
      content: SingleChildScrollView(
        child: r != null
            ? Column(mainAxisSize: MainAxisSize.min, crossAxisAlignment: CrossAxisAlignment.start, children: [
                Text('Assigned $assigned employee${assigned == 1 ? '' : 's'}; skipped ${skipped.length}.'),
                for (final s in skipped) Padding(padding: const EdgeInsets.only(top: 6), child: Text('• ${s['reason']}', style: const TextStyle(fontSize: 13))),
              ])
            : Column(mainAxisSize: MainAxisSize.min, crossAxisAlignment: CrossAxisAlignment.start, children: [
                const Text('Every monthly-paid employee employed on this date who has no salary structure yet gets this one. Daily-wage employees and anyone without a CTC are listed as skipped.'),
                const SizedBox(height: 12),
                DropdownButtonFormField<String>(
                  value: _structureId,
                  isExpanded: true,
                  decoration: const InputDecoration(labelText: 'Structure'),
                  items: [for (final s in widget.structures) DropdownMenuItem(value: s['id'] as String, child: Text('${s['name']}'))],
                  onChanged: (v) => setState(() => _structureId = v ?? _structureId),
                ),
                const SizedBox(height: 12),
                OutlinedButton.icon(onPressed: _pickDate, icon: const Icon(Icons.calendar_today_outlined, size: 18), label: Text('Effective from $_date')),
                if (_error != null) Padding(padding: const EdgeInsets.only(top: 8), child: Text(_error!, style: TextStyle(color: Theme.of(context).colorScheme.error))),
              ]),
      ),
      actions: r != null
          ? [FilledButton(onPressed: () => Navigator.of(context).pop(), child: const Text('Done'))]
          : [
              TextButton(onPressed: _saving ? null : () => Navigator.of(context).pop(), child: const Text('Cancel')),
              FilledButton(onPressed: _saving ? null : _assign, child: Text(_saving ? 'Assigning…' : 'Assign')),
            ],
    );
  }
}
