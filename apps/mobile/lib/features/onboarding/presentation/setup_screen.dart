import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import 'onboarding_cases_screen.dart' show onboardingRepositoryProvider;

/// "Mobile Setup Checklist" — `GET /companies/current/setup-progress`.
/// Currently a single-item registry (`COMPANY_PROFILE`) server-side, but
/// rendered generically so more steps slot in without a mobile change.
class SetupScreen extends ConsumerStatefulWidget {
  const SetupScreen({super.key});

  @override
  ConsumerState<SetupScreen> createState() => _SetupScreenState();
}

class _SetupScreenState extends ConsumerState<SetupScreen> {
  bool _loading = true;
  String? _status;
  List<dynamic> _steps = const [];

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    try {
      final progress = await ref.read(onboardingRepositoryProvider).getSetupProgress();
      if (mounted) {
        setState(() {
          _status = progress.status;
          _steps = progress.steps;
        });
      }
    } finally {
      if (mounted) setState(() => _loading = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('Setup')),
      body: _loading
          ? const Center(child: CircularProgressIndicator())
          : RefreshIndicator(
              onRefresh: _load,
              child: ListView(
                padding: const EdgeInsets.all(16),
                children: [
                  Text('Status: ${_status ?? '—'}', style: Theme.of(context).textTheme.headlineSmall),
                  const SizedBox(height: 16),
                  for (final step in _steps)
                    ListTile(
                      leading: Icon(step.isComplete ? Icons.check_circle : Icons.radio_button_unchecked, color: step.isComplete ? Colors.green : null),
                      title: Text(step.label),
                    ),
                ],
              ),
            ),
    );
  }
}
