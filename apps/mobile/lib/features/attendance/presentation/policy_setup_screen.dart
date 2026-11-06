import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../core/api/api_client.dart';
import '../../../core/api/api_error.dart';
import '../../../core/forms/choice_sources.dart';
import '../../../core/forms/form_spec.dart';
import '../../../core/forms/spec_form.dart';
import '../../../core/forms/spec_form_screen.dart';
import '../../../core/providers.dart';
import '../../../core/time.dart';
import '../../../core/widgets/ui.dart';
import '../../auth/presentation/widgets/auth_form_field.dart' show InlineAlert;
import '../../auth/state/auth_controller.dart';
import '../data/assignment_lookup.dart';
import '../domain/policy_assignment_form.dart';
import '../domain/policy_setup_config.dart';

/// Create a policy or shift on one page — mirrors the web "new policy" pages: pick a template,
/// adjust the everyday rules (the rest sits under Advanced), then save a draft or publish.
/// Publishing asks when the rules start and who follows them, and everything is sent in one
/// request to `$path/setup`, so a rejection leaves nothing half-made. Pops `true` when saved.
class PolicySetupScreen extends ConsumerStatefulWidget {
  const PolicySetupScreen({super.key, required this.config, this.now});
  final PolicySetupConfig config;

  /// The clock, for tests.
  final DateTime? now;

  @override
  ConsumerState<PolicySetupScreen> createState() => _PolicySetupScreenState();
}

class _PolicySetupScreenState extends ConsumerState<PolicySetupScreen> {
  late final FormSpec _head;
  late final FormSpec _everyday;
  late final FormSpec _advanced;
  late final FormSpec _all;
  final Map<String, dynamic> _values = {};
  Map<String, String> _errors = {};
  Map<String, List<Choice>> _choices = const {};
  String _templateKey = '';
  // Bumped when a template replaces the values, so the fields rebuild with the new text.
  int _epoch = 0;
  bool _loading = true;
  bool _saving = false;
  String? _banner;

  PolicySetupConfig get _c => widget.config;
  ApiClient get _client => ref.read(apiClientProvider);

  @override
  void initState() {
    super.initState();
    final byKey = {for (final f in _c.rules.fields) f.key: f};
    _head = FormSpec(name: 'setup_head', label: _c.title, fields: [
      if (_c.leaveTyped) const FieldSpec('leave_type_id', 'Leave type', kind: FieldKind.choice, choiceKey: 'leave_types', required: true, hint: 'Each policy covers one leave type, and this cannot be changed later.'),
      const FieldSpec('name', 'Name', required: true),
    ]);
    _everyday = FormSpec(name: 'setup_everyday', label: 'Rules', fields: [for (final k in _c.everydayKeys) if (byKey.containsKey(k)) byKey[k]!]);
    _advanced = FormSpec(name: 'setup_advanced', label: 'Advanced', fields: [for (final f in _c.rules.fields) if (!_c.everydayKeys.contains(f.key)) f]);
    _all = FormSpec(name: 'setup', label: _c.title, fields: [..._head.fields, ..._everyday.fields, ..._advanced.fields]);
    _applyTemplate(_c.templates.first);
    _loadChoices();
  }

  Future<void> _loadChoices() async {
    try {
      final sources = choiceSourcesOf(_all);
      final loaded = sources.isEmpty ? <String, List<Choice>>{} : await loadChoices(_client, sources);
      if (mounted) setState(() => _choices = loaded);
    } catch (e) {
      if (mounted) setState(() => _banner = 'Could not load the options for this form. ${e is ApiError ? e.message : ''}'.trim());
    } finally {
      if (mounted) setState(() => _loading = false);
    }
  }

  /// Replaces the rules with the template's. A name or leave type the user already chose is kept
  /// (the name only when they changed it from the previous template's suggestion).
  void _applyTemplate(SetupTemplate t) {
    final previous = _c.templates.where((x) => x.key == _templateKey).firstOrNull;
    final name = '${_values['name'] ?? ''}';
    final keepName = name.isNotEmpty && (previous == null || name != previous.defaultName);
    final fresh = rowFromWire(_all, {..._c.base, ...t.values, 'name': keepName ? name : t.defaultName, 'leave_type_id': _values['leave_type_id']});
    _values
      ..clear()
      ..addAll(fresh);
    _templateKey = t.key;
    _errors = {};
    _epoch++;
  }

  /// The rules as the API wants them: only filled-in values, plus the start date when known.
  Map<String, dynamic> _rulesPayload(String? effectiveFrom) {
    final payload = rowToPayload(_all, _values);
    const headKeys = {'name', 'leave_type_id'};
    return {
      for (final e in payload.entries)
        if (!headKeys.contains(e.key) && e.value != null) e.key: e.value,
      if (effectiveFrom != null) 'effective_from': effectiveFrom,
    };
  }

  Map<String, dynamic> _body({required bool publish, String? effectiveFrom, String? reason, Map<String, dynamic>? assign}) => {
        if (_c.leaveTyped) 'leave_type_id': _values['leave_type_id'],
        'name': '${_values['name']}'.trim(),
        'rules': _rulesPayload(effectiveFrom),
        'publish': publish,
        if (reason != null && reason.isNotEmpty) 'publish_reason': reason,
        if (assign != null) 'assign': assign,
      };

  bool _validate({required bool forPublish}) {
    final errors = validateRow(_all, _values);
    if (forPublish) {
      _c.requiredToPublish.forEach((key, message) {
        final raw = _values[key];
        if ((raw is List && raw.isEmpty) || (raw is String && raw.trim().isEmpty) || raw == null) errors[key] = message;
      });
    }
    setState(() {
      _errors = errors;
      _banner = errors.isEmpty ? null : 'Please fix the highlighted fields.';
    });
    return errors.isEmpty;
  }

  Map<String, String> _fieldErrors(ApiError e) {
    final out = <String, String>{};
    for (final d in e.details) {
      final key = d.field?.split('.').last;
      if (key != null && _all.fields.any((f) => f.key == key)) out[key] = d.message;
    }
    return out;
  }

  Future<void> _saveDraft() async {
    if (!_validate(forPublish: false)) return;
    setState(() => _saving = true);
    try {
      await _client.post<Object?>('${_c.path}/setup', body: _body(publish: false), parse: (_) => null);
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(const SnackBar(content: Text('Draft saved.')));
      Navigator.of(context).pop(true);
    } on ApiError catch (e) {
      if (!mounted) return;
      final fields = _fieldErrors(e);
      setState(() {
        _errors = fields;
        _banner = fields.isEmpty ? 'Nothing was saved. ${e.message}' : 'Nothing was saved. Please fix the highlighted fields.';
      });
    } catch (_) {
      if (mounted) setState(() => _banner = 'Nothing was saved. Something went wrong.');
    } finally {
      if (mounted) setState(() => _saving = false);
    }
  }

  /// Today in the company's timezone, not the device's: rules published from a phone in
  /// another zone must still start on the company's date.
  String _today() => businessToday(ref.read(authControllerProvider).user?.companyTimezone ?? 'Asia/Kolkata', now: widget.now);

  Future<void> _publish() async {
    if (!_validate(forPublish: true)) return;
    final kind = _c.policyKind;
    final leaveTypeId = _c.leaveTyped ? '${_values['leave_type_id']}' : null;
    // A brand-new policy in a company with none of this kind almost always applies company-wide.
    var assignTo = 'NOBODY';
    if (kind != null) {
      try {
        final company = await findOpenAssignment(_client, policyKind: kind, scopeType: 'COMPANY', leaveTypeId: leaveTypeId);
        if (company == null) assignTo = 'COMPANY';
      } catch (_) {}
    }
    if (!mounted) return;
    final spec = FormSpec(name: 'publish', label: 'Publish', fields: [
      const FieldSpec('effective_from', 'Rules start on', kind: FieldKind.date, required: true),
      if (kind != null) ...[
        FieldSpec('assign_to', 'Who follows this', kind: FieldKind.select, required: true, options: ['NOBODY', 'COMPANY', ...scopeSources.keys], optionLabels: {'NOBODY': "Nobody yet, I'll assign it later", ...scopeTypeLabels}),
        FieldSpec('scope_id', 'Applies to', kind: FieldKind.choice, required: true, showWhen: 'assign_to!=NOBODY&&assign_to!=COMPANY', dependsOn: 'assign_to', choiceMap: scopeSources),
      ],
      const FieldSpec('reason', 'Reason (optional)', kind: FieldKind.multiline),
    ]);
    final saved = await openSpecForm(
      context,
      title: 'Publish',
      intro: "Published rules can't be edited, and past days keep the rules they had. To change them later, publish again with a new date.",
      submitLabel: 'Publish',
      spec: spec,
      defaults: {'effective_from': _today(), if (kind != null) 'assign_to': assignTo},
      loadChoices: kind == null ? null : () => loadChoices(_client, scopeSources.values),
      onSubmit: (p, _) async {
        Map<String, dynamic>? assign;
        final to = p['assign_to'] as String?;
        if (kind != null && to != null && to != 'NOBODY') {
          final scopeId = to == 'COMPANY' ? null : p['scope_id'] as String?;
          final open = await findOpenAssignment(_client, policyKind: kind, scopeType: to, scopeId: scopeId, leaveTypeId: leaveTypeId);
          assign = {'scope_type': to, 'scope_id': scopeId, 'expected_version': open?['version']};
        }
        await _client.post<Object?>(
          '${_c.path}/setup',
          body: _body(publish: true, effectiveFrom: p['effective_from'] as String, reason: p['reason'] as String?, assign: assign),
          parse: (_) => null,
        );
      },
    );
    if (saved && mounted) {
      ScaffoldMessenger.of(context).showSnackBar(const SnackBar(content: Text('Published.')));
      Navigator.of(context).pop(true);
    }
  }

  @override
  Widget build(BuildContext context) {
    final scheme = Theme.of(context).colorScheme;
    return Scaffold(
      appBar: AppBar(title: Text(_c.title)),
      body: _loading
          ? const ListSkeleton(count: 4)
          : ListView(
              padding: const EdgeInsets.all(16),
              children: [
                if (_banner != null) ...[InlineAlert(message: _banner!), const SizedBox(height: 16)],
                const Text('Start from', style: TextStyle(fontWeight: FontWeight.w700)),
                const SizedBox(height: 8),
                for (final t in _c.templates)
                  Padding(
                    padding: const EdgeInsets.only(bottom: 8),
                    child: AppCard(
                      onTap: _saving ? null : () => setState(() => _applyTemplate(t)),
                      child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
                        Icon(_templateKey == t.key ? Icons.radio_button_checked : Icons.radio_button_unchecked, color: _templateKey == t.key ? scheme.primary : scheme.onSurfaceVariant),
                        const SizedBox(width: 12),
                        Expanded(
                          child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                            Text(t.label, style: const TextStyle(fontWeight: FontWeight.w600)),
                            const SizedBox(height: 2),
                            Text(t.description, style: TextStyle(color: scheme.onSurfaceVariant, fontSize: 12.5)),
                          ]),
                        ),
                      ]),
                    ),
                  ),
                Text('Choosing a template replaces the rules below.', style: TextStyle(color: scheme.onSurfaceVariant, fontSize: 12)),
                const SizedBox(height: 16),
                SpecForm(key: ValueKey('head$_epoch'), spec: _head, values: _values, errors: _errors, choices: _choices, readOnly: _saving, onChanged: () => setState(() {})),
                const SizedBox(height: 8),
                SpecForm(key: ValueKey('everyday$_epoch'), spec: _everyday, values: _values, errors: _errors, choices: _choices, readOnly: _saving, onChanged: () => setState(() {})),
                if (_advanced.fields.isNotEmpty)
                  Theme(
                    data: Theme.of(context).copyWith(dividerColor: Colors.transparent),
                    child: ExpansionTile(
                      tilePadding: EdgeInsets.zero,
                      title: const Text('Advanced settings', style: TextStyle(fontWeight: FontWeight.w600)),
                      initiallyExpanded: _advanced.fields.any((f) => _errors.keys.any((k) => k == f.key || k.startsWith('${f.key}.'))),
                      children: [SpecForm(key: ValueKey('advanced$_epoch'), spec: _advanced, values: _values, errors: _errors, choices: _choices, readOnly: _saving, onChanged: () => setState(() {}))],
                    ),
                  ),
                const SizedBox(height: 16),
                FilledButton(onPressed: _saving ? null : _publish, child: const Text('Save & publish…')),
                const SizedBox(height: 8),
                OutlinedButton(onPressed: _saving ? null : _saveDraft, child: Text(_saving ? 'Saving…' : 'Save as draft')),
              ],
            ),
    );
  }
}
