import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../core/api/api_error.dart';
import '../../../core/widgets/async_list_screen.dart';
import '../../auth/presentation/widgets/auth_form_field.dart';
import '../data/payroll_repository.dart';
import 'pay_runs_screen.dart' show payrollRepositoryProvider;

/// Identity CRUD only — a structure's versions/lines editor (component
/// percentages/amounts, up to 50 lines) is a separate, deeper build; this
/// screen creates the structure (and its first draft version, empty) and
/// lists what exists.
class SalaryStructuresScreen extends ConsumerStatefulWidget {
  const SalaryStructuresScreen({super.key});

  @override
  ConsumerState<SalaryStructuresScreen> createState() => _SalaryStructuresScreenState();
}

class _SalaryStructuresScreenState extends ConsumerState<SalaryStructuresScreen> {
  final _listKey = GlobalKey<AsyncListScreenState<SalaryStructure>>();

  Future<void> _create() async {
    final codeController = TextEditingController();
    final nameController = TextEditingController();
    final descriptionController = TextEditingController();
    final created = await showDialog<bool>(
      context: context,
      builder: (context) => AlertDialog(
        title: const Text('New salary structure'),
        content: Column(mainAxisSize: MainAxisSize.min, children: [
          AuthFormField(label: 'Code', required: true, child: TextField(controller: codeController)),
          const SizedBox(height: 12),
          AuthFormField(label: 'Name', required: true, child: TextField(controller: nameController)),
          const SizedBox(height: 12),
          AuthFormField(label: 'Description', description: 'Optional', child: TextField(controller: descriptionController)),
        ]),
        actions: [
          TextButton(onPressed: () => Navigator.of(context).pop(false), child: const Text('Cancel')),
          FilledButton(
            onPressed: () async {
              if (codeController.text.trim().isEmpty || nameController.text.trim().isEmpty) return;
              try {
                await ref.read(payrollRepositoryProvider).createSalaryStructure({
                  'code': codeController.text.trim(),
                  'name': nameController.text.trim(),
                  if (descriptionController.text.trim().isNotEmpty) 'description': descriptionController.text.trim(),
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
    return AsyncListScreen<SalaryStructure>(
      key: _listKey,
      title: 'Salary Structures',
      fetch: () => ref.read(payrollRepositoryProvider).listSalaryStructures(),
      createLabel: 'New structure',
      onCreate: _create,
      emptyLabel: 'No salary structures yet.',
      itemBuilder: (context, structure) => ListTile(
        title: Text('${structure.name} (${structure.code})'),
        subtitle: structure.description == null ? null : Text(structure.description!),
      ),
    );
  }
}
