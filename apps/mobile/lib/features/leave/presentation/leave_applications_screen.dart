import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../core/api/api_error.dart';
import '../../../core/widgets/async_list_screen.dart';
import '../../auth/presentation/widgets/auth_form_field.dart';
import '../../auth/state/auth_controller.dart';
import '../../shell/more_action.dart';
import '../data/leave_repository.dart';
import 'leave_types_screen.dart' show leaveRepositoryProvider;

/// Mirrors `apps/web/src/app/app/leave-applications/page.tsx` — the "Leave"
/// bottom-nav tab. Lists whatever's in the caller's data scope (own
/// applications for an employee, or the full team for a manager/HR) and
/// exposes submit/approve/reject/cancel.
class LeaveApplicationsScreen extends ConsumerStatefulWidget {
  const LeaveApplicationsScreen({super.key});

  @override
  ConsumerState<LeaveApplicationsScreen> createState() => _LeaveApplicationsScreenState();
}

class _LeaveApplicationsScreenState extends ConsumerState<LeaveApplicationsScreen> {
  final _listKey = GlobalKey<AsyncListScreenState<LeaveApplication>>();
  List<LeaveType> _types = const [];

  String _typeName(String id) =>
      _types.firstWhere((t) => t.id == id, orElse: () => LeaveType(id: id, code: id, name: id, isPaidDefault: true, requiresBalance: true, isCompOff: false, isActive: true, version: 1)).name;

  Future<void> _submit() async {
    final changed = await Navigator.of(context).push<bool>(MaterialPageRoute(builder: (_) => const _LeaveApplicationFormScreen()));
    if (changed == true) _listKey.currentState?.reload();
  }

  Future<void> _review(LeaveApplication application, {required bool approve}) async {
    final commentController = TextEditingController();
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (context) => AlertDialog(
        title: Text(approve ? 'Approve leave' : 'Reject leave'),
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
      final repository = ref.read(leaveRepositoryProvider);
      if (approve) {
        await repository.approveLeaveApplication(application.id, ifMatch: application.version.toString(), comment: commentController.text.trim());
      } else {
        await repository.rejectLeaveApplication(application.id, ifMatch: application.version.toString(), reason: commentController.text.trim());
      }
      _listKey.currentState?.reload();
    } catch (error) {
      if (mounted) ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(error is ApiError ? error.message : 'Something went wrong.')));
    }
  }

  Future<void> _cancel(LeaveApplication application) async {
    try {
      await ref.read(leaveRepositoryProvider).cancelLeaveApplication(application.id, ifMatch: application.version.toString());
      _listKey.currentState?.reload();
    } catch (error) {
      if (mounted) ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(error is ApiError ? error.message : 'Something went wrong.')));
    }
  }

  @override
  Widget build(BuildContext context) {
    final myEmployeeId = ref.watch(authControllerProvider).user?.employeeId;
    return AsyncListScreen<LeaveApplication>(
      key: _listKey,
      title: 'Leave',
      actions: const [MoreAction()],
      fetch: () async {
        _types = await ref.read(leaveRepositoryProvider).listLeaveTypes();
        return ref.read(leaveRepositoryProvider).listLeaveApplications();
      },
      createLabel: 'Apply',
      onCreate: _submit,
      emptyLabel: 'No leave applications yet.',
      itemBuilder: (context, application) {
        final canReview = application.status == 'SUBMITTED' && application.employeeId != myEmployeeId;
        final canCancel = application.status == 'SUBMITTED' && application.employeeId == myEmployeeId;
        return ListTile(
          title: Text('${_typeName(application.leaveTypeId)} · ${application.startDate} – ${application.endDate}'),
          subtitle: Text([
            application.status,
            if (application.totalDays != null) '${application.totalDays} days',
            if (application.reason != null) application.reason!,
          ].join(' · ')),
          trailing: canReview
              ? Row(mainAxisSize: MainAxisSize.min, children: [
                  IconButton(icon: const Icon(Icons.check, color: Colors.green), onPressed: () => _review(application, approve: true)),
                  IconButton(icon: const Icon(Icons.close, color: Colors.red), onPressed: () => _review(application, approve: false)),
                ])
              : canCancel
                  ? TextButton(onPressed: () => _cancel(application), child: const Text('Cancel'))
                  : null,
        );
      },
    );
  }
}

class _LeaveApplicationFormScreen extends ConsumerStatefulWidget {
  const _LeaveApplicationFormScreen();

  @override
  ConsumerState<_LeaveApplicationFormScreen> createState() => _LeaveApplicationFormScreenState();
}

class _LeaveApplicationFormScreenState extends ConsumerState<_LeaveApplicationFormScreen> {
  final _startDate = TextEditingController();
  final _endDate = TextEditingController();
  final _reason = TextEditingController();
  String? _leaveTypeId;
  bool _submitting = false;
  bool _loadingTypes = true;
  String? _formError;
  List<LeaveType> _types = const [];

  @override
  void initState() {
    super.initState();
    _loadTypes();
  }

  Future<void> _loadTypes() async {
    try {
      final types = await ref.read(leaveRepositoryProvider).listLeaveTypes();
      if (mounted) {
        setState(() {
          _types = types;
          _leaveTypeId = types.isNotEmpty ? types.first.id : null;
        });
      }
    } finally {
      if (mounted) setState(() => _loadingTypes = false);
    }
  }

  Future<void> _submit() async {
    final start = DateTime.tryParse(_startDate.text.trim());
    final end = DateTime.tryParse(_endDate.text.trim());
    if (_leaveTypeId == null || start == null || end == null || end.isBefore(start)) {
      setState(() => _formError = 'Choose a leave type and a valid date range.');
      return;
    }
    setState(() {
      _submitting = true;
      _formError = null;
    });
    try {
      await ref.read(leaveRepositoryProvider).submitLeaveApplication({
        'leave_type_id': _leaveTypeId,
        'start_date': _startDate.text.trim(),
        'end_date': _endDate.text.trim(),
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
      appBar: AppBar(title: const Text('Apply for leave')),
      body: _loadingTypes
          ? const Center(child: CircularProgressIndicator())
          : ListView(
              padding: const EdgeInsets.all(16),
              children: [
                if (_formError != null) ...[InlineAlert(message: _formError!), const SizedBox(height: 16)],
                AuthFormField(
                  label: 'Leave type',
                  required: true,
                  child: DropdownButtonFormField<String>(
                    value: _leaveTypeId,
                    items: [for (final t in _types) DropdownMenuItem(value: t.id, child: Text(t.name))],
                    onChanged: _submitting ? null : (v) => setState(() => _leaveTypeId = v),
                  ),
                ),
                const SizedBox(height: 16),
                Row(children: [
                  Expanded(child: AuthFormField(label: 'Start date', required: true, description: 'YYYY-MM-DD', child: TextField(controller: _startDate, enabled: !_submitting))),
                  const SizedBox(width: 12),
                  Expanded(child: AuthFormField(label: 'End date', required: true, description: 'YYYY-MM-DD', child: TextField(controller: _endDate, enabled: !_submitting))),
                ]),
                const SizedBox(height: 16),
                AuthFormField(label: 'Reason', child: TextField(controller: _reason, enabled: !_submitting, maxLines: 3)),
                const SizedBox(height: 20),
                PrimaryButton(label: 'Submit', loading: _submitting, onPressed: _submit),
              ],
            ),
    );
  }
}
