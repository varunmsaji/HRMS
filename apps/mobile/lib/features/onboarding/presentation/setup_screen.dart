import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../../core/api/api_error.dart';
import 'onboarding_cases_screen.dart' show onboardingRepositoryProvider;

/// Where each documented setup step sends the user to finish it (mirrors `STEP_DESTINATIONS` in
/// `apps/web/src/app/app/setup/page.tsx`).
const setupStepDestinations = {
  'COMPANY_PROFILE': ('Go to company profile', '/app/company'),
};

/// Company setup — `GET /companies/current/setup-progress`: overall status, the next step with a
/// shortcut, and each step as Complete/Pending. Rendered generically so more steps slot in.
class SetupScreen extends ConsumerStatefulWidget {
  const SetupScreen({super.key});

  @override
  ConsumerState<SetupScreen> createState() => _SetupScreenState();
}

class _SetupScreenState extends ConsumerState<SetupScreen> {
  bool _loading = true;
  String? _error;
  String? _status;
  String? _currentStep;
  List<dynamic> _steps = const [];

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
      final progress = await ref.read(onboardingRepositoryProvider).getSetupProgress();
      if (mounted) {
        setState(() {
          _status = progress.status;
          _currentStep = progress.currentStep;
          _steps = progress.steps;
        });
      }
    } catch (e) {
      if (mounted) setState(() => _error = e is ApiError ? (e.status == 403 ? 'You do not have permission to view company setup progress.' : e.message) : 'Something went wrong.');
    } finally {
      if (mounted) setState(() => _loading = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final scheme = Theme.of(context).colorScheme;
    final complete = _status == 'COMPLETE';
    final done = _steps.where((s) => s.isComplete).length;
    final next = _currentStep == null ? null : setupStepDestinations[_currentStep];
    final nextLabel = _steps.where((s) => s.code == _currentStep).map((s) => s.label).firstOrNull;
    return Scaffold(
      appBar: AppBar(title: const Text('Company setup')),
      body: _loading
          ? const Center(child: CircularProgressIndicator())
          : _error != null
              ? Center(child: Padding(padding: const EdgeInsets.all(24), child: Column(mainAxisSize: MainAxisSize.min, children: [Text(_error!, textAlign: TextAlign.center), const SizedBox(height: 16), FilledButton(onPressed: _load, child: const Text('Retry'))])))
              : RefreshIndicator(
                  onRefresh: _load,
                  child: ListView(
                    padding: const EdgeInsets.all(16),
                    children: [
                      Text('Track onboarding progress for your company.', style: TextStyle(color: scheme.onSurfaceVariant)),
                      const SizedBox(height: 12),
                      Chip(label: Text(complete ? 'Setup complete' : '$done of ${_steps.length} complete')),
                      if (!complete && next != null)
                        Container(
                          margin: const EdgeInsets.only(top: 12),
                          padding: const EdgeInsets.all(14),
                          decoration: BoxDecoration(border: Border.all(color: scheme.outlineVariant), borderRadius: BorderRadius.circular(12)),
                          child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                            const Text('Next step', style: TextStyle(fontWeight: FontWeight.w600)),
                            const SizedBox(height: 4),
                            Text('Finish setting up “${nextLabel ?? _currentStep}” to keep onboarding moving.'),
                            const SizedBox(height: 10),
                            FilledButton(onPressed: () => context.push(next.$2), child: Text(next.$1)),
                          ]),
                        ),
                      const SizedBox(height: 8),
                      for (final step in _steps)
                        ListTile(
                          contentPadding: EdgeInsets.zero,
                          title: Text(step.label),
                          trailing: Chip(
                            visualDensity: VisualDensity.compact,
                            avatar: step.isComplete ? const Icon(Icons.check_circle, size: 16, color: Colors.green) : null,
                            label: Text(step.isComplete ? 'Complete' : 'Pending'),
                          ),
                        ),
                    ],
                  ),
                ),
    );
  }
}
