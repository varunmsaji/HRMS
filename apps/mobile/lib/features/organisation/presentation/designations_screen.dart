import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../core/api/api_error.dart';
import '../../../core/widgets/async_list_screen.dart';
import '../../auth/presentation/widgets/auth_form_field.dart';
import '../data/organisation_repository.dart';
import 'legal_entities_screen.dart' show organisationRepositoryProvider;

class DesignationsScreen extends ConsumerStatefulWidget {
  const DesignationsScreen({super.key});

  @override
  ConsumerState<DesignationsScreen> createState() => _DesignationsScreenState();
}

class _DesignationsScreenState extends ConsumerState<DesignationsScreen> {
  final _listKey = GlobalKey<AsyncListScreenState<Designation>>();

  Future<void> _openForm([Designation? entity]) async {
    final changed = await Navigator.of(context).push<bool>(
      MaterialPageRoute(builder: (_) => _DesignationFormScreen(entity: entity)),
    );
    if (changed == true) _listKey.currentState?.reload();
  }

  @override
  Widget build(BuildContext context) {
    return AsyncListScreen<Designation>(
      key: _listKey,
      title: 'Designations',
      fetch: () => ref.read(organisationRepositoryProvider).listDesignations(),
      createLabel: 'New designation',
      onCreate: () => _openForm(),
      emptyLabel: 'No designations yet.',
      itemBuilder: (context, designation) => ListTile(
        title: Text(designation.title),
        subtitle: Text([if (designation.code != null) designation.code!, if (!designation.isActive) 'Inactive'].join(' · ')),
        onTap: () => _openForm(designation),
      ),
    );
  }
}

class _DesignationFormScreen extends ConsumerStatefulWidget {
  const _DesignationFormScreen({this.entity});
  final Designation? entity;

  @override
  ConsumerState<_DesignationFormScreen> createState() => _DesignationFormScreenState();
}

class _DesignationFormScreenState extends ConsumerState<_DesignationFormScreen> {
  late final _title = TextEditingController(text: widget.entity?.title);
  late final _code = TextEditingController(text: widget.entity?.code);
  String? _departmentId;
  String? _gradeId;
  bool _isActive = true;
  bool _submitting = false;
  bool _loadingOptions = true;
  String? _formError;
  List<Department> _departments = const [];
  List<Grade> _grades = const [];

  @override
  void initState() {
    super.initState();
    _isActive = widget.entity?.isActive ?? true;
    _departmentId = widget.entity?.departmentId;
    _gradeId = widget.entity?.gradeId;
    _loadOptions();
  }

  Future<void> _loadOptions() async {
    try {
      final repository = ref.read(organisationRepositoryProvider);
      final results = await Future.wait([repository.listDepartments(), repository.listGrades()]);
      if (mounted) {
        setState(() {
          _departments = results[0] as List<Department>;
          _grades = results[1] as List<Grade>;
        });
      }
    } finally {
      if (mounted) setState(() => _loadingOptions = false);
    }
  }

  Future<void> _submit() async {
    if (_title.text.trim().isEmpty) {
      setState(() => _formError = 'Title is required.');
      return;
    }
    setState(() {
      _submitting = true;
      _formError = null;
    });
    final body = {
      'title': _title.text.trim(),
      'code': _code.text.trim().isEmpty ? null : _code.text.trim(),
      'department_id': _departmentId,
      'grade_id': _gradeId,
      if (widget.entity != null) 'is_active': _isActive,
    };
    try {
      final repository = ref.read(organisationRepositoryProvider);
      if (widget.entity == null) {
        await repository.createDesignation(body);
      } else {
        await repository.updateDesignation(widget.entity!.id, body, ifMatch: widget.entity!.version.toString());
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
      appBar: AppBar(title: Text(widget.entity == null ? 'New designation' : 'Edit designation')),
      body: _loadingOptions
          ? const Center(child: CircularProgressIndicator())
          : ListView(
              padding: const EdgeInsets.all(16),
              children: [
                if (_formError != null) ...[InlineAlert(message: _formError!), const SizedBox(height: 16)],
                AuthFormField(label: 'Title', required: true, child: TextField(controller: _title, enabled: !_submitting)),
                const SizedBox(height: 16),
                AuthFormField(label: 'Code', child: TextField(controller: _code, enabled: !_submitting)),
                const SizedBox(height: 16),
                AuthFormField(
                  label: 'Department',
                  description: 'Optional',
                  child: DropdownButtonFormField<String?>(
                    value: _departmentId,
                    items: [
                      const DropdownMenuItem(value: null, child: Text('None')),
                      for (final d in _departments) DropdownMenuItem(value: d.id, child: Text(d.name)),
                    ],
                    onChanged: _submitting ? null : (v) => setState(() => _departmentId = v),
                  ),
                ),
                const SizedBox(height: 16),
                AuthFormField(
                  label: 'Grade',
                  description: 'Optional',
                  child: DropdownButtonFormField<String?>(
                    value: _gradeId,
                    items: [
                      const DropdownMenuItem(value: null, child: Text('None')),
                      for (final g in _grades) DropdownMenuItem(value: g.id, child: Text(g.name)),
                    ],
                    onChanged: _submitting ? null : (v) => setState(() => _gradeId = v),
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
