import 'package:flutter/material.dart';

import '../../auth/presentation/widgets/auth_form_field.dart';
import '../domain/onboarding_form_spec.dart';

/// Renders one section (or one row of a repeatable section) from its [OnboardingSectionSpec],
/// reading from and writing into the shared mutable [values] map.
class OnboardingRecordForm extends StatefulWidget {
  const OnboardingRecordForm({
    super.key,
    required this.spec,
    required this.values,
    required this.errors,
    required this.onChanged,
    this.readOnly = false,
  });

  final OnboardingSectionSpec spec;
  final Map<String, dynamic> values;
  final Map<String, String> errors;
  final VoidCallback onChanged;
  final bool readOnly;

  @override
  State<OnboardingRecordForm> createState() => _OnboardingRecordFormState();
}

class _OnboardingRecordFormState extends State<OnboardingRecordForm> {
  final _controllers = <String, TextEditingController>{};

  TextEditingController _controller(OnboardingField f) => _controllers.putIfAbsent(
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
    widget.onChanged();
  }

  Future<void> _pickDate(OnboardingField f) async {
    final current = DateTime.tryParse((widget.values[f.key] ?? '').toString());
    final picked = await showDatePicker(
      context: context,
      initialDate: current ?? DateTime(2000, 1, 1),
      firstDate: DateTime(1900),
      lastDate: DateTime(2100),
    );
    if (picked == null) return;
    final iso = '${picked.year.toString().padLeft(4, '0')}-${picked.month.toString().padLeft(2, '0')}-${picked.day.toString().padLeft(2, '0')}';
    _controller(f).text = iso;
    _set(f.key, iso);
  }

  TextInputType _keyboard(OnboardingFieldType t) {
    switch (t) {
      case OnboardingFieldType.integer:
        return TextInputType.number;
      case OnboardingFieldType.decimal:
      case OnboardingFieldType.money:
        return const TextInputType.numberWithOptions(decimal: true);
      case OnboardingFieldType.aadhaar:
        return TextInputType.number;
      default:
        return TextInputType.text;
    }
  }

  Widget _input(OnboardingField f) {
    final error = widget.errors[f.key];
    switch (f.type) {
      case OnboardingFieldType.toggle:
        return SwitchListTile(
          contentPadding: EdgeInsets.zero,
          title: Text(f.label),
          value: widget.values[f.key] == true,
          onChanged: widget.readOnly ? null : (v) => _set(f.key, v),
        );
      case OnboardingFieldType.select:
        final current = (widget.values[f.key] ?? '').toString();
        final options = [
          ...f.options,
          if (current.isNotEmpty && !f.options.contains(current)) current,
        ];
        return AuthFormField(
          label: f.label,
          required: f.required,
          errorText: error,
          child: DropdownButtonFormField<String>(
            value: current.isEmpty ? null : current,
            items: [for (final o in options) DropdownMenuItem(value: o, child: Text(paymentModeLabels[o] ?? o))],
            onChanged: widget.readOnly ? null : (v) => _set(f.key, v ?? ''),
            decoration: const InputDecoration(hintText: 'Select'),
          ),
        );
      case OnboardingFieldType.date:
        return AuthFormField(
          label: f.label,
          required: f.required,
          errorText: error,
          child: TextField(
            controller: _controller(f),
            readOnly: true,
            onTap: widget.readOnly ? null : () => _pickDate(f),
            decoration: const InputDecoration(hintText: 'YYYY-MM-DD', suffixIcon: Icon(Icons.calendar_today_outlined, size: 18)),
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
            enabled: !widget.readOnly,
            keyboardType: _keyboard(f.type),
            textCapitalization: (f.type == OnboardingFieldType.pan || f.type == OnboardingFieldType.upper)
                ? TextCapitalization.characters
                : TextCapitalization.none,
            onChanged: (v) => _set(f.key, v),
          ),
        );
    }
  }

  @override
  Widget build(BuildContext context) {
    final visible = widget.spec.fields.where((f) => f.type != OnboardingFieldType.hidden && fieldVisible(f, widget.values));
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        for (final f in visible) ...[_input(f), const SizedBox(height: 14)],
      ],
    );
  }
}
