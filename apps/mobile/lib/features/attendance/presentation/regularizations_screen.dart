import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../core/api/api_error.dart';
import '../../../core/widgets/async_list_screen.dart';
import '../../auth/presentation/widgets/auth_form_field.dart';
import '../../auth/state/auth_controller.dart';
import '../data/attendance_repository.dart';

class RegularizationsScreen extends ConsumerStatefulWidget {
  const RegularizationsScreen({super.key});

  @override
  ConsumerState<RegularizationsScreen> createState() => _RegularizationsScreenState();
}

class _RegularizationsScreenState extends ConsumerState<RegularizationsScreen> {
  final _listKey = GlobalKey<AsyncListScreenState<RegularizationRequest>>();

  Future<void> _submit() async {
    final changed = await Navigator.of(context).push<bool>(MaterialPageRoute(builder: (_) => const _RegularizationFormScreen()));
    if (changed == true) _listKey.currentState?.reload();
  }

  Future<void> _review(RegularizationRequest request, {required bool approve}) async {
    final commentController = TextEditingController();
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (context) => AlertDialog(
        title: Text(approve ? 'Approve request' : 'Reject request'),
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
        await repository.approveRegularization(request.id, ifMatch: request.version.toString(), comment: commentController.text.trim());
      } else {
        await repository.rejectRegularization(request.id, ifMatch: request.version.toString(), reason: commentController.text.trim());
      }
      _listKey.currentState?.reload();
    } catch (error) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(error is ApiError ? error.message : 'Something went wrong.')));
      }
    }
  }

  Future<void> _cancel(RegularizationRequest request) async {
    try {
      await ref.read(attendanceRepositoryProvider).cancelRegularization(request.id, ifMatch: request.version.toString());
      _listKey.currentState?.reload();
    } catch (error) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(error is ApiError ? error.message : 'Something went wrong.')));
      }
    }
  }

  @override
  Widget build(BuildContext context) {
    final myEmployeeId = ref.watch(authControllerProvider).user?.employeeId;
    return AsyncListScreen<RegularizationRequest>(
      key: _listKey,
      title: 'Regularizations',
      fetch: () => ref.read(attendanceRepositoryProvider).listRegularizations(),
      createLabel: 'New request',
      onCreate: _submit,
      emptyLabel: 'No regularization requests yet.',
      itemBuilder: (context, request) {
        final canReview = request.status == 'SUBMITTED' && request.employeeId != myEmployeeId;
        final canCancel = request.status == 'SUBMITTED' && request.employeeId == myEmployeeId;
        return ListTile(
          title: Text('${request.attendanceDate} · ${request.requestType}'),
          subtitle: Text([request.status, if (request.reason != null) request.reason!].join(' · ')),
          trailing: canReview
              ? Row(mainAxisSize: MainAxisSize.min, children: [
                  IconButton(icon: const Icon(Icons.check, color: Colors.green), onPressed: () => _review(request, approve: true)),
                  IconButton(icon: const Icon(Icons.close, color: Colors.red), onPressed: () => _review(request, approve: false)),
                ])
              : canCancel
                  ? TextButton(onPressed: () => _cancel(request), child: const Text('Cancel'))
                  : null,
        );
      },
    );
  }
}

class _RegularizationFormScreen extends ConsumerStatefulWidget {
  const _RegularizationFormScreen();

  @override
  ConsumerState<_RegularizationFormScreen> createState() => _RegularizationFormScreenState();
}

class _RegularizationFormScreenState extends ConsumerState<_RegularizationFormScreen> {
  final _date = TextEditingController();
  final _reason = TextEditingController();
  final _requestedInTime = TextEditingController();
  final _requestedOutTime = TextEditingController();
  String _requestType = 'MISSING_PUNCH';
  bool _submitting = false;
  String? _formError;

  Future<void> _submit() async {
    final date = DateTime.tryParse(_date.text.trim());
    if (date == null) {
      setState(() => _formError = 'Enter a valid date (YYYY-MM-DD).');
      return;
    }
    final punches = <Map<String, dynamic>>[];
    if (_requestedInTime.text.trim().isNotEmpty) {
      punches.add({'direction': 'IN', 'requested_time': '${_date.text.trim()}T${_requestedInTime.text.trim()}:00'});
    }
    if (_requestedOutTime.text.trim().isNotEmpty) {
      punches.add({'direction': 'OUT', 'requested_time': '${_date.text.trim()}T${_requestedOutTime.text.trim()}:00'});
    }
    if (punches.isEmpty) {
      setState(() => _formError = 'Enter at least one requested punch time.');
      return;
    }
    setState(() {
      _submitting = true;
      _formError = null;
    });
    try {
      await ref.read(attendanceRepositoryProvider).submitRegularization({
        'attendance_date': _date.text.trim(),
        'request_type': _requestType,
        if (_reason.text.trim().isNotEmpty) 'reason': _reason.text.trim(),
        'requested_punches': punches,
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
      appBar: AppBar(title: const Text('New regularization request')),
      body: ListView(
        padding: const EdgeInsets.all(16),
        children: [
          if (_formError != null) ...[InlineAlert(message: _formError!), const SizedBox(height: 16)],
          AuthFormField(label: 'Date', required: true, description: 'YYYY-MM-DD', child: TextField(controller: _date, enabled: !_submitting)),
          const SizedBox(height: 16),
          AuthFormField(
            label: 'Type',
            child: DropdownButtonFormField<String>(
              value: _requestType,
              items: const [
                DropdownMenuItem(value: 'MISSING_PUNCH', child: Text('Missing punch')),
                DropdownMenuItem(value: 'WRONG_PUNCH', child: Text('Wrong punch')),
                DropdownMenuItem(value: 'FORGOT_TO_APPLY_WFH', child: Text('Forgot to apply WFH')),
                DropdownMenuItem(value: 'ON_DUTY', child: Text('On duty')),
              ],
              onChanged: _submitting ? null : (v) => setState(() => _requestType = v ?? _requestType),
            ),
          ),
          const SizedBox(height: 16),
          Row(children: [
            Expanded(child: AuthFormField(label: 'Requested in', description: 'HH:MM, optional', child: TextField(controller: _requestedInTime, enabled: !_submitting))),
            const SizedBox(width: 12),
            Expanded(child: AuthFormField(label: 'Requested out', description: 'HH:MM, optional', child: TextField(controller: _requestedOutTime, enabled: !_submitting))),
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
