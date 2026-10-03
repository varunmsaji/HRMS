import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../core/api/api_error.dart';
import '../../../core/providers.dart';
import '../../../core/widgets/async_list_screen.dart';
import '../../auth/presentation/widgets/auth_form_field.dart';
import '../data/onboarding_repository.dart';
import 'onboarding_case_detail_screen.dart';

final onboardingRepositoryProvider = Provider<OnboardingRepository>((ref) => OnboardingRepository(ref.watch(apiClientProvider)));

/// Mirrors "Mobile Onboarding Cases" — list + entry into the wizard (create)
/// and case review.
class OnboardingCasesScreen extends ConsumerStatefulWidget {
  const OnboardingCasesScreen({super.key});

  @override
  ConsumerState<OnboardingCasesScreen> createState() => _OnboardingCasesScreenState();
}

class _OnboardingCasesScreenState extends ConsumerState<OnboardingCasesScreen> {
  final _listKey = GlobalKey<AsyncListScreenState<OnboardingCase>>();

  Future<void> _openWizard() async {
    final changed = await Navigator.of(context).push<bool>(MaterialPageRoute(builder: (_) => const OnboardingWizardScreen()));
    if (changed == true) _listKey.currentState?.reload();
  }

  @override
  Widget build(BuildContext context) {
    return AsyncListScreen<OnboardingCase>(
      key: _listKey,
      title: 'Onboarding',
      fetch: () => ref.read(onboardingRepositoryProvider).listCases(),
      createLabel: 'New case',
      onCreate: _openWizard,
      emptyLabel: 'No onboarding cases yet.',
      itemBuilder: (context, onboardingCase) => ListTile(
        title: Text(onboardingCase.candidateName),
        subtitle: Text([onboardingCase.status.replaceAll('_', ' '), onboardingCase.personalEmail].join(' · ')),
        trailing: const Icon(Icons.chevron_right, size: 20),
        onTap: () async {
          await Navigator.of(context).push(MaterialPageRoute(builder: (_) => OnboardingCaseDetailScreen(caseSummary: onboardingCase)));
          _listKey.currentState?.reload();
        },
      ),
    );
  }
}

/// "Mobile Onboarding Wizard" — the candidate-basics step (name, contact,
/// proposed role, joining date). The full web wizard has the candidate fill
/// in 9 further sections themselves via their invite link once this case is
/// created — this is the HR-side "start a case" step, not the full form.
class OnboardingWizardScreen extends ConsumerStatefulWidget {
  const OnboardingWizardScreen({super.key});

  @override
  ConsumerState<OnboardingWizardScreen> createState() => _OnboardingWizardScreenState();
}

class _OnboardingWizardScreenState extends ConsumerState<OnboardingWizardScreen> {
  final _firstName = TextEditingController();
  final _lastName = TextEditingController();
  final _email = TextEditingController();
  final _mobile = TextEditingController();
  final _joiningDate = TextEditingController();
  bool _submitting = false;
  String? _formError;

  Future<void> _submit() async {
    if (_firstName.text.trim().isEmpty || _email.text.trim().isEmpty || DateTime.tryParse(_joiningDate.text.trim()) == null) {
      setState(() => _formError = 'First name, email, and a valid joining date are required.');
      return;
    }
    setState(() {
      _submitting = true;
      _formError = null;
    });
    try {
      await ref.read(onboardingRepositoryProvider).createCase({
        'candidate_first_name': _firstName.text.trim(),
        if (_lastName.text.trim().isNotEmpty) 'candidate_last_name': _lastName.text.trim(),
        'personal_email': _email.text.trim(),
        if (_mobile.text.trim().isNotEmpty) 'personal_mobile': _mobile.text.trim(),
        'proposed_joining_date': _joiningDate.text.trim(),
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
      appBar: AppBar(title: const Text('New onboarding case')),
      body: ListView(
        padding: const EdgeInsets.all(16),
        children: [
          if (_formError != null) ...[InlineAlert(message: _formError!), const SizedBox(height: 16)],
          Row(children: [
            Expanded(child: AuthFormField(label: 'First name', required: true, child: TextField(controller: _firstName, enabled: !_submitting))),
            const SizedBox(width: 12),
            Expanded(child: AuthFormField(label: 'Last name', child: TextField(controller: _lastName, enabled: !_submitting))),
          ]),
          const SizedBox(height: 16),
          AuthFormField(label: 'Personal email', required: true, child: TextField(controller: _email, enabled: !_submitting, keyboardType: TextInputType.emailAddress)),
          const SizedBox(height: 16),
          AuthFormField(label: 'Mobile', child: TextField(controller: _mobile, enabled: !_submitting)),
          const SizedBox(height: 16),
          AuthFormField(label: 'Proposed joining date', required: true, description: 'YYYY-MM-DD', child: TextField(controller: _joiningDate, enabled: !_submitting)),
          const SizedBox(height: 20),
          PrimaryButton(label: 'Create case', loading: _submitting, onPressed: _submit),
        ],
      ),
    );
  }
}
