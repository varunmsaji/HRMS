import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../core/api/api_error.dart';
import '../../../core/providers.dart';
import '../../../core/widgets/async_list_screen.dart';
import '../../auth/presentation/widgets/auth_form_field.dart';
import '../data/onboarding_repository.dart';

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
          await Navigator.of(context).push(MaterialPageRoute(builder: (_) => OnboardingCaseReviewScreen(caseSummary: onboardingCase)));
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

/// "Mobile Onboarding Case Review" — status, section review states, and the
/// admin actions (send invite / request changes / activate).
class OnboardingCaseReviewScreen extends ConsumerStatefulWidget {
  const OnboardingCaseReviewScreen({super.key, required this.caseSummary});
  final OnboardingCase caseSummary;

  @override
  ConsumerState<OnboardingCaseReviewScreen> createState() => _OnboardingCaseReviewScreenState();
}

class _OnboardingCaseReviewScreenState extends ConsumerState<OnboardingCaseReviewScreen> {
  bool _loading = true;
  OnboardingCaseDetail? _detail;
  bool _busy = false;
  String? _message;

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    try {
      final detail = await ref.read(onboardingRepositoryProvider).getCase(widget.caseSummary.id);
      if (mounted) setState(() => _detail = detail);
    } catch (_) {
    } finally {
      if (mounted) setState(() => _loading = false);
    }
  }

  Future<void> _sendInvite() async {
    setState(() => _busy = true);
    try {
      final result = await ref.read(onboardingRepositoryProvider).sendInvite(widget.caseSummary.id);
      setState(() => _message = result['email_sent'] == true ? 'Invite sent.' : 'Invite created: ${result['invite_url']}');
      _load();
    } catch (error) {
      setState(() => _message = error is ApiError ? error.message : 'Something went wrong.');
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  Future<void> _requestChanges() async {
    setState(() => _busy = true);
    try {
      await ref.read(onboardingRepositoryProvider).requestChanges(widget.caseSummary.id);
      setState(() => _message = 'Changes requested.');
      _load();
    } catch (error) {
      setState(() => _message = error is ApiError ? error.message : 'Something went wrong.');
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  Future<void> _activate() async {
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (context) => AlertDialog(
        title: const Text('Activate employee'),
        content: const Text('This creates a real employee record from this case. This cannot be undone.'),
        actions: [
          TextButton(onPressed: () => Navigator.of(context).pop(false), child: const Text('Cancel')),
          FilledButton(onPressed: () => Navigator.of(context).pop(true), child: const Text('Activate')),
        ],
      ),
    );
    if (confirmed != true) return;
    setState(() => _busy = true);
    try {
      await ref.read(onboardingRepositoryProvider).activate(widget.caseSummary.id);
      setState(() => _message = 'Activated.');
      _load();
    } catch (error) {
      setState(() => _message = error is ApiError ? error.message : 'Something went wrong.');
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final detail = _detail;
    final status = detail?.status ?? widget.caseSummary.status;
    return Scaffold(
      appBar: AppBar(title: Text(widget.caseSummary.candidateName)),
      body: _loading
          ? const Center(child: CircularProgressIndicator())
          : ListView(
              padding: const EdgeInsets.all(16),
              children: [
                if (_message != null) ...[InlineAlert(message: _message!), const SizedBox(height: 16)],
                Text('Status: ${status.replaceAll('_', ' ')}', style: Theme.of(context).textTheme.headlineSmall),
                Text(widget.caseSummary.personalEmail),
                if (detail?.tokenStatus != null) Text('Invite: ${detail!.tokenStatus}'),
                const SizedBox(height: 20),
                if (detail != null && detail.sectionReviews.isNotEmpty) ...[
                  Text('Sections', style: Theme.of(context).textTheme.labelMedium),
                  const SizedBox(height: 8),
                  for (final review in detail.sectionReviews)
                    ListTile(
                      contentPadding: EdgeInsets.zero,
                      title: Text((review['section'] as String).replaceAll('_', ' ')),
                      trailing: Text(review['status'] as String),
                    ),
                  const SizedBox(height: 12),
                ],
                if (status == 'DRAFT') FilledButton(onPressed: _busy ? null : _sendInvite, child: const Text('Send invite')),
                if (status == 'UNDER_REVIEW') ...[
                  OutlinedButton(onPressed: _busy ? null : _requestChanges, child: const Text('Request changes')),
                  const SizedBox(height: 8),
                ],
                if (status == 'VERIFIED') FilledButton(onPressed: _busy ? null : _activate, child: const Text('Activate employee')),
              ],
            ),
    );
  }
}
