import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../core/api/api_error.dart';
import '../../../core/widgets/ui.dart';
import '../data/onboarding_repository.dart';
import 'onboarding_case_detail_screen.dart';
import 'onboarding_cases_screen.dart' show onboardingRepositoryProvider;

/// `/app/onboarding/:id`: opens one onboarding case from a link (a notification, the approvals
/// inbox). The detail screen needs the case summary up front, so this reads the case first.
class OnboardingCaseRouteScreen extends ConsumerStatefulWidget {
  const OnboardingCaseRouteScreen({super.key, required this.caseId});

  final String caseId;

  @override
  ConsumerState<OnboardingCaseRouteScreen> createState() => _OnboardingCaseRouteScreenState();
}

class _OnboardingCaseRouteScreenState extends ConsumerState<OnboardingCaseRouteScreen> {
  OnboardingCase? _case;
  ApiError? _error;

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    setState(() => _error = null);
    try {
      final loaded = await ref.read(onboardingRepositoryProvider).getCase(widget.caseId);
      if (mounted) setState(() => _case = loaded);
    } catch (e) {
      if (mounted) setState(() => _error = e is ApiError ? e : ApiError(status: 0, code: 'UNKNOWN_ERROR', message: 'Something went wrong.'));
    }
  }

  @override
  Widget build(BuildContext context) {
    final loaded = _case;
    if (loaded != null) return OnboardingCaseDetailScreen(caseSummary: loaded);
    final error = _error;
    final notFound = error?.status == 404 || error?.status == 403;
    return Scaffold(
      appBar: AppBar(title: const Text('Onboarding')),
      body: error == null
          ? const ListSkeleton(count: 3)
          : StateMessage(
              icon: notFound ? Icons.search_off_rounded : Icons.cloud_off_rounded,
              tone: notFound ? Tone.neutral : Tone.danger,
              title: notFound ? 'Not found' : 'Couldn\'t load this case',
              message: notFound ? 'This onboarding case was not found, or you don\'t have access to it.' : describeApiError(error),
              actionLabel: notFound ? null : 'Try again',
              onAction: notFound ? null : _load,
            ),
    );
  }
}
