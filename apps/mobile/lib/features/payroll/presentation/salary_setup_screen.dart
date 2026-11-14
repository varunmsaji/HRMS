import 'dart:async';
import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../core/api/api_error.dart';
import '../../../core/format.dart';
import '../../../core/providers.dart';
import '../domain/payroll_resources.dart';
import 'structure_lines_editor.dart';

const _revisionLabels = {'JOINING': 'Joining', 'ANNUAL': 'Annual increment', 'PROMOTION': 'Promotion', 'CORRECTION': 'Correction of an error', 'MARKET': 'Market correction'};

const _previewDelay = Duration(milliseconds: 400);

/// What a set of line inputs pays, ignoring order — equal keys, equal pay (mirrors web `payKey`).
String _payKey(List<Rec> inputs) {
  final keys = [
    for (final i in inputs)
      [
        i['salary_component_id'],
        i['calculation_type'],
        i['percentage'] == null ? null : num.tryParse('${i['percentage']}'),
        i['amount_monthly_minor'],
        i['base_salary_component_id'],
        i['max_monthly_minor'],
        i['applies_when'],
      ],
  ]..sort((a, b) => '${a[0]}'.compareTo('${b[0]}'));
  return jsonEncode(keys);
}

Rec? _currentVersion(Rec structure) {
  for (final v in ((structure['versions'] as List?) ?? const []).cast<Rec>()) {
    if (v['status'] == 'PUBLISHED' && v['effective_to'] == null) return v;
  }
  return null;
}

List<Rec> _templateLines(Rec? structure) => structure == null ? const [] : (((_currentVersion(structure)?['lines'] as List?) ?? const []).cast<Rec>());

String _iso(DateTime d) => '${d.year.toString().padLeft(4, '0')}-${d.month.toString().padLeft(2, '0')}-${d.day.toString().padLeft(2, '0')}';

/// An employee's CTC and salary structure edited together — mirrors
/// `apps/web/src/components/payroll/salary-setup-editor.tsx`: start from a company structure,
/// change any percentage for this employee, and every component's amount fills in as you type.
/// Saving records the CTC (when it changed) and the structure from one effective date; changed
/// lines become this employee's own structure, the template is left as it is.
/// "a", "a and b", "a, b and c".
String joinList(List<String> items) =>
    items.length <= 1 ? items.join() : '${items.sublist(0, items.length - 1).join(', ')} and ${items.last}';

class SalarySetupScreen extends ConsumerStatefulWidget {
  const SalarySetupScreen({super.key, required this.employeeId, required this.today});
  final String employeeId;
  final String today;

  @override
  ConsumerState<SalarySetupScreen> createState() => _SalarySetupScreenState();
}

class _SalarySetupScreenState extends ConsumerState<SalarySetupScreen> {
  Rec? _setup;
  List<Rec> _templates = const [];
  List<Rec> _components = const [];
  String? _loadError;

  String _templateId = '';
  final _ctc = TextEditingController();
  final _reason = TextEditingController();
  List<StructureLine> _lines = [];
  late String _effectiveFrom = widget.today;
  String _revisionType = 'ANNUAL';
  Rec? _preview;
  String? _previewError;
  String? _formError;
  /// Set when Save is pressed with something missing: from then on the missing fields are marked.
  bool _showMissing = false;
  bool _saving = false;
  Timer? _debounce;
  int _previewSeq = 0;

  String get _base => '/employees/${widget.employeeId}/salary/setup';

  @override
  void initState() {
    super.initState();
    _load();
  }

  @override
  void dispose() {
    _debounce?.cancel();
    _ctc.dispose();
    _reason.dispose();
    for (final l in _lines) {
      l.dispose();
    }
    super.dispose();
  }

  Future<void> _load() async {
    final client = ref.read(apiClientProvider);
    try {
      final setup = await client.get<Rec>('$_base?as_of=${widget.today}', parse: (d) => d as Rec);
      final structures = await client.getList<Rec>('/payroll/salary-structures', parseItem: (d) => d as Rec);
      final components = await client.getList<Rec>('/payroll/salary-components', parseItem: (d) => d as Rec);
      if (!mounted) return;
      setState(() {
        _templates = [
          for (final s in structures.data)
            if (hasCurrentVersion(s)) s,
        ];
        _components = components.data;
      });
      _apply(setup);
    } catch (e) {
      if (mounted) setState(() => _loadError = e is ApiError ? e.message : 'Something went wrong.');
    }
  }

  Rec? get _template {
    for (final s in _templates) {
      if (s['id'] == _templateId) return s;
    }
    return null;
  }

  void _setLines(List<Rec> reads) {
    for (final l in _lines) {
      l.dispose();
    }
    _lines = [for (final r in reads) StructureLine.fromRead(r)];
  }

  void _apply(Rec setup) {
    final ctc = setup['annual_ctc_minor'] as num?;
    Rec? template;
    for (final s in _templates) {
      if (s['id'] == setup['template_structure_id']) template = s;
    }
    template ??= _templates.isEmpty ? null : _templates.first;
    final lines = ((setup['lines'] as List?) ?? const []).cast<Rec>();
    setState(() {
      _setup = setup;
      _templateId = (template?['id'] as String?) ?? '';
      _setLines(lines.isNotEmpty ? lines : _templateLines(template));
      _ctc.text = ctc == null ? '' : (ctc / 100).toString().replaceAll(RegExp(r'\.0$'), '');
      _revisionType = ctc == null ? 'JOINING' : 'ANNUAL';
      _reason.clear();
      _formError = null;
      _showMissing = false;
    });
    _schedulePreview();
  }

  List<Rec> get _inputs => [for (var i = 0; i < _lines.length; i++) _lines[i].toInput(i)];
  bool get _complete => _lines.isNotEmpty && _lines.every((l) => l.componentId.isNotEmpty);
  int? get _annualMinor => rupeesToMinor(_ctc.text);
  bool get _ctcChanged => _annualMinor != null && _annualMinor != (_setup?['annual_ctc_minor'] as num?)?.toInt();
  bool get _customised => _template != null && _payKey(_inputs) != _payKey(structureLineInputs(_templateLines(_template)));
  bool get _dirty {
    final s = _setup;
    if (s == null) return false;
    return _ctcChanged || _templateId != (s['template_structure_id'] ?? '') || _payKey(_inputs) != _payKey(structureLineInputs(((s['lines'] as List?) ?? const []).cast<Rec>()));
  }

  /// Live auto-fill: recompute the breakup shortly after the CTC or a line stops changing.
  void _changed() {
    setState(() {});
    _schedulePreview();
  }

  void _schedulePreview() {
    _debounce?.cancel();
    final annual = _annualMinor;
    if (_setup == null || annual == null || annual == 0 || !_complete) return;
    _debounce = Timer(_previewDelay, () async {
      final seq = ++_previewSeq;
      try {
        final result = await ref.read(apiClientProvider).post<Rec>('$_base/preview', body: {'annual_ctc_minor': annual, 'as_of': _effectiveFrom, 'lines': _inputs}, parse: (d) => d as Rec);
        if (mounted && seq == _previewSeq) {
          setState(() {
            _preview = result;
            _previewError = null;
          });
        }
      } catch (e) {
        if (mounted && seq == _previewSeq) {
          setState(() {
            _preview = null;
            _previewError = e is ApiError ? e.message : 'Something went wrong.';
          });
        }
      }
    });
  }

  Map<String, num> get _amounts {
    final breakup = _preview?['breakup'] as Rec?;
    if (breakup == null) return const {};
    final idByCode = {for (final c in _components) c['code']: c['id']};
    return {
      for (final l in ((breakup['lines'] as List?) ?? const []).cast<Rec>())
        if (idByCode[l['component_code']] != null) idByCode[l['component_code']] as String: l['monthly_minor'] as num,
    };
  }

  bool get _ctcMissing => _annualMinor == null;
  bool get _reasonMissing => _reason.text.trim().isEmpty;

  /// What still has to be filled in before the salary can be saved, in form order.
  List<String> get _missing => [
        if (_ctcMissing) 'the annual CTC',
        if (_templateId.isEmpty) 'a structure',
        if (!_complete) 'at least one pay line',
        if (_reasonMissing) 'a reason',
      ];

  /// Live: shrinks as each missing field is filled in, and disappears once nothing is missing.
  String? get _shownError {
    final missing = _missing;
    if (_showMissing && missing.isNotEmpty) return 'Before saving, add ${joinList(missing)}.';
    return _formError;
  }

  Future<void> _save() async {
    final annual = _annualMinor;
    if (_missing.isNotEmpty || annual == null) {
      return setState(() {
        _showMissing = true;
        _formError = null;
      });
    }
    if (!_dirty) {
      return setState(() => _formError = 'Nothing has changed yet. Edit the CTC, the structure or a pay line first.');
    }
    setState(() {
      _saving = true;
      _formError = null;
    });
    try {
      await ref
          .read(apiClientProvider)
          .post<Object?>(
            _base,
            body: {
              'effective_from': _effectiveFrom,
              'reason': _reason.text.trim(),
              'template_structure_id': _templateId,
              'lines': _inputs,
              if (_ctcChanged) ...{'annual_ctc_minor': annual, 'revision_type': _revisionType},
            },
            parse: (_) => null,
          );
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(const SnackBar(content: Text('Salary saved.')));
      Navigator.of(context).pop(true);
    } catch (e) {
      if (mounted) setState(() => _formError = e is ApiError ? e.message : 'Something went wrong.');
    } finally {
      if (mounted) setState(() => _saving = false);
    }
  }

  Widget _stat(BuildContext context, String label, String value) => Expanded(
    child: Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text(label, style: TextStyle(fontSize: 12, color: Theme.of(context).colorScheme.onSurfaceVariant)),
        const SizedBox(height: 2),
        Text(value, style: const TextStyle(fontSize: 18, fontWeight: FontWeight.w700, fontFeatures: [FontFeature.tabularFigures()])),
      ],
    ),
  );

  @override
  Widget build(BuildContext context) {
    final scheme = Theme.of(context).colorScheme;
    final setup = _setup;
    Widget body;
    if (_loadError != null) {
      body = Center(child: Padding(padding: const EdgeInsets.all(24), child: Text(_loadError!, style: TextStyle(color: scheme.error))));
    } else if (setup == null) {
      body = const Center(child: CircularProgressIndicator());
    } else if (setup['pay_basis'] != 'MONTHLY') {
      body = Center(
        child: Padding(
          padding: const EdgeInsets.all(24),
          child: Text(
            setup['pay_basis'] == 'DAILY_WAGE' ? 'This is a daily-wage employee — set a daily rate with "Assign" on the Salary tab.' : 'This employee is not employed today.',
            textAlign: TextAlign.center,
          ),
        ),
      );
    } else {
      final template = _template;
      final annual = _annualMinor;
      final breakup = _preview?['breakup'] as Rec?;
      final shownError = _shownError;
      const dense = InputDecoration(isDense: true, border: OutlineInputBorder());
      final border = BoxDecoration(border: Border.all(color: scheme.outlineVariant), borderRadius: BorderRadius.circular(12));
      body = ListView(
        padding: const EdgeInsets.fromLTRB(16, 12, 16, 24),
        children: [
          Container(
            decoration: border,
            padding: const EdgeInsets.all(12),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Row(
                  children: [
                    Expanded(
                      child: TextField(
                        controller: _ctc,
                        keyboardType: const TextInputType.numberWithOptions(decimal: true),
                        decoration: dense.copyWith(labelText: 'Annual CTC (₹)', errorText: _showMissing && _ctcMissing ? 'Required' : null),
                        onChanged: (_) => _changed(),
                      ),
                    ),
                    const SizedBox(width: 8),
                    Expanded(
                      child: DropdownButtonFormField<String>(
                        value: _templateId.isEmpty ? null : _templateId,
                        isExpanded: true,
                        decoration: dense.copyWith(labelText: 'Structure', errorText: _showMissing && _templateId.isEmpty ? 'Required' : null),
                        items: [for (final s in _templates) DropdownMenuItem(value: s['id'] as String, child: Text('${s['name']}', overflow: TextOverflow.ellipsis))],
                        onChanged: (v) {
                          if (v == null) return;
                          _templateId = v;
                          _setLines(_templateLines(_template));
                          _changed();
                        },
                      ),
                    ),
                  ],
                ),
                const SizedBox(height: 12),
                Row(
                  children: [
                    _stat(context, 'CTC a month', annual == null ? '—' : formatInr((annual / 12).round())),
                    _stat(context, 'Gross a month', breakup == null ? '—' : formatInr(breakup['gross_monthly_minor'] as num)),
                  ],
                ),
                if (template != null) ...[
                  const SizedBox(height: 8),
                  Row(
                    children: [
                      Icon(_customised ? Icons.tune_rounded : Icons.check_circle_outline_rounded, size: 16, color: _customised ? scheme.tertiary : scheme.primary),
                      const SizedBox(width: 6),
                      Expanded(child: Text(_customised ? 'Customised for this employee' : 'Same as ${template['name']}', style: const TextStyle(fontSize: 13))),
                      if (_customised)
                        TextButton(
                          style: TextButton.styleFrom(visualDensity: VisualDensity.compact),
                          onPressed: () {
                            _setLines(_templateLines(template));
                            _changed();
                          },
                          child: const Text('Reset'),
                        ),
                    ],
                  ),
                ],
              ],
            ),
          ),
          const SizedBox(height: 12),
          StructureLinesEditor(lines: _lines, components: _components, amounts: _amounts, breakup: breakup, onChanged: _changed),
          if (_previewError != null)
            Padding(padding: const EdgeInsets.only(bottom: 8), child: Text(_previewError!, style: TextStyle(color: scheme.error)))
          else
            Padding(
              padding: const EdgeInsets.only(bottom: 8),
              child: Text(
                'Monthly amounts. One earning takes the rest of gross; employer contributions sit inside CTC. PF ${setup['pf_applicable'] == true ? 'applies' : 'does not apply'}.',
                style: TextStyle(fontSize: 12, color: scheme.onSurfaceVariant),
              ),
            ),
          const Divider(height: 24),
          Row(
            children: [
              Expanded(
                child: OutlinedButton.icon(
                  onPressed: () async {
                    final picked = await showDatePicker(context: context, initialDate: DateTime.tryParse(_effectiveFrom) ?? DateTime.now(), firstDate: DateTime(2020), lastDate: DateTime(2100));
                    if (picked == null) return;
                    _effectiveFrom = _iso(picked);
                    _changed();
                  },
                  icon: const Icon(Icons.calendar_today_outlined, size: 16),
                  label: Text('From $_effectiveFrom'),
                ),
              ),
              if (_ctcChanged) ...[
                const SizedBox(width: 8),
                Expanded(
                  child: DropdownButtonFormField<String>(
                    value: _revisionType,
                    isExpanded: true,
                    decoration: dense.copyWith(labelText: 'CTC change'),
                    items: [for (final e in _revisionLabels.entries) DropdownMenuItem(value: e.key, child: Text(e.value, overflow: TextOverflow.ellipsis))],
                    onChanged: (v) => setState(() => _revisionType = v ?? _revisionType),
                  ),
                ),
              ],
            ],
          ),
          const SizedBox(height: 10),
          TextField(
            controller: _reason,
            maxLength: 500,
            decoration: dense.copyWith(labelText: 'Reason', hintText: 'e.g. Annual review', counterText: '', errorText: _showMissing && _reasonMissing ? 'Required' : null),
            onChanged: (_) => setState(() {}),
          ),
          if (shownError != null) Padding(padding: const EdgeInsets.only(top: 8), child: Text(shownError, style: TextStyle(color: scheme.error))),
          const SizedBox(height: 12),
          FilledButton(onPressed: _saving ? null : _save, child: Text(_saving ? 'Saving…' : 'Save salary')),
        ],
      );
    }
    return Scaffold(appBar: AppBar(title: const Text('Salary setup')), body: body);
  }
}
