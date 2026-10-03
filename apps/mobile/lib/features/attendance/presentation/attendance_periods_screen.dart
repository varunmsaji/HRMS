import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../core/api/api_client.dart';
import '../../../core/api/api_error.dart';
import '../../../core/auth/permissions.dart';
import '../../../core/forms/choice_sources.dart';
import '../../../core/forms/form_spec.dart';
import '../../../core/forms/spec_form_screen.dart';
import '../../../core/providers.dart';
import '../../../core/time.dart';
import '../../auth/state/auth_controller.dart';
import '../../shell/more_action.dart';
import 'attendance_period_detail_screen.dart';

typedef Rec = Map<String, dynamic>;

/// Opening a period: a calendar month by default (decision 18), or a custom date range. Each
/// legal entity runs its own cycle. `custom_range` is UI-only; only `month` *or* the two dates are sent.
Map<String, String> _validatePeriod(Map<String, dynamic> v) {
  final errors = <String, String>{};
  if (v['custom_range'] == true) {
    final start = (v['period_start'] ?? '') as String;
    final end = (v['period_end'] ?? '') as String;
    if (start.isEmpty) errors['period_start'] = 'Choose the first day.';
    if (end.isEmpty) errors['period_end'] = 'Choose the last day.';
    if (start.isNotEmpty && end.isNotEmpty && end.compareTo(start) < 0) errors['period_end'] = 'The last day must not be before the first.';
  } else if (!RegExp(r'^\d{4}-(0[1-9]|1[0-2])$').hasMatch(((v['month'] ?? '') as String).trim())) {
    errors['month'] = 'Month must look like 2026-09.';
  }
  return errors;
}

const attendancePeriodSpec = FormSpec(name: 'attendance_period', label: 'Attendance period', extraValidate: _validatePeriod, fields: [
  FieldSpec('legal_entity_id', 'Legal entity', kind: FieldKind.choice, choiceKey: 'legal_entities', required: true),
  FieldSpec('custom_range', 'Use a custom date range instead of a calendar month', kind: FieldKind.toggle),
  FieldSpec('month', 'Month', hint: 'YYYY-MM — the whole calendar month', showWhen: '!custom_range'),
  FieldSpec('period_start', 'First day', kind: FieldKind.date, showWhen: 'custom_range'),
  FieldSpec('period_end', 'Last day', kind: FieldKind.date, showWhen: 'custom_range'),
  FieldSpec('label', 'Label'),
]);

/// Attendance periods — mirrors `apps/web/src/app/app/attendance-periods/page.tsx`: each legal
/// entity's pay-cycle windows; opening one needs `ATTENDANCE.LOCK`.
class AttendancePeriodsScreen extends ConsumerStatefulWidget {
  const AttendancePeriodsScreen({super.key});

  @override
  ConsumerState<AttendancePeriodsScreen> createState() => _AttendancePeriodsScreenState();
}

class _AttendancePeriodsScreenState extends ConsumerState<AttendancePeriodsScreen> {
  bool _loading = true;
  ApiError? _error;
  List<Rec> _periods = const [];
  List<Choice> _entities = const [];
  String _entity = '';

  ApiClient get _client => ref.read(apiClientProvider);

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
      final env = await _client.getList<Rec>('/attendance-periods', query: PageQuery(perPage: 100), parseItem: (d) => d as Rec);
      var entities = const <Choice>[];
      try {
        entities = (await loadChoices(_client, const ['legal_entities']))['legal_entities'] ?? const [];
      } catch (_) {}
      if (mounted) {
        setState(() {
          _periods = env.data;
          _entities = entities;
        });
      }
    } catch (e) {
      if (mounted) setState(() => _error = e is ApiError ? e : ApiError(status: 0, code: 'UNKNOWN_ERROR', message: 'Something went wrong.'));
    } finally {
      if (mounted) setState(() => _loading = false);
    }
  }

  String _entityName(String id) {
    for (final c in _entities) {
      if (c.value == id) return c.label;
    }
    return 'Legal entity';
  }

  Future<void> _create() async {
    final zone = ref.read(authControllerProvider).user?.companyTimezone ?? 'Asia/Kolkata';
    final saved = await openSpecForm(
      context,
      title: 'Open attendance period',
      spec: attendancePeriodSpec,
      // The default month is the *business* month, not the device's (TZ-06).
      defaults: {'month': businessToday(zone).substring(0, 7), if (_entities.length == 1) 'legal_entity_id': _entities.first.value},
      loadChoices: () => loadChoices(_client, const ['legal_entities']),
      submitLabel: 'Open period',
      onSubmit: (payload, _) async => _client.post<Object?>(
        '/attendance-periods',
        body: {
          'legal_entity_id': payload['legal_entity_id'],
          if (payload['custom_range'] == true) ...{'period_start': payload['period_start'], 'period_end': payload['period_end']} else 'month': payload['month'],
          if (payload['label'] != null) 'label': payload['label'],
        },
        parse: (_) => null,
      ),
    );
    if (saved && mounted) {
      ScaffoldMessenger.of(context).showSnackBar(const SnackBar(content: Text('Attendance period opened.')));
      _load();
    }
  }

  @override
  Widget build(BuildContext context) {
    final canManage = (ref.watch(authControllerProvider).user?.permissions ?? const <String>[]).contains(attendanceLock);
    final visible = _periods.where((p) => _entity.isEmpty || p['legal_entity_id'] == _entity).toList()
      ..sort((a, b) => (b['period_start'] as String).compareTo(a['period_start'] as String));
    return Scaffold(
      appBar: AppBar(title: const Text('Attendance Periods'), actions: const [MoreAction()]),
      floatingActionButton: canManage ? FloatingActionButton.extended(onPressed: _create, icon: const Icon(Icons.add), label: const Text('Open period')) : null,
      body: _loading
          ? const Center(child: CircularProgressIndicator())
          : _error != null
              ? Center(
                  child: Padding(
                    padding: const EdgeInsets.all(24),
                    child: Column(mainAxisSize: MainAxisSize.min, children: [
                      Text(_error!.message, textAlign: TextAlign.center),
                      const SizedBox(height: 16),
                      FilledButton(onPressed: _load, child: const Text('Retry')),
                    ]),
                  ),
                )
              : RefreshIndicator(
                  onRefresh: _load,
                  child: ListView(
                    padding: const EdgeInsets.only(bottom: 88),
                    children: [
                      if (_entities.length > 1)
                        Padding(
                          padding: const EdgeInsets.fromLTRB(16, 12, 16, 0),
                          child: DropdownButtonFormField<String>(
                            value: _entity,
                            isExpanded: true,
                            decoration: const InputDecoration(labelText: 'Legal entity'),
                            items: [const DropdownMenuItem(value: '', child: Text('All legal entities')), for (final e in _entities) DropdownMenuItem(value: e.value, child: Text(e.label))],
                            onChanged: (v) => setState(() => _entity = v ?? ''),
                          ),
                        ),
                      if (visible.isEmpty) const Padding(padding: EdgeInsets.all(32), child: Center(child: Text('No attendance periods yet.'))),
                      for (final p in visible)
                        ListTile(
                          title: Text(p['label'] as String? ?? '${p['period_start']} → ${p['period_end']}'),
                          subtitle: Text('${_entityName(p['legal_entity_id'] as String)} · ${p['period_start']} → ${p['period_end']}'),
                          trailing: Chip(
                            label: Text(p['status'] == 'CLOSED' ? 'Closed & locked' : 'Open'),
                            visualDensity: VisualDensity.compact,
                            backgroundColor: (p['status'] == 'CLOSED' ? Colors.green : Colors.orange).withValues(alpha: 0.15),
                          ),
                          onTap: () async {
                            await Navigator.of(context).push(MaterialPageRoute(builder: (_) => AttendancePeriodDetailScreen(periodId: p['id'] as String, initial: p)));
                            _load();
                          },
                        ),
                    ],
                  ),
                ),
    );
  }
}
