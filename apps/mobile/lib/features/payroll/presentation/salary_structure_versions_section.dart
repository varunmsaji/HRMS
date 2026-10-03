import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../core/api/api_error.dart';
import '../../../core/auth/permissions.dart';
import '../../../core/forms/choice_sources.dart';
import '../../../core/forms/spec_form_screen.dart';
import '../../../core/format.dart';
import '../../../core/providers.dart';
import '../../auth/state/auth_controller.dart';
import '../domain/payroll_resources.dart';
import 'salary_breakup_view.dart';

typedef Rec = Map<String, dynamic>;

/// The versions of a salary structure — mirrors `apps/web/src/app/app/payroll/salary-structures/[id]/page.tsx`:
/// published versions are read-only; "Edit (new draft)" copies the current version into a draft,
/// whose lines are edited as a whole (`PUT …/lines`), previewed against a CTC, then published from
/// an effective date. A draft can be discarded.
class SalaryStructureVersionsSection extends ConsumerStatefulWidget {
  const SalaryStructureVersionsSection({super.key, required this.structure, required this.onChanged});

  /// The `SalaryStructureRead` (its `versions` carry their lines).
  final Rec structure;

  /// Called after a change so the parent reloads the structure.
  final VoidCallback onChanged;

  @override
  ConsumerState<SalaryStructureVersionsSection> createState() => _SalaryStructureVersionsSectionState();
}

class _SalaryStructureVersionsSectionState extends ConsumerState<SalaryStructureVersionsSection> {
  String? _selectedId;
  bool _busy = false;
  final _ctc = TextEditingController(text: '1200000');
  bool _pf = true;
  Rec? _preview;
  String? _previewError;

  String get _base => '/payroll/salary-structures/${widget.structure['id']}';

  List<Rec> get _versions => ((widget.structure['versions'] as List?) ?? const []).cast<Rec>();

  Rec? get _draft {
    for (final v in _versions) {
      if (v['status'] == 'DRAFT') return v;
    }
    return null;
  }

  Rec? get _selected {
    final versions = _versions;
    if (versions.isEmpty) return null;
    for (final v in versions) {
      if (v['id'] == _selectedId) return v;
    }
    return _draft ??
        versions.lastWhere((v) => v['status'] == 'PUBLISHED' && v['effective_to'] == null, orElse: () => versions.last);
  }

  void _toast(String m) => ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(m)));

  String _explain(Object e) {
    if (e is ApiError) {
      if (e.code == 'STALE_RESOURCE') return 'This structure was changed by someone else. Reloading.';
      if (e.status == 403) return "You don't have permission to do that.";
      return e.message;
    }
    return 'Something went wrong.';
  }

  Future<void> _run(Future<Object?> Function() action, String success) async {
    setState(() => _busy = true);
    try {
      await action();
      _toast(success);
    } catch (e) {
      _toast(_explain(e));
    } finally {
      if (mounted) setState(() => _busy = false);
      widget.onChanged();
    }
  }

  Future<void> _newDraft() async {
    await _run(() async => ref.read(apiClientProvider).post<Object?>('$_base/versions', body: const {}, parse: (_) => null), 'Draft created from the current version.');
    if (mounted) setState(() => _selectedId = null);
  }

  Future<void> _editLines(Rec draft) async {
    final client = ref.read(apiClientProvider);
    final saved = await openSpecForm(
      context,
      title: 'Edit lines',
      spec: structureLinesSpec,
      initial: {'lines': draft['lines']},
      loadChoices: () => loadChoices(client, const ['salary_components']),
      onSubmit: (payload, changed) async =>
          client.put<Object?>('$_base/versions/${draft['id']}/lines', body: {'lines': payload['lines']}, ifMatch: draft['version'].toString(), parse: (_) => null),
    );
    if (saved && mounted) {
      _toast('Draft saved.');
      widget.onChanged();
    }
  }

  Future<void> _discard(Rec draft) async {
    final yes = await showDialog<bool>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: const Text('Discard draft?'),
        content: const Text('The draft and its lines will be deleted.'),
        actions: [
          TextButton(onPressed: () => Navigator.of(ctx).pop(false), child: const Text('Cancel')),
          FilledButton(style: FilledButton.styleFrom(backgroundColor: Theme.of(ctx).colorScheme.error), onPressed: () => Navigator.of(ctx).pop(true), child: const Text('Discard')),
        ],
      ),
    );
    if (yes != true) return;
    await _run(() async => ref.read(apiClientProvider).delete<Object?>('$_base/versions/${draft['id']}', ifMatch: draft['version'].toString(), parse: (_) => null), 'Draft discarded.');
    if (mounted) setState(() => _selectedId = null);
  }

  Future<void> _publish(Rec draft) async {
    final date = TextEditingController();
    String? error;
    final ok = await showDialog<bool>(
      context: context,
      builder: (ctx) => StatefulBuilder(
        builder: (ctx, setLocal) => AlertDialog(
          title: const Text('Publish this version?'),
          content: Column(mainAxisSize: MainAxisSize.min, crossAxisAlignment: CrossAxisAlignment.start, children: [
            const Text('The current version ends the day before. A published version cannot be edited.'),
            const SizedBox(height: 12),
            if (error != null) Padding(padding: const EdgeInsets.only(bottom: 8), child: Text(error!, style: TextStyle(color: Theme.of(ctx).colorScheme.error))),
            TextField(
              controller: date,
              readOnly: true,
              decoration: const InputDecoration(labelText: 'Effective from *', hintText: 'YYYY-MM-DD', suffixIcon: Icon(Icons.calendar_today_outlined, size: 18)),
              onTap: () async {
                final picked = await showDatePicker(context: ctx, initialDate: DateTime.now(), firstDate: DateTime(2020), lastDate: DateTime(2100));
                if (picked != null) date.text = '${picked.year.toString().padLeft(4, '0')}-${picked.month.toString().padLeft(2, '0')}-${picked.day.toString().padLeft(2, '0')}';
              },
            ),
          ]),
          actions: [
            TextButton(onPressed: () => Navigator.of(ctx).pop(false), child: const Text('Cancel')),
            FilledButton(
              onPressed: () {
                if (date.text.isEmpty) return setLocal(() => error = 'Choose the effective date.');
                Navigator.of(ctx).pop(true);
              },
              child: const Text('Publish'),
            ),
          ],
        ),
      ),
    );
    if (ok != true) return;
    await _run(
      () async => ref.read(apiClientProvider).post<Object?>('$_base/versions/${draft['id']}/publish', body: {'effective_from': date.text}, ifMatch: draft['version'].toString(), parse: (_) => null),
      'Version published.',
    );
  }

  Future<void> _runPreview(Rec version) async {
    final annual = rupeesToMinor(_ctc.text);
    if (annual == null || annual == 0) {
      setState(() => _previewError = 'Enter an annual CTC in rupees.');
      return;
    }
    setState(() => _previewError = null);
    try {
      final result = await ref.read(apiClientProvider).post<Rec>('$_base/versions/${version['id']}/preview', body: {'annual_ctc_minor': annual, 'pf_applicable': _pf}, parse: (d) => d as Rec);
      if (mounted) setState(() => _preview = result);
    } catch (e) {
      if (mounted) {
        setState(() {
          _preview = null;
          _previewError = _explain(e);
        });
      }
    }
  }

  @override
  Widget build(BuildContext context) {
    final permissions = ref.watch(authControllerProvider).user?.permissions ?? const <String>[];
    final canManage = permissions.contains(payrollSetupManage);
    final scheme = Theme.of(context).colorScheme;
    final versions = _versions;
    final selected = _selected;
    final draft = _draft;
    final lines = ((selected?['lines'] as List?) ?? const []).cast<Rec>();
    final editing = selected != null && selected['status'] == 'DRAFT' && canManage;
    return Container(
      margin: const EdgeInsets.only(top: 16),
      padding: const EdgeInsets.all(14),
      decoration: BoxDecoration(border: Border.all(color: scheme.outlineVariant), borderRadius: BorderRadius.circular(12)),
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Text('Versions', style: Theme.of(context).textTheme.titleSmall),
        const SizedBox(height: 4),
        Text('Published versions are read-only. "Edit" starts a draft from the current version.', style: TextStyle(fontSize: 12, color: scheme.onSurfaceVariant)),
        if (canManage && draft == null)
          Padding(padding: const EdgeInsets.only(top: 10), child: FilledButton(onPressed: _busy ? null : _newDraft, child: const Text('Edit (new draft)'))),
        const SizedBox(height: 10),
        if (versions.isEmpty)
          Text('No versions yet.', style: TextStyle(color: scheme.onSurfaceVariant))
        else
          Wrap(spacing: 8, runSpacing: 4, children: [
            for (final v in versions)
              ChoiceChip(
                label: Text(v['status'] == 'DRAFT' ? 'Draft' : '${v['effective_from']} → ${v['effective_to'] ?? 'now'}'),
                selected: selected?['id'] == v['id'],
                onSelected: (_) => setState(() {
                  _selectedId = v['id'] as String;
                  _preview = null;
                }),
              ),
          ]),
        if (selected != null) ...[
          const SizedBox(height: 12),
          Row(children: [
            Text(selected['status'] == 'DRAFT' ? 'Draft' : 'Published', style: const TextStyle(fontWeight: FontWeight.w700)),
            const Spacer(),
          ]),
          if (editing)
            Padding(
              padding: const EdgeInsets.symmetric(vertical: 8),
              child: Wrap(spacing: 8, runSpacing: 8, children: [
                FilledButton(onPressed: _busy ? null : () => _editLines(selected), child: const Text('Edit lines')),
                FilledButton.tonal(onPressed: (_busy || lines.isEmpty) ? null : () => _publish(selected), child: const Text('Publish')),
                OutlinedButton(onPressed: _busy ? null : () => _discard(selected), child: const Text('Discard draft')),
              ]),
            ),
          if (lines.isEmpty)
            Text(editing ? 'No lines yet — use "Edit lines" to add components.' : 'No lines in this version.', style: TextStyle(color: scheme.onSurfaceVariant))
          else
            for (final l in lines)
              ListTile(
                contentPadding: EdgeInsets.zero,
                dense: true,
                title: Text('${l['component_name']}'),
                subtitle: Text(describeStructureLine(l, lines)),
              ),
          if (lines.isNotEmpty) ...[
            const Divider(height: 24),
            Text('Preview', style: Theme.of(context).textTheme.titleSmall),
            const SizedBox(height: 8),
            TextField(
              controller: _ctc,
              keyboardType: const TextInputType.numberWithOptions(decimal: true),
              decoration: const InputDecoration(labelText: 'Annual CTC (₹)'),
            ),
            SwitchListTile(contentPadding: EdgeInsets.zero, title: const Text('PF applies'), value: _pf, onChanged: (v) => setState(() => _pf = v)),
            Align(alignment: Alignment.centerLeft, child: OutlinedButton(onPressed: () => _runPreview(selected), child: const Text('Preview breakup'))),
            if (_previewError != null) Padding(padding: const EdgeInsets.only(top: 8), child: Text(_previewError!, style: TextStyle(color: scheme.error))),
            if (_preview != null) Padding(padding: const EdgeInsets.only(top: 10), child: SalaryBreakupView(breakup: _preview!)),
          ],
        ],
      ]),
    );
  }
}
