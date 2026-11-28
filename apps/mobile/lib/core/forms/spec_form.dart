import 'package:flutter/material.dart';
import 'package:flutter/services.dart';

import '../../features/auth/presentation/widgets/auth_form_field.dart';
import '../format.dart';
import '../widgets/choice_picker.dart';
import 'choice_sources.dart';
import 'form_spec.dart';

/// Renders a [FormSpec] (or one row of a repeatable one), reading from and writing into the shared
/// mutable [values] map. [choices] supplies the runtime options for [FieldKind.choice] fields;
/// [editing] disables create-only fields.
class SpecForm extends StatefulWidget {
  const SpecForm({
    super.key,
    required this.spec,
    required this.values,
    required this.errors,
    required this.onChanged,
    this.readOnly = false,
    this.editing = false,
    this.choices = const {},
    this.unavailable = const {},
  });

  final FormSpec spec;
  final Map<String, dynamic> values;
  final Map<String, String> errors;
  final VoidCallback onChanged;
  final bool readOnly;
  final bool editing;
  final Map<String, List<Choice>> choices;

  /// Optional choice sources that could not be loaded. A toggle that only reveals a field needing
  /// one of them is switched off and disabled, with a reason.
  final Map<String, ChoiceUnavailable> unavailable;

  @override
  State<SpecForm> createState() => _SpecFormState();
}

class _SpecFormState extends State<SpecForm> {
  final _controllers = <String, TextEditingController>{};

  TextEditingController _controller(FieldSpec f) => _controllers.putIfAbsent(
        f.key,
        () => TextEditingController(text: (widget.values[f.key] ?? '').toString()),
      );

  @override
  void dispose() {
    for (final c in _controllers.values) {
      c.dispose();
    }
    super.dispose();
  }

  void _set(String key, dynamic value) {
    widget.values[key] = value;
    // A field whose options depend on this one is stale once this changes — clear it.
    for (final f in widget.spec.fields) {
      if (f.dependsOn == key) widget.values[f.key] = '';
    }
    widget.onChanged();
  }

  /// Set when this toggle only reveals a choice field whose source is unavailable.
  ChoiceUnavailable? _blockedBy(FieldSpec toggle) {
    for (final g in widget.spec.fields) {
      if (g.showWhen == toggle.key && g.kind == FieldKind.choice && g.choiceKey != null) {
        final why = widget.unavailable[g.choiceKey];
        if (why != null) return why;
      }
    }
    return null;
  }

  bool _disabled(FieldSpec f) => widget.readOnly || (widget.editing && f.readOnlyOnEdit);

  Future<void> _pickDate(FieldSpec f) async {
    final current = DateTime.tryParse((widget.values[f.key] ?? '').toString());
    final picked = await showDatePicker(
      context: context,
      initialDate: current ?? DateTime.now(),
      firstDate: DateTime(1900),
      lastDate: DateTime(2100),
    );
    if (picked == null) return;
    final iso = '${picked.year.toString().padLeft(4, '0')}-${picked.month.toString().padLeft(2, '0')}-${picked.day.toString().padLeft(2, '0')}';
    _controller(f).text = _dateLabel(iso);
    _set(f.key, iso);
  }

  Future<void> _pickTime(FieldSpec f) async {
    final parts = (widget.values[f.key] ?? '').toString().split(':');
    final initial = parts.length >= 2 ? TimeOfDay(hour: int.tryParse(parts[0]) ?? 9, minute: int.tryParse(parts[1]) ?? 0) : const TimeOfDay(hour: 9, minute: 0);
    final picked = await showTimePicker(context: context, initialTime: initial);
    if (picked == null) return;
    final value = '${picked.hour.toString().padLeft(2, '0')}:${picked.minute.toString().padLeft(2, '0')}';
    _controller(f).text = value;
    _set(f.key, value);
  }

  Future<void> _pickDateTime(FieldSpec f) async {
    final current = DateTime.tryParse((widget.values[f.key] ?? '').toString());
    final date = await showDatePicker(context: context, initialDate: current ?? DateTime.now(), firstDate: DateTime(1900), lastDate: DateTime(2100));
    if (date == null || !mounted) return;
    final time = await showTimePicker(context: context, initialTime: current == null ? const TimeOfDay(hour: 9, minute: 0) : TimeOfDay(hour: current.hour, minute: current.minute));
    if (time == null) return;
    final value = '${date.year.toString().padLeft(4, '0')}-${date.month.toString().padLeft(2, '0')}-${date.day.toString().padLeft(2, '0')}T${time.hour.toString().padLeft(2, '0')}:${time.minute.toString().padLeft(2, '0')}';
    _controller(f).text = _dateTimeLabel(value);
    _set(f.key, value);
  }

  static String _dateLabel(Object? value) {
    final v = (value ?? '').toString();
    return v.isEmpty ? '' : formatDayDate(v);
  }

  /// "Thu, 12 Nov · 09:30" for a `YYYY-MM-DDTHH:MM` value.
  static String _dateTimeLabel(Object? value) {
    final v = (value ?? '').toString();
    final t = v.indexOf('T');
    if (t < 0) return _dateLabel(v);
    final time = v.substring(t + 1);
    return '${formatDayDate(v.substring(0, t))} · ${time.length >= 5 ? time.substring(0, 5) : time}';
  }

  TextInputType _keyboard(FieldKind t) {
    switch (t) {
      case FieldKind.integer:
      case FieldKind.aadhaar:
        return TextInputType.number;
      case FieldKind.decimal:
        return const TextInputType.numberWithOptions(decimal: true, signed: true);
      // An amount is never negative: no minus key (audit MOB-UX-025).
      case FieldKind.money:
        return const TextInputType.numberWithOptions(decimal: true);
      case FieldKind.phone:
        return TextInputType.phone;
      case FieldKind.pincode:
        return TextInputType.number;
      case FieldKind.email:
        return TextInputType.emailAddress;
      case FieldKind.multiline:
        return TextInputType.multiline;
      default:
        return TextInputType.text;
    }
  }

  Widget _dropdown(FieldSpec f, List<Choice> options, String? error) {
    final current = (widget.values[f.key] ?? '').toString();
    final items = [...options];
    if (current.isNotEmpty && !items.any((o) => o.value == current)) items.add((value: current, label: current));
    if (items.length > kSearchableChoiceThreshold) {
      return AuthFormField(
        label: f.label,
        required: f.required,
        errorText: error,
        child: SearchableChoiceField(
          title: f.label,
          choices: items,
          value: current,
          allLabel: f.required ? null : '—',
          onChanged: _disabled(f) ? null : (v) => _set(f.key, v),
        ),
      );
    }
    return AuthFormField(
      label: f.label,
      required: f.required,
      errorText: error,
      child: DropdownButtonFormField<String>(
        value: current.isEmpty ? null : current,
        isExpanded: true,
        items: [
          if (!f.required) const DropdownMenuItem(value: '', child: Text('—')),
          for (final o in items) DropdownMenuItem(value: o.value, child: Text(o.label)),
        ],
        onChanged: _disabled(f) ? null : (v) => _set(f.key, v ?? ''),
        decoration: const InputDecoration(hintText: 'Select'),
      ),
    );
  }

  Widget _input(FieldSpec f) {
    final error = widget.errors[f.key];
    switch (f.kind) {
      case FieldKind.toggle:
        final blocked = _blockedBy(f);
        if (blocked != null && widget.values[f.key] == true) widget.values[f.key] = false;
        return SwitchListTile(
          contentPadding: EdgeInsets.zero,
          title: Text(f.label),
          subtitle: blocked == null
              ? null
              : Text(blocked == ChoiceUnavailable.denied
                  ? 'Not available with your access. Ask HR to change this for you.'
                  : 'Couldn\'t load the options for this. Try again later.'),
          value: widget.values[f.key] == true,
          onChanged: (_disabled(f) || blocked != null) ? null : (v) => _set(f.key, v),
        );
      case FieldKind.select:
        return _dropdown(f, [for (final o in f.options) (value: o, label: f.optionLabels[o] ?? prettyEnum(o))], error);
      case FieldKind.choice:
        final source = f.dependsOn != null ? f.choiceMap['${widget.values[f.dependsOn] ?? ''}'] : f.choiceKey;
        return _dropdown(f, widget.choices[source] ?? const [], error);
      case FieldKind.rows:
        final rows = (widget.values[f.key] as List?)?.cast<Map<String, dynamic>>() ?? <Map<String, dynamic>>[];
        final scheme = Theme.of(context).colorScheme;
        return AuthFormField(
          label: f.label,
          required: f.required,
          errorText: error,
          child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
            for (var i = 0; i < rows.length; i++)
              Container(
                key: ObjectKey(rows[i]),
                margin: const EdgeInsets.only(bottom: 10),
                padding: const EdgeInsets.fromLTRB(12, 4, 12, 0),
                decoration: BoxDecoration(border: Border.all(color: scheme.outlineVariant), borderRadius: BorderRadius.circular(10)),
                child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
                  Row(children: [
                    Expanded(child: Text('${f.rowNoun[0].toUpperCase()}${f.rowNoun.substring(1)} ${i + 1}', style: Theme.of(context).textTheme.titleSmall)),
                    if (!_disabled(f)) IconButton(tooltip: 'Remove', icon: const Icon(Icons.delete_outline), onPressed: () => _set(f.key, [...rows]..removeAt(i))),
                  ]),
                  SpecForm(
                    spec: f.rowSpec!,
                    values: rows[i],
                    errors: {
                      for (final e in widget.errors.entries)
                        if (e.key.startsWith('${f.key}.$i.')) e.key.substring('${f.key}.$i.'.length): e.value,
                    },
                    choices: widget.choices,
                    unavailable: widget.unavailable,
                    editing: widget.editing,
                    readOnly: _disabled(f),
                    onChanged: widget.onChanged,
                  ),
                ]),
              ),
            if (!_disabled(f))
              Align(
                alignment: Alignment.centerLeft,
                child: OutlinedButton.icon(
                  icon: const Icon(Icons.add),
                  label: Text('Add ${f.rowNoun}'),
                  onPressed: () => _set(f.key, [...rows, rowFromWire(f.rowSpec!, const {})]),
                ),
              ),
          ]),
        );
      case FieldKind.multiChoice:
        final selected = ((widget.values[f.key] as List?) ?? const []).map((e) => e.toString()).toSet();
        final options = widget.choices[f.choiceKey] ?? const <Choice>[];
        return AuthFormField(
          label: f.label,
          required: f.required,
          errorText: error,
          child: Column(children: [
            if (options.isEmpty) const Align(alignment: Alignment.centerLeft, child: Text('Nothing to choose from yet.')),
            for (final o in options)
              CheckboxListTile(
                dense: true,
                contentPadding: EdgeInsets.zero,
                controlAffinity: ListTileControlAffinity.leading,
                title: Text(o.label),
                value: selected.contains(o.value),
                onChanged: _disabled(f) ? null : (v) => _set(f.key, [for (final x in options) if (x.value == o.value ? v == true : selected.contains(x.value)) x.value]),
              ),
          ]),
        );
      case FieldKind.date:
        return AuthFormField(
          label: f.label,
          required: f.required,
          errorText: error,
          child: TextField(
            // The value stays ISO on the wire; the field shows it as a person reads a date
            // (audit MOB-UX-026).
            controller: _controller(f)..text = _dateLabel(widget.values[f.key]),
            readOnly: true,
            onTap: _disabled(f) ? null : () => _pickDate(f),
            decoration: InputDecoration(
              hintText: 'Choose a date',
              suffixIcon: (!f.required && !_disabled(f) && (widget.values[f.key] ?? '').toString().isNotEmpty)
                  ? IconButton(
                      icon: const Icon(Icons.clear, size: 18),
                      onPressed: () {
                        _controller(f).clear();
                        _set(f.key, '');
                      },
                    )
                  : const Icon(Icons.calendar_today_outlined, size: 18),
            ),
          ),
        );
      case FieldKind.dateTime:
        return AuthFormField(
          label: f.label,
          required: f.required,
          errorText: error,
          child: TextField(
            controller: _controller(f)..text = _dateTimeLabel(widget.values[f.key]),
            readOnly: true,
            onTap: _disabled(f) ? null : () => _pickDateTime(f),
            decoration: const InputDecoration(hintText: 'Choose a date and time', suffixIcon: Icon(Icons.event_available_outlined, size: 18)),
          ),
        );
      case FieldKind.time:
        return AuthFormField(
          label: f.label,
          required: f.required,
          errorText: error,
          child: TextField(
            controller: _controller(f),
            readOnly: true,
            onTap: _disabled(f) ? null : () => _pickTime(f),
            decoration: const InputDecoration(hintText: 'HH:MM', suffixIcon: Icon(Icons.schedule, size: 18)),
          ),
        );
      default:
        return AuthFormField(
          label: f.label,
          required: f.required,
          errorText: error,
          description: f.hint,
          child: TextField(
            controller: _controller(f),
            enabled: !_disabled(f),
            keyboardType: _keyboard(f.kind),
            minLines: f.kind == FieldKind.multiline ? 3 : 1,
            maxLines: f.kind == FieldKind.multiline ? 6 : 1,
            // The keyboard's action moves to the next field (audit MOB-UX-025).
            textInputAction: f.kind == FieldKind.multiline ? TextInputAction.newline : TextInputAction.next,
            textCapitalization: switch (f.kind) {
              FieldKind.pan || FieldKind.upper => TextCapitalization.characters,
              FieldKind.multiline => TextCapitalization.sentences,
              _ => TextCapitalization.none,
            },
            autofillHints: switch (f.kind) {
              FieldKind.phone => const [AutofillHints.telephoneNumber],
              FieldKind.email => const [AutofillHints.email],
              FieldKind.pincode => const [AutofillHints.postalCode],
              _ => null,
            },
            inputFormatters: switch (f.kind) {
              FieldKind.pincode => [FilteringTextInputFormatter.digitsOnly, LengthLimitingTextInputFormatter(6)],
              FieldKind.aadhaar => [FilteringTextInputFormatter.allow(RegExp(r'[0-9 ]')), LengthLimitingTextInputFormatter(14)],
              FieldKind.phone => [FilteringTextInputFormatter.allow(RegExp(r'[0-9+ ()-]')), LengthLimitingTextInputFormatter(20)],
              _ => null,
            },
            onChanged: (v) => _set(f.key, v),
          ),
        );
    }
  }

  final _fieldKeys = <String, GlobalKey>{};

  /// Titles' keys of the sections currently open (only used by a form that has sections).
  final _open = <String>{};
  bool _openInitialised = false;

  /// The section each field belongs to: the nearest [FieldKind.section] above it, or null.
  Map<String, String?> _sectionOf() {
    final out = <String, String?>{};
    String? current;
    for (final f in widget.spec.fields) {
      if (f.kind == FieldKind.section) {
        current = f.key;
      } else {
        out[f.key] = current;
      }
    }
    return out;
  }

  /// Opens, for a first build: the first section, and any holding a required field or an error, so
  /// nothing the person must fill in or fix starts hidden.
  void _initOpen() {
    _openInitialised = true;
    final sectionOf = _sectionOf();
    final sections = [for (final f in widget.spec.fields) if (f.kind == FieldKind.section) f.key];
    if (sections.isEmpty) return;
    _open.add(sections.first);
    for (final f in widget.spec.fields) {
      final sec = sectionOf[f.key];
      if (sec != null && (f.required || widget.errors.containsKey(f.key))) _open.add(sec);
    }
  }

  @override
  void didUpdateWidget(covariant SpecForm old) {
    super.didUpdateWidget(old);
    // A failed submit brings the first field with an error into view, rather than leaving the
    // person at the bottom of a long form looking for it (audit MOB-UX-027). A field inside a
    // closed section is opened first.
    if (widget.errors.isNotEmpty && !_sameKeys(old.errors, widget.errors)) {
      final sectionOf = _sectionOf();
      final toOpen = {for (final k in widget.errors.keys) if (sectionOf[k] != null) sectionOf[k]!};
      if (toOpen.any((k) => !_open.contains(k))) setState(() => _open.addAll(toOpen));
      WidgetsBinding.instance.addPostFrameCallback((_) {
        if (!mounted) return;
        for (final f in widget.spec.fields) {
          final ctx = widget.errors.containsKey(f.key) ? _fieldKeys[f.key]?.currentContext : null;
          if (ctx != null) {
            Scrollable.ensureVisible(ctx, duration: const Duration(milliseconds: 250), alignment: 0.1);
            break;
          }
        }
      });
    }
  }

  static bool _sameKeys(Map<String, String> a, Map<String, String> b) => identical(a, b) || (a.length == b.length && a.keys.every(b.containsKey));

  Widget _fieldWidget(FieldSpec f) => Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [KeyedSubtree(key: _fieldKeys.putIfAbsent(f.key, GlobalKey.new), child: _input(f)), const SizedBox(height: 14)],
      );

  Widget _sectionCard(FieldSpec header, List<FieldSpec> fields) {
    final scheme = Theme.of(context).colorScheme;
    final open = _open.contains(header.key);
    final errorCount = fields.where((f) => widget.errors.containsKey(f.key)).length;
    return Padding(
      padding: const EdgeInsets.only(bottom: 12),
      child: DecoratedBox(
        decoration: BoxDecoration(
          border: Border.all(color: errorCount > 0 ? scheme.error : scheme.outlineVariant),
          borderRadius: BorderRadius.circular(12),
        ),
        child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
          Semantics(
            button: true,
            expanded: open,
            label: header.label,
            child: InkWell(
              key: Key('section-${header.key}'),
              borderRadius: BorderRadius.circular(12),
              onTap: () => setState(() => open ? _open.remove(header.key) : _open.add(header.key)),
              child: Padding(
                padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 12),
                child: Row(children: [
                  Expanded(
                    child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                      Text(header.label, style: Theme.of(context).textTheme.titleSmall?.copyWith(fontWeight: FontWeight.w700)),
                      if (header.hint != null) Text(header.hint!, style: Theme.of(context).textTheme.bodySmall?.copyWith(color: scheme.onSurfaceVariant)),
                    ]),
                  ),
                  if (errorCount > 0)
                    Padding(
                      padding: const EdgeInsets.only(right: 8),
                      child: Text(errorCount == 1 ? '1 to fix' : '$errorCount to fix', style: TextStyle(color: scheme.error, fontSize: 12, fontWeight: FontWeight.w600)),
                    ),
                  Icon(open ? Icons.expand_less_rounded : Icons.expand_more_rounded, color: scheme.onSurfaceVariant),
                ]),
              ),
            ),
          ),
          if (open)
            Padding(
              padding: const EdgeInsets.fromLTRB(14, 4, 14, 0),
              child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [for (final f in fields) _fieldWidget(f)]),
            ),
        ]),
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    final visible = widget.spec.fields.where((f) => f.kind != FieldKind.hidden && (!f.editOnly || widget.editing) && fieldVisible(f, widget.values)).toList();
    if (!visible.any((f) => f.kind == FieldKind.section)) {
      return AutofillGroup(
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [for (final f in visible) _fieldWidget(f)],
        ),
      );
    }
    if (!_openInitialised) _initOpen();
    // Group: fields before any section stand alone; the rest go under their section's header.
    final children = <Widget>[];
    FieldSpec? header;
    var group = <FieldSpec>[];
    void flush() {
      if (header != null) {
        if (group.isNotEmpty) children.add(_sectionCard(header, group));
      } else {
        children.addAll(group.map(_fieldWidget));
      }
      group = <FieldSpec>[];
    }

    for (final f in visible) {
      if (f.kind == FieldKind.section) {
        flush();
        header = f;
      } else {
        group.add(f);
      }
    }
    flush();
    return AutofillGroup(child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: children));
  }
}
