import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../core/api/api_error.dart';
import '../../auth/presentation/widgets/auth_form_field.dart';
import '../data/organisation_repository.dart';

/// Mirrors `apps/web/src/app/app/company/page.tsx` — view + edit the core
/// company profile fields. `locale`/`fiscal_year`/`working_days`/
/// `business_hours`/`branding` aren't editable here yet.
class CompanyProfileScreen extends ConsumerStatefulWidget {
  const CompanyProfileScreen({super.key});

  @override
  ConsumerState<CompanyProfileScreen> createState() => _CompanyProfileScreenState();
}

class _CompanyProfileScreenState extends ConsumerState<CompanyProfileScreen> {
  bool _loading = true;
  CompanyProfile? _profile;
  ApiError? _error;

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    setState(() {
      _loading = true;
      _error = null;
    });
    try {
      final profile = await ref.read(organisationRepositoryProvider).getCompanyProfile();
      if (mounted) setState(() => _profile = profile);
    } catch (error) {
      if (mounted) setState(() => _error = error is ApiError ? error : ApiError(status: 0, code: 'UNKNOWN_ERROR', message: 'Something went wrong.'));
    } finally {
      if (mounted) setState(() => _loading = false);
    }
  }

  Future<void> _edit() async {
    final changed = await Navigator.of(context).push<bool>(
      MaterialPageRoute(builder: (_) => _CompanyProfileFormScreen(profile: _profile!)),
    );
    if (changed == true) _load();
  }

  @override
  Widget build(BuildContext context) {
    Widget body;
    if (_loading) {
      body = const Center(child: CircularProgressIndicator());
    } else if (_error != null) {
      body = Center(
        child: Padding(
          padding: const EdgeInsets.all(24),
          child: Column(mainAxisSize: MainAxisSize.min, children: [
            Text(_error!.message, textAlign: TextAlign.center),
            const SizedBox(height: 16),
            FilledButton(onPressed: _load, child: const Text('Retry')),
          ]),
        ),
      );
    } else {
      final profile = _profile!;
      body = RefreshIndicator(
        onRefresh: _load,
        child: ListView(
          padding: const EdgeInsets.all(16),
          children: [
            _Section('Identity', [
              _Field('Name', profile.name),
              _Field('Legal name', profile.legalName),
              _Field('Registration number', profile.registrationNumber),
              _Field('Industry', profile.industryCode),
              _Field('Company size', profile.companySize),
              _Field('Status', profile.status),
            ]),
            const SizedBox(height: 20),
            _Section('Contact', [
              _Field('Email', profile.contact.email),
              _Field('Phone', profile.contact.phone),
              _Field('Website', profile.contact.website),
            ]),
            const SizedBox(height: 20),
            _Section('Address', [
              _Field('Line 1', profile.address.line1),
              _Field('Line 2', profile.address.line2),
              _Field('City', profile.address.city),
              _Field('State', profile.address.state),
              _Field('Postal code', profile.address.postalCode),
              _Field('Country', profile.address.countryCode),
            ]),
            const SizedBox(height: 20),
            _Section('Locale', [
              _Field('Country code', profile.countryCode),
              _Field('Currency', profile.currency),
              _Field('Timezone', profile.timezone),
            ]),
          ],
        ),
      );
    }

    return Scaffold(
      appBar: AppBar(title: const Text('Company'), actions: [
        if (!_loading && _error == null) IconButton(icon: const Icon(Icons.edit_outlined), onPressed: _edit),
      ]),
      body: body,
    );
  }
}

class _Field {
  const _Field(this.label, this.value);
  final String label;
  final String? value;
}

class _Section extends StatelessWidget {
  const _Section(this.title, this.fields);
  final String title;
  final List<_Field> fields;

  @override
  Widget build(BuildContext context) {
    final scheme = Theme.of(context).colorScheme;
    return Container(
      padding: const EdgeInsets.all(16),
      decoration: BoxDecoration(color: scheme.surfaceContainerLowest, borderRadius: BorderRadius.circular(12), border: Border.all(color: scheme.outlineVariant)),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(title, style: Theme.of(context).textTheme.headlineSmall),
          const SizedBox(height: 12),
          for (final field in fields)
            Padding(
              padding: const EdgeInsets.symmetric(vertical: 6),
              child: Row(
                mainAxisAlignment: MainAxisAlignment.spaceBetween,
                children: [
                  Text(field.label, style: TextStyle(color: scheme.onSurfaceVariant)),
                  Flexible(
                    child: Text(
                      (field.value != null && field.value!.trim().isNotEmpty) ? field.value! : 'Not configured',
                      textAlign: TextAlign.right,
                      style: TextStyle(color: (field.value != null && field.value!.trim().isNotEmpty) ? scheme.onSurface : scheme.onSurfaceVariant),
                    ),
                  ),
                ],
              ),
            ),
        ],
      ),
    );
  }
}

class _CompanyProfileFormScreen extends ConsumerStatefulWidget {
  const _CompanyProfileFormScreen({required this.profile});
  final CompanyProfile profile;

  @override
  ConsumerState<_CompanyProfileFormScreen> createState() => _CompanyProfileFormScreenState();
}

class _CompanyProfileFormScreenState extends ConsumerState<_CompanyProfileFormScreen> {
  late final _name = TextEditingController(text: widget.profile.name);
  late final _legalName = TextEditingController(text: widget.profile.legalName);
  late final _registrationNumber = TextEditingController(text: widget.profile.registrationNumber);
  late final _industryCode = TextEditingController(text: widget.profile.industryCode);
  late final _email = TextEditingController(text: widget.profile.contact.email);
  late final _phone = TextEditingController(text: widget.profile.contact.phone);
  late final _website = TextEditingController(text: widget.profile.contact.website);
  late final _addressLine1 = TextEditingController(text: widget.profile.address.line1);
  late final _addressLine2 = TextEditingController(text: widget.profile.address.line2);
  late final _city = TextEditingController(text: widget.profile.address.city);
  late final _state = TextEditingController(text: widget.profile.address.state);
  late final _postalCode = TextEditingController(text: widget.profile.address.postalCode);
  bool _submitting = false;
  String? _formError;

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
      'legal_name': _legalName.text.trim().isEmpty ? null : _legalName.text.trim(),
      'registration_number': _registrationNumber.text.trim().isEmpty ? null : _registrationNumber.text.trim(),
      'industry_code': _industryCode.text.trim().isEmpty ? null : _industryCode.text.trim(),
      'contact': {
        'email': _email.text.trim().isEmpty ? null : _email.text.trim(),
        'phone': _phone.text.trim().isEmpty ? null : _phone.text.trim(),
        'website': _website.text.trim().isEmpty ? null : _website.text.trim(),
      },
      'address': {
        'line1': _addressLine1.text.trim().isEmpty ? null : _addressLine1.text.trim(),
        'line2': _addressLine2.text.trim().isEmpty ? null : _addressLine2.text.trim(),
        'city': _city.text.trim().isEmpty ? null : _city.text.trim(),
        'state': _state.text.trim().isEmpty ? null : _state.text.trim(),
        'postal_code': _postalCode.text.trim().isEmpty ? null : _postalCode.text.trim(),
      },
    };
    try {
      await ref.read(organisationRepositoryProvider).updateCompanyProfile(body, ifMatch: widget.profile.version.toString());
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
      appBar: AppBar(title: const Text('Edit company profile')),
      body: ListView(
        padding: const EdgeInsets.all(16),
        children: [
          if (_formError != null) ...[InlineAlert(message: _formError!), const SizedBox(height: 16)],
          AuthFormField(label: 'Name', required: true, child: TextField(controller: _name, enabled: !_submitting)),
          const SizedBox(height: 16),
          AuthFormField(label: 'Legal name', child: TextField(controller: _legalName, enabled: !_submitting)),
          const SizedBox(height: 16),
          AuthFormField(label: 'Registration number', child: TextField(controller: _registrationNumber, enabled: !_submitting)),
          const SizedBox(height: 16),
          AuthFormField(label: 'Industry', child: TextField(controller: _industryCode, enabled: !_submitting)),
          const SizedBox(height: 20),
          Text('Contact', style: Theme.of(context).textTheme.labelMedium),
          const SizedBox(height: 12),
          AuthFormField(label: 'Email', child: TextField(controller: _email, enabled: !_submitting, keyboardType: TextInputType.emailAddress)),
          const SizedBox(height: 16),
          AuthFormField(label: 'Phone', child: TextField(controller: _phone, enabled: !_submitting, keyboardType: TextInputType.phone)),
          const SizedBox(height: 16),
          AuthFormField(label: 'Website', child: TextField(controller: _website, enabled: !_submitting)),
          const SizedBox(height: 20),
          Text('Address', style: Theme.of(context).textTheme.labelMedium),
          const SizedBox(height: 12),
          AuthFormField(label: 'Line 1', child: TextField(controller: _addressLine1, enabled: !_submitting)),
          const SizedBox(height: 16),
          AuthFormField(label: 'Line 2', child: TextField(controller: _addressLine2, enabled: !_submitting)),
          const SizedBox(height: 16),
          Row(children: [
            Expanded(child: AuthFormField(label: 'City', child: TextField(controller: _city, enabled: !_submitting))),
            const SizedBox(width: 12),
            Expanded(child: AuthFormField(label: 'State', child: TextField(controller: _state, enabled: !_submitting))),
          ]),
          const SizedBox(height: 16),
          AuthFormField(label: 'Postal code', child: TextField(controller: _postalCode, enabled: !_submitting)),
          const SizedBox(height: 20),
          PrimaryButton(label: 'Save changes', loading: _submitting, onPressed: _submit),
        ],
      ),
    );
  }
}
