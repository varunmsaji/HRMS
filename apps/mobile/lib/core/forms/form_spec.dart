/// A tiny declarative form engine: a [FormSpec] lists [FieldSpec]s; [SpecForm] renders them and the
/// helpers here convert between the wire JSON and the form's working values, validate, and build
/// payloads. Used by the onboarding wizard and every create/edit form in the app, so adding a field
/// is one line in a spec, not a widget.
library;

enum FieldKind {
  text,
  multiline,
  date,
  time,
  select,

  /// Options supplied at runtime (`choices[choiceKey]` on the form) — stores the option's value.
  choice,
  toggle,
  integer,
  decimal,
  money,
  pan,
  aadhaar,
  upper,
  email,
  hidden,
}

class FieldSpec {
  const FieldSpec(
    this.key,
    this.label, {
    this.kind = FieldKind.text,
    this.required = false,
    this.options = const [],
    this.optionLabels = const {},
    this.choiceKey,
    this.showWhen,
    this.hint,
    this.exactLength,
    this.readOnlyOnEdit = false,
  });

  /// Wire key in the JSON (e.g. `pan_number_enc`).
  final String key;
  final String label;
  final FieldKind kind;
  final bool required;

  /// Allowed values for [FieldKind.select]; shown via [optionLabels] when present.
  final List<String> options;
  final Map<String, String> optionLabels;

  /// Key into the runtime `choices` map for [FieldKind.choice].
  final String? choiceKey;

  /// Only shown (and sent) when this toggle key in the same row is true (or false when `!`-prefixed).
  final String? showWhen;
  final String? hint;

  /// For [FieldKind.upper] codes (e.g. a 3-letter currency).
  final int? exactLength;

  /// Create-only field (e.g. a code that can't change once set).
  final bool readOnlyOnEdit;
}

typedef RowValidator = Map<String, String> Function(Map<String, dynamic> values);

class FormSpec {
  const FormSpec({
    required this.name,
    required this.label,
    required this.fields,
    this.description = '',
    this.repeatable = false,
    this.itemNoun = 'entry',
    this.defaults = const {},
    this.extraValidate,
  });

  /// Wire section name / form id.
  final String name;
  final String label;
  final String description;
  final List<FieldSpec> fields;

  /// Stored as `{"items": [ {...}, ... ]}` instead of a flat object (onboarding sections).
  final bool repeatable;
  final String itemNoun;
  final Map<String, dynamic> defaults;

  /// Cross-field rules a per-field spec can't express.
  final RowValidator? extraValidate;
}

/// A runtime option for [FieldKind.choice].
typedef Choice = ({String value, String label});

// ---- wire <-> form-string conversion ----------------------------------------------------------

final _panPattern = RegExp(r'^[A-Z]{5}[0-9]{4}[A-Z]$');
final _aadhaarPattern = RegExp(r'^[0-9]{12}$');
final _emailPattern = RegExp(r'^[^@\s]+@[^@\s]+\.[^@\s]+$');
final _timePattern = RegExp(r'^([01]\d|2[0-3]):[0-5]\d(:[0-5]\d)?$');

bool fieldVisible(FieldSpec f, Map<String, dynamic> values) {
  final cond = f.showWhen;
  if (cond == null) return true;
  if (cond.startsWith('!')) return values[cond.substring(1)] != true;
  return values[cond] == true;
}

/// Wire JSON value -> the form's working value (strings for text-like, bool for toggles).
dynamic toFormValue(FieldSpec f, dynamic wire) {
  switch (f.kind) {
    case FieldKind.toggle:
      return wire == true;
    case FieldKind.money:
      return wire is num ? (wire / 100).toString().replaceAll(RegExp(r'\.0$'), '') : '';
    case FieldKind.hidden:
      return wire;
    default:
      return wire == null ? '' : wire.toString();
  }
}

/// Form working value -> wire JSON value.
dynamic toWireValue(FieldSpec f, dynamic form) {
  switch (f.kind) {
    case FieldKind.toggle:
      return form == true;
    case FieldKind.hidden:
      return form;
    case FieldKind.integer:
      final s = (form ?? '').toString().trim();
      return s.isEmpty ? null : num.tryParse(s)?.truncate();
    case FieldKind.decimal:
      final s = (form ?? '').toString().trim();
      return s.isEmpty ? null : num.tryParse(s);
    case FieldKind.money:
      final s = (form ?? '').toString().trim();
      final n = s.isEmpty ? null : num.tryParse(s);
      return n == null ? null : (n * 100).round();
    case FieldKind.pan:
    case FieldKind.upper:
      final s = (form ?? '').toString().trim().toUpperCase();
      return s.isEmpty ? null : s;
    case FieldKind.aadhaar:
      final s = (form ?? '').toString().replaceAll(RegExp(r'\s+'), '');
      return s.isEmpty ? null : s;
    default:
      final s = (form ?? '').toString().trim();
      return s.isEmpty ? null : s;
  }
}

/// Form values -> wire payload (fields hidden by their condition are sent as null/false).
Map<String, dynamic> rowToPayload(FormSpec spec, Map<String, dynamic> values) {
  return {
    for (final f in spec.fields)
      f.key: fieldVisible(f, values) ? toWireValue(f, values[f.key]) : (f.kind == FieldKind.toggle ? false : null),
  };
}

Map<String, dynamic> rowFromWire(FormSpec spec, Map<String, dynamic> wire) {
  return {
    for (final f in spec.fields) f.key: toFormValue(f, wire.containsKey(f.key) ? wire[f.key] : spec.defaults[f.key]),
  };
}

/// Only the keys whose value differs from [original] (a wire JSON map) — for PATCH.
Map<String, dynamic> changedOnly(Map<String, dynamic> original, Map<String, dynamic> payload) {
  return {
    for (final e in payload.entries)
      if (!_sameWire(original[e.key], e.value)) e.key: e.value,
  };
}

bool _sameWire(dynamic a, dynamic b) {
  if (a is num && b is num) return a == b;
  if (a is String && b is num) return num.tryParse(a) == b;
  if (a is num && b is String) return a == num.tryParse(b);
  return a == b;
}

/// Per-field validation for one row/form. Returns `{fieldKey: message}`.
Map<String, String> validateRow(FormSpec spec, Map<String, dynamic> values) {
  final errors = <String, String>{};
  for (final f in spec.fields) {
    if (!fieldVisible(f, values)) continue;
    final raw = values[f.key];
    final text = raw is String ? raw.trim() : '';
    if (f.required && f.kind != FieldKind.toggle && text.isEmpty) {
      errors[f.key] = '${f.label} is required.';
      continue;
    }
    if (text.isEmpty) continue;
    switch (f.kind) {
      case FieldKind.pan:
        if (!_panPattern.hasMatch(text.toUpperCase())) errors[f.key] = 'Enter a valid 10-character PAN (e.g. ABCDE1234F).';
      case FieldKind.aadhaar:
        if (!_aadhaarPattern.hasMatch(text.replaceAll(RegExp(r'\s+'), ''))) errors[f.key] = 'Enter a valid 12-digit Aadhaar number.';
      case FieldKind.email:
        if (!_emailPattern.hasMatch(text)) errors[f.key] = 'Enter a valid email address.';
      case FieldKind.time:
        if (!_timePattern.hasMatch(text)) errors[f.key] = 'Use HH:MM (24-hour).';
      case FieldKind.date:
        if (DateTime.tryParse(text) == null) errors[f.key] = 'Enter a valid date (YYYY-MM-DD).';
      case FieldKind.money:
        final n = num.tryParse(text);
        if (n == null || n < 0) errors[f.key] = 'Enter a valid amount.';
      case FieldKind.integer || FieldKind.decimal:
        if (num.tryParse(text) == null) errors[f.key] = 'Enter a valid number.';
      case FieldKind.upper:
        if (f.exactLength != null && text.length != f.exactLength) errors[f.key] = 'Enter ${f.exactLength} characters.';
      default:
        break;
    }
  }
  errors.addAll(spec.extraValidate?.call(values) ?? const {});
  return errors;
}
