import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../core/api/api_error.dart';
import '../../../core/widgets/async_list_screen.dart';
import '../../auth/presentation/widgets/auth_form_field.dart';
import '../data/attendance_repository.dart';
import 'holiday_calendars_screen.dart' show attendanceRepositoryProvider;

class AttendancePeriodsScreen extends ConsumerStatefulWidget {
  const AttendancePeriodsScreen({super.key});

  @override
  ConsumerState<AttendancePeriodsScreen> createState() => _AttendancePeriodsScreenState();
}

class _AttendancePeriodsScreenState extends ConsumerState<AttendancePeriodsScreen> {
  final _listKey = GlobalKey<AsyncListScreenState<AttendancePeriod>>();

  Future<void> _create() async {
    final monthController = TextEditingController();
    final legalEntityIdController = TextEditingController();
    final created = await showDialog<bool>(
      context: context,
      builder: (context) => AlertDialog(
        title: const Text('Open attendance period'),
        content: Column(mainAxisSize: MainAxisSize.min, children: [
          AuthFormField(label: 'Legal entity ID', required: true, child: TextField(controller: legalEntityIdController)),
          const SizedBox(height: 12),
          AuthFormField(label: 'Month', required: true, description: 'YYYY-MM', child: TextField(controller: monthController)),
        ]),
        actions: [
          TextButton(onPressed: () => Navigator.of(context).pop(false), child: const Text('Cancel')),
          FilledButton(
            onPressed: () async {
              if (monthController.text.trim().isEmpty || legalEntityIdController.text.trim().isEmpty) return;
              try {
                await ref.read(attendanceRepositoryProvider).createAttendancePeriod({
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
            child: const Text('Open'),
          ),
        ],
      ),
    );
    if (created == true) _listKey.currentState?.reload();
  }

  @override
  Widget build(BuildContext context) {
    return AsyncListScreen<AttendancePeriod>(
      key: _listKey,
      title: 'Attendance Periods',
      fetch: () => ref.read(attendanceRepositoryProvider).listAttendancePeriods(),
      createLabel: 'Open period',
      onCreate: _create,
      emptyLabel: 'No attendance periods yet.',
      itemBuilder: (context, period) => ListTile(
        title: Text(period.label ?? '${period.periodStart} – ${period.periodEnd}'),
        subtitle: Text(period.status),
        trailing: const Icon(Icons.chevron_right, size: 20),
        onTap: () async {
          await Navigator.of(context).push(MaterialPageRoute(builder: (_) => AttendancePeriodDetailScreen(period: period)));
          _listKey.currentState?.reload();
        },
      ),
    );
  }
}

class AttendancePeriodDetailScreen extends ConsumerStatefulWidget {
  const AttendancePeriodDetailScreen({super.key, required this.period});
  final AttendancePeriod period;

  @override
  ConsumerState<AttendancePeriodDetailScreen> createState() => _AttendancePeriodDetailScreenState();
}

class _AttendancePeriodDetailScreenState extends ConsumerState<AttendancePeriodDetailScreen> {
  Map<String, dynamic>? _validation;
  bool _busy = false;
  String? _message;

  Future<void> _validate() async {
    setState(() => _busy = true);
    try {
      final result = await ref.read(attendanceRepositoryProvider).validateAttendancePeriod(widget.period.id);
      setState(() => _validation = result);
    } catch (error) {
      setState(() => _message = error is ApiError ? error.message : 'Something went wrong.');
    } finally {
      setState(() => _busy = false);
    }
  }

  Future<void> _finalize() async {
    setState(() => _busy = true);
    try {
      await ref.read(attendanceRepositoryProvider).finalizeAttendancePeriod(widget.period.id, ifMatch: widget.period.version.toString());
      if (mounted) setState(() => _message = 'Period finalized.');
    } catch (error) {
      setState(() => _message = error is ApiError ? error.message : 'Something went wrong.');
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  Future<void> _reopen() async {
    final reasonController = TextEditingController();
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (context) => AlertDialog(
        title: const Text('Reopen period'),
        content: AuthFormField(label: 'Reason', required: true, child: TextField(controller: reasonController)),
        actions: [
          TextButton(onPressed: () => Navigator.of(context).pop(false), child: const Text('Cancel')),
          FilledButton(onPressed: () => Navigator.of(context).pop(true), child: const Text('Reopen')),
        ],
      ),
    );
    if (confirmed != true || reasonController.text.trim().isEmpty) return;
    setState(() => _busy = true);
    try {
      await ref.read(attendanceRepositoryProvider).reopenAttendancePeriod(
            widget.period.id,
            ifMatch: widget.period.version.toString(),
            reason: reasonController.text.trim(),
          );
      if (mounted) setState(() => _message = 'Period reopened.');
    } catch (error) {
      setState(() => _message = error is ApiError ? error.message : 'Something went wrong.');
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final scheme = Theme.of(context).colorScheme;
    final validation = _validation;
    return Scaffold(
      appBar: AppBar(title: Text(widget.period.label ?? widget.period.periodStart)),
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
                Text('${widget.period.periodStart} – ${widget.period.periodEnd}', style: Theme.of(context).textTheme.headlineSmall),
                const SizedBox(height: 4),
                Text('Status: ${widget.period.status}', style: TextStyle(color: scheme.onSurfaceVariant)),
              ],
            ),
          ),
          const SizedBox(height: 16),
          if (widget.period.status == 'OPEN') ...[
            FilledButton.tonal(onPressed: _busy ? null : _validate, child: const Text('Validate')),
            if (validation != null) ...[
              const SizedBox(height: 12),
              Text('Validation: ${validation['status']}', style: const TextStyle(fontWeight: FontWeight.w600)),
              for (final reason in (validation['reasons'] as List? ?? []))
                Padding(
                  padding: const EdgeInsets.only(top: 4),
                  child: Text('${reason['message']} (${reason['count']})'),
                ),
              const SizedBox(height: 12),
              if (validation['status'] == 'READY')
                FilledButton(onPressed: _busy ? null : _finalize, child: const Text('Finalize')),
            ],
          ] else if (widget.period.status == 'CLOSED')
            OutlinedButton(onPressed: _busy ? null : _reopen, child: const Text('Reopen')),
        ],
      ),
    );
  }
}
