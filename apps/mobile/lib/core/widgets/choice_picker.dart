import 'package:flutter/material.dart';

import '../forms/form_spec.dart' show Choice;

/// Lists longer than this open a searchable sheet instead of a dropdown (audit MOB-UX-028): a
/// 300-person company should not scroll a 300-row menu to find one name.
const kSearchableChoiceThreshold = 10;

/// A bottom sheet that lists [choices] with a search box. Resolves to the chosen value, `''` for
/// the [allLabel] row when one is given, or null when dismissed.
Future<String?> pickChoice(
  BuildContext context, {
  required String title,
  required List<Choice> choices,
  String? selected,
  String? allLabel,
}) =>
    showModalBottomSheet<String>(
      context: context,
      isScrollControlled: true,
      showDragHandle: true,
      builder: (_) => _ChoicePickerSheet(title: title, choices: choices, selected: selected, allLabel: allLabel),
    );

class _ChoicePickerSheet extends StatefulWidget {
  const _ChoicePickerSheet({required this.title, required this.choices, this.selected, this.allLabel});
  final String title;
  final List<Choice> choices;
  final String? selected;
  final String? allLabel;

  @override
  State<_ChoicePickerSheet> createState() => _ChoicePickerSheetState();
}

class _ChoicePickerSheetState extends State<_ChoicePickerSheet> {
  final _search = TextEditingController();

  @override
  void dispose() {
    _search.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final q = _search.text.trim().toLowerCase();
    final shown = q.isEmpty ? widget.choices : widget.choices.where((c) => c.label.toLowerCase().contains(q)).toList();
    final theme = Theme.of(context);
    Widget row(String value, String label) {
      final on = value == (widget.selected ?? '');
      return ListTile(
        title: Text(label),
        trailing: on ? Icon(Icons.check_rounded, color: theme.colorScheme.primary) : null,
        selected: on,
        onTap: () => Navigator.pop(context, value),
      );
    }

    return SafeArea(
      child: SizedBox(
        height: MediaQuery.sizeOf(context).height * 0.75,
        child: Padding(
          padding: EdgeInsets.only(bottom: MediaQuery.viewInsetsOf(context).bottom),
          child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
            Padding(
              padding: const EdgeInsets.fromLTRB(16, 0, 16, 8),
              child: Text(widget.title, style: theme.textTheme.titleLarge),
            ),
            Padding(
              padding: const EdgeInsets.symmetric(horizontal: 16),
              child: TextField(
                controller: _search,
                textInputAction: TextInputAction.search,
                decoration: const InputDecoration(hintText: 'Search', prefixIcon: Icon(Icons.search_rounded)),
                onChanged: (_) => setState(() {}),
              ),
            ),
            const SizedBox(height: 8),
            Expanded(
              child: ListView(children: [
                if (widget.allLabel != null && q.isEmpty) row('', widget.allLabel!),
                for (final c in shown) row(c.value, c.label),
                if (shown.isEmpty)
                  Padding(
                    padding: const EdgeInsets.all(24),
                    child: Text('Nothing matches "${_search.text.trim()}".', textAlign: TextAlign.center, style: theme.textTheme.bodyMedium),
                  ),
              ]),
            ),
          ]),
        ),
      ),
    );
  }
}

/// Looks like a form field and opens [pickChoice]. For lists too long for a dropdown.
class SearchableChoiceField extends StatelessWidget {
  const SearchableChoiceField({
    super.key,
    required this.title,
    required this.choices,
    required this.value,
    required this.onChanged,
    this.allLabel,
    this.hint = 'Select',
    this.label,
  });

  /// The sheet's heading ("Choose an employee").
  final String title;
  final List<Choice> choices;
  final String value;
  final ValueChanged<String>? onChanged;

  /// Offered first in the sheet and shown when [value] is empty ("All employees").
  final String? allLabel;
  final String hint;

  /// A floating label, for filters that have no surrounding form label.
  final String? label;

  @override
  Widget build(BuildContext context) {
    String? shown;
    for (final c in choices) {
      if (c.value == value) shown = c.label;
    }
    if (shown == null && value.isNotEmpty) shown = value;
    if (shown == null && allLabel != null) shown = allLabel;
    final enabled = onChanged != null;
    return Semantics(
      button: true,
      label: label ?? title,
      child: InkWell(
        borderRadius: BorderRadius.circular(8),
        onTap: !enabled
            ? null
            : () async {
                final picked = await pickChoice(context, title: title, choices: choices, selected: value, allLabel: allLabel);
                if (picked != null) onChanged!(picked);
              },
        child: InputDecorator(
          isEmpty: shown == null,
          decoration: InputDecoration(
            labelText: label,
            hintText: hint,
            enabled: enabled,
            suffixIcon: const Icon(Icons.unfold_more_rounded),
            contentPadding: label == null ? null : const EdgeInsets.symmetric(horizontal: 12, vertical: 8),
          ),
          child: shown == null ? null : Text(shown, maxLines: 1, overflow: TextOverflow.ellipsis),
        ),
      ),
    );
  }
}
