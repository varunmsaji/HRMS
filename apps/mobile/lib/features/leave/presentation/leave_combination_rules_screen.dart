import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../core/api/api_error.dart';
import '../../../core/widgets/async_list_screen.dart';
import '../../auth/presentation/widgets/auth_form_field.dart';
import '../data/leave_repository.dart';
import 'leave_types_screen.dart' show leaveRepositoryProvider;

class LeaveCombinationRulesScreen extends ConsumerStatefulWidget {
  const LeaveCombinationRulesScreen({super.key});

  @override
  ConsumerState<LeaveCombinationRulesScreen> createState() => _LeaveCombinationRulesScreenState();
}

class _LeaveCombinationRulesScreenState extends ConsumerState<LeaveCombinationRulesScreen> {
  final _listKey = GlobalKey<AsyncListScreenState<LeaveCombinationRule>>();
  List<LeaveType> _types = const [];

  Future<List<LeaveType>> _loadTypes() async {
    _types = await ref.read(leaveRepositoryProvider).listLeaveTypes();
    return _types;
  }

  String _typeName(String id) => _types.firstWhere((t) => t.id == id, orElse: () => LeaveType(id: id, code: id, name: id, isPaidDefault: true, requiresBalance: true, isCompOff: false, isActive: true, version: 1)).name;

  Future<void> _create() async {
    if (_types.isEmpty) await _loadTypes();
    if (_types.length < 2) {
      if (mounted) ScaffoldMessenger.of(context).showSnackBar(const SnackBar(content: Text('Need at least two leave types.')));
      return;
    }
    if (!mounted) return;
    String typeA = _types[0].id;
    String typeB = _types[1].id;
    bool allowed = false;
    final reasonController = TextEditingController();
    final created = await showDialog<bool>(
      context: context,
      builder: (context) => StatefulBuilder(
        builder: (context, setState) => AlertDialog(
          title: const Text('New combination rule'),
          content: Column(mainAxisSize: MainAxisSize.min, children: [
            AuthFormField(
              label: 'Leave type A',
              child: DropdownButtonFormField<String>(
                value: typeA,
                items: [for (final t in _types) DropdownMenuItem(value: t.id, child: Text(t.name))],
                onChanged: (v) => setState(() => typeA = v ?? typeA),
              ),
            ),
            const SizedBox(height: 12),
            AuthFormField(
              label: 'Leave type B',
              child: DropdownButtonFormField<String>(
                value: typeB,
                items: [for (final t in _types) DropdownMenuItem(value: t.id, child: Text(t.name))],
                onChanged: (v) => setState(() => typeB = v ?? typeB),
              ),
            ),
            SwitchListTile(contentPadding: EdgeInsets.zero, title: const Text('Allowed together'), value: allowed, onChanged: (v) => setState(() => allowed = v)),
            AuthFormField(label: 'Reason', description: 'Optional', child: TextField(controller: reasonController)),
          ]),
          actions: [
            TextButton(onPressed: () => Navigator.of(context).pop(false), child: const Text('Cancel')),
            FilledButton(
              onPressed: () async {
                if (typeA == typeB) return;
                try {
                  await ref.read(leaveRepositoryProvider).createCombinationRule({
                    'leave_type_id_a': typeA,
                    'leave_type_id_b': typeB,
                    'allowed': allowed,
                    if (reasonController.text.trim().isNotEmpty) 'reason': reasonController.text.trim(),
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
      ),
    );
    if (created == true) _listKey.currentState?.reload();
  }

  @override
  Widget build(BuildContext context) {
    return AsyncListScreen<LeaveCombinationRule>(
      key: _listKey,
      title: 'Leave Combination Rules',
      fetch: () async {
        await _loadTypes();
        return ref.read(leaveRepositoryProvider).listCombinationRules();
      },
      createLabel: 'New rule',
      onCreate: _create,
      emptyLabel: 'No combination rules yet — any pair is allowed by default.',
      itemBuilder: (context, rule) => ListTile(
        title: Text('${_typeName(rule.leaveTypeIdA)} + ${_typeName(rule.leaveTypeIdB)}'),
        subtitle: Text([rule.allowed ? 'Allowed' : 'Not allowed', if (rule.reason != null) rule.reason!].join(' · ')),
        trailing: IconButton(
          icon: const Icon(Icons.delete_outline),
          onPressed: () async {
            try {
              await ref.read(leaveRepositoryProvider).deleteCombinationRule(rule.id);
              _listKey.currentState?.reload();
            } catch (error) {
              if (mounted) ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(error is ApiError ? error.message : 'Something went wrong.')));
            }
          },
        ),
      ),
    );
  }
}
