import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../core/api/api_error.dart';
import '../../../core/widgets/async_list_screen.dart';
import '../../auth/presentation/widgets/auth_form_field.dart';
import '../data/leave_repository.dart';
import 'leave_types_screen.dart' show leaveRepositoryProvider;

const _leaveCategories = ['EARNED', 'SICK', 'CASUAL', 'MATERNITY', 'PATERNITY'];

class StatutoryLeaveMinimumsScreen extends ConsumerStatefulWidget {
  const StatutoryLeaveMinimumsScreen({super.key});

  @override
  ConsumerState<StatutoryLeaveMinimumsScreen> createState() => _StatutoryLeaveMinimumsScreenState();
}

class _StatutoryLeaveMinimumsScreenState extends ConsumerState<StatutoryLeaveMinimumsScreen> {
  final _listKey = GlobalKey<AsyncListScreenState<StatutoryLeaveMinimum>>();

  Future<void> _create() async {
    String category = _leaveCategories.first;
    final stateController = TextEditingController();
    final minDaysController = TextEditingController();
    final noteController = TextEditingController();
    final created = await showDialog<bool>(
      context: context,
      builder: (context) => StatefulBuilder(
        builder: (context, setState) => AlertDialog(
          title: const Text('New statutory minimum'),
          content: Column(mainAxisSize: MainAxisSize.min, children: [
            AuthFormField(
              label: 'Leave category',
              child: DropdownButtonFormField<String>(
                value: category,
                items: [for (final c in _leaveCategories) DropdownMenuItem(value: c, child: Text(c))],
                onChanged: (v) => setState(() => category = v ?? category),
              ),
            ),
            const SizedBox(height: 12),
            AuthFormField(label: 'Minimum days/year', required: true, child: TextField(controller: minDaysController, keyboardType: TextInputType.number)),
            const SizedBox(height: 12),
            AuthFormField(label: 'State code', description: 'Optional — blank applies everywhere', child: TextField(controller: stateController)),
            const SizedBox(height: 12),
            AuthFormField(label: 'Note', description: 'Optional', child: TextField(controller: noteController)),
          ]),
          actions: [
            TextButton(onPressed: () => Navigator.of(context).pop(false), child: const Text('Cancel')),
            FilledButton(
              onPressed: () async {
                final minDays = num.tryParse(minDaysController.text.trim());
                if (minDays == null || minDays <= 0) return;
                try {
                  await ref.read(leaveRepositoryProvider).createStatutoryMinimum({
                    'leave_category': category,
                    'min_days_per_year': minDays,
                    if (stateController.text.trim().isNotEmpty) 'state_code': stateController.text.trim(),
                    if (noteController.text.trim().isNotEmpty) 'note': noteController.text.trim(),
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
    return AsyncListScreen<StatutoryLeaveMinimum>(
      key: _listKey,
      title: 'Statutory Minimums',
      fetch: () => ref.read(leaveRepositoryProvider).listStatutoryMinimums(),
      createLabel: 'New minimum',
      onCreate: _create,
      emptyLabel: 'No statutory minimums configured.',
      itemBuilder: (context, minimum) => ListTile(
        title: Text('${minimum.leaveCategory} · ${minimum.minDaysPerYear} days/year'),
        subtitle: Text([minimum.stateCode ?? 'All states', if (minimum.note != null) minimum.note!].join(' · ')),
        trailing: IconButton(
          icon: const Icon(Icons.delete_outline),
          onPressed: () async {
            try {
              await ref.read(leaveRepositoryProvider).deleteStatutoryMinimum(minimum.id);
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
