import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../../core/api/api_error.dart';
import '../../../core/validation.dart';
import '../data/auth_repository.dart';
import '../state/auth_controller.dart';
import '../state/auth_state.dart';
import 'widgets/auth_form_field.dart';
import 'widgets/auth_scaffold.dart';

const _months = [
  'January', 'February', 'March', 'April', 'May', 'June',
  'July', 'August', 'September', 'October', 'November', 'December',
];

const _companySizeBands = ['1-10', '11-50', '51-200', '201-500', '501-1000', '1000+'];

/// Mirrors `apps/web/src/app/register/page.tsx` (company sign-up + admin
/// account creation in one call, `POST /companies/register`).
class RegisterScreen extends ConsumerStatefulWidget {
  const RegisterScreen({super.key});

  @override
  ConsumerState<RegisterScreen> createState() => _RegisterScreenState();
}

class _RegisterScreenState extends ConsumerState<RegisterScreen> {
  final _nameController = TextEditingController();
  final _industryController = TextEditingController();
  final _countryController = TextEditingController(text: 'IN');
  final _currencyController = TextEditingController(text: 'INR');
  final _adminFirstNameController = TextEditingController();
  final _adminLastNameController = TextEditingController();
  final _adminEmailController = TextEditingController();
  final _adminPasswordController = TextEditingController();
  final _confirmPasswordController = TextEditingController();

  List<String> _timezones = const ['Asia/Kolkata'];
  String _timezone = 'Asia/Kolkata';
  int _fyStartMonth = 4;
  String? _companySize;

  final Map<String, String?> _errors = {};
  String? _formError;
  bool _submitting = false;

  @override
  void initState() {
    super.initState();
    _loadTimezones();
  }

  Future<void> _loadTimezones() async {
    try {
      final config = await ref.read(authRepositoryProvider).registrationConfig();
      if (!mounted || config.allowedCompanyTimezones.isEmpty) return;
      setState(() {
        _timezones = config.allowedCompanyTimezones;
        if (!_timezones.contains(_timezone)) _timezone = _timezones.first;
      });
    } catch (_) {
      // Defaults to `Asia/Kolkata` alone, matching the server's own default.
    }
  }

  @override
  void dispose() {
    _nameController.dispose();
    _industryController.dispose();
    _countryController.dispose();
    _currencyController.dispose();
    _adminFirstNameController.dispose();
    _adminLastNameController.dispose();
    _adminEmailController.dispose();
    _adminPasswordController.dispose();
    _confirmPasswordController.dispose();
    super.dispose();
  }

  Future<void> _submit() async {
    setState(() => _formError = null);

    final errors = <String, String?>{};
    final name = _nameController.text.trim();
    if (name.isEmpty) {
      errors['name'] = 'Company name is required.';
    } else if (name.length > 200) {
      errors['name'] = 'Must be 200 characters or fewer.';
    }
    if (_adminFirstNameController.text.trim().isEmpty) errors['adminFirstName'] = 'First name is required.';
    if (_adminLastNameController.text.trim().isEmpty) errors['adminLastName'] = 'Last name is required.';

    final email = _adminEmailController.text.trim();
    if (email.isEmpty) {
      errors['adminEmail'] = 'Email is required.';
    } else if (!isValidEmail(email)) {
      errors['adminEmail'] = 'Enter a valid email address.';
    }

    final password = _adminPasswordController.text;
    if (password.isEmpty) {
      errors['adminPassword'] = 'Password is required.';
    } else if (!isPasswordStrongEnough(password)) {
      errors['adminPassword'] = passwordRequirementMessage();
    }
    if (_confirmPasswordController.text != password) errors['confirmPassword'] = 'Passwords do not match.';

    final country = _countryController.text.trim();
    if (country.isNotEmpty && !RegExp(r'^[A-Za-z]{2}$').hasMatch(country)) {
      errors['countryCode'] = 'Use a 2-letter country code.';
    }
    final currency = _currencyController.text.trim();
    if (currency.isNotEmpty && !RegExp(r'^[A-Za-z]{3}$').hasMatch(currency)) {
      errors['currency'] = 'Use a 3-letter currency code.';
    }

    if (errors.values.any((v) => v != null)) {
      setState(() {
        _errors.clear();
        _errors.addAll(errors);
      });
      return;
    }

    setState(() => _submitting = true);
    try {
      final data = await ref.read(authRepositoryProvider).registerCompany(
            CompanyRegistrationRequest(
              name: name,
              industryCode: _industryController.text.trim().isEmpty ? null : _industryController.text.trim(),
              countryCode: country.isEmpty ? null : country.toUpperCase(),
              currency: currency.isEmpty ? null : currency.toUpperCase(),
              timezone: _timezone,
              fyStartMonth: _fyStartMonth,
              companySize: _companySize,
              adminFirstName: _adminFirstNameController.text.trim(),
              adminLastName: _adminLastNameController.text.trim(),
              adminEmail: email,
              adminPassword: password,
            ),
          );
      final user = await ref.read(authControllerProvider.notifier).applyTokenResponse(data);
      if (!mounted) return;
      context.go(landingPathFor(user));
    } catch (error) {
      if (error is ApiError) {
        if (error.status == 409) {
          setState(() {
            _formError = 'An account with this email already exists. Try signing in instead.';
            _errors['adminEmail'] = 'Already registered.';
          });
        } else if (error.status == 422) {
          final nextErrors = <String, String?>{
            'name': getFieldError(error.details, 'name'),
            'industryCode': getFieldError(error.details, 'industry_code'),
            'countryCode': getFieldError(error.details, 'country_code'),
            'currency': getFieldError(error.details, 'currency'),
            'timezone': getFieldError(error.details, 'timezone'),
            'fyStartMonth': getFieldError(error.details, 'fy_start_month'),
            'companySize': getFieldError(error.details, 'company_size'),
            'adminFirstName': getFieldError(error.details, 'admin_first_name'),
            'adminLastName': getFieldError(error.details, 'admin_last_name'),
            'adminEmail': getFieldError(error.details, 'admin_email'),
            'adminPassword': getFieldError(error.details, 'admin_password'),
          };
          final hasFieldError = nextErrors.values.any((v) => v != null);
          setState(() {
            _errors.clear();
            _errors.addAll(nextErrors);
            _formError = hasFieldError ? null : error.message;
          });
        } else if (error.status == 429) {
          setState(() => _formError = 'Too many attempts. Please wait a moment and try again.');
        } else {
          setState(() => _formError = error.message);
        }
      } else {
        setState(() => _formError = 'Something went wrong. Please try again.');
      }
    } finally {
      if (mounted) setState(() => _submitting = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    return AuthScaffold(
      title: 'Register your company',
      description: "Create your organisation's workspace and admin account.",
      footer: Wrap(
        alignment: WrapAlignment.center,
        children: [
          const Text('Already have an account? '),
          GestureDetector(
            onTap: () => context.go('/login'),
            child: Text('Sign in', style: TextStyle(color: Theme.of(context).colorScheme.primary, fontWeight: FontWeight.w600)),
          ),
        ],
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          if (_formError != null) ...[
            InlineAlert(message: _formError!),
            const SizedBox(height: 16),
          ],
          Text('Company details', style: Theme.of(context).textTheme.labelMedium),
          const SizedBox(height: 12),
          AuthFormField(
            label: 'Company name',
            required: true,
            errorText: _errors['name'],
            child: TextField(controller: _nameController, enabled: !_submitting),
          ),
          const SizedBox(height: 16),
          AuthFormField(
            label: 'Industry',
            description: _errors['industryCode'] == null ? 'Optional' : null,
            errorText: _errors['industryCode'],
            child: TextField(
              controller: _industryController,
              enabled: !_submitting,
              decoration: const InputDecoration(hintText: 'e.g. Manufacturing, IT Services'),
            ),
          ),
          const SizedBox(height: 16),
          Row(
            children: [
              Expanded(
                child: AuthFormField(
                  label: 'Country code',
                  errorText: _errors['countryCode'],
                  child: TextField(
                    controller: _countryController,
                    enabled: !_submitting,
                    textCapitalization: TextCapitalization.characters,
                  ),
                ),
              ),
              const SizedBox(width: 12),
              Expanded(
                child: AuthFormField(
                  label: 'Currency',
                  errorText: _errors['currency'],
                  child: TextField(
                    controller: _currencyController,
                    enabled: !_submitting,
                    textCapitalization: TextCapitalization.characters,
                  ),
                ),
              ),
            ],
          ),
          const SizedBox(height: 16),
          AuthFormField(
            label: 'Timezone',
            errorText: _errors['timezone'],
            description: _timezones.length == 1 ? 'India-only for now — more regions coming soon.' : null,
            child: _timezones.length == 1
                ? TextField(controller: TextEditingController(text: _timezones.first), enabled: false)
                : DropdownButtonFormField<String>(
                    value: _timezone,
                    items: _timezones.map((tz) => DropdownMenuItem(value: tz, child: Text(tz))).toList(),
                    onChanged: _submitting ? null : (value) => setState(() => _timezone = value ?? _timezone),
                  ),
          ),
          const SizedBox(height: 16),
          AuthFormField(
            label: 'Financial year starts',
            errorText: _errors['fyStartMonth'],
            child: DropdownButtonFormField<int>(
              value: _fyStartMonth,
              items: [
                for (var i = 0; i < _months.length; i++) DropdownMenuItem(value: i + 1, child: Text(_months[i])),
              ],
              onChanged: _submitting ? null : (value) => setState(() => _fyStartMonth = value ?? _fyStartMonth),
            ),
          ),
          const SizedBox(height: 16),
          AuthFormField(
            label: 'Company size',
            description: _errors['companySize'] == null ? 'Optional' : null,
            errorText: _errors['companySize'],
            child: DropdownButtonFormField<String?>(
              value: _companySize,
              items: [
                const DropdownMenuItem(value: null, child: Text('Select a range')),
                for (final band in _companySizeBands) DropdownMenuItem(value: band, child: Text('$band employees')),
              ],
              onChanged: _submitting ? null : (value) => setState(() => _companySize = value),
            ),
          ),
          const SizedBox(height: 24),
          Text('Admin account', style: Theme.of(context).textTheme.labelMedium),
          const SizedBox(height: 12),
          Row(
            children: [
              Expanded(
                child: AuthFormField(
                  label: 'First name',
                  required: true,
                  errorText: _errors['adminFirstName'],
                  child: TextField(controller: _adminFirstNameController, enabled: !_submitting),
                ),
              ),
              const SizedBox(width: 12),
              Expanded(
                child: AuthFormField(
                  label: 'Last name',
                  required: true,
                  errorText: _errors['adminLastName'],
                  child: TextField(controller: _adminLastNameController, enabled: !_submitting),
                ),
              ),
            ],
          ),
          const SizedBox(height: 16),
          AuthFormField(
            label: 'Work email',
            required: true,
            errorText: _errors['adminEmail'],
            child: TextField(
              controller: _adminEmailController,
              keyboardType: TextInputType.emailAddress,
              autofillHints: const [AutofillHints.email],
              enabled: !_submitting,
            ),
          ),
          const SizedBox(height: 16),
          AuthFormField(
            label: 'Password',
            required: true,
            errorText: _errors['adminPassword'],
            description: _errors['adminPassword'] == null ? 'At least 8 characters, with a letter and a digit.' : null,
            child: AuthPasswordField(
              controller: _adminPasswordController,
              enabled: !_submitting,
              autofillHints: const [AutofillHints.newPassword],
            ),
          ),
          const SizedBox(height: 16),
          AuthFormField(
            label: 'Confirm password',
            required: true,
            errorText: _errors['confirmPassword'],
            child: AuthPasswordField(
              controller: _confirmPasswordController,
              enabled: !_submitting,
              autofillHints: const [AutofillHints.newPassword],
            ),
          ),
          const SizedBox(height: 20),
          PrimaryButton(
            label: _submitting ? 'Creating your workspace…' : 'Create workspace',
            loading: _submitting,
            onPressed: _submit,
          ),
        ],
      ),
    );
  }
}
