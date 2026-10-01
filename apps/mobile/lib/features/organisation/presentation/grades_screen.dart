import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../core/api/api_error.dart';
import '../../../core/widgets/async_list_screen.dart';
import '../../auth/presentation/widgets/auth_form_field.dart';
import '../data/organisation_repository.dart';
import 'legal_entities_screen.dart' show organisationRepositoryProvider;

class GradesScreen extends ConsumerStatefulWidget {
  const GradesScreen({super.key});

  @override
  ConsumerState<GradesScreen> createState() => _GradesScreenState();
}

class _GradesScreenState extends ConsumerState<GradesScreen> {
  final _listKey = GlobalKey<AsyncListScreenState<Grade>>();

  Future<void> _openForm([Grade? entity]) async {
    final changed = await Navigator.of(context).push<bool>(
      MaterialPageRoute(builder: (_) => _GradeFormScreen(entity: entity)),
    );
    if (changed == true) _listKey.currentState?.reload();
  }

  @override
  Widget build(BuildContext context) {
    return AsyncListScreen<Grade>(
      key: _listKey,
      title: 'Grades',
      fetch: () => ref.read(organisationRepositoryProvider).listGrades(),
      createLabel: 'New grade',
      onCreate: () => _openForm(),
      emptyLabel: 'No grades yet.',
      itemBuilder: (context, grade) => ListTile(
        title: Text('${grade.name} (${grade.code})'),
        subtitle: Text([
          if (grade.level != null) 'Level ${grade.level}',
          if (grade.minCtc != null && grade.maxCtc != null) 'CTC ${grade.minCtc}–${grade.maxCtc}',
          if (!grade.isActive) 'Inactive',
        ].join(' · ')),
        onTap: () => _openForm(grade),
      ),
    );
  }
}

class _GradeFormScreen extends ConsumerStatefulWidget {
  const _GradeFormScreen({this.entity});
  final Grade? entity;

  @override
  ConsumerState<_GradeFormScreen> createState() => _GradeFormScreenState();
}

class _GradeFormScreenState extends ConsumerState<_GradeFormScreen> {
  late final _code = TextEditingController(text: widget.entity?.code);
  late final _name = TextEditingController(text: widget.entity?.name);
  late final _level = TextEditingController(text: widget.entity?.level?.toString());
  late final _minCtc = TextEditingController(text: widget.entity?.minCtc?.toString());
  late final _maxCtc = TextEditingController(text: widget.entity?.maxCtc?.toString());
  bool _isActive = true;
  bool _submitting = false;
  String? _formError;

  @override
  void initState() {
    super.initState();
    _isActive = widget.entity?.isActive ?? true;
  }

  Future<void> _submit() async {
    if (_code.text.trim().isEmpty || _name.text.trim().isEmpty) {
      setState(() => _formError = 'Code and name are required.');
      return;
    }
    final minCtc = int.tryParse(_minCtc.text.trim());
    final maxCtc = int.tryParse(_maxCtc.text.trim());
    if (minCtc != null && maxCtc != null && minCtc > maxCtc) {
      setState(() => _formError = 'Min CTC cannot exceed max CTC.');
      return;
    }
    setState(() {
      _submitting = true;
      _formError = null;
    });
    final body = {
      if (widget.entity == null) 'code': _code.text.trim(),
      'name': _name.text.trim(),
      'level': int.tryParse(_level.text.trim()),
      'min_ctc': minCtc,
      'max_ctc': maxCtc,
      if (widget.entity != null) 'is_active': _isActive,
    };
    try {
      final repository = ref.read(organisationRepositoryProvider);
      if (widget.entity == null) {
        await repository.createGrade(body);
      } else {
        await repository.updateGrade(widget.entity!.id, body, ifMatch: widget.entity!.version.toString());
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
      appBar: AppBar(title: Text(widget.entity == null ? 'New grade' : 'Edit grade')),
      body: ListView(
        padding: const EdgeInsets.all(16),
        children: [
          if (_formError != null) ...[InlineAlert(message: _formError!), const SizedBox(height: 16)],
          Row(children: [
            Expanded(
              child: AuthFormField(
                label: 'Code',
                required: true,
                child: TextField(controller: _code, enabled: !_submitting && widget.entity == null),
              ),
            ),
            const SizedBox(width: 12),
            Expanded(child: AuthFormField(label: 'Name', required: true, child: TextField(controller: _name, enabled: !_submitting))),
          ]),
          const SizedBox(height: 16),
          AuthFormField(
            label: 'Level',
            description: 'Optional',
            child: TextField(controller: _level, enabled: !_submitting, keyboardType: TextInputType.number),
          ),
          const SizedBox(height: 16),
          Row(children: [
            Expanded(
              child: AuthFormField(
                label: 'Min CTC',
                description: 'Optional',
                child: TextField(controller: _minCtc, enabled: !_submitting, keyboardType: TextInputType.number),
              ),
            ),
            const SizedBox(width: 12),
            Expanded(
              child: AuthFormField(
                label: 'Max CTC',
                description: 'Optional',
                child: TextField(controller: _maxCtc, enabled: !_submitting, keyboardType: TextInputType.number),
              ),
            ),
          ]),
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
