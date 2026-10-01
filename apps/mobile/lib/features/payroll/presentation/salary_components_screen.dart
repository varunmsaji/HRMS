import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../core/api/api_error.dart';
import '../../../core/widgets/async_list_screen.dart';
import '../../auth/presentation/widgets/auth_form_field.dart';
import '../data/payroll_repository.dart';
import 'pay_runs_screen.dart' show payrollRepositoryProvider;

const _componentTypes = ['EARNING', 'DEDUCTION', 'EMPLOYER_CONTRIBUTION', 'REIMBURSEMENT'];

class SalaryComponentsScreen extends ConsumerStatefulWidget {
  const SalaryComponentsScreen({super.key});

  @override
  ConsumerState<SalaryComponentsScreen> createState() => _SalaryComponentsScreenState();
}

class _SalaryComponentsScreenState extends ConsumerState<SalaryComponentsScreen> {
  final _listKey = GlobalKey<AsyncListScreenState<SalaryComponent>>();

  Future<void> _create() async {
    final codeController = TextEditingController();
    final nameController = TextEditingController();
    String componentType = _componentTypes.first;
    final created = await showDialog<bool>(
      context: context,
      builder: (context) => StatefulBuilder(
        builder: (context, setState) => AlertDialog(
          title: const Text('New salary component'),
          content: Column(mainAxisSize: MainAxisSize.min, children: [
            AuthFormField(label: 'Code', required: true, description: 'Uppercase letters/digits/underscore', child: TextField(controller: codeController, textCapitalization: TextCapitalization.characters)),
            const SizedBox(height: 12),
            AuthFormField(label: 'Name', required: true, child: TextField(controller: nameController)),
            const SizedBox(height: 12),
            AuthFormField(
              label: 'Type',
              child: DropdownButtonFormField<String>(
                value: componentType,
                items: [for (final t in _componentTypes) DropdownMenuItem(value: t, child: Text(t.replaceAll('_', ' ')))],
                onChanged: (v) => setState(() => componentType = v ?? componentType),
              ),
            ),
          ]),
          actions: [
            TextButton(onPressed: () => Navigator.of(context).pop(false), child: const Text('Cancel')),
            FilledButton(
              onPressed: () async {
                if (codeController.text.trim().isEmpty || nameController.text.trim().isEmpty) return;
                try {
                  await ref.read(payrollRepositoryProvider).createSalaryComponent({
                    'code': codeController.text.trim().toUpperCase(),
                    'name': nameController.text.trim(),
                    'component_type': componentType,
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
    return AsyncListScreen<SalaryComponent>(
      key: _listKey,
      title: 'Salary Components',
      fetch: () => ref.read(payrollRepositoryProvider).listSalaryComponents(),
      createLabel: 'New component',
      onCreate: _create,
      emptyLabel: 'No salary components yet.',
      itemBuilder: (context, component) => ListTile(
        title: Text('${component.name} (${component.code})'),
        subtitle: Text([component.componentType.replaceAll('_', ' '), if (!component.isActive) 'Inactive'].join(' · ')),
      ),
    );
  }
}
