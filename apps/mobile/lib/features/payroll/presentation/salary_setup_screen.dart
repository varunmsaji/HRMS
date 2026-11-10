import 'dart:async';
import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../core/api/api_error.dart';
import '../../../core/format.dart';
import '../../../core/providers.dart';
import '../domain/payroll_resources.dart';

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
  int? _expanded;

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
    _expanded = _lines.length - 1;
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

  String _summary(_Line line) {
    final pct = line.percentage.text.trim();
    var text = switch (line.calc) {
      'FIXED' => '${formatInr(rupeesToMinor(line.amount.text) ?? 0)} fixed',
      'PERCENTAGE_OF_CTC' => '$pct% of CTC',
      'PERCENTAGE_OF_GROSS' => '$pct% of gross',
      'PERCENTAGE_OF_COMPONENT' => '$pct% of ${line.baseId.isEmpty ? '…' : _componentName(line.baseId)}',
      _ => 'Rest of gross',
    };
    if (line.cap.text.trim().isNotEmpty) text += ' · cap ${formatInr(rupeesToMinor(line.cap.text) ?? 0)}';
    if (line.appliesWhen != 'ALWAYS') text += ' · ${appliesWhenLabels[line.appliesWhen]!.replaceFirst('O', 'o')}';
    return text;
  }

  /// One component: name, what it is, and what it pays; tapped, its fields open underneath.
  Widget _lineTile(BuildContext context, int index) {
    final line = _lines[index];
    final scheme = Theme.of(context).colorScheme;
    final expanded = _expanded == index;
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
    const dense = InputDecoration(isDense: true, border: OutlineInputBorder());
    return Column(
      children: [
        InkWell(
          onTap: () => setState(() => _expanded = expanded ? null : index),
          child: Padding(
            padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 10),
            child: Row(
              children: [
                Expanded(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text(_componentName(line.componentId), style: const TextStyle(fontWeight: FontWeight.w600)),
                      const SizedBox(height: 2),
                      Text(_summary(line), maxLines: 1, overflow: TextOverflow.ellipsis, style: TextStyle(fontSize: 12, color: scheme.onSurfaceVariant)),
                    ],
                  ),
                ),
                const SizedBox(width: 8),
                Text(
                  amount == null ? '—' : formatInr(amount),
                  key: ValueKey('line-amount-${line.componentId}'),
                  style: TextStyle(fontWeight: FontWeight.w600, fontFeatures: const [FontFeature.tabularFigures()], color: amount == null ? scheme.onSurfaceVariant : scheme.onSurface),
                ),
                Icon(expanded ? Icons.expand_less_rounded : Icons.expand_more_rounded, color: scheme.onSurfaceVariant),
              ],
            ),
          ),
        ),
        if (expanded)
          Container(
            color: scheme.surfaceContainerHighest.withValues(alpha: 0.4),
            padding: const EdgeInsets.fromLTRB(12, 10, 12, 4),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Row(
                  children: [
                    Expanded(
                      child: DropdownButtonFormField<String>(
                        key: ValueKey('calc-${line.componentId}'),
                        value: calcs.contains(line.calc) ? line.calc : calcs.first,
                        isExpanded: true,
                        decoration: dense.copyWith(labelText: 'Calculated as'),
                        items: [for (final t in calcs) DropdownMenuItem(value: t, child: Text(calculationTypeLabels[t]!))],
                        onChanged: (v) {
                          if (v == null) return;
                          line.calc = v;
                          _changed();
                        },
                      ),
                    ),
                    if (line.calc != 'BALANCING') ...[
                      const SizedBox(width: 8),
                      SizedBox(
                        width: 110,
                        child:
                            line.calc == 'FIXED'
                                ? TextField(
                                  key: ValueKey('amount-${line.componentId}'),
                                  controller: line.amount,
                                  keyboardType: const TextInputType.numberWithOptions(decimal: true),
                                  decoration: dense.copyWith(labelText: '₹ a month'),
                                  onChanged: (_) => _changed(),
                                )
                                : TextField(
                                  key: ValueKey('pct-${line.componentId}'),
                                  controller: line.percentage,
                                  keyboardType: const TextInputType.numberWithOptions(decimal: true),
                                  decoration: dense.copyWith(labelText: 'Percent', suffixText: '%'),
                                  onChanged: (_) => _changed(),
                                ),
                      ),
                    ],
                  ],
                ),
                if (line.calc == 'PERCENTAGE_OF_COMPONENT') ...[
                  const SizedBox(height: 10),
                  DropdownButtonFormField<String>(
                    key: ValueKey('base-${line.componentId}'),
                    value: earnings.any((c) => c['id'] == line.baseId) ? line.baseId : null,
                    isExpanded: true,
                    decoration: dense.copyWith(labelText: 'Of component'),
                    items: [for (final c in earnings) DropdownMenuItem(value: c['id'] as String, child: Text('${c['name']}'))],
                    onChanged: (v) {
                      line.baseId = v ?? '';
                      _changed();
                    },
                  ),
                ],
                const SizedBox(height: 10),
                Row(
                  children: [
                    if (line.calc != 'BALANCING') ...[
                      SizedBox(
                        width: 120,
                        child: TextField(
                          controller: line.cap,
                          keyboardType: const TextInputType.numberWithOptions(decimal: true),
                          decoration: dense.copyWith(labelText: 'Cap ₹/mo'),
                          onChanged: (_) => _changed(),
                        ),
                      ),
                      const SizedBox(width: 8),
                    ],
                    Expanded(
                      child: DropdownButtonFormField<String>(
                        key: ValueKey('applies-${line.componentId}'),
                        value: line.appliesWhen,
                        isExpanded: true,
                        decoration: dense.copyWith(labelText: 'Applies'),
                        items: [for (final e in appliesWhenLabels.entries) DropdownMenuItem(value: e.key, child: Text(e.value))],
                        onChanged: (v) {
                          line.appliesWhen = v ?? 'ALWAYS';
                          _changed();
                        },
                      ),
                    ),
                  ],
                ),
                Align(
                  alignment: Alignment.centerRight,
                  child: TextButton.icon(
                    style: TextButton.styleFrom(foregroundColor: scheme.error),
                    onPressed: () {
                      _lines.removeAt(index).dispose();
                      _expanded = null;
                      _changed();
                    },
                    icon: const Icon(Icons.delete_outline_rounded, size: 18),
                    label: const Text('Remove'),
                  ),
                ),
              ],
            ),
          ),
      ],
    );
  }

  Widget _section(BuildContext context, String label) => Container(
    width: double.infinity,
    color: Theme.of(context).colorScheme.surfaceContainerHighest.withValues(alpha: 0.6),
    padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 6),
    child: Text(label.toUpperCase(), style: TextStyle(fontSize: 11, letterSpacing: 0.6, fontWeight: FontWeight.w600, color: Theme.of(context).colorScheme.onSurfaceVariant)),
  );

  Widget _total(BuildContext context, String label, num monthly, {bool strong = false}) {
    final style = TextStyle(fontWeight: strong ? FontWeight.w700 : FontWeight.w500, fontFeatures: const [FontFeature.tabularFigures()]);
    return Container(
      color: strong ? Theme.of(context).colorScheme.surfaceContainerHighest.withValues(alpha: 0.6) : null,
      padding: const EdgeInsets.fromLTRB(12, 10, 36, 10),
      child: Row(children: [Expanded(child: Text(label, style: style)), Text(formatInr(monthly), style: style)]),
    );
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
      final canSave = !_saving && _dirty && _reason.text.trim().isNotEmpty && _templateId.isNotEmpty && _complete;
      const dense = InputDecoration(isDense: true, border: OutlineInputBorder());
      final employerIdx = [
        for (var i = 0; i < _lines.length; i++)
          if (_componentType(_lines[i].componentId) == 'EMPLOYER_CONTRIBUTION') i,
      ];
      final earningIdx = [
        for (var i = 0; i < _lines.length; i++)
          if (!employerIdx.contains(i)) i,
      ];
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
                        decoration: dense.copyWith(labelText: 'Annual CTC (₹)'),
                        onChanged: (_) => _changed(),
                      ),
                    ),
                    const SizedBox(width: 8),
                    Expanded(
                      child: DropdownButtonFormField<String>(
                        value: _templateId.isEmpty ? null : _templateId,
                        isExpanded: true,
                        decoration: dense.copyWith(labelText: 'Structure'),
                        items: [for (final s in _templates) DropdownMenuItem(value: s['id'] as String, child: Text('${s['name']}', overflow: TextOverflow.ellipsis))],
                        onChanged: (v) {
                          if (v == null) return;
                          _templateId = v;
                          _setLines(_templateLines(_template));
                          _expanded = null;
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
                            _expanded = null;
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
          Container(
            decoration: border,
            clipBehavior: Clip.antiAlias,
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.stretch,
              children: [
                if (employerIdx.isNotEmpty) _section(context, 'Earnings'),
                for (final i in earningIdx) ...[_lineTile(context, i), const Divider(height: 1)],
                if (breakup != null) _total(context, 'Gross', breakup['gross_monthly_minor'] as num),
                if (employerIdx.isNotEmpty) _section(context, 'Employer contributions'),
                for (final i in employerIdx) ...[_lineTile(context, i), const Divider(height: 1)],
                if (breakup != null) _total(context, 'Cost to company', breakup['monthly_ctc_minor'] as num, strong: true),
              ],
            ),
          ),
          Align(alignment: Alignment.centerLeft, child: TextButton.icon(onPressed: _addLine, icon: const Icon(Icons.add_rounded), label: const Text('Add component'))),
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
          TextField(controller: _reason, maxLength: 500, decoration: dense.copyWith(labelText: 'Reason', hintText: 'e.g. Annual review', counterText: ''), onChanged: (_) => setState(() {})),
          if (_formError != null) Padding(padding: const EdgeInsets.only(top: 8), child: Text(_formError!, style: TextStyle(color: scheme.error))),
          const SizedBox(height: 12),
          FilledButton(onPressed: canSave ? _save : null, child: Text(_saving ? 'Saving…' : 'Save salary')),
        ],
      );
    }
    return Scaffold(appBar: AppBar(title: const Text('Salary setup')), body: body);
  }
}
