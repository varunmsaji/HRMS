import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../core/api/api_error.dart';
import '../../../core/providers.dart';
import '../../../core/widgets/async_list_screen.dart';
import '../../attendance/data/policy_repository.dart';
import '../../attendance/presentation/policy_screens.dart' show PolicyDetailScreen;
import '../../auth/presentation/widgets/auth_form_field.dart';
import '../data/leave_repository.dart';
import 'leave_types_screen.dart' show leaveRepositoryProvider;

/// Leave Policies share the identity+versions+publish shape with
/// Attendance/Overtime/Regularization Policies (reuses `PolicyDetailScreen`
/// for versions), but the identity itself also carries a required
/// `leave_type_id`, so list+create are bespoke here rather than the fully
/// generic `PolicyListScreen`.
class LeavePoliciesScreen extends ConsumerStatefulWidget {
  const LeavePoliciesScreen({super.key});

  @override
  ConsumerState<LeavePoliciesScreen> createState() => _LeavePoliciesScreenState();
}

class _LeavePoliciesScreenState extends ConsumerState<LeavePoliciesScreen> {
  late final _policyRepository = PolicyRepository(ref.read(apiClientProvider), 'leave-policies');
  final _listKey = GlobalKey<AsyncListScreenState<PolicyIdentity>>();
  List<LeaveType> _types = const [];

  Future<void> _create() async {
    _types = await ref.read(leaveRepositoryProvider).listLeaveTypes();
    if (_types.isEmpty) {
      if (mounted) ScaffoldMessenger.of(context).showSnackBar(const SnackBar(content: Text('Create a leave type first.')));
      return;
    }
    if (!mounted) return;
    final nameController = TextEditingController();
    String leaveTypeId = _types.first.id;
    final created = await showDialog<bool>(
      context: context,
      builder: (context) => StatefulBuilder(
        builder: (context, setState) => AlertDialog(
          title: const Text('New leave policy'),
          content: Column(mainAxisSize: MainAxisSize.min, children: [
            AuthFormField(
              label: 'Leave type',
              child: DropdownButtonFormField<String>(
                value: leaveTypeId,
                items: [for (final t in _types) DropdownMenuItem(value: t.id, child: Text(t.name))],
                onChanged: (v) => setState(() => leaveTypeId = v ?? leaveTypeId),
              ),
            ),
            const SizedBox(height: 12),
            AuthFormField(label: 'Name', required: true, child: TextField(controller: nameController)),
          ]),
          actions: [
            TextButton(onPressed: () => Navigator.of(context).pop(false), child: const Text('Cancel')),
            FilledButton(
              onPressed: () async {
                if (nameController.text.trim().isEmpty) return;
                try {
                  await ref.read(leaveRepositoryProvider).createLeavePolicy(leaveTypeId: leaveTypeId, name: nameController.text.trim());
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
      ),
    );
    if (created == true) _listKey.currentState?.reload();
  }

  @override
  Widget build(BuildContext context) {
    return AsyncListScreen<PolicyIdentity>(
      key: _listKey,
      title: 'Leave Policies',
      fetch: _policyRepository.listPolicies,
      createLabel: 'New policy',
      onCreate: _create,
      emptyLabel: 'No leave policies yet.',
      itemBuilder: (context, policy) => ListTile(
        title: Text(policy.name),
        subtitle: Text([if (policy.code != null) policy.code!, if (!policy.isActive) 'Inactive'].join(' · ')),
        trailing: const Icon(Icons.chevron_right, size: 20),
        onTap: () => Navigator.of(context).push(MaterialPageRoute(
          builder: (_) => PolicyDetailScreen(
            title: policy.name,
            repository: _policyRepository,
            policyId: policy.id,
            versionFormBuilder: (context, repository, policyId) => LeavePolicyVersionForm(repository: repository, policyId: policyId),
          ),
        )),
      ),
    );
  }
}

const _accrualFrequencies = ['NONE', 'MONTHLY', 'YEARLY'];
const _yearEndActions = ['CARRY_FORWARD', 'LAPSE', 'ENCASH_EXCESS'];

class LeavePolicyVersionForm extends StatefulWidget {
  const LeavePolicyVersionForm({super.key, required this.repository, required this.policyId});
  final PolicyRepository repository;
  final String policyId;

  @override
  State<LeavePolicyVersionForm> createState() => _LeavePolicyVersionFormState();
}

class _LeavePolicyVersionFormState extends State<LeavePolicyVersionForm> {
  final _effectiveFrom = TextEditingController();
  final _maxCarryForwardDays = TextEditingController();
  final _accrualRate = TextEditingController();
  final _negativeBalanceFloor = TextEditingController();
  String _accrualFrequency = 'NONE';
  String _yearEndAction = 'CARRY_FORWARD';
  bool _allowEmployeeRequest = true;
  bool _allowNegativeBalance = false;
  bool _submitting = false;
  String? _formError;

  Future<void> _submit() async {
    if (DateTime.tryParse(_effectiveFrom.text.trim()) == null) {
      setState(() => _formError = 'Enter a valid effective-from date.');
      return;
    }
    setState(() {
      _submitting = true;
      _formError = null;
    });
    try {
      await widget.repository.createVersion(widget.policyId, {
        'effective_from': _effectiveFrom.text.trim(),
        'allow_employee_request': _allowEmployeeRequest,
        'accrual_frequency': _accrualFrequency,
        if (_accrualFrequency != 'NONE' && _accrualRate.text.trim().isNotEmpty) 'accrual_rate_per_cycle': num.tryParse(_accrualRate.text.trim()),
        if (_maxCarryForwardDays.text.trim().isNotEmpty) 'max_carry_forward_days': num.tryParse(_maxCarryForwardDays.text.trim()),
        'year_end_action': _yearEndAction,
        'allow_negative_balance': _allowNegativeBalance,
        if (_allowNegativeBalance && _negativeBalanceFloor.text.trim().isNotEmpty) 'negative_balance_floor': num.tryParse(_negativeBalanceFloor.text.trim()),
      });
      if (mounted) Navigator.of(context).pop(true);
    } catch (error) {
      setState(() => _formError = error is ApiError ? error.message : 'Something went wrong.');
    } finally {
      if (mounted) setState(() => _submitting = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('New leave policy draft')),
      body: ListView(
        padding: const EdgeInsets.all(16),
        children: [
          if (_formError != null) ...[InlineAlert(message: _formError!), const SizedBox(height: 16)],
          AuthFormField(label: 'Effective from', required: true, description: 'YYYY-MM-DD', child: TextField(controller: _effectiveFrom, enabled: !_submitting)),
          const SizedBox(height: 8),
          SwitchListTile(contentPadding: EdgeInsets.zero, title: const Text('Employees can request'), value: _allowEmployeeRequest, onChanged: _submitting ? null : (v) => setState(() => _allowEmployeeRequest = v)),
          const SizedBox(height: 8),
          AuthFormField(
            label: 'Accrual frequency',
            child: DropdownButtonFormField<String>(
              value: _accrualFrequency,
              items: [for (final f in _accrualFrequencies) DropdownMenuItem(value: f, child: Text(f))],
              onChanged: _submitting ? null : (v) => setState(() => _accrualFrequency = v ?? _accrualFrequency),
            ),
          ),
          if (_accrualFrequency != 'NONE') ...[
            const SizedBox(height: 16),
            AuthFormField(label: 'Accrual rate per cycle', child: TextField(controller: _accrualRate, enabled: !_submitting, keyboardType: TextInputType.number)),
          ],
          const SizedBox(height: 16),
          AuthFormField(label: 'Max carry-forward days', description: 'Optional', child: TextField(controller: _maxCarryForwardDays, enabled: !_submitting, keyboardType: TextInputType.number)),
          const SizedBox(height: 16),
          AuthFormField(
            label: 'Year-end action',
            child: DropdownButtonFormField<String>(
              value: _yearEndAction,
              items: [for (final a in _yearEndActions) DropdownMenuItem(value: a, child: Text(a.replaceAll('_', ' ')))],
              onChanged: _submitting ? null : (v) => setState(() => _yearEndAction = v ?? _yearEndAction),
            ),
          ),
          const SizedBox(height: 8),
          SwitchListTile(contentPadding: EdgeInsets.zero, title: const Text('Allow negative balance'), value: _allowNegativeBalance, onChanged: _submitting ? null : (v) => setState(() => _allowNegativeBalance = v)),
          if (_allowNegativeBalance) ...[
            const SizedBox(height: 8),
            AuthFormField(label: 'Negative balance floor', required: true, child: TextField(controller: _negativeBalanceFloor, enabled: !_submitting, keyboardType: TextInputType.number)),
          ],
          const SizedBox(height: 20),
          PrimaryButton(label: 'Create draft', loading: _submitting, onPressed: _submit),
        ],
      ),
    );
  }
}
