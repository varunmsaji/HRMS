import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:image_picker/image_picker.dart';

import '../../../core/api/api_error.dart';
import 'holiday_calendars_screen.dart' show attendanceRepositoryProvider;

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

/// Face punch in/out for the signed-in employee: selfie -> server liveness + face match ->
/// server-timed punch. Every rejection message comes from the server and is shown as-is.
class FacePunchCard extends ConsumerStatefulWidget {
  const FacePunchCard({super.key, this.onPunched});

  /// Called after a successful punch so the parent can refresh its attendance list.
  final VoidCallback? onPunched;

  @override
  ConsumerState<FacePunchCard> createState() => _FacePunchCardState();
}

class _FacePunchCardState extends ConsumerState<FacePunchCard> {
  String? _verifyingDirection;

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
    try {
      final result = await ref.read(attendanceRepositoryProvider).facePunchMe(direction: direction, photoJpeg: photo);
      final label = result.direction == 'IN' ? 'Punched in' : 'Punched out';
      messenger.showSnackBar(SnackBar(
        content: Text('$label · face verified (${(result.similarity * 100).round()}% match)'),
      ));
      widget.onPunched?.call();
    } catch (error) {
      messenger.showSnackBar(SnackBar(content: Text(describeApiError(error))));
    } finally {
      if (mounted) setState(() => _verifyingDirection = null);
    }
  }

  @override
  Widget build(BuildContext context) {
    final scheme = Theme.of(context).colorScheme;
    final busy = _verifyingDirection != null;

    return Container(
      padding: const EdgeInsets.all(16),
      decoration: BoxDecoration(
        color: scheme.surfaceContainerLowest,
        borderRadius: BorderRadius.circular(12),
        border: Border.all(color: scheme.outlineVariant),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(children: [
            Icon(Icons.face_retouching_natural, color: scheme.primary),
            const SizedBox(width: 8),
            Text('Face attendance', style: Theme.of(context).textTheme.titleSmall),
          ]),
          const SizedBox(height: 4),
          Text(
            busy
                ? 'Verifying your face…'
                : 'Take a selfie to punch. Face the camera in good light, with no one else in frame.',
            style: Theme.of(context).textTheme.bodySmall?.copyWith(color: scheme.onSurfaceVariant),
          ),
          const SizedBox(height: 12),
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
        ],
      ),
    );
  }
}
