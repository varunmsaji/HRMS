import 'dart:io';

import 'package:camera/camera.dart';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:google_mlkit_face_detection/google_mlkit_face_detection.dart';

import '../../../core/api/api_error.dart';
import '../domain/face_pose_tracker.dart';
import '../data/attendance_repository.dart' show attendanceRepositoryProvider;
import 'camera_input_image.dart';

enum _Stage { consent, capturing, review, submitting }

/// One-time guided face enrollment inside an HR-opened window: consent -> five auto-captured
/// angles (live camera + on-device face detection) -> review -> submit for HR approval.
/// Pops with `true` once submitted.
class FaceEnrollmentScreen extends ConsumerStatefulWidget {
  const FaceEnrollmentScreen({super.key});

  @override
  ConsumerState<FaceEnrollmentScreen> createState() => _FaceEnrollmentScreenState();
}

class _FaceEnrollmentScreenState extends ConsumerState<FaceEnrollmentScreen> {
  _Stage _stage = _Stage.consent;
  bool _consent = false;
  String? _error;

  CameraController? _camera;
  CameraDescription? _cameraDescription;
  FaceDetector? _detector;
  FacePoseTracker _tracker = FacePoseTracker();
  final Map<String, Uint8List> _photos = {};
  bool _processingFrame = false;
  bool _capturing = false;
  String? _hint;

  @override
  void dispose() {
    _stopCamera();
    super.dispose();
  }

  Future<void> _startCapture() async {
    setState(() {
      _stage = _Stage.capturing;
      _error = null;
      _hint = null;
      _photos.clear();
      _tracker = FacePoseTracker();
    });
    try {
      final cameras = await availableCameras();
      _cameraDescription = cameras.firstWhere(
        (c) => c.lensDirection == CameraLensDirection.front,
        orElse: () => cameras.first,
      );
      final controller = CameraController(
        _cameraDescription!,
        // 720p keeps each capture well under the server's 5 MB limit with plenty of face detail.
        ResolutionPreset.high,
        enableAudio: false,
        imageFormatGroup: Platform.isAndroid ? ImageFormatGroup.nv21 : ImageFormatGroup.bgra8888,
      );
      await controller.initialize();
      _detector ??= FaceDetector(
        options: FaceDetectorOptions(performanceMode: FaceDetectorMode.fast, minFaceSize: 0.25),
      );
      if (!mounted) {
        await controller.dispose();
        return;
      }
      setState(() => _camera = controller);
      await controller.startImageStream(_onFrame);
    } on CameraException catch (e) {
      _fail(e.code.contains('AccessDenied')
          ? 'Camera access is off. Allow camera access for this app in your phone settings, then try again.'
          : 'Could not start the camera. Please try again.');
    }
  }

  Future<void> _stopCamera() async {
    final controller = _camera;
    _camera = null;
    if (controller != null) {
      if (controller.value.isStreamingImages) await controller.stopImageStream();
      await controller.dispose();
    }
    await _detector?.close();
    _detector = null;
  }

  void _fail(String message) {
    _stopCamera();
    if (mounted) {
      setState(() {
        _stage = _Stage.consent;
        _error = message;
      });
    }
  }

  Future<void> _onFrame(CameraImage image) async {
    if (_processingFrame || _capturing || _tracker.isDone) return;
    final input = _toInputImage(image);
    final detector = _detector;
    if (input == null || detector == null) return;
    _processingFrame = true;
    try {
      final faces = await detector.processImage(input);
      final reading = FacePoseReading(
        faceCount: faces.length,
        yaw: faces.length == 1 ? faces.first.headEulerAngleY : null,
        pitch: faces.length == 1 ? faces.first.headEulerAngleX : null,
      );
      final ready = _tracker.accept(reading);
      if (mounted) setState(() => _hint = _tracker.hintFor(reading));
      if (ready) await _captureCurrentStep();
    } catch (_) {
      // A dropped frame is harmless; the next one is analysed instead.
    } finally {
      _processingFrame = false;
    }
  }

  Future<void> _captureCurrentStep() async {
    final controller = _camera;
    if (controller == null) return;
    _capturing = true;
    try {
      await controller.stopImageStream();
      final file = await controller.takePicture();
      _photos[_tracker.current.angle] = await readAndDeleteCapture(file);
      HapticFeedback.mediumImpact();
      _tracker.advance();
      if (_tracker.isDone) {
        await _stopCamera();
        if (mounted) setState(() => _stage = _Stage.review);
      } else {
        if (mounted) setState(() {});
        await controller.startImageStream(_onFrame);
      }
    } catch (_) {
      _fail('Could not take the photo. Please try again.');
    } finally {
      _capturing = false;
    }
  }

  InputImage? _toInputImage(CameraImage image) {
    final camera = _cameraDescription;
    final controller = _camera;
    if (camera == null || controller == null) return null;
    return cameraFrameToInputImage(image, camera, controller);
  }

  Future<void> _submit() async {
    setState(() {
      _stage = _Stage.submitting;
      _error = null;
    });
    try {
      await ref.read(attendanceRepositoryProvider).submitFaceEnrollment(photos: _photos, consentConfirmed: _consent);
      if (mounted) Navigator.of(context).pop(true);
    } catch (error) {
      if (mounted) {
        setState(() {
          _stage = _Stage.review;
          _error = describeApiError(error);
        });
      }
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('Set up face attendance')),
      body: SafeArea(
        child: switch (_stage) {
          _Stage.consent => _buildConsent(context),
          _Stage.capturing => _buildCapture(context),
          _Stage.review || _Stage.submitting => _buildReview(context),
        },
      ),
    );
  }

  Widget _buildConsent(BuildContext context) {
    final text = Theme.of(context).textTheme;
    return ListView(
      padding: const EdgeInsets.all(20),
      children: [
        Text('Register your face', style: text.titleLarge),
        const SizedBox(height: 12),
        const Text(
          'You will be asked to look straight ahead, turn your head to each side, and tilt it up '
          'and down. Photos are taken automatically. Find good light, remove sunglasses or a mask, '
          'and make sure no one else is in view.',
        ),
        const SizedBox(height: 12),
        const Text(
          'HR will check your photo before face punching is switched on. This can only be done '
          'once — HR has to open it again if you need to redo it.',
        ),
        const SizedBox(height: 20),
        CheckboxListTile(
          value: _consent,
          onChanged: (v) => setState(() => _consent = v ?? false),
          controlAffinity: ListTileControlAffinity.leading,
          contentPadding: EdgeInsets.zero,
          title: const Text('I agree to my face being used to verify my attendance.'),
        ),
        if (_error != null) ...[
          const SizedBox(height: 8),
          Text(_error!, style: TextStyle(color: Theme.of(context).colorScheme.error)),
        ],
        const SizedBox(height: 20),
        FilledButton.icon(
          onPressed: _consent ? _startCapture : null,
          icon: const Icon(Icons.camera_front),
          label: const Text('Start'),
        ),
      ],
    );
  }

  Widget _buildCapture(BuildContext context) {
    final controller = _camera;
    final scheme = Theme.of(context).colorScheme;
    final step = _tracker.isDone ? null : _tracker.current;
    return Column(
      children: [
        Padding(
          padding: const EdgeInsets.fromLTRB(20, 16, 20, 8),
          child: Column(children: [
            Text(
              step?.instruction ?? 'Done',
              style: Theme.of(context).textTheme.titleMedium,
              textAlign: TextAlign.center,
            ),
            const SizedBox(height: 4),
            Text(
              _hint ?? 'Hold still — the photo is taken automatically',
              style: TextStyle(color: scheme.onSurfaceVariant),
              textAlign: TextAlign.center,
            ),
          ]),
        ),
        Expanded(
          child: Center(
            child: controller == null || !controller.value.isInitialized
                ? const CircularProgressIndicator()
                : AspectRatio(
                    aspectRatio: 3 / 4,
                    child: Stack(fit: StackFit.expand, children: [
                      ClipRRect(borderRadius: BorderRadius.circular(16), child: CameraPreview(controller)),
                      IgnorePointer(child: CustomPaint(painter: _FaceGuidePainter(color: scheme.primary))),
                    ]),
                  ),
          ),
        ),
        Padding(
          padding: const EdgeInsets.all(20),
          child: Row(
            mainAxisAlignment: MainAxisAlignment.center,
            children: [
              for (var i = 0; i < facePoseSteps.length; i++)
                Container(
                  margin: const EdgeInsets.symmetric(horizontal: 4),
                  width: 28,
                  height: 6,
                  decoration: BoxDecoration(
                    color: i < _tracker.completedSteps ? scheme.primary : scheme.outlineVariant,
                    borderRadius: BorderRadius.circular(3),
                  ),
                ),
            ],
          ),
        ),
      ],
    );
  }

  Widget _buildReview(BuildContext context) {
    final submitting = _stage == _Stage.submitting;
    return ListView(
      padding: const EdgeInsets.all(20),
      children: [
        Text('Check your photos', style: Theme.of(context).textTheme.titleLarge),
        const SizedBox(height: 12),
        GridView.count(
          crossAxisCount: 3,
          shrinkWrap: true,
          physics: const NeverScrollableScrollPhysics(),
          mainAxisSpacing: 8,
          crossAxisSpacing: 8,
          children: [
            for (final step in facePoseSteps)
              if (_photos[step.angle] != null)
                ClipRRect(
                  borderRadius: BorderRadius.circular(8),
                  child: Image.memory(_photos[step.angle]!, fit: BoxFit.cover),
                ),
          ],
        ),
        if (_error != null) ...[
          const SizedBox(height: 12),
          Text(_error!, style: TextStyle(color: Theme.of(context).colorScheme.error)),
        ],
        const SizedBox(height: 20),
        if (submitting) const LinearProgressIndicator(),
        if (submitting) const SizedBox(height: 12),
        FilledButton(
          onPressed: submitting ? null : _submit,
          child: Text(submitting ? 'Checking your photos…' : 'Submit for HR approval'),
        ),
        const SizedBox(height: 8),
        OutlinedButton(
          onPressed: submitting ? null : _startCapture,
          child: const Text('Retake photos'),
        ),
      ],
    );
  }
}

/// An oval face guide over the camera preview.
class _FaceGuidePainter extends CustomPainter {
  _FaceGuidePainter({required this.color});

  final Color color;

  @override
  void paint(Canvas canvas, Size size) {
    final oval = Rect.fromCenter(
      center: size.center(Offset.zero),
      width: size.width * 0.62,
      height: size.height * 0.62,
    );
    canvas.drawOval(
      oval,
      Paint()
        ..color = color
        ..style = PaintingStyle.stroke
        ..strokeWidth = 3,
    );
  }

  @override
  bool shouldRepaint(_FaceGuidePainter oldDelegate) => oldDelegate.color != color;
}
