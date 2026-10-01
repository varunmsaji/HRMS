import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../core/api/api_error.dart';
import '../../../core/widgets/async_list_screen.dart';
import '../../auth/presentation/widgets/auth_form_field.dart';
import '../data/organisation_repository.dart';
import 'legal_entities_screen.dart' show organisationRepositoryProvider;

class BranchesScreen extends ConsumerStatefulWidget {
  const BranchesScreen({super.key});

  @override
  ConsumerState<BranchesScreen> createState() => _BranchesScreenState();
}

class _BranchesScreenState extends ConsumerState<BranchesScreen> {
  final _listKey = GlobalKey<AsyncListScreenState<Branch>>();

  Future<void> _openForm([Branch? entity]) async {
    final changed = await Navigator.of(context).push<bool>(
      MaterialPageRoute(builder: (_) => _BranchFormScreen(entity: entity)),
    );
    if (changed == true) _listKey.currentState?.reload();
  }

  @override
  Widget build(BuildContext context) {
    return AsyncListScreen<Branch>(
      key: _listKey,
      title: 'Branches',
      fetch: () => ref.read(organisationRepositoryProvider).listBranches(),
      createLabel: 'New branch',
      onCreate: () => _openForm(),
      emptyLabel: 'No branches yet.',
      itemBuilder: (context, branch) => ListTile(
        title: Text(branch.name),
        subtitle: Text([
          if (branch.code != null) branch.code!,
          if (branch.city != null) branch.city!,
          if (!branch.isActive) 'Inactive',
        ].join(' · ')),
        onTap: () => _openForm(branch),
      ),
    );
  }
}

class _BranchFormScreen extends ConsumerStatefulWidget {
  const _BranchFormScreen({this.entity});
  final Branch? entity;

  @override
  ConsumerState<_BranchFormScreen> createState() => _BranchFormScreenState();
}

class _BranchFormScreenState extends ConsumerState<_BranchFormScreen> {
  late final _name = TextEditingController(text: widget.entity?.name);
  late final _code = TextEditingController(text: widget.entity?.code);
  late final _city = TextEditingController(text: widget.entity?.city);
  late final _stateCode = TextEditingController(text: widget.entity?.stateCode);
  String? _legalEntityId;
  bool _isActive = true;
  bool _submitting = false;
  bool _loadingEntities = true;
  String? _formError;
  List<LegalEntity> _legalEntities = const [];

  @override
  void initState() {
    super.initState();
    _isActive = widget.entity?.isActive ?? true;
    _legalEntityId = widget.entity?.legalEntityId;
    _loadEntities();
  }

  Future<void> _loadEntities() async {
    try {
      final entities = await ref.read(organisationRepositoryProvider).listLegalEntities();
      if (mounted) {
        setState(() {
          _legalEntities = entities;
          _legalEntityId ??= entities.isNotEmpty ? entities.first.id : null;
        });
      }
    } finally {
      if (mounted) setState(() => _loadingEntities = false);
    }
  }

  Future<void> _submit() async {
    if (_name.text.trim().isEmpty || _legalEntityId == null) {
      setState(() => _formError = 'Name and legal entity are required.');
      return;
    }
    setState(() {
      _submitting = true;
      _formError = null;
    });
    final body = {
      'name': _name.text.trim(),
      'legal_entity_id': _legalEntityId,
      'code': _code.text.trim().isEmpty ? null : _code.text.trim(),
      'city': _city.text.trim().isEmpty ? null : _city.text.trim(),
      'state_code': _stateCode.text.trim().isEmpty ? null : _stateCode.text.trim(),
      if (widget.entity != null) 'is_active': _isActive,
    };
    try {
      final repository = ref.read(organisationRepositoryProvider);
      if (widget.entity == null) {
        await repository.createBranch(body);
      } else {
        await repository.updateBranch(widget.entity!.id, body, ifMatch: widget.entity!.version.toString());
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
      appBar: AppBar(title: Text(widget.entity == null ? 'New branch' : 'Edit branch')),
      body: _loadingEntities
          ? const Center(child: CircularProgressIndicator())
          : ListView(
              padding: const EdgeInsets.all(16),
              children: [
                if (_formError != null) ...[InlineAlert(message: _formError!), const SizedBox(height: 16)],
                AuthFormField(label: 'Name', required: true, child: TextField(controller: _name, enabled: !_submitting)),
                const SizedBox(height: 16),
                AuthFormField(
                  label: 'Legal entity',
                  required: true,
                  child: DropdownButtonFormField<String>(
                    value: _legalEntityId,
                    items: [for (final e in _legalEntities) DropdownMenuItem(value: e.id, child: Text(e.name))],
                    onChanged: _submitting ? null : (v) => setState(() => _legalEntityId = v),
                  ),
                ),
                const SizedBox(height: 16),
                AuthFormField(label: 'Code', child: TextField(controller: _code, enabled: !_submitting)),
                const SizedBox(height: 16),
                Row(children: [
                  Expanded(child: AuthFormField(label: 'City', child: TextField(controller: _city, enabled: !_submitting))),
                  const SizedBox(width: 12),
                  Expanded(child: AuthFormField(label: 'State code', child: TextField(controller: _stateCode, enabled: !_submitting))),
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
