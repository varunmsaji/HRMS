import 'package:flutter/material.dart';

import '../../../core/format.dart';
import '../domain/payroll_resources.dart';

typedef Rec = Map<String, dynamic>;

/// One structure line as an editor holds it — amounts in rupees, as typed (mirrors web `LineRow`).
class StructureLine {
  StructureLine({required this.componentId, required this.calc, String percentage = '', String amount = '', this.baseId = '', String cap = '', this.appliesWhen = 'ALWAYS'})
    : percentage = TextEditingController(text: percentage),
      amount = TextEditingController(text: amount),
      cap = TextEditingController(text: cap);

  /// From a `SalaryStructureLineRead` (mirrors web `toRow`).
  factory StructureLine.fromRead(Rec l) {
    String rupees(Object? minor) => minor == null ? '' : ((minor as num) / 100).toString().replaceAll(RegExp(r'\.0$'), '');
    return StructureLine(
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

/// The line inputs of a set of read lines, as an editor would send them unchanged.
List<Rec> structureLineInputs(List<Rec> lines) => [for (var i = 0; i < lines.length; i++) StructureLine.fromRead(lines[i]).toInput(i)];

/// Editable structure lines — mirrors `apps/web/src/components/payroll/structure-lines-editor.tsx`.
/// Each component is a tile with its name, how it is calculated and (with [amounts], monthly paise
/// by component id) what it pays; tapping it opens its fields underneath, with Remove. Earnings and
/// employer contributions are separate sections, and with [breakup] they end in Gross and Cost to
/// company totals. Employer contributions can't take "Balance of gross" or "% of gross".
///
/// [lines] is edited in place; [onChanged] runs after every edit. Passing a different list (a new
/// template, a reset, a reload) closes any open tile.
class StructureLinesEditor extends StatefulWidget {
  const StructureLinesEditor({super.key, required this.lines, required this.components, required this.onChanged, this.amounts, this.breakup});

  final List<StructureLine> lines;
  final List<Rec> components;
  final VoidCallback onChanged;
  final Map<String, num>? amounts;
  final Rec? breakup;

  @override
  State<StructureLinesEditor> createState() => _StructureLinesEditorState();
}

class _StructureLinesEditorState extends State<StructureLinesEditor> {
  int? _expanded;

  @override
  void didUpdateWidget(StructureLinesEditor oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (!identical(oldWidget.lines, widget.lines)) _expanded = null;
  }

  List<StructureLine> get _lines => widget.lines;

  void _changed() {
    setState(() {});
    widget.onChanged();
  }

  List<Rec> get _usable => [
    for (final c in widget.components)
      if (c['is_active'] != false && c['component_type'] != 'DEDUCTION') c,
  ];

  String _componentName(String id) {
    for (final c in widget.components) {
      if (c['id'] == id) return '${c['name']}';
    }
    return 'Component';
  }

  String? _componentType(String id) {
    for (final c in widget.components) {
      if (c['id'] == id) return c['component_type'] as String?;
    }
    return null;
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
    if (picked == null || !mounted) return;
    _lines.add(StructureLine(componentId: picked, calc: 'FIXED'));
    _expanded = _lines.length - 1;
    _changed();
  }

  String _summary(StructureLine line) {
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
    final amounts = widget.amounts;
    final amount = amounts?[line.componentId];
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
                if (amounts != null)
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

  @override
  Widget build(BuildContext context) {
    final scheme = Theme.of(context).colorScheme;
    final breakup = widget.breakup;
    final employerIdx = [
      for (var i = 0; i < _lines.length; i++)
        if (_componentType(_lines[i].componentId) == 'EMPLOYER_CONTRIBUTION') i,
    ];
    final earningIdx = [
      for (var i = 0; i < _lines.length; i++)
        if (!employerIdx.contains(i)) i,
    ];
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        Container(
          decoration: BoxDecoration(border: Border.all(color: scheme.outlineVariant), borderRadius: BorderRadius.circular(12)),
          clipBehavior: Clip.antiAlias,
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              if (_lines.isEmpty) Padding(padding: const EdgeInsets.all(12), child: Text('No components yet.', style: TextStyle(color: scheme.onSurfaceVariant))),
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
      ],
    );
  }
}
