import 'package:flutter/foundation.dart';
import 'package:flutter/material.dart';

import '../format.dart';
import '../forms/form_spec.dart' show Choice;
import 'choice_picker.dart';

/// The one filter pattern for lists (audit MOB-UX-013, 043): a line saying what is shown and a
/// "Filter" button with a count of what is narrowed, which opens [showListFilterSheet]. Replaces
/// the rows of date buttons, chips and dropdowns that used to sit above the first row.

/// A group of options the sheet offers as chips ("Status", "Request type").
class FilterGroup {
  const FilterGroup({required this.key, required this.label, required this.options, this.multi = false});

  /// Where the choice is kept in [ListFilter.groups]; usually the query parameter.
  final String key;
  final String label;
  final List<(String value, String label)> options;

  /// Several may be chosen; the value is then comma-separated.
  final bool multi;
}

/// What a list is narrowed to. Empty strings and nulls mean "no filter". Dates are ISO
/// `YYYY-MM-DD`, as the API expects.
@immutable
class ListFilter {
  const ListFilter({this.from, this.to, this.employee = '', this.groups = const {}});

  final String? from;
  final String? to;
  final String employee;
  final Map<String, String> groups;

  String group(String key) => groups[key] ?? '';

  Set<String> multi(String key) => {for (final v in group(key).split(',')) if (v.isNotEmpty) v};

  ListFilter copyWith({String? from, String? to, bool clearDates = false, String? employee, Map<String, String>? groups}) => ListFilter(
        from: clearDates ? null : (from ?? this.from),
        to: clearDates ? null : (to ?? this.to),
        employee: employee ?? this.employee,
        groups: groups ?? this.groups,
      );

  ListFilter withGroup(String key, String value) => copyWith(groups: {...groups, key: value});

  /// How many things differ from [defaults]: the number on the Filter button.
  int countAgainst(ListFilter defaults) {
    var n = 0;
    if (from != defaults.from || to != defaults.to) n++;
    if (employee != defaults.employee) n++;
    for (final k in {...groups.keys, ...defaults.groups.keys}) {
      if (group(k) != defaults.group(k)) n++;
    }
    return n;
  }

  @override
  bool operator ==(Object other) =>
      other is ListFilter && other.from == from && other.to == to && other.employee == employee && mapEquals(_trimmed(other.groups), _trimmed(groups));

  static Map<String, String> _trimmed(Map<String, String> m) => {for (final e in m.entries) if (e.value.isNotEmpty) e.key: e.value};

  @override
  int get hashCode => Object.hash(from, to, employee, Object.hashAllUnordered(_trimmed(groups).entries.map((e) => '${e.key}=${e.value}')));
}

/// "12 Oct – 11 Nov", "From 12 Oct", "Until 11 Nov" or "Any date".
String describeDates(String? from, String? to) {
  if (from != null && to != null) return formatDateRange(from, to);
  if (from != null) return 'From ${formatShortDateWithYear(from)}';
  if (to != null) return 'Until ${formatShortDateWithYear(to)}';
  return 'Any date';
}

/// "12 Nov", with the year when it is not this year's.
String formatShortDateWithYear(String iso) => formatDateRange(iso, iso);

/// The summary line and Filter button above a list.
class ListFilterBar extends StatelessWidget {
  const ListFilterBar({super.key, required this.summary, required this.activeCount, required this.onTap, this.leading});

  /// What the list shows, in words ("Last 30 days, plus anything still waiting · All statuses").
  final String summary;
  final int activeCount;
  final VoidCallback onTap;

  /// An extra control before the summary (the day picker on Team attendance).
  final Widget? leading;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final label = activeCount == 0 ? 'Filter' : 'Filter ($activeCount)';
    return Row(children: [
      if (leading != null) ...[leading!, const SizedBox(width: 8)],
      Expanded(
        child: Text(summary, maxLines: 2, overflow: TextOverflow.ellipsis, style: theme.textTheme.bodyMedium?.copyWith(color: theme.colorScheme.onSurfaceVariant)),
      ),
      const SizedBox(width: 8),
      Semantics(
        label: activeCount == 0 ? 'Filter' : 'Filter, $activeCount ${activeCount == 1 ? 'filter' : 'filters'} on',
        button: true,
        excludeSemantics: true,
        child: activeCount == 0
            ? OutlinedButton.icon(onPressed: onTap, icon: const Icon(Icons.tune_rounded, size: 18), label: Text(label))
            : FilledButton.tonalIcon(onPressed: onTap, icon: const Icon(Icons.tune_rounded, size: 18), label: Text(label)),
      ),
    ]);
  }
}

/// The filter sheet. Resolves to the new filter on "Show results", to [defaults] on "Reset", or
/// null when dismissed.
///
/// [dates] false hides the date range (Team attendance picks one day outside the sheet).
/// [employees], when given, adds a searchable employee choice.
Future<ListFilter?> showListFilterSheet(
  BuildContext context, {
  required ListFilter initial,
  required ListFilter defaults,
  List<FilterGroup> groups = const [],
  List<Choice>? employees,
  bool dates = true,
  String title = 'Filter',
}) =>
    showModalBottomSheet<ListFilter>(
      context: context,
      isScrollControlled: true,
      showDragHandle: true,
      builder: (_) => _ListFilterSheet(initial: initial, defaults: defaults, groups: groups, employees: employees, dates: dates, title: title),
    );

class _ListFilterSheet extends StatefulWidget {
  const _ListFilterSheet({required this.initial, required this.defaults, required this.groups, required this.employees, required this.dates, required this.title});
  final ListFilter initial;
  final ListFilter defaults;
  final List<FilterGroup> groups;
  final List<Choice>? employees;
  final bool dates;
  final String title;

  @override
  State<_ListFilterSheet> createState() => _ListFilterSheetState();
}

class _ListFilterSheetState extends State<_ListFilterSheet> {
  late ListFilter _f = widget.initial;

  static String _iso(DateTime d) => '${d.year.toString().padLeft(4, '0')}-${d.month.toString().padLeft(2, '0')}-${d.day.toString().padLeft(2, '0')}';

  Future<void> _pickDates() async {
    final from = DateTime.tryParse(_f.from ?? ''), to = DateTime.tryParse(_f.to ?? '');
    final picked = await showDateRangePicker(
      context: context,
      firstDate: DateTime(2000),
      lastDate: DateTime(2100),
      initialDateRange: from != null && to != null && !to.isBefore(from) ? DateTimeRange(start: from, end: to) : null,
      helpText: 'Show requests between',
    );
    if (picked == null) return;
    setState(() => _f = _f.copyWith(from: _iso(picked.start), to: _iso(picked.end)));
  }

  Widget _heading(String text) => Padding(
        padding: const EdgeInsets.only(top: 20, bottom: 8),
        child: Text(text, style: Theme.of(context).textTheme.titleSmall),
      );

  Widget _group(FilterGroup g) {
    if (g.multi) {
      final on = _f.multi(g.key);
      return Wrap(spacing: 8, runSpacing: 8, children: [
        for (final (value, label) in g.options)
          FilterChip(
            label: Text(label),
            selected: on.contains(value),
            onSelected: (v) {
              final next = {...on};
              v ? next.add(value) : next.remove(value);
              setState(() => _f = _f.withGroup(g.key, next.join(',')));
            },
          ),
      ]);
    }
    final current = _f.group(g.key);
    return Wrap(spacing: 8, runSpacing: 8, children: [
      ChoiceChip(label: const Text('All'), selected: current.isEmpty, onSelected: (_) => setState(() => _f = _f.withGroup(g.key, ''))),
      for (final (value, label) in g.options)
        ChoiceChip(label: Text(label), selected: current == value, onSelected: (_) => setState(() => _f = _f.withGroup(g.key, value))),
    ]);
  }

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final employees = widget.employees;
    return SafeArea(
      child: ConstrainedBox(
        constraints: BoxConstraints(maxHeight: MediaQuery.sizeOf(context).height * 0.85),
        child: Column(mainAxisSize: MainAxisSize.min, crossAxisAlignment: CrossAxisAlignment.stretch, children: [
          Padding(padding: const EdgeInsets.symmetric(horizontal: 16), child: Text(widget.title, style: theme.textTheme.titleLarge)),
          Flexible(
            child: SingleChildScrollView(
              padding: const EdgeInsets.symmetric(horizontal: 16),
              child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
                if (widget.dates) ...[
                  _heading('Dates'),
                  OutlinedButton.icon(
                    onPressed: _pickDates,
                    icon: const Icon(Icons.date_range_rounded, size: 18),
                    label: Text(describeDates(_f.from, _f.to)),
                  ),
                  if (_f.from != null || _f.to != null)
                    Align(
                      alignment: Alignment.centerLeft,
                      child: TextButton(onPressed: () => setState(() => _f = _f.copyWith(clearDates: true)), child: const Text('Any date')),
                    ),
                ],
                for (final g in widget.groups) ...[_heading(g.label), _group(g)],
                if (employees != null && employees.isNotEmpty) ...[
                  _heading('Employee'),
                  SearchableChoiceField(
                    title: 'Choose an employee',
                    choices: employees,
                    value: _f.employee,
                    allLabel: 'All employees',
                    onChanged: (v) => setState(() => _f = _f.copyWith(employee: v)),
                  ),
                ],
                const SizedBox(height: 16),
              ]),
            ),
          ),
          Padding(
            padding: EdgeInsets.fromLTRB(16, 8, 16, 16 + MediaQuery.viewInsetsOf(context).bottom),
            child: Row(children: [
              Expanded(child: OutlinedButton(onPressed: () => Navigator.pop(context, widget.defaults), child: const Text('Reset'))),
              const SizedBox(width: 12),
              Expanded(flex: 2, child: FilledButton(onPressed: () => Navigator.pop(context, _f), child: const Text('Show results'))),
            ]),
          ),
        ]),
      ),
    );
  }
}
