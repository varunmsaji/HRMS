import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../core/api/api_error.dart';
import '../../../core/widgets/async_list_screen.dart';
import '../../auth/presentation/widgets/auth_form_field.dart';
import '../data/attendance_repository.dart';

/// Overtime records are system-generated from attendance calculation — no
/// create action, only review.
class OvertimeScreen extends ConsumerStatefulWidget {
  const OvertimeScreen({super.key});

  @override
  ConsumerState<OvertimeScreen> createState() => _OvertimeScreenState();
}

class _OvertimeScreenState extends ConsumerState<OvertimeScreen> {
  final _listKey = GlobalKey<AsyncListScreenState<OvertimeRecord>>();

  Future<void> _review(OvertimeRecord record, {required bool approve}) async {
    final commentController = TextEditingController();
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (context) => AlertDialog(
        title: Text(approve ? 'Approve overtime' : 'Reject overtime'),
        content: AuthFormField(
          label: approve ? 'Comment' : 'Reason',
          description: 'Optional',
          child: TextField(controller: commentController, maxLines: 3),
        ),
        actions: [
          TextButton(onPressed: () => Navigator.of(context).pop(false), child: const Text('Cancel')),
          FilledButton(onPressed: () => Navigator.of(context).pop(true), child: Text(approve ? 'Approve' : 'Reject')),
        ],
      ),
    );
    if (confirmed != true) return;
    try {
      final repository = ref.read(attendanceRepositoryProvider);
      if (approve) {
        await repository.approveOvertime(record.id, ifMatch: record.version.toString(), comment: commentController.text.trim());
      } else {
        await repository.rejectOvertime(record.id, ifMatch: record.version.toString(), reason: commentController.text.trim());
      }
      _listKey.currentState?.reload();
    } catch (error) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(error is ApiError ? error.message : 'Something went wrong.')));
      }
    }
  }

  @override
  Widget build(BuildContext context) {
    return AsyncListScreen<OvertimeRecord>(
      key: _listKey,
      title: 'Overtime',
      fetch: () => ref.read(attendanceRepositoryProvider).listOvertimeRecords(),
      emptyLabel: 'No overtime records yet.',
      itemBuilder: (context, record) => ListTile(
        title: Text('${record.attendanceDate} · ${record.minutesDetected} min detected'),
        subtitle: Text([record.status, if (record.minutesApproved != null) '${record.minutesApproved} min approved'].join(' · ')),
        trailing: record.status == 'SUBMITTED'
            ? Row(mainAxisSize: MainAxisSize.min, children: [
                IconButton(icon: const Icon(Icons.check, color: Colors.green), onPressed: () => _review(record, approve: true)),
                IconButton(icon: const Icon(Icons.close, color: Colors.red), onPressed: () => _review(record, approve: false)),
              ])
            : null,
      ),
    );
  }
}
