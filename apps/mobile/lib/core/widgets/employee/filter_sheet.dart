import 'package:flutter/material.dart';

import '../../theme/employee_tokens.dart';

/// The filters the list screens share. All fields optional; null/empty means "no filter".
@immutable
class EmployeeFilter {
  const EmployeeFilter({this.dateFrom, this.dateTo, this.status = '', this.type = ''});

  /// `YYYY-MM-DD` (company-zone dates, as the API expects).
  final String? dateFrom;
  final String? dateTo;
  final String status;
  final String type;

  EmployeeFilter copyWith({String? dateFrom, String? dateTo, String? status, String? type, bool clearDates = false}) => EmployeeFilter(
        dateFrom: clearDates ? null : (dateFrom ?? this.dateFrom),
        dateTo: clearDates ? null : (dateTo ?? this.dateTo),
        status: status ?? this.status,
        type: type ?? this.type,
      );

  /// "1 Oct – 30 Oct · Submitted" / "All dates · All statuses". [statusLabels] maps codes to words.
  String caption({Map<String, String> statusLabels = const {}, Map<String, String> typeLabels = const {}}) {
    final dates = (dateFrom == null && dateTo == null) ? 'All dates' : '${dateFrom ?? '…'} – ${dateTo ?? '…'}';
    final s = status.isEmpty ? 'All statuses' : (statusLabels[status] ?? status);
    final ty = type.isEmpty ? null : (typeLabels[type] ?? type);
    return [dates, s, if (ty != null) ty].join(' · ');
  }

  @override
  bool operator ==(Object other) => other is EmployeeFilter && other.dateFrom == dateFrom && other.dateTo == dateTo && other.status == status && other.type == type;

  @override
  int get hashCode => Object.hash(dateFrom, dateTo, status, type);
}

/// Bottom sheet for date range, status and (optionally) type. Returns the new filter on Apply,
/// `EmployeeFilter()` on Clear, or null if dismissed.
Future<EmployeeFilter?> showEmployeeFilterSheet(
  BuildContext context, {
  required EmployeeFilter initial,
  Map<String, String> statuses = const {},
  Map<String, String> types = const {},
  String title = 'Filter',
}) {
  return showModalBottomSheet<EmployeeFilter>(
    context: context,
    isScrollControlled: true,
    builder: (ctx) => _FilterSheet(initial: initial, statuses: statuses, types: types, title: title),
  );
}

class _FilterSheet extends StatefulWidget {
  const _FilterSheet({required this.initial, required this.statuses, required this.types, required this.title});
  final EmployeeFilter initial;
  final Map<String, String> statuses;
  final Map<String, String> types;
  final String title;

  @override
  State<_FilterSheet> createState() => _FilterSheetState();
}

class _FilterSheetState extends State<_FilterSheet> {
  late EmployeeFilter _f = widget.initial;

  static String _iso(DateTime d) => '${d.year.toString().padLeft(4, '0')}-${d.month.toString().padLeft(2, '0')}-${d.day.toString().padLeft(2, '0')}';

  Future<void> _pick(bool from) async {
    final current = DateTime.tryParse((from ? _f.dateFrom : _f.dateTo) ?? '') ?? DateTime.now();
    final picked = await showDatePicker(context: context, initialDate: current, firstDate: DateTime(2000), lastDate: DateTime(2100));
    if (picked == null) return;
    setState(() => _f = from ? _f.copyWith(dateFrom: _iso(picked)) : _f.copyWith(dateTo: _iso(picked)));
  }

  Widget _chips(String label, Map<String, String> options, String selected, void Function(String) onPick) {
    final t = EmployeeTokens.of(context);
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        const SizedBox(height: 16),
        Text(label, style: Theme.of(context).textTheme.labelMedium?.copyWith(color: t.inkSecondary)),
        const SizedBox(height: 8),
        Wrap(spacing: 8, runSpacing: 8, children: [
          ChoiceChip(label: const Text('All'), selected: selected.isEmpty, onSelected: (_) => onPick('')),
          for (final e in options.entries) ChoiceChip(label: Text(e.value), selected: selected == e.key, onSelected: (_) => onPick(e.key)),
        ]),
      ],
    );
  }

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return SafeArea(
      child: Padding(
        padding: EdgeInsets.fromLTRB(16, 0, 16, 16 + MediaQuery.viewInsetsOf(context).bottom),
        child: SingleChildScrollView(
          child: Column(
            mainAxisSize: MainAxisSize.min,
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text(widget.title, style: theme.textTheme.headlineSmall),
              const SizedBox(height: 16),
              Row(children: [
                Expanded(child: OutlinedButton(onPressed: () => _pick(true), child: Text(_f.dateFrom == null ? 'From' : 'From ${_f.dateFrom}'))),
                const SizedBox(width: 12),
                Expanded(child: OutlinedButton(onPressed: () => _pick(false), child: Text(_f.dateTo == null ? 'To' : 'To ${_f.dateTo}'))),
              ]),
              if (_f.dateFrom != null || _f.dateTo != null)
                Align(alignment: Alignment.centerLeft, child: TextButton(onPressed: () => setState(() => _f = _f.copyWith(clearDates: true)), child: const Text('Clear dates'))),
              if (widget.statuses.isNotEmpty) _chips('Status', widget.statuses, _f.status, (v) => setState(() => _f = _f.copyWith(status: v))),
              if (widget.types.isNotEmpty) _chips('Type', widget.types, _f.type, (v) => setState(() => _f = _f.copyWith(type: v))),
              const SizedBox(height: 24),
              Row(children: [
                Expanded(child: OutlinedButton(onPressed: () => Navigator.pop(context, const EmployeeFilter()), child: const Text('Clear'))),
                const SizedBox(width: 12),
                Expanded(flex: 2, child: FilledButton(onPressed: () => Navigator.pop(context, _f), child: const Text('Apply'))),
              ]),
            ],
          ),
        ),
      ),
    );
  }
}
