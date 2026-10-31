import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../core/api/api_error.dart';
import '../data/attendance_repository.dart';
import '../domain/face_liveness_capture.dart';
import 'face_enrollment_screen.dart';
import 'face_liveness_capture_screen.dart';
import '../state/punch_controller.dart';
import 'context_punch_ui.dart';
import '../../../core/theme/employee_theme_scope.dart';
import '../../../core/theme/employee_tokens.dart';

/// Captures the frames for one server-issued liveness challenge.
typedef FaceLivenessCapture = Future<FaceCaptureOutcome> Function(BuildContext context, FaceLivenessSession session);

final faceLivenessCaptureProvider = Provider<FaceLivenessCapture>((ref) {
  return (context, session) async {
    final outcome = await Navigator.of(context).push<FaceCaptureOutcome>(
      MaterialPageRoute(fullscreenDialog: true, builder: (_) => FaceLivenessCaptureScreen(session: session)),
    );
    return outcome ?? const FaceCaptureCancelled();
  };
});

/// Face attendance for the signed-in employee. Shows whichever applies: set up (when HR has
/// opened enrollment), waiting for HR approval, rejected, not set up — or, once enrolled,
/// face punch in/out: server challenge -> guided capture -> server liveness on every frame +
/// face match -> server-timed punch. The app never decides liveness and offers no way to
/// override a failed check. Server messages are shown as-is.
class FacePunchCard extends ConsumerStatefulWidget {
  const FacePunchCard({super.key, this.onPunched, this.onStatus, this.onResolved, this.showButtons = true});

  /// Called after a successful punch so the parent can refresh its attendance list.
  final VoidCallback? onPunched;

  /// Reports the loaded enrollment status so the parent can hide the plain punch controls while
  /// [FaceEnrollmentStatus.faceVerificationRequired] is true.
  final ValueChanged<FaceEnrollmentStatus>? onStatus;

  /// Called once the status read has finished, whether it worked or not, so a screen that owns
  /// the punch buttons knows when it may offer them.
  final VoidCallback? onResolved;

  /// False when the screen's own sticky punch control takes over the face buttons; the card then
  /// keeps only the status sentences and progress.
  final bool showButtons;

  @override
  ConsumerState<FacePunchCard> createState() => _FacePunchCardState();
}

class _FacePunchCardState extends ConsumerState<FacePunchCard> {
  FaceEnrollmentStatus? _status;
  String? _loadError;
  bool _loading = true;

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    setState(() {
      _loading = true;
      _loadError = null;
    });
    try {
      final status = await ref.read(attendanceRepositoryProvider).getMyFaceEnrollment();
      if (mounted) {
        setState(() => _status = status);
        ref.read(punchControllerProvider.notifier).setFaceRequired(status.faceVerificationRequired);
        widget.onStatus?.call(status);
      }
    } catch (error) {
      if (mounted) setState(() => _loadError = describeApiError(error));
    } finally {
      if (mounted) {
        setState(() => _loading = false);
        widget.onResolved?.call();
      }
    }
  }

  Future<void> _openEnrollment() async {
    final submitted = await pushKeepingTheme<bool>(context, (_) => const FaceEnrollmentScreen());
    if (submitted == true && mounted) {
      ScaffoldMessenger.of(context).showSnackBar(const SnackBar(
        content: Text('Face submitted. HR will review it before face punching is switched on.'),
      ));
    }
    await _load();
  }

  /// The punch flow lives in [PunchController] (shared with Home); this supplies the dialogs and camera.
  void _punch(String direction) {
    final ui = ContextPunchUi(context, ref, onPunchedCallback: widget.onPunched, onFaceNotEnrolledCallback: _load);
    ref.read(punchControllerProvider.notifier).punchFace(direction, ui);
  }

  @override
  Widget build(BuildContext context) {
    final scheme = Theme.of(context).colorScheme;
    final text = Theme.of(context).textTheme;
    final status = _status;

    String message;
    List<Widget> actions = const [];
    if (_loading) {
      message = 'Loading…';
    } else if (_loadError != null) {
      message = _loadError!;
      actions = [OutlinedButton(onPressed: _load, child: const Text('Retry'))];
    } else if (status!.isEnrolled) {
      final phase = ref.watch(punchControllerProvider.select((s) => s.facePhase));
      final busy = phase != FacePhase.idle;
      message = switch (phase) {
        FacePhase.locating => 'Checking your location…',
        FacePhase.challenge => 'Preparing a face check…',
        FacePhase.capturing => 'Look at the camera…',
        FacePhase.verifying => 'Verifying your face…',
        FacePhase.idle => 'Punch with your face. Hold the phone yourself, in good light, with no one else in frame.',
      };
      actions = [
        if (busy) const LinearProgressIndicator(),
        if (busy) const SizedBox(height: 12),
        if (widget.showButtons) Row(children: [
          Expanded(
            child: FilledButton.icon(
              onPressed: busy ? null : () => _punch('IN'),
              icon: const Icon(Icons.camera_front),
              label: const Text('Face punch in'),
            ),
          ),
          const SizedBox(width: 12),
          Expanded(
            child: OutlinedButton.icon(
              onPressed: busy ? null : () => _punch('OUT'),
              icon: const Icon(Icons.camera_front_outlined),
              label: const Text('Face punch out'),
            ),
          ),
        ]),
      ];
    } else if (status.isPendingApproval) {
      message = 'Your face has been submitted and is waiting for HR approval.';
    } else if (status.canEnroll) {
      final expires = status.windowExpiresAt!.toLocal();
      message = 'HR has opened face enrollment for you until '
          '${MaterialLocalizations.of(context).formatShortDate(expires)} '
          '${MaterialLocalizations.of(context).formatTimeOfDay(TimeOfDay.fromDateTime(expires))}. '
          'It takes about a minute.';
      actions = [
        FilledButton.icon(
          onPressed: _openEnrollment,
          icon: const Icon(Icons.face),
          label: const Text('Set up face attendance'),
        ),
      ];
    } else if (status.profileStatus == 'REJECTED') {
      message = 'Your face enrollment was not approved. Ask HR to open it again.'
          '${status.reviewNote != null ? ' Reason: ${status.reviewNote}' : ''}';
    } else {
      message = 'Face attendance is not set up yet. Ask HR to open face enrollment for you.';
    }

    final t = EmployeeTokens.of(context);
    // Nothing to enroll in and nothing required: one quiet caption, no box.
    final notSetUp = !_loading && _loadError == null && !status!.isEnrolled && !status.isPendingApproval && !status.canEnroll && status.profileStatus != 'REJECTED';
    if (notSetUp) {
      return Padding(
        padding: const EdgeInsets.symmetric(vertical: 4),
        child: Text('Face attendance is not set up. Ask HR to open face enrollment for you.', style: text.bodySmall?.copyWith(color: t.inkSecondary)),
      );
    }
    // A flat inset, not a card with an icon badge: it is a status block, not a destination.
    return Container(
      padding: const EdgeInsets.all(14),
      decoration: BoxDecoration(color: t.inset, borderRadius: BorderRadius.circular(EmployeeTokens.radiusSurface)),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          Semantics(header: true, child: Text('FACE ATTENDANCE', style: text.labelMedium?.copyWith(color: t.inkSecondary))),
          const SizedBox(height: 6),
          Text(message, style: text.bodyMedium?.copyWith(color: scheme.onSurface, height: 1.4)),
          if (actions.isNotEmpty) const SizedBox(height: 12),
          ...actions,
        ],
      ),
    );
  }
}
