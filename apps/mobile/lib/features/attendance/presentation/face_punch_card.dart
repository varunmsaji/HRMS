import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:image_picker/image_picker.dart';

import '../../../core/api/api_client.dart';
import '../../../core/api/api_error.dart';
import '../data/attendance_repository.dart';
import 'face_enrollment_screen.dart';

/// Opens the front camera and returns the selfie as JPEG bytes, or null if cancelled.
typedef FaceCapture = Future<List<int>?> Function();

/// `imageQuality` forces a JPEG re-encode (iOS would otherwise hand back HEIC, which the
/// server rejects); 1280px keeps uploads small while leaving plenty of face detail.
final faceCaptureProvider = Provider<FaceCapture>((ref) {
  return () async {
    final photo = await ImagePicker().pickImage(
      source: ImageSource.camera,
      preferredCameraDevice: CameraDevice.front,
      maxWidth: 1280,
      maxHeight: 1280,
      imageQuality: 90,
    );
    return photo?.readAsBytes();
  };
});

/// Face attendance for the signed-in employee. Shows whichever applies: set up (when HR has
/// opened enrollment), waiting for HR approval, rejected, not set up — or, once enrolled,
/// selfie punch in/out (server liveness + face match -> server-timed punch). Server messages
/// are shown as-is.
class FacePunchCard extends ConsumerStatefulWidget {
  const FacePunchCard({super.key, this.onPunched});

  /// Called after a successful punch so the parent can refresh its attendance list.
  final VoidCallback? onPunched;

  @override
  ConsumerState<FacePunchCard> createState() => _FacePunchCardState();
}

class _FacePunchCardState extends ConsumerState<FacePunchCard> {
  FaceEnrollmentStatus? _status;
  String? _loadError;
  bool _loading = true;
  String? _verifyingDirection;

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
      if (mounted) setState(() => _status = status);
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

  /// The key of a face punch whose outcome is unknown (no response). A retry of the same
  /// direction reuses it, so a punch the server did record is returned, not recorded twice.
  ({String direction, String key})? _unconfirmedPunch;

  Future<void> _punch(String direction) async {
    final messenger = ScaffoldMessenger.of(context);
    final List<int>? photo;
    try {
      photo = await ref.read(faceCaptureProvider)();
    } catch (_) {
      messenger.showSnackBar(const SnackBar(
        content: Text('Could not open the camera. Allow camera access for this app in your phone settings.'),
      ));
      return;
    }
    if (photo == null || !mounted) return;

    setState(() => _verifyingDirection = direction);
    final pending = _unconfirmedPunch;
    final key = pending != null && pending.direction == direction ? pending.key : ApiClient.newIdempotencyKey();
    try {
      final result = await ref.read(attendanceRepositoryProvider).facePunchMe(direction: direction, photoJpeg: photo, idempotencyKey: key);
      _unconfirmedPunch = null;
      final label = result.direction == 'IN' ? 'Punched in' : 'Punched out';
      messenger.showSnackBar(SnackBar(
        content: Text('$label · face verified (${(result.similarity * 100).round()}% match)'),
      ));
      widget.onPunched?.call();
    } catch (error) {
      // No response: keep the key for a retry. Any real answer settles this attempt.
      _unconfirmedPunch = error is ApiError && error.status == 0 ? (direction: direction, key: key) : null;
      messenger.showSnackBar(SnackBar(content: Text(describeApiError(error))));
      if (error is ApiError && error.code == 'FACE_NOT_ENROLLED') _load();
    } finally {
      if (mounted) setState(() => _verifyingDirection = null);
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
      final busy = _verifyingDirection != null;
      message = busy
          ? 'Verifying your face…'
          : 'Take a selfie to punch. Face the camera in good light, with no one else in frame.';
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

    return Container(
      padding: const EdgeInsets.all(16),
      decoration: BoxDecoration(
        color: scheme.surfaceContainerLowest,
        borderRadius: BorderRadius.circular(12),
        border: Border.all(color: scheme.outlineVariant),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          Row(children: [
            Icon(Icons.face_retouching_natural, color: scheme.primary),
            const SizedBox(width: 8),
            Text('Face attendance', style: text.titleSmall),
          ]),
          const SizedBox(height: 4),
          Text(message, style: text.bodySmall?.copyWith(color: scheme.onSurfaceVariant)),
          if (actions.isNotEmpty) const SizedBox(height: 12),
          ...actions,
        ],
      ),
    );
  }
}
