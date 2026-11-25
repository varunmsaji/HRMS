import 'package:flutter/material.dart';

import '../api/api_error.dart';
import 'choice_sources.dart';
import '../../features/auth/presentation/widgets/auth_form_field.dart' show InlineAlert;
import 'form_spec.dart';
import 'spec_form.dart';
import '../widgets/employee/interaction.dart' show confirmDestructive;
import '../widgets/ui.dart';
import '../theme/employee_theme_scope.dart';

/// Thrown by an `onSubmit` when the user backed out of a confirmation step: nothing was saved, so
/// the form stays open and shows no error.
class SubmitCancelled implements Exception {
  const SubmitCancelled();
}

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
    this.loadChoiceSet,
    this.submitLabel,
    this.intro,
    this.defaults = const {},
  });

  final String title;
  final FormSpec spec;
  final Map<String, dynamic>? initial;
  final Map<String, dynamic> defaults;
  final Future<Map<String, List<Choice>>> Function()? loadChoices;

  /// Like [loadChoices] but tolerant of optional sources ([loadChoicesTolerant]); wins if both are set.
  final Future<ChoiceLoad> Function()? loadChoiceSet;
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
  Map<String, ChoiceUnavailable> _unavailable = const {};
  bool _loading = true;
  bool _saving = false;
  String? _banner;

  /// Set once the user changes any field. Leaving a changed form asks first (MOB-UX-024).
  bool _dirty = false;

  /// Back with unsaved changes: ask, and leave only on "Discard".
  Future<void> _confirmLeave() async {
    final discard = await confirmDestructive(
      context,
      title: 'Discard changes?',
      body: 'What you entered on this form has not been saved.',
      confirmLabel: 'Discard',
      cancelLabel: 'Keep editing',
    );
    if (!discard || !mounted) return;
    setState(() => _dirty = false);
    Navigator.of(context).pop();
  }

  bool get _editing => widget.initial != null;

  @override
  void initState() {
    super.initState();
    _values = rowFromWire(widget.spec, {...widget.defaults, ...?widget.initial});
    _loadChoices();
  }

  Future<void> _loadChoices() async {
    try {
      if (widget.loadChoiceSet != null) {
        final set = await widget.loadChoiceSet!();
        if (mounted) {
          setState(() {
            _choices = set.choices;
            _unavailable = set.unavailable;
          });
        }
        return;
      }
      final loaded = await widget.loadChoices?.call();
      if (mounted && loaded != null) setState(() => _choices = loaded);
    } catch (e) {
      if (mounted) setState(() => _banner = 'Could not load the options for this form. ${e is ApiError ? describeApiError(e) : ''}'.trim());
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
    var payload = rowToPayload(widget.spec, _values);
    if (!_editing) {
      // A create sends only what was filled in: edit-only fields don't exist yet, and an optional
      // field with a server-side default must be omitted, not sent as null.
      final editOnlyKeys = widget.spec.fields.where((f) => f.editOnly).map((f) => f.key).toSet();
      payload = {
        for (final e in payload.entries)
          if (e.value != null && !editOnlyKeys.contains(e.key)) e.key: e.value,
      };
    }
    final changed = _editing ? changedOnly(widget.initial!, payload) : payload;
    if (_editing && changed.isEmpty) {
      setState(() => _banner = 'No changes to save.');
      return;
    }
    setState(() => _saving = true);
    try {
      await widget.onSubmit(payload, changed);
      if (!mounted) return;
      // Saved: nothing left to lose, so the guard must not ask on the way out.
      setState(() => _dirty = false);
      Navigator.of(context).pop(true);
    } on SubmitCancelled {
      // Back on the form, as the user left it.
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
            : (e.status == 403 ? "You don't have permission to do that." : (fieldErrors.isEmpty ? describeApiError(e) : 'Please fix the highlighted fields.'));
      });
    } catch (_) {
      if (mounted) setState(() => _banner = 'Something went wrong.');
    } finally {
      if (mounted) setState(() => _saving = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    return PopScope(
      canPop: !_dirty,
      onPopInvokedWithResult: (didPop, _) {
        if (!didPop) _confirmLeave();
      },
      child: Scaffold(
      appBar: AppBar(title: Text(widget.title)),
      body: _loading
          ? const ListSkeleton(count: 4)
          : Column(children: [
              Expanded(
                // Not a lazy ListView: the whole form stays built, so a failed submit can bring any
                // field into view.
                child: SingleChildScrollView(
                  padding: const EdgeInsets.all(16),
                  child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
                    if (widget.intro != null) Padding(padding: const EdgeInsets.only(bottom: 16), child: Text(widget.intro!)),
                    if (_banner != null) ...[InlineAlert(message: _banner!), const SizedBox(height: 16)],
                    SpecForm(
                      spec: widget.spec,
                      values: _values,
                      errors: _errors,
                      choices: _choices,
                      unavailable: _unavailable,
                      editing: _editing,
                      readOnly: _saving,
                      onChanged: () => setState(() => _dirty = true),
                    ),
                  ]),
                ),
              ),
              // Pinned below the fields and above the keyboard, so a long form never has to be
              // scrolled to the end to submit it (audit MOB-UX-027).
              Material(
                color: Theme.of(context).colorScheme.surface,
                elevation: 3,
                child: SafeArea(
                  top: false,
                  child: Padding(
                    padding: const EdgeInsets.fromLTRB(16, 10, 16, 10),
                    child: SizedBox(
                      width: double.infinity,
                      child: FilledButton(
                        onPressed: _saving ? null : _submit,
                        child: Text(_saving ? 'Saving…' : (widget.submitLabel ?? (_editing ? 'Save changes' : 'Create'))),
                      ),
                    ),
                  ),
                ),
              ),
            ]),
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
  Future<ChoiceLoad> Function()? loadChoiceSet,
  String? submitLabel,
  String? intro,
}) async {
  final saved = await pushKeepingTheme<bool>(
    context,
    (_) => SpecFormScreen(
      title: title,
      spec: spec,
      onSubmit: onSubmit,
      initial: initial,
      defaults: defaults,
      loadChoices: loadChoices,
      loadChoiceSet: loadChoiceSet,
      submitLabel: submitLabel,
      intro: intro,
    ),
  );
  return saved == true;
}
