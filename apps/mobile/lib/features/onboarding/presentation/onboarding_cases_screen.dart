import 'package:flutter/material.dart';
import '../../../core/widgets/ui.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../core/forms/choice_sources.dart';
import '../../../core/forms/spec_form_screen.dart';
import '../../../core/providers.dart';
import '../../../core/widgets/async_list_screen.dart';
import '../data/onboarding_repository.dart';
import '../domain/onboarding_form_spec.dart';
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
    final client = ref.read(apiClientProvider);
    final saved = await openSpecForm(
      context,
      title: 'New onboarding case',
      spec: onboardingCaseSpec,
      loadChoices: () => loadChoices(client, const ['branches', 'departments', 'designations']),
      onSubmit: (payload, _) async => ref.read(onboardingRepositoryProvider).createCase(payload),
    );
    if (saved) _listKey.currentState?.reload();
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
      searchText: (c) => '${c.candidateName} ${c.personalEmail} ${c.status}',
      itemBuilder: (context, onboardingCase) => ListRowCard(
        title: onboardingCase.candidateName,
        subtitle: onboardingCase.personalEmail,
        leading: InitialsAvatar(name: onboardingCase.candidateName),
        trailing: StatusChip.status(onboardingCase.status),
        onTap: () async {
          await Navigator.of(context).push(MaterialPageRoute(builder: (_) => OnboardingCaseDetailScreen(caseSummary: onboardingCase)));
          _listKey.currentState?.reload();
        },
      ),
    );
  }
}
