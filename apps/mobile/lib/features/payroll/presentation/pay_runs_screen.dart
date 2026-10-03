import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../core/api/api_error.dart';
import '../../../core/auth/permissions.dart';
import '../../../core/format.dart';
import '../../../core/providers.dart';
import '../../auth/presentation/widgets/auth_form_field.dart';
import '../../auth/state/auth_controller.dart';
import '../../organisation/data/organisation_repository.dart';
import '../../organisation/presentation/legal_entities_screen.dart' show organisationRepositoryProvider;
import '../../shell/more_action.dart';
import '../data/payroll_repository.dart';
import 'pay_run_detail_screen.dart';

final payrollRepositoryProvider = Provider<PayrollRepository>((ref) => PayrollRepository(ref.watch(apiClientProvider)));

/// Mirrors `apps/web/src/app/app/payroll/pay-runs/page.tsx`: pay runs per legal entity, create
/// (legal entity + month + optional pay date) and the company-wide variance threshold.
class PayRunsScreen extends ConsumerStatefulWidget {
  const PayRunsScreen({super.key});

  @override
  ConsumerState<PayRunsScreen> createState() => _PayRunsScreenState();
}

class _PayRunsScreenState extends ConsumerState<PayRunsScreen> {
  bool _loading = true;
  ApiError? _error;
  List<PayRun> _runs = const [];
  List<LegalEntity> _entities = const [];
  String? _entityFilter;

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
      final runs = await ref.read(payrollRepositoryProvider).listPayRuns();
      List<LegalEntity> entities;
      try {
        entities = await ref.read(organisationRepositoryProvider).listLegalEntities();
      } catch (_) {
        entities = const [];
      }
      if (mounted) {
        setState(() {
          _runs = runs;
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
    for (final e in _entities) {
      if (e.id == id) return e.name;
    }
    return 'Legal entity';
  }

  String _defaultMonth() {
    final n = DateTime.now();
    final prev = DateTime(n.year, n.month - 1, 1);
    return '${prev.year}-${prev.month.toString().padLeft(2, '0')}';
  }

  Future<void> _create() async {
    final active = _entities.where((e) => e.isActive).toList();
    String? entityId = active.length == 1 ? active.first.id : null;
    final month = TextEditingController(text: _defaultMonth());
    final payDate = TextEditingController();
    String? error;
    final created = await showDialog<bool>(
      context: context,
      builder: (ctx) => StatefulBuilder(
        builder: (ctx, setLocal) => AlertDialog(
          title: const Text('New pay run'),
          content: SingleChildScrollView(
            child: Column(mainAxisSize: MainAxisSize.min, children: [
              if (error != null) Padding(padding: const EdgeInsets.only(bottom: 8), child: Text(error!, style: TextStyle(color: Theme.of(ctx).colorScheme.error))),
              AuthFormField(
                label: 'Legal entity',
                required: true,
                child: DropdownButtonFormField<String>(
                  value: entityId,
                  isExpanded: true,
                  items: [for (final e in active) DropdownMenuItem(value: e.id, child: Text(e.name))],
                  onChanged: (v) => setLocal(() => entityId = v),
                  decoration: const InputDecoration(hintText: 'Select'),
                ),
              ),
              const SizedBox(height: 12),
              AuthFormField(label: 'Month', required: true, description: 'YYYY-MM — covers the whole calendar month', child: TextField(controller: month)),
              const SizedBox(height: 12),
              AuthFormField(label: 'Pay date', description: 'YYYY-MM-DD — defaults to the first weekday of next month', child: TextField(controller: payDate)),
            ]),
          ),
          actions: [
            TextButton(onPressed: () => Navigator.of(ctx).pop(false), child: const Text('Cancel')),
            FilledButton(
              onPressed: () async {
                if (entityId == null) return setLocal(() => error = 'Choose a legal entity.');
                if (!RegExp(r'^\d{4}-(0[1-9]|1[0-2])$').hasMatch(month.text.trim())) return setLocal(() => error = 'Month must look like 2026-09.');
                if (payDate.text.trim().isNotEmpty && DateTime.tryParse(payDate.text.trim()) == null) return setLocal(() => error = 'Pay date must look like 2026-10-01.');
                try {
                  await ref.read(payrollRepositoryProvider).createPayRun({
                    'legal_entity_id': entityId,
                    'month': month.text.trim(),
                    if (payDate.text.trim().isNotEmpty) 'pay_date': payDate.text.trim(),
                  });
                  if (ctx.mounted) Navigator.of(ctx).pop(true);
                } catch (e) {
                  setLocal(() => error = e is ApiError ? e.message : 'Something went wrong.');
                }
              },
              child: const Text('Create'),
            ),
          ],
        ),
      ),
    );
    if (created == true) _load();
  }

  Future<void> _openSettings() async {
    final repo = ref.read(payrollRepositoryProvider);
    PayrollSetting setting;
    try {
      setting = await repo.getSettings();
    } catch (e) {
      if (mounted) ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(e is ApiError ? e.message : 'Something went wrong.')));
      return;
    }
    if (!mounted) return;
    final threshold = TextEditingController(text: setting.varianceThresholdPercent);
    String? error;
    final saved = await showDialog<bool>(
      context: context,
      builder: (ctx) => StatefulBuilder(
        builder: (ctx, setLocal) => AlertDialog(
          title: const Text('Payroll settings'),
          content: Column(mainAxisSize: MainAxisSize.min, children: [
            if (error != null) Padding(padding: const EdgeInsets.only(bottom: 8), child: Text(error!, style: TextStyle(color: Theme.of(ctx).colorScheme.error))),
            AuthFormField(
              label: 'Variance threshold (%)',
              description: "A pay run flags an employee whose net pay moves by more than this since the previous run.",
              child: TextField(controller: threshold, keyboardType: const TextInputType.numberWithOptions(decimal: true)),
            ),
          ]),
          actions: [
            TextButton(onPressed: () => Navigator.of(ctx).pop(false), child: const Text('Cancel')),
            FilledButton(
              onPressed: () async {
                if (num.tryParse(threshold.text.trim()) == null) return setLocal(() => error = 'Enter a number.');
                try {
                  await repo.updateSettings(varianceThresholdPercent: threshold.text.trim(), ifMatch: setting.version);
                  if (ctx.mounted) Navigator.of(ctx).pop(true);
                } catch (e) {
                  setLocal(() => error = e is ApiError ? e.message : 'Something went wrong.');
                }
              },
              child: const Text('Save'),
            ),
          ],
        ),
      ),
    );
    if (saved == true && mounted) ScaffoldMessenger.of(context).showSnackBar(const SnackBar(content: Text('Settings saved.')));
  }

  @override
  Widget build(BuildContext context) {
    final permissions = ref.watch(authControllerProvider).user?.permissions ?? const <String>[];
    final canProcess = permissions.contains(payrollRunProcess);
    final visible = _runs.where((r) => _entityFilter == null || r.legalEntityId == _entityFilter).toList();
    return Scaffold(
      appBar: AppBar(
        title: const Text('Payroll'),
        actions: [
          if (canProcess) IconButton(tooltip: 'Payroll settings', icon: const Icon(Icons.tune), onPressed: _openSettings),
          const MoreAction(),
        ],
      ),
      floatingActionButton: canProcess ? FloatingActionButton.extended(onPressed: _create, icon: const Icon(Icons.add), label: const Text('New pay run')) : null,
      body: _loading
          ? const Center(child: CircularProgressIndicator())
          : _error != null
              ? Center(
                  child: Padding(
                    padding: const EdgeInsets.all(24),
                    child: Column(mainAxisSize: MainAxisSize.min, children: [
                      Text(_error!.status == 403 ? 'You do not have permission to view pay runs.' : _error!.message, textAlign: TextAlign.center),
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
                          child: DropdownButtonFormField<String?>(
                            value: _entityFilter,
                            isExpanded: true,
                            decoration: const InputDecoration(labelText: 'Legal entity'),
                            items: [const DropdownMenuItem(value: null, child: Text('All legal entities')), for (final e in _entities) DropdownMenuItem(value: e.id, child: Text(e.name))],
                            onChanged: (v) => setState(() => _entityFilter = v),
                          ),
                        ),
                      if (visible.isEmpty) const Padding(padding: EdgeInsets.all(32), child: Center(child: Text('No pay runs yet.'))),
                      for (final run in visible)
                        ListTile(
                          title: Text(formatPayMonth(run.month)),
                          subtitle: Text([_entityName(run.legalEntityId), run.status.replaceAll('_', ' '), if (run.employeeCount != null) '${run.employeeCount} employees'].join(' · ')),
                          trailing: run.isComputed && run.netMinor != null ? Text(formatInr(run.netMinor!), style: const TextStyle(fontWeight: FontWeight.w600)) : const Icon(Icons.chevron_right, size: 20),
                          onTap: () async {
                            await Navigator.of(context).push(MaterialPageRoute(builder: (_) => PayRunDetailScreen(runId: run.id)));
                            _load();
                          },
                        ),
                    ],
                  ),
                ),
    );
  }
}
