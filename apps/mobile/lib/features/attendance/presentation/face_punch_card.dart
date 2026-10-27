import 'package:flutter/material.dart';
import '../../../core/widgets/ui.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../core/api/api_client.dart';
import '../../../core/api/api_error.dart';
import '../data/attendance_repository.dart';
import '../domain/face_liveness_capture.dart';
import 'face_enrollment_screen.dart';
import 'face_liveness_capture_screen.dart';

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

enum _Phase { idle, challenge, capturing, verifying }

/// Face attendance for the signed-in employee. Shows whichever applies: set up (when HR has
/// opened enrollment), waiting for HR approval, rejected, not set up — or, once enrolled,
/// face punch in/out: server challenge -> guided capture -> server liveness on every frame +
/// face match -> server-timed punch. The app never decides liveness and offers no way to
/// override a failed check. Server messages are shown as-is.
class FacePunchCard extends ConsumerStatefulWidget {
  const FacePunchCard({super.key, this.onPunched, this.onStatus});

  /// Called after a successful punch so the parent can refresh its attendance list.
  final VoidCallback? onPunched;

  /// Reports the loaded enrollment status so the parent can hide the plain punch controls while
  /// [FaceEnrollmentStatus.faceVerificationRequired] is true.
  final ValueChanged<FaceEnrollmentStatus>? onStatus;

  @override
  ConsumerState<FacePunchCard> createState() => _FacePunchCardState();
}

class _FacePunchCardState extends ConsumerState<FacePunchCard> {
  FaceEnrollmentStatus? _status;
  String? _loadError;
  bool _loading = true;
  _Phase _phase = _Phase.idle;

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
        widget.onStatus?.call(status);
      }
    } catch (error) {
      if (mounted) setState(() => _loadError = describeApiError(error));
    } finally {
      if (mounted) setState(() => _loading = false);
    }
  }

  Future<void> _openEnrollment() async {
    final submitted = await Navigator.of(context).push<bool>(
      MaterialPageRoute(builder: (_) => const FaceEnrollmentScreen()),
    );
    if (submitted == true && mounted) {
      ScaffoldMessenger.of(context).showSnackBar(const SnackBar(
        content: Text('Face submitted. HR will review it before face punching is switched on.'),
      ));
    }
    await _load();
  }

  /// The key of a face punch whose outcome is unknown ([facePunchOutcomeUnknown]). The next
  /// attempt in the same direction reuses it — with a fresh challenge and capture — so a punch
  /// the server did record is returned, not recorded twice.
  ({String direction, String key})? _unconfirmedPunch;

  void _show(String message) {
    if (mounted) ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(message)));
  }

  Future<void> _punch(String direction) async {
    if (_phase != _Phase.idle) return; // one attempt at a time
    final repository = ref.read(attendanceRepositoryProvider);
    setState(() => _phase = _Phase.challenge);
    List<List<int>>? frames;
    try {
      final FaceLivenessSession session;
      try {
        session = await repository.startFaceLivenessSession(direction);
      } catch (error) {
        _show(describeApiError(error));
        if (error is ApiError && error.code == 'FACE_NOT_ENROLLED') _load();
        return;
      }
      if (!mounted) return;

      setState(() => _phase = _Phase.capturing);
      final outcome = await ref.read(faceLivenessCaptureProvider)(context, session);
      switch (outcome) {
        case FaceCaptureFrames(frames: final captured):
          frames = captured;
        case FaceCaptureCancelled():
          return;
        case FaceCapturePermissionDenied():
          _show('Camera access is off. Allow camera access for this app in your phone settings, then try again.');
          return;
        case FaceCaptureExpired():
          _show('That took too long. Please try again.');
          return;
        case FaceCaptureFailed(message: final message):
          _show(message);
          return;
      }
      if (!mounted) return;

      setState(() => _phase = _Phase.verifying);
      final pending = _unconfirmedPunch;
      final key = pending != null && pending.direction == direction ? pending.key : ApiClient.newIdempotencyKey();
      try {
        final result = await repository.facePunchMe(
          direction: direction,
          livenessSessionId: session.sessionId,
          frames: frames,
          idempotencyKey: key,
        );
        _unconfirmedPunch = null;
        final label = result.direction == 'IN' ? 'Punched in' : 'Punched out';
        _show('$label · face verified (${(result.similarity * 100).round()}% match)');
        widget.onPunched?.call();
      } catch (error) {
        final unknown = facePunchOutcomeUnknown(error);
        // Unknown outcome: keep the key for the retry. Any real answer settles this attempt.
        _unconfirmedPunch = unknown ? (direction: direction, key: key) : null;
        _show(unknown
            ? 'No response from the server — your punch may have been recorded. Trying again is safe: it will not be recorded twice.'
            : describeApiError(error));
        if (error is ApiError && error.code == 'FACE_NOT_ENROLLED') _load();
      }
    } finally {
      frames?.clear(); // drop the face images as soon as the attempt is over
      if (mounted) setState(() => _phase = _Phase.idle);
    }
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
      final busy = _phase != _Phase.idle;
      message = switch (_phase) {
        _Phase.challenge => 'Preparing a face check…',
        _Phase.capturing => 'Look at the camera…',
        _Phase.verifying => 'Verifying your face…',
        _Phase.idle => 'Punch with your face. Hold the phone yourself, in good light, with no one else in frame.',
      };
      actions = [
        if (busy) const LinearProgressIndicator(),
        if (busy) const SizedBox(height: 12),
        Row(children: [
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

    return AppCard(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          Row(children: [
            const IconBadge(icon: Icons.face_retouching_natural, size: 36),
            const SizedBox(width: 12),
            Text('Face attendance', style: text.headlineSmall?.copyWith(fontWeight: FontWeight.w700)),
          ]),
          const SizedBox(height: 10),
          Text(message, style: text.bodyMedium?.copyWith(color: scheme.onSurfaceVariant, height: 1.4)),
          if (actions.isNotEmpty) const SizedBox(height: 14),
          ...actions,
        ],
      ),
    );
  }
}
