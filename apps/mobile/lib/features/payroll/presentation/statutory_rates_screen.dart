import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../core/api/api_error.dart';
import '../../../core/auth/permissions.dart';
import '../../../core/forms/form_spec.dart';
import '../../../core/forms/spec_form_screen.dart';
import '../../../core/providers.dart';
import '../../auth/state/auth_controller.dart';
import '../../shell/more_action.dart';
import '../domain/payroll_resources.dart';
import '../../../core/widgets/ui.dart';

typedef Rec = Map<String, dynamic>;

const _monthNames = ['January', 'February', 'March', 'April', 'May', 'June', 'July', 'August', 'September', 'October', 'November', 'December'];

final _monthChoices = <String, List<Choice>>{
  'months': [for (var i = 0; i < 12; i++) (value: '${i + 1}', label: _monthNames[i])],
};

const _stateField = FieldSpec('state_code', 'State code', kind: FieldKind.upper, required: true, hint: 'e.g. MH — required for PT and LWF');
const _effectiveFromField = FieldSpec('effective_from', 'Effective from', kind: FieldKind.date, required: true);
const _notesField = FieldSpec('notes', 'Notes', kind: FieldKind.multiline);

/// Statutory rates (PF, ESI, PT, LWF, TDS) — mirrors `apps/web/src/app/app/payroll/statutory-rates/page.tsx`
/// and `statutory-rate-dialog.tsx`. A new rate for a scheme (and state) ends the open one the day
/// before it starts; rates are edited, then marked verified by someone who has checked the figures.
class StatutoryRatesScreen extends ConsumerStatefulWidget {
  const StatutoryRatesScreen({super.key});

  @override
  ConsumerState<StatutoryRatesScreen> createState() => _StatutoryRatesScreenState();
}

class _StatutoryRatesScreenState extends ConsumerState<StatutoryRatesScreen> {
  bool _loading = true;
  ApiError? _error;
  List<Rec> _rates = const [];
  String _scheme = '';
  bool _showHistory = false;

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    setState(() {
      _loading = true;
      _error = null;
    });
    try {
      final env = await ref.read(apiClientProvider).getList<Rec>('/payroll/statutory-rates', parseItem: (d) => d as Rec);
      if (mounted) setState(() => _rates = env.data);
    } catch (e) {
      if (mounted) setState(() => _error = e is ApiError ? e : ApiError(status: 0, code: 'UNKNOWN_ERROR', message: 'Something went wrong.'));
    } finally {
      if (mounted) setState(() => _loading = false);
    }
  }

  void _toast(String m) => ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(m)));

  Future<void> _create() async {
    var scheme = 'PF';
    final chosen = await showDialog<String>(
      context: context,
      builder: (ctx) => StatefulBuilder(
        builder: (ctx, setLocal) => AlertDialog(
          title: const Text('New statutory rate'),
          content: DropdownButtonFormField<String>(
            value: scheme,
            decoration: const InputDecoration(labelText: 'Scheme'),
            items: [for (final e in statutorySchemeLabels.entries) DropdownMenuItem(value: e.key, child: Text(e.value))],
            onChanged: (v) => setLocal(() => scheme = v ?? scheme),
          ),
          actions: [
            TextButton(onPressed: () => Navigator.of(ctx).pop(), child: const Text('Cancel')),
            FilledButton(onPressed: () => Navigator.of(ctx).pop(scheme), child: const Text('Continue')),
          ],
        ),
      ),
    );
    if (chosen == null || !mounted) return;
    final params = statutoryParameterSpecs[chosen]!;
    final usesState = stateSchemes.contains(chosen);
    final spec = FormSpec(
      name: 'statutory_rate',
      label: statutorySchemeLabels[chosen]!,
      defaults: params.defaults,
      fields: [if (usesState) _stateField, _effectiveFromField, _notesField, ...params.fields],
    );
    final paramKeys = params.fields.map((f) => f.key).toSet();
    final client = ref.read(apiClientProvider);
    final saved = await openSpecForm(
      context,
      title: 'New ${statutorySchemeLabels[chosen]} rate',
      spec: spec,
      loadChoices: () async => _monthChoices,
      onSubmit: (payload, _) async => client.post<Object?>(
        '/payroll/statutory-rates',
        body: {
          'scheme': chosen,
          if (usesState) 'state_code': payload['state_code'],
          'effective_from': payload['effective_from'],
          if (payload['notes'] != null) 'notes': payload['notes'],
          'parameters': {for (final k in paramKeys) k: payload[k]},
        },
        parse: (_) => null,
      ),
    );
    if (saved && mounted) {
      _toast('Rate created.');
      _load();
    }
  }

  Future<void> _edit(Rec rate) async {
    final scheme = rate['scheme'] as String;
    final params = statutoryParameterSpecs[scheme]!;
    final spec = FormSpec(name: 'statutory_rate_edit', label: statutorySchemeLabels[scheme]!, defaults: params.defaults, fields: [_notesField, ...params.fields]);
    final paramKeys = params.fields.map((f) => f.key).toSet();
    final original = {'notes': rate['notes'], ...(rate['parameters'] as Map).cast<String, dynamic>()};
    final client = ref.read(apiClientProvider);
    final saved = await openSpecForm(
      context,
      title: 'Edit ${statutorySchemeLabels[scheme]} rate',
      spec: spec,
      initial: original,
      loadChoices: () async => _monthChoices,
      onSubmit: (payload, changed) async {
        final paramsChanged = changed.keys.any(paramKeys.contains);
        await client.patch<Object?>(
          '/payroll/statutory-rates/${rate['id']}',
          body: {
            if (changed.containsKey('notes')) 'notes': changed['notes'],
            if (paramsChanged) 'parameters': {for (final k in paramKeys) k: payload[k]},
          },
          ifMatch: rate['version'].toString(),
          parse: (_) => null,
        );
      },
    );
    if (saved && mounted) {
      _toast('Rate saved.');
      _load();
    }
  }

  Future<void> _verify(Rec rate) async {
    try {
      await ref.read(apiClientProvider).post<Object?>('/payroll/statutory-rates/${rate['id']}/verify', ifMatch: rate['version'].toString(), parse: (_) => null);
      _toast('Rate marked as verified.');
    } catch (e) {
      _toast(e is ApiError ? (e.code == 'STALE_RESOURCE' ? 'This rate was changed by someone else. Reloading.' : e.message) : 'Something went wrong.');
    }
    _load();
  }

  @override
  Widget build(BuildContext context) {
    final permissions = ref.watch(authControllerProvider).user?.permissions ?? const <String>[];
    final canManage = permissions.contains(payrollStatutoryManage);
    final scheme = Theme.of(context).colorScheme;
    final visible = _rates.where((r) => (_scheme.isEmpty || r['scheme'] == _scheme) && (_showHistory || r['effective_to'] == null)).toList()
      ..sort((a, b) => '${a['scheme']}${a['state_code'] ?? ''}${b['effective_from']}'.compareTo('${b['scheme']}${b['state_code'] ?? ''}${a['effective_from']}'));
    return Scaffold(
      appBar: AppBar(title: const Text('Statutory Rates'), actions: const [MoreAction()]),
      floatingActionButton: canManage ? FloatingActionButton.extended(onPressed: _create, icon: const Icon(Icons.add), label: const Text('New rate')) : null,
      body: _loading
          ? const ListSkeleton()
          : _error != null
              ? StateMessage(icon: Icons.error_outline_rounded, tone: Tone.danger, title: 'Something went wrong', message: _error!.message, actionLabel: 'Retry', onAction: _load)
              : RefreshIndicator(
                  onRefresh: _load,
                  child: ListView(
                    padding: const EdgeInsets.fromLTRB(16, 12, 16, 88),
                    children: [
                      Wrap(spacing: 6, children: [
                        ChoiceChip(label: const Text('All'), selected: _scheme.isEmpty, onSelected: (_) => setState(() => _scheme = '')),
                        for (final s in statutorySchemeLabels.keys) ChoiceChip(label: Text(s), selected: _scheme == s, onSelected: (_) => setState(() => _scheme = s)),
                      ]),
                      SwitchListTile(contentPadding: EdgeInsets.zero, dense: true, title: const Text('Show past rates'), value: _showHistory, onChanged: (v) => setState(() => _showHistory = v)),
                      if (visible.isEmpty) const SizedBox(height: 300, child: StateMessage(icon: Icons.percent_rounded, title: 'No statutory rates yet')),
                      for (final r in visible)
                        Padding(
                          padding: const EdgeInsets.only(bottom: 10),
                          child: AppCard(
                            child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                              Row(children: [
                                Expanded(child: Text('${statutorySchemeLabels[r['scheme']] ?? r['scheme']}${r['state_code'] != null ? ' · ${r['state_code']}' : ''}', style: const TextStyle(fontWeight: FontWeight.w700, fontSize: 15))),
                                if (r['verified'] == true)
                                  const StatusChip(label: 'Verified', tone: Tone.success)
                                else
                                  const StatusChip(label: 'Unverified', tone: Tone.warning),
                              ]),
                              const SizedBox(height: 2),
                              Text('${r['effective_from']} → ${r['effective_to'] ?? 'open'}${r['is_seeded'] == true ? ' · seeded' : ''}', style: TextStyle(color: scheme.onSurfaceVariant)),
                              const SizedBox(height: 6),
                              Text(summariseStatutoryRate(r)),
                              if (r['notes'] != null) Padding(padding: const EdgeInsets.only(top: 4), child: Text('${r['notes']}', style: TextStyle(color: scheme.onSurfaceVariant, fontSize: 12))),
                              if (canManage)
                                Padding(
                                  padding: const EdgeInsets.only(top: 10),
                                  child: Wrap(spacing: 8, children: [
                                    OutlinedButton(onPressed: () => _edit(r), child: const Text('Edit')),
                                    if (r['verified'] != true) FilledButton.tonal(onPressed: () => _verify(r), child: const Text('Mark verified')),
                                  ]),
                                ),
                            ]),
                          ),
                        ),
                    ],
                  ),
                ),
    );
  }
}
