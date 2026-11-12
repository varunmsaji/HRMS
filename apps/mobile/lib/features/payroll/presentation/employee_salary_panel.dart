import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../core/api/api_error.dart';
import '../../../core/auth/permissions.dart';
import '../../../core/forms/choice_sources.dart';
import '../../../core/forms/form_spec.dart';
import '../../../core/forms/spec_form_screen.dart';
import '../../../core/format.dart';
import '../../../core/providers.dart';
import '../../../core/time.dart';
import '../../auth/state/auth_controller.dart';
import 'salary_breakup_view.dart';
import 'salary_setup_screen.dart';
import '../../../core/widgets/ui.dart';

/// Assign a salary structure — or, for a daily-wage employee, a daily rate (D5). The `rate_kind`
/// toggle is UI-only and is dropped before the request (the backend forbids unknown fields).
const employeeSalaryAssignSpec = FormSpec(
  name: 'employee_salary',
  label: 'Assign salary',
  fields: [
    FieldSpec('is_daily_wage', 'Daily-wage rate instead of a salary structure', kind: FieldKind.toggle),
    FieldSpec('salary_structure_id', 'Salary structure', kind: FieldKind.choice, choiceKey: 'salary_structures', required: true, showWhen: '!is_daily_wage'),
    FieldSpec('daily_rate_minor', 'Daily rate (₹)', kind: FieldKind.money, required: true, showWhen: 'is_daily_wage'),
    FieldSpec('effective_from', 'Effective from', kind: FieldKind.date, required: true),
    FieldSpec('reason', 'Reason', kind: FieldKind.multiline, required: true),
  ],
);

/// The Salary tab of an employee record — mirrors `apps/web/src/components/payroll/salary-panel.tsx`:
/// the CTC breakup under the assigned structure as of a date, the assignment history, and (with
/// `PAYROLL.SETUP_MANAGE`) assigning a structure or daily rate. With `EMPLOYEE.UPDATE_COMPENSATION`
/// too, "Edit salary & structure" opens [SalarySetupScreen] for the CTC and structure together.
class EmployeeSalaryPanel extends ConsumerStatefulWidget {
  const EmployeeSalaryPanel({super.key, required this.employeeId});
  final String employeeId;

  @override
  ConsumerState<EmployeeSalaryPanel> createState() => _EmployeeSalaryPanelState();
}

class _EmployeeSalaryPanelState extends ConsumerState<EmployeeSalaryPanel> {
  late String _asOf;
  bool _loading = true;
  ApiError? _error;
  List<Map<String, dynamic>> _history = const [];
  Map<String, dynamic>? _breakup;
  String? _breakupMessage;
  Map<String, String> _structureNames = const {};

  @override
  void initState() {
    super.initState();
    _asOf = businessToday(ref.read(authControllerProvider).user?.companyTimezone ?? 'Asia/Kolkata');
    _load();
  }

  Future<void> _load() async {
    setState(() {
      _loading = true;
      _error = null;
      _breakupMessage = null;
    });
    final client = ref.read(apiClientProvider);
    try {
      final history = await client.getList<Map<String, dynamic>>('/employees/${widget.employeeId}/salary', parseItem: (d) => d as Map<String, dynamic>);
      Map<String, dynamic>? breakup;
      String? message;
      try {
        breakup = await client.get<Map<String, dynamic>>('/employees/${widget.employeeId}/salary/breakup?as_of=$_asOf', parse: (d) => d as Map<String, dynamic>);
      } on ApiError catch (e) {
        message = e.message; // e.g. no salary assigned as of that date
      }
      Map<String, String> names = const {};
      try {
        final choices = await loadChoices(client, const ['salary_structures']);
        names = {for (final c in choices['salary_structures'] ?? const <Choice>[]) c.value: c.label};
      } catch (_) {}
      if (mounted) {
        setState(() {
          _history = history.data;
          _breakup = breakup;
          _breakupMessage = message;
          _structureNames = names;
        });
      }
    } catch (e) {
      if (mounted) setState(() => _error = e is ApiError ? e : ApiError(status: 0, code: 'UNKNOWN_ERROR', message: 'Something went wrong.'));
    } finally {
      if (mounted) setState(() => _loading = false);
    }
  }

  Future<void> _pickAsOf() async {
    final picked = await showDatePicker(context: context, initialDate: DateTime.tryParse(_asOf) ?? DateTime.now(), firstDate: DateTime(2020), lastDate: DateTime(2100));
    if (picked == null) return;
    setState(() => _asOf = '${picked.year.toString().padLeft(4, '0')}-${picked.month.toString().padLeft(2, '0')}-${picked.day.toString().padLeft(2, '0')}');
    _load();
  }

  Future<void> _assign() async {
    final client = ref.read(apiClientProvider);
    final saved = await openSpecForm(
      context,
      title: 'Assign salary',
      spec: employeeSalaryAssignSpec,
      loadChoices: () => loadChoices(client, const ['salary_structures']),
      onSubmit: (payload, _) async {
        final daily = payload['is_daily_wage'] == true;
        await client.post<Object?>(
          '/employees/${widget.employeeId}/salary',
          body: {
            if (daily) 'daily_rate_minor': payload['daily_rate_minor'] else 'salary_structure_id': payload['salary_structure_id'],
            'effective_from': payload['effective_from'],
            'reason': payload['reason'],
          },
          parse: (_) => null,
        );
      },
    );
    if (saved && mounted) {
      ScaffoldMessenger.of(context).showSnackBar(const SnackBar(content: Text('Salary assigned.')));
      await _load();
    }
  }

  Future<void> _editSetup() async {
    final today = businessToday(ref.read(authControllerProvider).user?.companyTimezone ?? 'Asia/Kolkata');
    final saved = await Navigator.of(context).push<bool>(MaterialPageRoute(builder: (_) => SalarySetupScreen(employeeId: widget.employeeId, today: today)));
    if (saved == true && mounted) await _load();
  }

  String _structure(String? id) => id == null ? '—' : (_structureNames[id] ?? 'Customised structure');

  @override
  Widget build(BuildContext context) {
    final permissions = ref.watch(authControllerProvider).user?.permissions ?? const <String>[];
    final scheme = Theme.of(context).colorScheme;
    if (_loading) return const ListSkeleton(count: 3);
    if (_error != null) return StateMessage(icon: Icons.error_outline_rounded, tone: Tone.danger, title: 'Something went wrong', message: _error!.status == 403 ? "You do not have permission to view this employee's salary." : _error!.message, actionLabel: 'Retry', onAction: _load);
    final b = _breakup;
    final inner = b?['breakup'] as Map<String, dynamic>?;
    return RefreshIndicator(
      onRefresh: _load,
      child: ListView(
        padding: const EdgeInsets.all(16),
        children: [
          Row(children: [
            Expanded(child: OutlinedButton.icon(onPressed: _pickAsOf, icon: const Icon(Icons.calendar_today_outlined, size: 18), label: Text('Salary as of $_asOf'))),
            if (permissions.contains(payrollSetupManage)) ...[const SizedBox(width: 8), OutlinedButton(onPressed: _assign, child: const Text('Assign'))],
          ]),
          if (permissions.contains(payrollSetupManage) && permissions.contains(employeeUpdateCompensation))
            Padding(
              padding: const EdgeInsets.only(top: 8),
              child: FilledButton.icon(onPressed: _editSetup, icon: const Icon(Icons.tune_rounded, size: 18), label: const Text('Edit salary & structure')),
            ),
          const SizedBox(height: 12),
          if (_breakupMessage != null) Text(_breakupMessage!, style: TextStyle(color: scheme.onSurfaceVariant)),
          if (b != null) ...[
            Text(
              b['pay_basis'] == 'DAILY_WAGE'
                  ? 'Daily-wage employee — ${formatInr((b['daily_rate_minor'] as num?) ?? 0)} a day.'
                  : '${_structure(b['salary_structure_id'] as String?)} · PF ${b['pf_applicable'] == true ? 'applies' : 'does not apply'} · ESI ${b['esi_applicable'] == true ? 'applies' : 'does not apply'}',
              style: TextStyle(color: scheme.onSurfaceVariant),
            ),
            if (inner != null) Padding(padding: const EdgeInsets.only(top: 10), child: SalaryBreakupView(breakup: inner)),
          ],
          const SizedBox(height: 18),
          const SectionHeader('Assignment history'),
          if (_history.isEmpty) Text('No salary assigned yet.', style: TextStyle(color: scheme.onSurfaceVariant)),
          for (final h in _history)
            Padding(
              padding: const EdgeInsets.only(bottom: 8),
              child: ListRowCard(
                leading: const IconBadge(icon: Icons.payments_outlined, size: 38),
                title: h['daily_rate_minor'] != null ? 'Daily rate ${formatInr(h['daily_rate_minor'] as num)}' : _structure(h['salary_structure_id'] as String?),
                subtitle: '${h['effective_from']} → ${h['effective_to'] ?? 'present'}${h['reason'] != null ? '\n${h['reason']}' : ''}',
                showChevron: false,
              ),
            ),
        ],
      ),
    );
  }
}
