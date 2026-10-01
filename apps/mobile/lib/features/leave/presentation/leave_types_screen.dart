import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../core/api/api_error.dart';
import '../../../core/providers.dart';
import '../../../core/widgets/async_list_screen.dart';
import '../../auth/presentation/widgets/auth_form_field.dart';
import '../data/leave_repository.dart';

final leaveRepositoryProvider = Provider<LeaveRepository>((ref) => LeaveRepository(ref.watch(apiClientProvider)));

class LeaveTypesScreen extends ConsumerStatefulWidget {
  const LeaveTypesScreen({super.key});

  @override
  ConsumerState<LeaveTypesScreen> createState() => _LeaveTypesScreenState();
}

class _LeaveTypesScreenState extends ConsumerState<LeaveTypesScreen> {
  final _listKey = GlobalKey<AsyncListScreenState<LeaveType>>();

  Future<void> _openForm([LeaveType? entity]) async {
    final changed = await Navigator.of(context).push<bool>(MaterialPageRoute(builder: (_) => _LeaveTypeFormScreen(entity: entity)));
    if (changed == true) _listKey.currentState?.reload();
  }

  @override
  Widget build(BuildContext context) {
    return AsyncListScreen<LeaveType>(
      key: _listKey,
      title: 'Leave Types',
      fetch: () => ref.read(leaveRepositoryProvider).listLeaveTypes(),
      createLabel: 'New type',
      onCreate: () => _openForm(),
      emptyLabel: 'No leave types yet.',
      itemBuilder: (context, type) => ListTile(
        title: Text('${type.name} (${type.code})'),
        subtitle: Text([
          if (type.isPaidDefault) 'Paid' else 'Unpaid',
          if (!type.requiresBalance) 'No balance tracking',
          if (type.isCompOff) 'Comp-off',
          if (!type.isActive) 'Inactive',
        ].join(' · ')),
        onTap: () => _openForm(type),
      ),
    );
  }
}

class _LeaveTypeFormScreen extends ConsumerStatefulWidget {
  const _LeaveTypeFormScreen({this.entity});
  final LeaveType? entity;

  @override
  ConsumerState<_LeaveTypeFormScreen> createState() => _LeaveTypeFormScreenState();
}

class _LeaveTypeFormScreenState extends ConsumerState<_LeaveTypeFormScreen> {
  late final _code = TextEditingController(text: widget.entity?.code);
  late final _name = TextEditingController(text: widget.entity?.name);
  bool _isPaidDefault = true;
  bool _requiresBalance = true;
  bool _isCompOff = false;
  bool _isActive = true;
  bool _submitting = false;
  String? _formError;

  @override
  void initState() {
    super.initState();
    _isPaidDefault = widget.entity?.isPaidDefault ?? true;
    _requiresBalance = widget.entity?.requiresBalance ?? true;
    _isCompOff = widget.entity?.isCompOff ?? false;
    _isActive = widget.entity?.isActive ?? true;
  }

  Future<void> _submit() async {
    if (_name.text.trim().isEmpty || (widget.entity == null && _code.text.trim().isEmpty)) {
      setState(() => _formError = 'Code and name are required.');
      return;
    }
    setState(() {
      _submitting = true;
      _formError = null;
    });
    final body = {
      if (widget.entity == null) 'code': _code.text.trim(),
      'name': _name.text.trim(),
      'is_paid_default': _isPaidDefault,
      'requires_balance': _requiresBalance,
      'is_comp_off': _isCompOff,
      if (widget.entity != null) 'is_active': _isActive,
    };
    try {
      final repository = ref.read(leaveRepositoryProvider);
      if (widget.entity == null) {
        await repository.createLeaveType(body);
      } else {
        await repository.updateLeaveType(widget.entity!.id, body, ifMatch: widget.entity!.version.toString());
      }
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
      appBar: AppBar(title: Text(widget.entity == null ? 'New leave type' : 'Edit leave type')),
      body: ListView(
        padding: const EdgeInsets.all(16),
        children: [
          if (_formError != null) ...[InlineAlert(message: _formError!), const SizedBox(height: 16)],
          AuthFormField(
            label: 'Code',
            required: true,
            child: TextField(controller: _code, enabled: !_submitting && widget.entity == null),
          ),
          const SizedBox(height: 16),
          AuthFormField(label: 'Name', required: true, child: TextField(controller: _name, enabled: !_submitting)),
          const SizedBox(height: 8),
          SwitchListTile(contentPadding: EdgeInsets.zero, title: const Text('Paid by default'), value: _isPaidDefault, onChanged: _submitting ? null : (v) => setState(() => _isPaidDefault = v)),
          SwitchListTile(contentPadding: EdgeInsets.zero, title: const Text('Tracks a balance'), value: _requiresBalance, onChanged: _submitting ? null : (v) => setState(() => _requiresBalance = v)),
          SwitchListTile(contentPadding: EdgeInsets.zero, title: const Text('Is comp-off'), value: _isCompOff, onChanged: _submitting ? null : (v) => setState(() => _isCompOff = v)),
          if (widget.entity != null)
            SwitchListTile(contentPadding: EdgeInsets.zero, title: const Text('Active'), value: _isActive, onChanged: _submitting ? null : (v) => setState(() => _isActive = v)),
          const SizedBox(height: 12),
          PrimaryButton(label: widget.entity == null ? 'Create' : 'Save changes', loading: _submitting, onPressed: _submit),
        ],
      ),
    );
  }
}
