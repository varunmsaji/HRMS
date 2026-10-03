import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../core/api/api_client.dart';
import '../../../core/api/api_error.dart';
import '../../../core/forms/choice_sources.dart';
import '../../../core/forms/form_spec.dart';
import '../../../core/providers.dart';
import '../../../core/time.dart';
import '../../auth/presentation/widgets/auth_form_field.dart';
import '../../auth/state/auth_controller.dart';
import '../../shell/more_action.dart';
import '../domain/policy_assignment_form.dart';

typedef Rec = Map<String, dynamic>;

/// The kinds that can be previewed: the three attendance policy kinds the web page offers
/// (`/attendance-policy-resolution`), plus the work calendar (`/calendar-resolution`).
const resolutionKinds = ['ATTENDANCE_POLICY', 'OVERTIME_POLICY', 'REGULARIZATION_POLICY', 'WORK_CALENDAR'];

/// Policy resolution preview — mirrors `apps/web/src/app/app/policy-resolution/page.tsx`: for one
/// employee on one date, which policy applies and through which precedence level it was resolved
/// (the WD-09 walk). A missing assignment is `CONFIG_INCOMPLETE` — it never falls back silently.
class PolicyResolutionScreen extends ConsumerStatefulWidget {
  const PolicyResolutionScreen({super.key});

  @override
  ConsumerState<PolicyResolutionScreen> createState() => _PolicyResolutionScreenState();
}

class _PolicyResolutionScreenState extends ConsumerState<PolicyResolutionScreen> {
  List<Choice> _employees = const [];
  String _employeeId = '';
  late String _date;
  String _kind = 'ATTENDANCE_POLICY';
  bool _loading = false;
  String? _error;
  Rec? _result;
  String? _resultKind;

  ApiClient get _client => ref.read(apiClientProvider);

  @override
  void initState() {
    super.initState();
    _date = businessToday(ref.read(authControllerProvider).user?.companyTimezone ?? 'Asia/Kolkata');
    _loadEmployees();
  }

  Future<void> _loadEmployees() async {
    try {
      final c = await loadChoices(_client, const ['employees']);
      if (mounted) setState(() => _employees = c['employees'] ?? const []);
    } catch (_) {}
  }

  Future<void> _pickDate() async {
    final picked = await showDatePicker(context: context, initialDate: DateTime.tryParse(_date) ?? DateTime.now(), firstDate: DateTime(2020), lastDate: DateTime(2100));
    if (picked != null) setState(() => _date = '${picked.year.toString().padLeft(4, '0')}-${picked.month.toString().padLeft(2, '0')}-${picked.day.toString().padLeft(2, '0')}');
  }

  Future<void> _resolve() async {
    if (_employeeId.isEmpty) {
      setState(() => _error = 'Choose an employee and a date.');
      return;
    }
    setState(() {
      _loading = true;
      _error = null;
      _result = null;
    });
    try {
      final result = _kind == 'WORK_CALENDAR'
          ? await _client.get<Rec>('/calendar-resolution?employee_id=$_employeeId&date=$_date', parse: (d) => d as Rec)
          : await _client.get<Rec>('/attendance-policy-resolution?employee_id=$_employeeId&date=$_date&policy_kind=$_kind', parse: (d) => d as Rec);
      if (mounted) {
        setState(() {
          _result = result;
          _resultKind = _kind;
        });
      }
    } catch (e) {
      if (mounted) setState(() => _error = e is ApiError ? e.message : 'Something went wrong.');
    } finally {
      if (mounted) setState(() => _loading = false);
    }
  }

  Widget _kv(String k, String v) => Padding(
        padding: const EdgeInsets.symmetric(vertical: 4),
        child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Expanded(flex: 4, child: Text(k, style: TextStyle(color: Theme.of(context).colorScheme.onSurfaceVariant))),
          Expanded(flex: 5, child: Text(v, textAlign: TextAlign.end)),
        ]),
      );

  Widget _resultCard(Rec r) {
    final scheme = Theme.of(context).colorScheme;
    final incomplete = r['config_incomplete'] == true;
    final isCalendar = _resultKind == 'WORK_CALENDAR';
    return Container(
      margin: const EdgeInsets.only(top: 16),
      padding: const EdgeInsets.all(14),
      decoration: BoxDecoration(border: Border.all(color: scheme.outlineVariant), borderRadius: BorderRadius.circular(12)),
      child: incomplete
          ? Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
              Text('CONFIG_INCOMPLETE', style: TextStyle(fontWeight: FontWeight.w700, color: scheme.error)),
              const SizedBox(height: 6),
              Text(isCalendar
                  ? 'No work calendar resolves for this employee on this date.'
                  : 'No applicable policy is assigned at any scope for this employee and date. This never silently falls back to a default — assign a policy at company scope at minimum.'),
            ])
          : isCalendar
              ? Column(children: [
                  _kv('Work calendar', '${r['work_calendar_name'] ?? '—'}'),
                  _kv('Resolved through', prettyEnum('${r['resolved_scope_type'] ?? '—'}')),
                  _kv('Weekly-off resolved through', prettyEnum('${r['weekly_off_resolved_scope_type'] ?? '—'}')),
                  if (r['day_type'] is Map) ...[
                    _kv('Day type', prettyEnum('${(r['day_type'] as Map)['day_type']}')),
                    if ((r['day_type'] as Map)['holiday_name'] != null) _kv('Holiday', '${(r['day_type'] as Map)['holiday_name']}'),
                  ],
                ])
              : Column(children: [
                  _kv('Resolved policy', '${r['resolved_policy_name'] ?? '—'}${r['resolved_policy_code'] != null ? ' (${r['resolved_policy_code']})' : ''}'),
                  _kv('Resolved through', prettyEnum('${r['resolved_through'] ?? '—'}')),
                  _kv('Policy version', '${r['resolved_version_id'] ?? '—'}'),
                ]),
    );
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('Policy Resolution'), actions: const [MoreAction()]),
      body: ListView(
        padding: const EdgeInsets.all(16),
        children: [
          Text('Which policy applies to an employee on a date, and which precedence level resolved it.', style: TextStyle(color: Theme.of(context).colorScheme.onSurfaceVariant)),
          const SizedBox(height: 16),
          AuthFormField(
            label: 'Employee',
            required: true,
            child: DropdownButtonFormField<String>(
              value: _employeeId.isEmpty ? null : _employeeId,
              isExpanded: true,
              items: [for (final e in _employees) DropdownMenuItem(value: e.value, child: Text(e.label))],
              onChanged: (v) => setState(() => _employeeId = v ?? ''),
              decoration: const InputDecoration(hintText: 'Choose…'),
            ),
          ),
          const SizedBox(height: 14),
          AuthFormField(label: 'Date', required: true, child: OutlinedButton.icon(onPressed: _pickDate, icon: const Icon(Icons.calendar_today_outlined, size: 18), label: Text(_date))),
          const SizedBox(height: 14),
          AuthFormField(
            label: 'Policy kind',
            required: true,
            child: DropdownButtonFormField<String>(
              value: _kind,
              isExpanded: true,
              items: [for (final k in resolutionKinds) DropdownMenuItem(value: k, child: Text(policyKindLabels[k]!))],
              onChanged: (v) => setState(() => _kind = v ?? _kind),
            ),
          ),
          const SizedBox(height: 16),
          FilledButton(onPressed: _loading ? null : _resolve, child: Text(_loading ? 'Resolving…' : 'Resolve')),
          if (_error != null) Padding(padding: const EdgeInsets.only(top: 12), child: Text(_error!, style: TextStyle(color: Theme.of(context).colorScheme.error))),
          if (_result != null) _resultCard(_result!),
        ],
      ),
    );
  }
}
