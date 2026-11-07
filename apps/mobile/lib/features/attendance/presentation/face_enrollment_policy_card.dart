import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../core/api/api_error.dart';
import '../../../core/auth/permissions.dart';
import '../../../core/providers.dart';
import '../../../core/widgets/ui.dart';
import '../../auth/state/auth_controller.dart';

const _path = '/attendance/face-enrollment-policy';

/// Company setting: is face enrollment a required onboarding step? Mirrors web
/// `components/attendance/face-enrollment-policy-card.tsx`, shown above the Attendance Policies
/// list as on web. Policy only: it never marks anyone enrolled, and existing employees are not
/// locked out of attendance when it is turned on. Rendered only for callers holding
/// `ATTENDANCE.FACE_ENROLLMENT_MANAGE`; the server enforces it.
class FaceEnrollmentPolicyCard extends ConsumerWidget {
  const FaceEnrollmentPolicyCard({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final permissions = ref.watch(authControllerProvider).user?.permissions ?? const <String>[];
    if (!permissions.contains(attendanceFaceEnrollmentManage)) return const SizedBox.shrink();
    return const Padding(padding: EdgeInsets.only(bottom: 10), child: _Card());
  }
}

class _Card extends ConsumerStatefulWidget {
  const _Card();

  @override
  ConsumerState<_Card> createState() => _CardState();
}

class _CardState extends ConsumerState<_Card> {
  bool? _required;
  String? _error;
  bool _saving = false;

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    try {
      final policy = await ref.read(apiClientProvider).get<Map<String, dynamic>>(_path, parse: (d) => d as Map<String, dynamic>);
      if (mounted) setState(() => _required = policy['require_enrollment_on_onboarding'] == true);
    } catch (e) {
      if (mounted) setState(() => _error = describeApiError(e));
    }
  }

  Future<void> _toggle(bool next) async {
    setState(() => _saving = true);
    final messenger = ScaffoldMessenger.of(context);
    try {
      final policy = await ref.read(apiClientProvider).put<Map<String, dynamic>>(_path, body: {'require_enrollment_on_onboarding': next}, parse: (d) => d as Map<String, dynamic>);
      if (!mounted) return;
      setState(() => _required = policy['require_enrollment_on_onboarding'] == true);
      messenger.showSnackBar(SnackBar(content: Text(next ? 'Face enrollment is now required in onboarding' : 'Face enrollment is optional in onboarding')));
    } catch (e) {
      messenger.showSnackBar(SnackBar(content: Text('Could not update the setting. ${describeApiError(e)}')));
    } finally {
      if (mounted) setState(() => _saving = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final muted = TextStyle(fontSize: 12.5, color: theme.colorScheme.onSurfaceVariant);
    return AppCard(
      padding: const EdgeInsets.fromLTRB(14, 12, 14, 8),
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Row(children: [
          Icon(Icons.face_retouching_natural_outlined, size: 18, color: theme.colorScheme.onSurfaceVariant),
          const SizedBox(width: 8),
          Text('Face enrollment during onboarding', style: theme.textTheme.titleSmall?.copyWith(fontWeight: FontWeight.w600)),
        ]),
        if (_error != null)
          Padding(padding: const EdgeInsets.symmetric(vertical: 8), child: Semantics(liveRegion: true, child: Text(_error!, style: muted)))
        else
          SwitchListTile(
            contentPadding: EdgeInsets.zero,
            value: _required ?? false,
            onChanged: _required == null || _saving ? null : _toggle,
            title: const Text('Require face enrollment', style: TextStyle(fontWeight: FontWeight.w600)),
            subtitle: Text(
              'When on, onboarding is not complete until the employee enrolls and HR approves. '
              'When off, employees can be onboarded without it and enroll later from the app.',
              style: muted,
            ),
          ),
      ]),
    );
  }
}
