import 'dart:async';
import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../core/api/api_error.dart';
import '../../../core/format.dart';
import '../../../core/providers.dart';
import '../domain/payroll_resources.dart';
import 'salary_breakup_view.dart';

typedef Rec = Map<String, dynamic>;

const _revisionLabels = {'JOINING': 'Joining', 'ANNUAL': 'Annual increment', 'PROMOTION': 'Promotion', 'CORRECTION': 'Correction of an error', 'MARKET': 'Market correction'};

const _previewDelay = Duration(milliseconds: 400);

/// One structure line as the screen holds it — amounts in rupees, as typed.
class _Line {
  _Line({required this.componentId, required this.calc, String percentage = '', String amount = '', this.baseId = '', String cap = '', this.appliesWhen = 'ALWAYS'})
    : percentage = TextEditingController(text: percentage),
      amount = TextEditingController(text: amount),
      cap = TextEditingController(text: cap);

  factory _Line.fromRead(Rec l) {
    String rupees(Object? minor) => minor == null ? '' : ((minor as num) / 100).toString().replaceAll(RegExp(r'\.0$'), '');
    return _Line(
      componentId: l['salary_component_id'] as String,
      calc: l['calculation_type'] as String,
      percentage: (l['percentage'] as String?) ?? '',
      amount: rupees(l['amount_monthly_minor']),
      baseId: (l['base_salary_component_id'] as String?) ?? '',
      cap: rupees(l['max_monthly_minor']),
      appliesWhen: (l['applies_when'] as String?) ?? 'ALWAYS',
    );
  }

  String componentId;
  String calc;
  String baseId;
  String appliesWhen;
  final TextEditingController percentage;
  final TextEditingController amount;
  final TextEditingController cap;

  void dispose() {
    percentage.dispose();
    amount.dispose();
    cap.dispose();
  }

  /// The `SalaryStructureLineInput` (mirrors web `toInput`).
  Rec toInput(int index) {
    final pct = calc.startsWith('PERCENTAGE') && percentage.text.trim().isNotEmpty ? percentage.text.trim() : null;
    return {
      'salary_component_id': componentId,
      'calculation_type': calc,
      'percentage': pct,
      'amount_monthly_minor': calc == 'FIXED' ? rupeesToMinor(amount.text) : null,
      'base_salary_component_id': calc == 'PERCENTAGE_OF_COMPONENT' && baseId.isNotEmpty ? baseId : null,
      'max_monthly_minor': cap.text.trim().isEmpty ? null : rupeesToMinor(cap.text),
      'applies_when': appliesWhen,
      'display_order': (index + 1) * 10,
    };
  }
}

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

List<Rec> _readInputs(List<Rec> lines) => [for (var i = 0; i < lines.length; i++) _Line.fromRead(lines[i]).toInput(i)];

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
  List<_Line> _lines = [];
  late String _effectiveFrom = widget.today;
  String _revisionType = 'ANNUAL';
  Rec? _preview;
  String? _previewError;
  String? _formError;
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
    _lines = [for (final r in reads) _Line.fromRead(r)];
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
    });
    _schedulePreview();
  }

  List<Rec> get _inputs => [for (var i = 0; i < _lines.length; i++) _lines[i].toInput(i)];
  bool get _complete => _lines.isNotEmpty && _lines.every((l) => l.componentId.isNotEmpty);
  int? get _annualMinor => rupeesToMinor(_ctc.text);
  bool get _ctcChanged => _annualMinor != null && _annualMinor != (_setup?['annual_ctc_minor'] as num?)?.toInt();
  bool get _customised => _template != null && _payKey(_inputs) != _payKey(_readInputs(_templateLines(_template)));
  bool get _dirty {
    final s = _setup;
    if (s == null) return false;
    return _ctcChanged || _templateId != (s['template_structure_id'] ?? '') || _payKey(_inputs) != _payKey(_readInputs(((s['lines'] as List?) ?? const []).cast<Rec>()));
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

  Future<void> _save() async {
    final annual = _annualMinor;
    if (annual == null) return setState(() => _formError = 'Enter the annual CTC in rupees.');
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

  Future<void> _addLine() async {
    final usable = _usable;
    final picked = await showModalBottomSheet<String>(
      context: context,
      builder:
          (ctx) => SafeArea(
            child: ListView(
              shrinkWrap: true,
              children: [
                for (final c in usable)
                  if (!_lines.any((l) => l.componentId == c['id'])) ListTile(title: Text('${c['name']}'), onTap: () => Navigator.of(ctx).pop(c['id'] as String)),
              ],
            ),
          ),
    );
    if (picked == null) return;
    _lines.add(_Line(componentId: picked, calc: 'FIXED'));
    _changed();
  }

  List<Rec> get _usable => [
    for (final c in _components)
      if (c['is_active'] != false && c['component_type'] != 'DEDUCTION') c,
  ];

  String _componentName(String id) {
    for (final c in _components) {
      if (c['id'] == id) return '${c['name']}';
    }
    return 'Component';
  }

  String? _componentType(String id) {
    for (final c in _components) {
      if (c['id'] == id) return c['component_type'] as String?;
    }
    return null;
  }

  Widget _lineCard(BuildContext context, int index) {
    final line = _lines[index];
    final scheme = Theme.of(context).colorScheme;
    final employer = _componentType(line.componentId) == 'EMPLOYER_CONTRIBUTION';
    final calcs = [
      for (final t in calculationTypeLabels.keys)
        if (!employer || (t != 'BALANCING' && t != 'PERCENTAGE_OF_GROSS')) t,
    ];
    final earnings = [
      for (final c in _usable)
        if (c['component_type'] == 'EARNING' && c['id'] != line.componentId) c,
    ];
    final amount = _amounts[line.componentId];
    return Card(
      margin: const EdgeInsets.only(bottom: 10),
      child: Padding(
        padding: const EdgeInsets.fromLTRB(14, 8, 6, 12),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              children: [
                Expanded(child: Text(_componentName(line.componentId), style: const TextStyle(fontWeight: FontWeight.w600))),
                IconButton(
                  tooltip: 'Remove line',
                  icon: const Icon(Icons.delete_outline_rounded),
                  onPressed: () {
                    _lines.removeAt(index).dispose();
                    _changed();
                  },
                ),
              ],
            ),
            Padding(
              padding: const EdgeInsets.only(right: 8),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  DropdownButtonFormField<String>(
                    key: ValueKey('calc-${line.componentId}'),
                    value: calcs.contains(line.calc) ? line.calc : calcs.first,
                    isExpanded: true,
                    decoration: const InputDecoration(labelText: 'Calculation'),
                    items: [for (final t in calcs) DropdownMenuItem(value: t, child: Text(calculationTypeLabels[t]!))],
                    onChanged: (v) {
                      if (v == null) return;
                      line.calc = v;
                      _changed();
                    },
                  ),
                  const SizedBox(height: 8),
                  if (line.calc == 'FIXED')
                    TextField(
                      key: ValueKey('amount-${line.componentId}'),
                      controller: line.amount,
                      keyboardType: const TextInputType.numberWithOptions(decimal: true),
                      decoration: const InputDecoration(labelText: 'Monthly amount (₹)'),
                      onChanged: (_) => _changed(),
                    )
                  else if (line.calc == 'BALANCING')
                    Text('Takes whatever remains of gross', style: TextStyle(fontSize: 12, color: scheme.onSurfaceVariant))
                  else
                    TextField(
                      key: ValueKey('pct-${line.componentId}'),
                      controller: line.percentage,
                      keyboardType: const TextInputType.numberWithOptions(decimal: true),
                      decoration: const InputDecoration(labelText: 'Percentage', suffixText: '%'),
                      onChanged: (_) => _changed(),
                    ),
                  if (line.calc == 'PERCENTAGE_OF_COMPONENT') ...[
                    const SizedBox(height: 8),
                    DropdownButtonFormField<String>(
                      key: ValueKey('base-${line.componentId}'),
                      value: earnings.any((c) => c['id'] == line.baseId) ? line.baseId : null,
                      isExpanded: true,
                      decoration: const InputDecoration(labelText: 'Of component'),
                      items: [for (final c in earnings) DropdownMenuItem(value: c['id'] as String, child: Text('${c['name']}'))],
                      onChanged: (v) {
                        line.baseId = v ?? '';
                        _changed();
                      },
                    ),
                  ],
                  if (line.calc != 'BALANCING') ...[
                    const SizedBox(height: 8),
                    TextField(
                      controller: line.cap,
                      keyboardType: const TextInputType.numberWithOptions(decimal: true),
                      decoration: const InputDecoration(labelText: 'Monthly cap (₹, optional)'),
                      onChanged: (_) => _changed(),
                    ),
                  ],
                  const SizedBox(height: 8),
                  DropdownButtonFormField<String>(
                    key: ValueKey('applies-${line.componentId}'),
                    value: line.appliesWhen,
                    isExpanded: true,
                    decoration: const InputDecoration(labelText: 'Applies'),
                    items: [for (final e in appliesWhenLabels.entries) DropdownMenuItem(value: e.key, child: Text(e.value))],
                    onChanged: (v) {
                      line.appliesWhen = v ?? 'ALWAYS';
                      _changed();
                    },
                  ),
                  const SizedBox(height: 10),
                  Text(
                    amount == null ? '—' : '${formatInr(amount)} a month · ${formatInr(amount * 12)} a year',
                    key: ValueKey('line-amount-${line.componentId}'),
                    style: TextStyle(fontWeight: FontWeight.w600, color: amount == null ? scheme.onSurfaceVariant : scheme.onSurface),
                  ),
                ],
              ),
            ),
          ],
        ),
      ),
    );
  }

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
      final canSave = !_saving && _dirty && _reason.text.trim().isNotEmpty && _templateId.isNotEmpty && _complete;
      body = ListView(
        padding: const EdgeInsets.all(16),
        children: [
          if (template != null)
            Align(
              alignment: Alignment.centerLeft,
              child: Chip(
                avatar: Icon(_customised ? Icons.tune_rounded : Icons.check_circle_outline_rounded, size: 18),
                label: Text(_customised ? 'Customised for this employee' : 'Same as ${template['name']}'),
              ),
            ),
          const SizedBox(height: 8),
          TextField(
            controller: _ctc,
            keyboardType: const TextInputType.numberWithOptions(decimal: true),
            decoration: InputDecoration(labelText: 'Annual CTC (₹) *', helperText: annual == null ? null : '${formatInr((annual / 12).round())} a month'),
            onChanged: (_) => _changed(),
          ),
          const SizedBox(height: 12),
          DropdownButtonFormField<String>(
            value: _templateId.isEmpty ? null : _templateId,
            isExpanded: true,
            decoration: const InputDecoration(labelText: 'Start from structure', helperText: 'Changes below apply to this employee only.'),
            items: [for (final s in _templates) DropdownMenuItem(value: s['id'] as String, child: Text('${s['name']}'))],
            onChanged: (v) {
              if (v == null) return;
              _templateId = v;
              _setLines(_templateLines(_template));
              _changed();
            },
          ),
          Align(
            alignment: Alignment.centerLeft,
            child: TextButton.icon(
              onPressed:
                  _customised
                      ? () {
                        _setLines(_templateLines(template));
                        _changed();
                      }
                      : null,
              icon: const Icon(Icons.restart_alt_rounded),
              label: Text('Reset to ${template?['name'] ?? 'template'}'),
            ),
          ),
          const SizedBox(height: 4),
          for (var i = 0; i < _lines.length; i++) _lineCard(context, i),
          Align(alignment: Alignment.centerLeft, child: OutlinedButton.icon(onPressed: _addLine, icon: const Icon(Icons.add_rounded), label: const Text('Add component'))),
          const SizedBox(height: 8),
          Text(
            'Exactly one earning must be "Balance of gross". Employer contributions are part of CTC, so gross = CTC − employer contributions. '
            'PF ${setup['pf_applicable'] == true ? 'applies' : 'does not apply'} to this employee.',
            style: TextStyle(fontSize: 12, color: scheme.onSurfaceVariant),
          ),
          if (_previewError != null) Padding(padding: const EdgeInsets.only(top: 10), child: Text(_previewError!, style: TextStyle(color: scheme.error))),
          if (breakup != null) Padding(padding: const EdgeInsets.only(top: 12), child: SalaryBreakupView(breakup: breakup)),
          const Divider(height: 32),
          OutlinedButton.icon(
            onPressed: () async {
              final picked = await showDatePicker(context: context, initialDate: DateTime.tryParse(_effectiveFrom) ?? DateTime.now(), firstDate: DateTime(2020), lastDate: DateTime(2100));
              if (picked == null) return;
              _effectiveFrom = _iso(picked);
              _changed();
            },
            icon: const Icon(Icons.calendar_today_outlined, size: 18),
            label: Text('Effective from $_effectiveFrom'),
          ),
          if (_ctcChanged) ...[
            const SizedBox(height: 12),
            DropdownButtonFormField<String>(
              value: _revisionType,
              isExpanded: true,
              decoration: const InputDecoration(labelText: 'Why the CTC is changing *'),
              items: [for (final e in _revisionLabels.entries) DropdownMenuItem(value: e.key, child: Text(e.value))],
              onChanged: (v) => setState(() => _revisionType = v ?? _revisionType),
            ),
          ],
          const SizedBox(height: 12),
          TextField(controller: _reason, maxLength: 500, decoration: const InputDecoration(labelText: 'Reason *'), onChanged: (_) => setState(() {})),
          if (_formError != null) Padding(padding: const EdgeInsets.only(bottom: 8), child: Text(_formError!, style: TextStyle(color: scheme.error))),
          FilledButton(onPressed: canSave ? _save : null, child: Text(_saving ? 'Saving…' : 'Save salary')),
          const SizedBox(height: 24),
        ],
      );
    }
    return Scaffold(appBar: AppBar(title: const Text('Salary setup')), body: body);
  }
}
