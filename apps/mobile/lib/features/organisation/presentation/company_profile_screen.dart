import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../core/api/api_client.dart';
import '../../../core/api/api_error.dart';
import '../../../core/auth/permissions.dart';
import '../../../core/forms/spec_form_screen.dart';
import '../../../core/providers.dart';
import '../../auth/state/auth_controller.dart';
import '../domain/company_profile_form.dart';

typedef Rec = Map<String, dynamic>;

/// Mirrors `apps/web/src/app/app/company/page.tsx` — the whole company profile (basic info,
/// contact, address, localisation, working days, business hours, branding, metadata), viewable by
/// everyone and editable with `SETTINGS.COMPANY.MANAGE`. The patch carries the profile `version`
/// as `If-Match`.
class CompanyProfileScreen extends ConsumerStatefulWidget {
  const CompanyProfileScreen({super.key});

  @override
  ConsumerState<CompanyProfileScreen> createState() => _CompanyProfileScreenState();
}

class _CompanyProfileScreenState extends ConsumerState<CompanyProfileScreen> {
  bool _loading = true;
  Rec? _profile;
  ApiError? _error;

  ApiClient get _client => ref.read(apiClientProvider);

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
      final p = await _client.get<Rec>('/companies/current', parse: (d) => d as Rec);
      if (mounted) setState(() => _profile = p);
    } catch (e) {
      if (mounted) setState(() => _error = e is ApiError ? e : ApiError(status: 0, code: 'UNKNOWN_ERROR', message: 'Something went wrong.'));
    } finally {
      if (mounted) setState(() => _loading = false);
    }
  }

  Future<void> _edit() async {
    final profile = _profile!;
    final saved = await openSpecForm(
      context,
      title: 'Edit company profile',
      spec: companyProfileSpec(currencyLocked: profile['status'] != 'TRIAL'),
      initial: profileToForm(profile),
      onSubmit: (payload, changed) async {
        final patch = buildProfilePatch(payload, changed);
        if (patch.isEmpty) return;
        await _client.patch<Object?>('/companies/current', body: patch, ifMatch: '${profile['version']}', parse: (_) => null);
      },
    );
    if (saved && mounted) {
      ScaffoldMessenger.of(context).showSnackBar(const SnackBar(content: Text('Company profile saved.')));
      _load();
    }
  }

  @override
  Widget build(BuildContext context) {
    final canEdit = (ref.watch(authControllerProvider).user?.permissions ?? const <String>[]).contains(orgCompanyManage);
    return Scaffold(
      appBar: AppBar(title: const Text('Company'), actions: [
        if (canEdit && !_loading && _error == null) IconButton(tooltip: 'Edit', icon: const Icon(Icons.edit_outlined), onPressed: _edit),
      ]),
      body: _loading
          ? const Center(child: CircularProgressIndicator())
          : _error != null
              ? Center(
                  child: Padding(
                    padding: const EdgeInsets.all(24),
                    child: Column(mainAxisSize: MainAxisSize.min, children: [
                      Text(_error!.status == 403 ? 'You do not have permission to view the company profile.' : _error!.message, textAlign: TextAlign.center),
                      const SizedBox(height: 16),
                      FilledButton(onPressed: _load, child: const Text('Retry')),
                    ]),
                  ),
                )
              : RefreshIndicator(onRefresh: _load, child: _view(_profile!)),
    );
  }

  Widget _view(Rec p) {
    final f = profileToForm(p);
    String? s(String key) => (f[key] == null || '${f[key]}'.isEmpty) ? null : '${f[key]}';
    final days = [for (final d in weekDays) if (f['wd_$d'] == true) weekDayLabels[d]!].join(', ');
    final hours = s('bh_start') != null && s('bh_end') != null ? '${s('bh_start')} – ${s('bh_end')}' : null;
    final month = f['fiscal_start_month'] is int ? monthNames[(f['fiscal_start_month'] as int) - 1] : null;
    return ListView(padding: const EdgeInsets.all(16), children: [
      _Section('Basic information', [
        _Field('Company name', s('name')),
        _Field('Legal name', s('legal_name')),
        _Field('Registration number', s('registration_number')),
        _Field('Industry', s('industry_code')),
        _Field('Company size', s('company_size')),
        _Field('Country', s('country_code')),
        _Field('Currency', s('currency')),
        _Field('Timezone', s('timezone')),
      ]),
      _Section('Contact information', [_Field('Email', s('contact_email')), _Field('Phone', s('contact_phone')), _Field('Website', s('contact_website'))]),
      _Section('Address', [
        _Field('Line 1', s('address_line1')),
        _Field('Line 2', s('address_line2')),
        _Field('City', s('address_city')),
        _Field('State', s('address_state')),
        _Field('Postal code', s('address_postal_code')),
        _Field('Country code', s('address_country_code')),
      ]),
      _Section('Localization', [_Field('Language', s('locale_language_code')), _Field('Date format', s('locale_date_format')), _Field('Fiscal year start', month)]),
      _Section('Working schedule', [_Field('Working days', days.isEmpty ? null : days)]),
      _Section('Business hours', [_Field('Hours', hours)]),
      _Section('Branding', [_Field('Logo URL', s('logo_url')), _Field('Primary color', s('primary_color'))]),
      _Section('Company metadata', [
        _Field('Status', p['status'] as String?),
        _Field('Version', '${p['version']}'),
        _Field('Subdomain', p['subdomain'] as String?),
        _Field('Onboarded at', p['onboarded_at'] as String?),
        _Field('Trial ends at', p['trial_ends_at'] as String?),
      ]),
    ]);
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
      margin: const EdgeInsets.only(bottom: 16),
      padding: const EdgeInsets.all(16),
      decoration: BoxDecoration(color: scheme.surfaceContainerLowest, borderRadius: BorderRadius.circular(12), border: Border.all(color: scheme.outlineVariant)),
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Text(title, style: Theme.of(context).textTheme.titleMedium),
        const SizedBox(height: 8),
        for (final field in fields)
          Padding(
            padding: const EdgeInsets.symmetric(vertical: 5),
            child: Row(mainAxisAlignment: MainAxisAlignment.spaceBetween, crossAxisAlignment: CrossAxisAlignment.start, children: [
              Text(field.label, style: TextStyle(color: scheme.onSurfaceVariant)),
              const SizedBox(width: 12),
              Flexible(child: Text(field.value ?? 'Not configured', textAlign: TextAlign.right, style: TextStyle(color: field.value != null ? scheme.onSurface : scheme.onSurfaceVariant))),
            ]),
          ),
      ]),
    );
  }
}
