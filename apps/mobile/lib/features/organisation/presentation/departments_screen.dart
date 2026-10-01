import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../core/api/api_error.dart';
import '../../../core/widgets/async_list_screen.dart';
import '../../auth/presentation/widgets/auth_form_field.dart';
import '../data/organisation_repository.dart';
import 'legal_entities_screen.dart' show organisationRepositoryProvider;

class DepartmentsScreen extends ConsumerStatefulWidget {
  const DepartmentsScreen({super.key});

  @override
  ConsumerState<DepartmentsScreen> createState() => _DepartmentsScreenState();
}

class _DepartmentsScreenState extends ConsumerState<DepartmentsScreen> {
  final _listKey = GlobalKey<AsyncListScreenState<Department>>();

  Future<void> _openForm([Department? entity]) async {
    final changed = await Navigator.of(context).push<bool>(
      MaterialPageRoute(builder: (_) => _DepartmentFormScreen(entity: entity)),
    );
    if (changed == true) _listKey.currentState?.reload();
  }

  @override
  Widget build(BuildContext context) {
    return AsyncListScreen<Department>(
      key: _listKey,
      title: 'Departments',
      fetch: () => ref.read(organisationRepositoryProvider).listDepartments(),
      createLabel: 'New department',
      onCreate: () => _openForm(),
      emptyLabel: 'No departments yet.',
      itemBuilder: (context, dept) => ListTile(
        title: Text(dept.name),
        subtitle: Text([if (dept.code != null) dept.code!, if (!dept.isActive) 'Inactive'].join(' · ')),
        onTap: () => _openForm(dept),
      ),
    );
  }
}

class _DepartmentFormScreen extends ConsumerStatefulWidget {
  const _DepartmentFormScreen({this.entity});
  final Department? entity;

  @override
  ConsumerState<_DepartmentFormScreen> createState() => _DepartmentFormScreenState();
}

class _DepartmentFormScreenState extends ConsumerState<_DepartmentFormScreen> {
  late final _name = TextEditingController(text: widget.entity?.name);
  late final _code = TextEditingController(text: widget.entity?.code);
  String? _branchId;
  String? _parentId;
  bool _isActive = true;
  bool _submitting = false;
  bool _loadingOptions = true;
  String? _formError;
  List<Branch> _branches = const [];
  List<Department> _departments = const [];

  @override
  void initState() {
    super.initState();
    _isActive = widget.entity?.isActive ?? true;
    _branchId = widget.entity?.branchId;
    _parentId = widget.entity?.parentId;
    _loadOptions();
  }

  Future<void> _loadOptions() async {
    try {
      final repository = ref.read(organisationRepositoryProvider);
      final results = await Future.wait([repository.listBranches(), repository.listDepartments()]);
      if (mounted) {
        setState(() {
          _branches = results[0] as List<Branch>;
          _departments = (results[1] as List<Department>).where((d) => d.id != widget.entity?.id).toList();
        });
      }
    } finally {
      if (mounted) setState(() => _loadingOptions = false);
    }
  }

  Future<void> _submit() async {
    if (_name.text.trim().isEmpty) {
      setState(() => _formError = 'Name is required.');
      return;
    }
    setState(() {
      _submitting = true;
      _formError = null;
    });
    final body = {
      'name': _name.text.trim(),
      'code': _code.text.trim().isEmpty ? null : _code.text.trim(),
      'branch_id': _branchId,
      'parent_id': _parentId,
      if (widget.entity != null) 'is_active': _isActive,
    };
    try {
      final repository = ref.read(organisationRepositoryProvider);
      if (widget.entity == null) {
        await repository.createDepartment(body);
      } else {
        await repository.updateDepartment(widget.entity!.id, body, ifMatch: widget.entity!.version.toString());
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
      appBar: AppBar(title: Text(widget.entity == null ? 'New department' : 'Edit department')),
      body: _loadingOptions
          ? const Center(child: CircularProgressIndicator())
          : ListView(
              padding: const EdgeInsets.all(16),
              children: [
                if (_formError != null) ...[InlineAlert(message: _formError!), const SizedBox(height: 16)],
                AuthFormField(label: 'Name', required: true, child: TextField(controller: _name, enabled: !_submitting)),
                const SizedBox(height: 16),
                AuthFormField(label: 'Code', child: TextField(controller: _code, enabled: !_submitting)),
                const SizedBox(height: 16),
                AuthFormField(
                  label: 'Branch',
                  description: 'Optional',
                  child: DropdownButtonFormField<String?>(
                    value: _branchId,
                    items: [
                      const DropdownMenuItem(value: null, child: Text('None')),
                      for (final b in _branches) DropdownMenuItem(value: b.id, child: Text(b.name)),
                    ],
                    onChanged: _submitting ? null : (v) => setState(() => _branchId = v),
                  ),
                ),
                const SizedBox(height: 16),
                AuthFormField(
                  label: 'Parent department',
                  description: 'Optional',
                  child: DropdownButtonFormField<String?>(
                    value: _parentId,
                    items: [
                      const DropdownMenuItem(value: null, child: Text('None')),
                      for (final d in _departments) DropdownMenuItem(value: d.id, child: Text(d.name)),
                    ],
                    onChanged: _submitting ? null : (v) => setState(() => _parentId = v),
                  ),
                ),
                if (widget.entity != null) ...[
                  const SizedBox(height: 16),
                  SwitchListTile(
                    contentPadding: EdgeInsets.zero,
                    title: const Text('Active'),
                    value: _isActive,
                    onChanged: _submitting ? null : (v) => setState(() => _isActive = v),
                  ),
                ],
                const SizedBox(height: 20),
                PrimaryButton(label: widget.entity == null ? 'Create' : 'Save changes', loading: _submitting, onPressed: _submit),
              ],
            ),
    );
  }
}
