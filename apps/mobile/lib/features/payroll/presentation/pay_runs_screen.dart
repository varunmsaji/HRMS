import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../core/api/api_error.dart';
import '../../../core/providers.dart';
import '../../../core/widgets/async_list_screen.dart';
import '../../auth/presentation/widgets/auth_form_field.dart';
import '../../shell/more_action.dart';
import '../data/payroll_repository.dart';

final payrollRepositoryProvider = Provider<PayrollRepository>((ref) => PayrollRepository(ref.watch(apiClientProvider)));

/// Mirrors `apps/web/src/app/app/payroll/pay-runs/[id]/page.tsx` — a single
/// detail page with stage-action buttons (lock-inputs → compute → approve →
/// finalise → mark-paid), not a wizard.
class PayRunsScreen extends ConsumerStatefulWidget {
  const PayRunsScreen({super.key});

  @override
  ConsumerState<PayRunsScreen> createState() => _PayRunsScreenState();
}

class _PayRunsScreenState extends ConsumerState<PayRunsScreen> {
  final _listKey = GlobalKey<AsyncListScreenState<PayRun>>();

  Future<void> _create() async {
    final legalEntityIdController = TextEditingController();
    final monthController = TextEditingController();
    final created = await showDialog<bool>(
      context: context,
      builder: (context) => AlertDialog(
        title: const Text('New pay run'),
        content: Column(mainAxisSize: MainAxisSize.min, children: [
          AuthFormField(label: 'Legal entity ID', required: true, child: TextField(controller: legalEntityIdController)),
          const SizedBox(height: 12),
          AuthFormField(label: 'Month', required: true, description: 'YYYY-MM', child: TextField(controller: monthController)),
        ]),
        actions: [
          TextButton(onPressed: () => Navigator.of(context).pop(false), child: const Text('Cancel')),
          FilledButton(
            onPressed: () async {
              if (legalEntityIdController.text.trim().isEmpty || monthController.text.trim().isEmpty) return;
              try {
                await ref.read(payrollRepositoryProvider).createPayRun({
                  'legal_entity_id': legalEntityIdController.text.trim(),
                  'month': monthController.text.trim(),
                });
                if (context.mounted) Navigator.of(context).pop(true);
              } catch (error) {
                if (context.mounted) {
                  ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(error is ApiError ? error.message : 'Something went wrong.')));
                }
              }
            },
            child: const Text('Create'),
          ),
        ],
      ),
    );
    if (created == true) _listKey.currentState?.reload();
  }

  @override
  Widget build(BuildContext context) {
    return AsyncListScreen<PayRun>(
      key: _listKey,
      title: 'Payroll',
      actions: const [MoreAction()],
      fetch: () => ref.read(payrollRepositoryProvider).listPayRuns(),
      createLabel: 'New pay run',
      onCreate: _create,
      emptyLabel: 'No pay runs yet.',
      itemBuilder: (context, run) => ListTile(
        title: Text(run.month),
        subtitle: Text([run.status, if (run.employeeCount != null) '${run.employeeCount} employees'].join(' · ')),
        trailing: const Icon(Icons.chevron_right, size: 20),
        onTap: () async {
          await Navigator.of(context).push(MaterialPageRoute(builder: (_) => PayRunDetailScreen(run: run)));
          _listKey.currentState?.reload();
        },
      ),
    );
  }
}

class PayRunDetailScreen extends ConsumerStatefulWidget {
  const PayRunDetailScreen({super.key, required this.run});
  final PayRun run;

  @override
  ConsumerState<PayRunDetailScreen> createState() => _PayRunDetailScreenState();
}

class _PayRunDetailScreenState extends ConsumerState<PayRunDetailScreen> {
  late PayRun _run = widget.run;
  bool _busy = false;
  bool _loadingEmployees = true;
  List<PayRunEmployee> _employees = const [];
  String? _message;

  @override
  void initState() {
    super.initState();
    _loadEmployees();
  }

  Future<void> _loadEmployees() async {
    try {
      final employees = await ref.read(payrollRepositoryProvider).listPayRunEmployees(_run.id);
      if (mounted) setState(() => _employees = employees);
    } catch (_) {
      // Non-fatal — the stage actions still work without the breakdown loaded.
    } finally {
      if (mounted) setState(() => _loadingEmployees = false);
    }
  }

  Future<void> _runAction(Future<PayRun> Function() action, String successMessage) async {
    setState(() {
      _busy = true;
      _message = null;
    });
    try {
      final updated = await action();
      if (mounted) setState(() => _run = updated);
      if (mounted) setState(() => _message = successMessage);
      _loadEmployees();
    } catch (error) {
      if (mounted) setState(() => _message = error is ApiError ? error.message : 'Something went wrong.');
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final scheme = Theme.of(context).colorScheme;
    final repository = ref.read(payrollRepositoryProvider);
    final ifMatch = _run.version.toString();

    Widget? stageAction;
    switch (_run.status) {
      case 'DRAFT':
        stageAction = FilledButton(onPressed: _busy ? null : () => _runAction(() => repository.lockInputs(_run.id, ifMatch: ifMatch), 'Inputs locked.'), child: const Text('Lock inputs'));
      case 'INPUTS_LOCKED':
        stageAction = FilledButton(onPressed: _busy ? null : () => _runAction(() => repository.compute(_run.id, ifMatch: ifMatch), 'Computed.'), child: const Text('Compute'));
      case 'COMPUTED':
        stageAction = FilledButton(onPressed: _busy ? null : () => _runAction(() => repository.approve(_run.id, ifMatch: ifMatch), 'Approved.'), child: const Text('Approve'));
      case 'APPROVED':
        stageAction = FilledButton(onPressed: _busy ? null : () => _runAction(() => repository.finalise(_run.id, ifMatch: ifMatch), 'Finalised.'), child: const Text('Finalise'));
      case 'FINALISED':
        stageAction = FilledButton(onPressed: _busy ? null : () => _runAction(() => repository.markPaid(_run.id, ifMatch: ifMatch), 'Marked paid.'), child: const Text('Mark paid'));
      default:
        stageAction = null;
    }

    return Scaffold(
      appBar: AppBar(title: Text(_run.month)),
      body: ListView(
        padding: const EdgeInsets.all(16),
        children: [
          if (_message != null) ...[InlineAlert(message: _message!), const SizedBox(height: 16)],
          Container(
            padding: const EdgeInsets.all(16),
            decoration: BoxDecoration(color: scheme.surfaceContainerLowest, borderRadius: BorderRadius.circular(12), border: Border.all(color: scheme.outlineVariant)),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text('Status: ${_run.status}', style: Theme.of(context).textTheme.headlineSmall),
                if (_run.payDate != null) Text('Pay date: ${_run.payDate}'),
                if (_run.employeeCount != null) Text('Employees: ${_run.employeeCount}'),
                if (_run.netMinor != null) Text('Net: ${(_run.netMinor! / 100).toStringAsFixed(2)}'),
              ],
            ),
          ),
          if (stageAction != null) ...[const SizedBox(height: 16), stageAction],
          const SizedBox(height: 24),
          Text('Employees', style: Theme.of(context).textTheme.labelMedium),
          const SizedBox(height: 8),
          if (_loadingEmployees)
            const Center(child: CircularProgressIndicator())
          else if (_employees.isEmpty)
            const Text('No breakdown yet.')
          else
            for (final employee in _employees)
              ListTile(
                contentPadding: EdgeInsets.zero,
                title: Text(employee.employeeName),
                subtitle: employee.hasError ? const Text('Has errors', style: TextStyle(color: Colors.red)) : null,
                trailing: employee.netMinor != null ? Text((employee.netMinor! / 100).toStringAsFixed(2)) : null,
              ),
        ],
      ),
    );
  }
}
