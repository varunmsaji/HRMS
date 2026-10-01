import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../core/api/api_error.dart';
import '../../../core/providers.dart';
import '../../../core/widgets/async_list_screen.dart';
import '../../auth/presentation/widgets/auth_form_field.dart';
import '../data/organisation_repository.dart';

final organisationRepositoryProvider = Provider<OrganisationRepository>(
  (ref) => OrganisationRepository(ref.watch(apiClientProvider)),
);

class LegalEntitiesScreen extends ConsumerStatefulWidget {
  const LegalEntitiesScreen({super.key});

  @override
  ConsumerState<LegalEntitiesScreen> createState() => _LegalEntitiesScreenState();
}

class _LegalEntitiesScreenState extends ConsumerState<LegalEntitiesScreen> {
  final _listKey = GlobalKey<AsyncListScreenState<LegalEntity>>();

  Future<void> _openForm([LegalEntity? entity]) async {
    final changed = await Navigator.of(context).push<bool>(
      MaterialPageRoute(builder: (_) => _LegalEntityFormScreen(entity: entity)),
    );
    if (changed == true) _listKey.currentState?.reload();
  }

  @override
  Widget build(BuildContext context) {
    return AsyncListScreen<LegalEntity>(
      key: _listKey,
      title: 'Legal Entities',
      fetch: () => ref.read(organisationRepositoryProvider).listLegalEntities(),
      createLabel: 'New entity',
      onCreate: () => _openForm(),
      emptyLabel: 'No legal entities yet.',
      itemBuilder: (context, entity) => ListTile(
        title: Text(entity.name),
        subtitle: Text([if (entity.gstin != null) 'GSTIN ${entity.gstin}', if (!entity.isActive) 'Inactive'].join(' · ')),
        onTap: () => _openForm(entity),
      ),
    );
  }
}

class _LegalEntityFormScreen extends ConsumerStatefulWidget {
  const _LegalEntityFormScreen({this.entity});
  final LegalEntity? entity;

  @override
  ConsumerState<_LegalEntityFormScreen> createState() => _LegalEntityFormScreenState();
}

class _LegalEntityFormScreenState extends ConsumerState<_LegalEntityFormScreen> {
  late final _name = TextEditingController(text: widget.entity?.name);
  late final _registeredAddress = TextEditingController(text: widget.entity?.registeredAddress);
  late final _pan = TextEditingController(text: widget.entity?.pan);
  late final _tan = TextEditingController(text: widget.entity?.tan);
  late final _cin = TextEditingController(text: widget.entity?.cin);
  late final _gstin = TextEditingController(text: widget.entity?.gstin);
  bool _isActive = true;
  bool _submitting = false;
  String? _formError;

  @override
  void initState() {
    super.initState();
    _isActive = widget.entity?.isActive ?? true;
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
      'registered_address': _registeredAddress.text.trim().isEmpty ? null : _registeredAddress.text.trim(),
      'pan': _pan.text.trim().isEmpty ? null : _pan.text.trim(),
      'tan': _tan.text.trim().isEmpty ? null : _tan.text.trim(),
      'cin': _cin.text.trim().isEmpty ? null : _cin.text.trim(),
      'gstin': _gstin.text.trim().isEmpty ? null : _gstin.text.trim(),
      if (widget.entity != null) 'is_active': _isActive,
    };
    try {
      final repository = ref.read(organisationRepositoryProvider);
      if (widget.entity == null) {
        await repository.createLegalEntity(body);
      } else {
        await repository.updateLegalEntity(widget.entity!.id, body, ifMatch: widget.entity!.version.toString());
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
      appBar: AppBar(title: Text(widget.entity == null ? 'New legal entity' : 'Edit legal entity')),
      body: ListView(
        padding: const EdgeInsets.all(16),
        children: [
          if (_formError != null) ...[InlineAlert(message: _formError!), const SizedBox(height: 16)],
          AuthFormField(label: 'Name', required: true, child: TextField(controller: _name, enabled: !_submitting)),
          const SizedBox(height: 16),
          AuthFormField(label: 'Registered address', child: TextField(controller: _registeredAddress, enabled: !_submitting, maxLines: 3)),
          const SizedBox(height: 16),
          Row(children: [
            Expanded(child: AuthFormField(label: 'PAN', child: TextField(controller: _pan, enabled: !_submitting, textCapitalization: TextCapitalization.characters))),
            const SizedBox(width: 12),
            Expanded(child: AuthFormField(label: 'TAN', child: TextField(controller: _tan, enabled: !_submitting, textCapitalization: TextCapitalization.characters))),
          ]),
          const SizedBox(height: 16),
          Row(children: [
            Expanded(child: AuthFormField(label: 'CIN', child: TextField(controller: _cin, enabled: !_submitting, textCapitalization: TextCapitalization.characters))),
            const SizedBox(width: 12),
            Expanded(child: AuthFormField(label: 'GSTIN', child: TextField(controller: _gstin, enabled: !_submitting, textCapitalization: TextCapitalization.characters))),
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
