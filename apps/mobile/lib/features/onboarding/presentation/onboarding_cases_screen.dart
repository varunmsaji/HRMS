import 'package:flutter/material.dart';
import '../../../core/widgets/ui.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../core/forms/choice_sources.dart';
import '../../../core/forms/spec_form_screen.dart';
import '../../../core/providers.dart';
import '../../../core/widgets/async_list_screen.dart';
import '../data/onboarding_repository.dart';
import '../domain/onboarding_invitation.dart';
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
  String? _status;
  ({int total, Map<String, int> byStatus})? _counts;

  @override
  void initState() {
    super.initState();
    _loadCounts();
  }

  /// The tabs still work without their numbers.
  Future<void> _loadCounts() async {
    try {
      final counts = await ref.read(onboardingRepositoryProvider).getStatusCounts();
      if (mounted) setState(() => _counts = counts);
    } catch (_) {}
  }

  void _reload() {
    _listKey.currentState?.reload();
    _loadCounts();
  }

  Widget _tabs() {
    final counts = _counts;
    return SizedBox(
      height: 48,
      child: ListView(
        scrollDirection: Axis.horizontal,
        padding: const EdgeInsets.fromLTRB(16, 4, 16, 4),
        children: [
          for (final (label, status) in onboardingStatusTabs)
            Padding(
              padding: const EdgeInsets.only(right: 8),
              child: ChoiceChip(
                label: Text(counts == null ? label : '$label (${status == null ? counts.total : counts.byStatus[status] ?? 0})'),
                selected: _status == status,
                onSelected: (_) {
                  setState(() => _status = status);
                  _reload();
                },
              ),
            ),
        ],
      ),
    );
  }

  Future<void> _openWizard() async {
    final client = ref.read(apiClientProvider);
    OnboardingCase? created;
    final saved = await openSpecForm(
      context,
      title: 'New onboarding case',
      spec: onboardingCaseSpec,
      loadChoices: () => loadChoices(client, const ['branches', 'departments', 'designations']),
      onSubmit: (payload, _) async => created = await ref.read(onboardingRepositoryProvider).createCase(payload),
    );
    if (!saved || !mounted) return;
    _reload();
    // On to the invitation straight away, as on the web. Nothing is sent without a tap.
    final newCase = created;
    if (newCase == null) return;
    await Navigator.of(context).push(MaterialPageRoute(builder: (_) => OnboardingCaseDetailScreen(caseSummary: newCase, composeOnOpen: true)));
    if (mounted) _reload();
  }

  @override
  Widget build(BuildContext context) {
    return AsyncListScreen<OnboardingCase>(
      key: _listKey,
      title: 'Onboarding',
      fetch: () => ref.read(onboardingRepositoryProvider).listCases(status: _status),
      header: _tabs(),
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
          _reload();
        },
      ),
    );
  }
}
