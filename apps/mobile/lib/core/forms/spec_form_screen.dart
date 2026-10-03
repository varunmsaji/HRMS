import 'package:flutter/material.dart';

import '../api/api_error.dart';
import '../../features/auth/presentation/widgets/auth_form_field.dart' show InlineAlert;
import 'form_spec.dart';
import 'spec_form.dart';

/// A full-screen create/edit form driven by a [FormSpec]. Pops `true` after [onSubmit] succeeds so
/// the caller can reload.
///
/// * [initial] — wire JSON of the record being edited (null = create).
/// * [loadChoices] — runtime options for `FieldKind.choice` fields (legal entities, branches, …).
/// * [onSubmit] receives the full wire payload and, for edits, only the changed keys ([changed]).
class SpecFormScreen extends StatefulWidget {
  const SpecFormScreen({
    super.key,
    required this.title,
    required this.spec,
    required this.onSubmit,
    this.initial,
    this.loadChoices,
    this.submitLabel,
    this.intro,
    this.defaults = const {},
  });

  final String title;
  final FormSpec spec;
  final Map<String, dynamic>? initial;
  final Map<String, dynamic> defaults;
  final Future<Map<String, List<Choice>>> Function()? loadChoices;
  final Future<void> Function(Map<String, dynamic> payload, Map<String, dynamic> changed) onSubmit;
  final String? submitLabel;
  final String? intro;

  @override
  State<SpecFormScreen> createState() => _SpecFormScreenState();
}

class _SpecFormScreenState extends State<SpecFormScreen> {
  late final Map<String, dynamic> _values;
  Map<String, String> _errors = {};
  Map<String, List<Choice>> _choices = const {};
  bool _loading = true;
  bool _saving = false;
  String? _banner;

  bool get _editing => widget.initial != null;

  @override
  void initState() {
    super.initState();
    _values = rowFromWire(widget.spec, {...widget.defaults, ...?widget.initial});
    _loadChoices();
  }

  Future<void> _loadChoices() async {
    try {
      final loaded = await widget.loadChoices?.call();
      if (mounted && loaded != null) setState(() => _choices = loaded);
    } catch (e) {
      if (mounted) setState(() => _banner = 'Could not load the options for this form. ${e is ApiError ? e.message : ''}'.trim());
    } finally {
      if (mounted) setState(() => _loading = false);
    }
  }

  Future<void> _submit() async {
    final errors = validateRow(widget.spec, _values);
    setState(() {
      _errors = errors;
      _banner = errors.isEmpty ? null : 'Please fix the highlighted fields.';
    });
    if (errors.isNotEmpty) return;
    final payload = rowToPayload(widget.spec, _values);
    final changed = _editing ? changedOnly(widget.initial!, payload) : payload;
    if (_editing && changed.isEmpty) {
      setState(() => _banner = 'No changes to save.');
      return;
    }
    setState(() => _saving = true);
    try {
      await widget.onSubmit(payload, changed);
      if (mounted) Navigator.of(context).pop(true);
    } on ApiError catch (e) {
      if (!mounted) return;
      final fieldErrors = <String, String>{};
      for (final d in e.details) {
        final key = d.field?.split('.').last;
        if (key != null && widget.spec.fields.any((f) => f.key == key)) fieldErrors[key] = d.message;
      }
      setState(() {
        _errors = fieldErrors;
        _banner = e.code == 'STALE_RESOURCE'
            ? 'This record was changed by someone else. Go back, reload, and try again.'
            : (e.status == 403 ? "You don't have permission to do that." : (fieldErrors.isEmpty ? e.message : 'Please fix the highlighted fields.'));
      });
    } catch (_) {
      if (mounted) setState(() => _banner = 'Something went wrong.');
    } finally {
      if (mounted) setState(() => _saving = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: Text(widget.title)),
      body: _loading
          ? const Center(child: CircularProgressIndicator())
          : ListView(
              padding: const EdgeInsets.all(16),
              children: [
                if (widget.intro != null) Padding(padding: const EdgeInsets.only(bottom: 16), child: Text(widget.intro!)),
                if (_banner != null) ...[InlineAlert(message: _banner!), const SizedBox(height: 16)],
                SpecForm(
                  spec: widget.spec,
                  values: _values,
                  errors: _errors,
                  choices: _choices,
                  editing: _editing,
                  readOnly: _saving,
                  onChanged: () => setState(() {}),
                ),
                const SizedBox(height: 8),
                FilledButton(
                  onPressed: _saving ? null : _submit,
                  child: Text(_saving ? 'Saving…' : (widget.submitLabel ?? (_editing ? 'Save changes' : 'Create'))),
                ),
              ],
            ),
    );
  }
}

/// Pushes a [SpecFormScreen]; resolves to true when the form saved.
Future<bool> openSpecForm(
  BuildContext context, {
  required String title,
  required FormSpec spec,
  required Future<void> Function(Map<String, dynamic> payload, Map<String, dynamic> changed) onSubmit,
  Map<String, dynamic>? initial,
  Map<String, dynamic> defaults = const {},
  Future<Map<String, List<Choice>>> Function()? loadChoices,
  String? submitLabel,
  String? intro,
}) async {
  final saved = await Navigator.of(context).push<bool>(MaterialPageRoute(
    builder: (_) => SpecFormScreen(
      title: title,
      spec: spec,
      onSubmit: onSubmit,
      initial: initial,
      defaults: defaults,
      loadChoices: loadChoices,
      submitLabel: submitLabel,
      intro: intro,
    ),
  ));
  return saved == true;
}
