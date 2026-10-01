import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../core/api/api_error.dart';
import '../../../core/widgets/async_list_screen.dart';
import '../../auth/presentation/widgets/auth_form_field.dart';
import '../data/payroll_repository.dart';
import 'pay_runs_screen.dart' show payrollRepositoryProvider;

const _schemes = ['PF', 'ESI', 'PT', 'LWF', 'TDS'];

class StatutoryRatesScreen extends ConsumerStatefulWidget {
  const StatutoryRatesScreen({super.key});

  @override
  ConsumerState<StatutoryRatesScreen> createState() => _StatutoryRatesScreenState();
}

class _StatutoryRatesScreenState extends ConsumerState<StatutoryRatesScreen> {
  final _listKey = GlobalKey<AsyncListScreenState<StatutoryRate>>();

  Future<void> _create() async {
    final changed = await Navigator.of(context).push<bool>(MaterialPageRoute(builder: (_) => const _StatutoryRateFormScreen()));
    if (changed == true) _listKey.currentState?.reload();
  }

  Future<void> _verify(StatutoryRate rate) async {
    try {
      await ref.read(payrollRepositoryProvider).verifyStatutoryRate(rate.id, ifMatch: rate.version.toString());
      _listKey.currentState?.reload();
    } catch (error) {
      if (mounted) ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(error is ApiError ? error.message : 'Something went wrong.')));
    }
  }

  @override
  Widget build(BuildContext context) {
    return AsyncListScreen<StatutoryRate>(
      key: _listKey,
      title: 'Statutory Rates',
      fetch: () => ref.read(payrollRepositoryProvider).listStatutoryRates(),
      createLabel: 'New rate',
      onCreate: _create,
      emptyLabel: 'No statutory rates configured.',
      itemBuilder: (context, rate) => ListTile(
        title: Text('${rate.scheme}${rate.stateCode != null ? ' · ${rate.stateCode}' : ''}'),
        subtitle: Text(['from ${rate.effectiveFrom}', rate.verified ? 'Verified' : 'Not verified'].join(' · ')),
        trailing: rate.verified ? null : TextButton(onPressed: () => _verify(rate), child: const Text('Verify')),
      ),
    );
  }
}

class _StatutoryRateFormScreen extends ConsumerStatefulWidget {
  const _StatutoryRateFormScreen();

  @override
  ConsumerState<_StatutoryRateFormScreen> createState() => _StatutoryRateFormScreenState();
}

class _StatutoryRateFormScreenState extends ConsumerState<_StatutoryRateFormScreen> {
  String _scheme = 'PF';
  final _stateCode = TextEditingController();
  final _effectiveFrom = TextEditingController();
  final _employeePercent = TextEditingController();
  final _employerPercent = TextEditingController();
  final _flatAmount = TextEditingController();
  bool _submitting = false;
  String? _formError;

  bool get _needsStateCode => _scheme == 'PT' || _scheme == 'LWF';

  Future<void> _submit() async {
    if (DateTime.tryParse(_effectiveFrom.text.trim()) == null) {
      setState(() => _formError = 'Enter a valid effective-from date.');
      return;
    }
    if (_needsStateCode && _stateCode.text.trim().isEmpty) {
      setState(() => _formError = 'State code is required for PT/LWF.');
      return;
    }
    setState(() {
      _submitting = true;
      _formError = null;
    });
    Map<String, dynamic> parameters;
    switch (_scheme) {
      case 'PF':
      case 'ESI':
        parameters = {
          'employee_percent': num.tryParse(_employeePercent.text.trim()) ?? 0,
          'employer_percent': num.tryParse(_employerPercent.text.trim()) ?? 0,
        };
      case 'PT':
      case 'LWF':
        parameters = {'flat_amount_minor': int.tryParse(_flatAmount.text.trim()) ?? 0};
      default:
        parameters = {'regime': 'NEW'};
    }
    try {
      await ref.read(payrollRepositoryProvider).createStatutoryRate({
        'scheme': _scheme,
        if (_needsStateCode) 'state_code': _stateCode.text.trim().toUpperCase(),
        'effective_from': _effectiveFrom.text.trim(),
        'parameters': parameters,
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
      appBar: AppBar(title: const Text('New statutory rate')),
      body: ListView(
        padding: const EdgeInsets.all(16),
        children: [
          if (_formError != null) ...[InlineAlert(message: _formError!), const SizedBox(height: 16)],
          AuthFormField(
            label: 'Scheme',
            child: DropdownButtonFormField<String>(
              value: _scheme,
              items: [for (final s in _schemes) DropdownMenuItem(value: s, child: Text(s))],
              onChanged: _submitting ? null : (v) => setState(() => _scheme = v ?? _scheme),
            ),
          ),
          if (_needsStateCode) ...[
            const SizedBox(height: 16),
            AuthFormField(label: 'State code', required: true, child: TextField(controller: _stateCode, enabled: !_submitting, textCapitalization: TextCapitalization.characters)),
          ],
          const SizedBox(height: 16),
          AuthFormField(label: 'Effective from', required: true, description: 'YYYY-MM-DD', child: TextField(controller: _effectiveFrom, enabled: !_submitting)),
          const SizedBox(height: 16),
          if (_scheme == 'PF' || _scheme == 'ESI')
            Row(children: [
              Expanded(child: AuthFormField(label: 'Employee %', child: TextField(controller: _employeePercent, enabled: !_submitting, keyboardType: TextInputType.number))),
              const SizedBox(width: 12),
              Expanded(child: AuthFormField(label: 'Employer %', child: TextField(controller: _employerPercent, enabled: !_submitting, keyboardType: TextInputType.number))),
            ])
          else if (_scheme == 'PT' || _scheme == 'LWF')
            AuthFormField(label: 'Flat amount (minor units)', child: TextField(controller: _flatAmount, enabled: !_submitting, keyboardType: TextInputType.number))
          else
            Text('TDS uses the new tax regime with server-managed slabs — create with defaults, adjust on web.', style: Theme.of(context).textTheme.bodySmall),
          const SizedBox(height: 20),
          PrimaryButton(label: 'Create', loading: _submitting, onPressed: _submit),
        ],
      ),
    );
  }
}
