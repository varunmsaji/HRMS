import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../../core/api/api_error.dart';
import '../data/onboarding_repository.dart' show SetupChecklist;
import 'onboarding_cases_screen.dart' show onboardingRepositoryProvider;
import '../../../core/widgets/ui.dart';

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
  // Null when the checklist cannot be shown (no permission or an older server): the screen then
  // shows the registration record alone.
  SetupChecklist? _checklist;

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
      final repo = ref.read(onboardingRepositoryProvider);
      SetupChecklist? checklist;
      try {
        checklist = await repo.getSetupChecklist();
      } catch (_) {}
      final progress = await repo.getSetupProgress();
      if (mounted) {
        setState(() {
          _status = progress.status;
          _currentStep = progress.currentStep;
          _steps = progress.steps;
          _checklist = checklist;
        });
      }
    } catch (e) {
      if (mounted) setState(() => _error = e is ApiError ? (e.status == 403 ? 'You do not have permission to view company setup progress.' : e.message) : 'Something went wrong.');
    } finally {
      if (mounted) setState(() => _loading = false);
    }
  }

  List<Widget> _checklistSection(SetupChecklist checklist) => [
        for (final item in checklist.items)
          Padding(
            padding: const EdgeInsets.only(top: 8),
            child: ListRowCard(
              leading: IconBadge(
                icon: item.isComplete ? Icons.check_rounded : Icons.radio_button_unchecked_rounded,
                tone: item.isComplete ? Tone.success : Tone.neutral,
                size: 36,
              ),
              title: item.label,
              subtitle: item.description,
              onTap: item.isComplete ? null : () => context.push(item.appPath),
              showChevron: !item.isComplete,
              trailing: StatusChip(
                label: item.isComplete ? 'Done' : (item.required ? 'To do' : 'Optional'),
                tone: item.isComplete ? Tone.success : (item.required ? Tone.warning : Tone.neutral),
              ),
            ),
          ),
      ];

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
          ? const ListSkeleton()
          : _error != null
              ? StateMessage(icon: Icons.error_outline_rounded, tone: Tone.danger, title: 'Something went wrong', message: _error!, actionLabel: 'Retry', onAction: _load)
              : RefreshIndicator(
                  onRefresh: _load,
                  child: ListView(
                    padding: const EdgeInsets.all(16),
                    children: [
                      HeroCard(
                        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                          const Text('Company setup', style: TextStyle(color: Colors.white70, fontSize: 12.5)),
                          const SizedBox(height: 4),
                          Text(_checklist != null ? '${_checklist!.requiredComplete} of ${_checklist!.requiredTotal} essentials done' : (complete ? 'Setup complete' : '$done of ${_steps.length} complete'), style: const TextStyle(color: Colors.white, fontSize: 22, fontWeight: FontWeight.w800)),
                          const SizedBox(height: 4),
                          Text(_checklist != null ? 'What your company needs to run attendance and leave.' : 'Track onboarding progress for your company.', style: TextStyle(color: Colors.white70, fontSize: 12.5)),
                          const SizedBox(height: 14),
                          ClipRRect(
                            borderRadius: BorderRadius.circular(8),
                            child: LinearProgressIndicator(
                              value: _checklist != null ? (_checklist!.requiredTotal == 0 ? 0 : _checklist!.requiredComplete / _checklist!.requiredTotal) : (_steps.isEmpty ? 0 : done / _steps.length),
                              minHeight: 8,
                              backgroundColor: Colors.white24,
                              valueColor: const AlwaysStoppedAnimation(Colors.white),
                            ),
                          ),
                        ]),
                      ),
                      if (_checklist != null) ..._checklistSection(_checklist!),
                      if (_checklist != null)
                        const Padding(padding: EdgeInsets.fromLTRB(4, 16, 4, 8), child: Text('Registration', style: TextStyle(fontWeight: FontWeight.w700))),
                      if (!complete && next != null)
                        Padding(
                          padding: const EdgeInsets.only(top: 12),
                          child: AppCard(
                            child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                              const Text('Next step', style: TextStyle(fontWeight: FontWeight.w700)),
                              const SizedBox(height: 4),
                              Text('Finish setting up “${nextLabel ?? _currentStep}” to keep onboarding moving.', style: TextStyle(color: scheme.onSurfaceVariant)),
                              const SizedBox(height: 12),
                              FilledButton(onPressed: () => context.push(next.$2), child: Text(next.$1)),
                            ]),
                          ),
                        ),
                      const SizedBox(height: 12),
                      for (final step in _steps)
                        Padding(
                          padding: const EdgeInsets.only(bottom: 8),
                          child: ListRowCard(
                            leading: IconBadge(
                              icon: step.isComplete ? Icons.check_rounded : Icons.radio_button_unchecked_rounded,
                              tone: step.isComplete ? Tone.success : Tone.neutral,
                              size: 36,
                            ),
                            title: step.label,
                            showChevron: false,
                            trailing: StatusChip(label: step.isComplete ? 'Complete' : 'Pending', tone: step.isComplete ? Tone.success : Tone.warning),
                          ),
                        ),
                    ],
                  ),
                ),
    );
  }
}
