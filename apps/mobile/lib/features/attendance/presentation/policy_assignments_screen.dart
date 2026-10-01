import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../core/api/api_error.dart';
import '../../../core/widgets/async_list_screen.dart';
import '../../auth/presentation/widgets/auth_form_field.dart';
import '../data/attendance_repository.dart';
import 'holiday_calendars_screen.dart' show attendanceRepositoryProvider;

const _policyKinds = ['WORK_CALENDAR', 'WEEKLY_OFF', 'ATTENDANCE_POLICY', 'OVERTIME_POLICY', 'REGULARIZATION_POLICY'];
const _scopeTypes = ['COMPANY', 'LEGAL_ENTITY', 'BRANCH', 'DEPARTMENT', 'GRADE', 'DESIGNATION', 'SHIFT', 'EMPLOYEE'];

class PolicyAssignmentsScreen extends ConsumerStatefulWidget {
  const PolicyAssignmentsScreen({super.key});

  @override
  ConsumerState<PolicyAssignmentsScreen> createState() => _PolicyAssignmentsScreenState();
}

class _PolicyAssignmentsScreenState extends ConsumerState<PolicyAssignmentsScreen> {
  final _listKey = GlobalKey<AsyncListScreenState<PolicyAssignment>>();

  Future<void> _create() async {
    final changed = await Navigator.of(context).push<bool>(MaterialPageRoute(builder: (_) => const _PolicyAssignmentFormScreen()));
    if (changed == true) _listKey.currentState?.reload();
  }

  @override
  Widget build(BuildContext context) {
    return AsyncListScreen<PolicyAssignment>(
      key: _listKey,
      title: 'Policy Assignments',
      fetch: () => ref.read(attendanceRepositoryProvider).listPolicyAssignments(),
      createLabel: 'New assignment',
      onCreate: _create,
      emptyLabel: 'No policy assignments yet.',
      itemBuilder: (context, assignment) => ListTile(
        title: Text(assignment.policyKind.replaceAll('_', ' ')),
        subtitle: Text('${assignment.scopeType}${assignment.scopeId != null ? ' · ${assignment.scopeId}' : ''} · from ${assignment.effectiveFrom}'),
      ),
    );
  }
}

class _PolicyAssignmentFormScreen extends ConsumerStatefulWidget {
  const _PolicyAssignmentFormScreen();

  @override
  ConsumerState<_PolicyAssignmentFormScreen> createState() => _PolicyAssignmentFormScreenState();
}

class _PolicyAssignmentFormScreenState extends ConsumerState<_PolicyAssignmentFormScreen> {
  final _policyId = TextEditingController();
  final _scopeId = TextEditingController();
  final _effectiveFrom = TextEditingController();
  final _reason = TextEditingController();
  String _policyKind = _policyKinds.first;
  String _scopeType = 'COMPANY';
  bool _submitting = false;
  String? _formError;

  Future<void> _submit() async {
    if (_policyId.text.trim().isEmpty || DateTime.tryParse(_effectiveFrom.text.trim()) == null) {
      setState(() => _formError = 'Policy ID and a valid effective-from date are required.');
      return;
    }
    setState(() {
      _submitting = true;
      _formError = null;
    });
    try {
      await ref.read(attendanceRepositoryProvider).createPolicyAssignment({
        'policy_kind': _policyKind,
        'policy_id': _policyId.text.trim(),
        'scope_type': _scopeType,
        if (_scopeType != 'COMPANY' && _scopeId.text.trim().isNotEmpty) 'scope_id': _scopeId.text.trim(),
        'effective_from': _effectiveFrom.text.trim(),
        if (_reason.text.trim().isNotEmpty) 'reason': _reason.text.trim(),
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
      appBar: AppBar(title: const Text('New policy assignment')),
      body: ListView(
        padding: const EdgeInsets.all(16),
        children: [
          if (_formError != null) ...[InlineAlert(message: _formError!), const SizedBox(height: 16)],
          AuthFormField(
            label: 'Policy kind',
            child: DropdownButtonFormField<String>(
              value: _policyKind,
              items: [for (final k in _policyKinds) DropdownMenuItem(value: k, child: Text(k.replaceAll('_', ' ')))],
              onChanged: _submitting ? null : (v) => setState(() => _policyKind = v ?? _policyKind),
            ),
          ),
          const SizedBox(height: 16),
          AuthFormField(label: 'Policy ID', required: true, description: 'The policy or calendar\'s ID', child: TextField(controller: _policyId, enabled: !_submitting)),
          const SizedBox(height: 16),
          AuthFormField(
            label: 'Scope type',
            child: DropdownButtonFormField<String>(
              value: _scopeType,
              items: [for (final s in _scopeTypes) DropdownMenuItem(value: s, child: Text(s.replaceAll('_', ' ')))],
              onChanged: _submitting ? null : (v) => setState(() => _scopeType = v ?? _scopeType),
            ),
          ),
          if (_scopeType != 'COMPANY') ...[
            const SizedBox(height: 16),
            AuthFormField(label: 'Scope ID', required: true, child: TextField(controller: _scopeId, enabled: !_submitting)),
          ],
          const SizedBox(height: 16),
          AuthFormField(label: 'Effective from', required: true, description: 'YYYY-MM-DD', child: TextField(controller: _effectiveFrom, enabled: !_submitting)),
          const SizedBox(height: 16),
          AuthFormField(label: 'Reason', description: 'Optional', child: TextField(controller: _reason, enabled: !_submitting)),
          const SizedBox(height: 20),
          PrimaryButton(label: 'Create', loading: _submitting, onPressed: _submit),
        ],
      ),
    );
  }
}
