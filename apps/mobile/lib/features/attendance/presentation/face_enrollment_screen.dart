import 'dart:async';
import 'dart:io';
import 'dart:ui' as ui;

import 'package:camera/camera.dart';
import 'package:flutter/foundation.dart' show kDebugMode;
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:google_mlkit_face_detection/google_mlkit_face_detection.dart';

import '../../../core/api/api_error.dart';
import '../domain/face_framing.dart';
import '../domain/face_pose_tracker.dart';
import '../data/attendance_repository.dart' show attendanceRepositoryProvider;
import 'camera_input_image.dart';

enum _Stage { consent, capturing, review, submitting }

/// One-time guided face enrollment inside an HR-opened window: tips + consent -> five auto-captured
/// photos (live camera + on-device face detection) -> review -> submit for HR approval.
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
  int _unreadableFrames = 0;
  String? _debugReading;

  /// Seconds left before the automatic photo (null = not counting down). The countdown only runs
  /// while the pose stays right; moving away cancels it so the photo is never taken mid-movement.
  int? _countdown;
  Timer? _countdownTimer;
  bool _faceDetected = false;
  bool _poseGood = false;
  bool _flash = false;
  String? _captureNotice;

  @override
  void dispose() {
    _cancelCountdown();
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
      _captureNotice = null;
      _faceDetected = false;
      _poseGood = false;
    });
    _cancelCountdown();
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
        options: FaceDetectorOptions(performanceMode: FaceDetectorMode.fast, minFaceSize: 0.2),
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
    _cancelCountdown();
    _stopCamera();
    if (mounted) {
      setState(() {
        _stage = _Stage.consent;
        _error = message;
      });
    }
  }

  /// Leaves the camera and returns to the start page without submitting anything.
  void _cancelCapture() {
    _cancelCountdown();
    _stopCamera();
    if (mounted) setState(() => _stage = _Stage.consent);
  }

  Future<void> _onFrame(CameraImage image) async {
    if (_processingFrame || _capturing || _tracker.isDone) return;
    final input = _toInputImage(image);
    final detector = _detector;
    if (input == null || detector == null) {
      // Never silently ignore every frame: after a few, say so instead of "hold still" forever.
      if (++_unreadableFrames == 15 && mounted) {
        setState(() => _hint = "This phone's camera could not be read for automatic photos. Please contact support.");
      }
      return;
    }
    _unreadableFrames = 0;
    _processingFrame = true;
    try {
      final faces = await detector.processImage(input);
      final reading = FacePoseReading(
        faceCount: faces.length,
        yaw: faces.length == 1 ? faces.first.headEulerAngleY : null,
        pitch: faces.length == 1 ? faces.first.headEulerAngleX : null,
      );
      // A face that is too small, too big or off to the side is treated like no usable face, so
      // the countdown never starts on a badly framed photo.
      final framing = faces.length == 1 ? _judgeFraming(faces.first, input) : null;
      final framingOk = framing == null || framing == FaceFraming.ok;
      final ready = _tracker.accept(framingOk ? reading : const FacePoseReading(faceCount: 0));
      if (ready) {
        _startCountdown();
      } else {
        _cancelCountdown();
      }
      if (mounted) {
        setState(() {
          _faceDetected = reading.faceCount > 0;
          _poseGood = ready;
          if (_captureNotice != null && reading.faceCount > 0 && !ready) _captureNotice = null;
          _hint = _tracker.hintFor(reading) ?? (framing == null ? null : framingHint(framing)) ?? (ready ? null : _poseHint(reading));
          if (kDebugMode) {
            _debugReading = reading.yaw == null ? 'faces: ${reading.faceCount}' : 'yaw ${reading.yaw!.toStringAsFixed(0)}°  pitch ${reading.pitch!.toStringAsFixed(0)}°  $framing';
          }
        });
      }
    } catch (_) {
      // A dropped frame is harmless; the next one is analysed instead.
    } finally {
      _processingFrame = false;
    }
  }

  FaceFraming _judgeFraming(Face face, InputImage input) {
    final metadata = input.metadata!;
    final quarterTurn = metadata.rotation == InputImageRotation.rotation90deg || metadata.rotation == InputImageRotation.rotation270deg;
    final width = quarterTurn ? metadata.size.height : metadata.size.width;
    final height = quarterTurn ? metadata.size.width : metadata.size.height;
    final box = face.boundingBox;
    return judgeFraming(
      centerX: box.center.dx / width,
      centerY: box.center.dy / height,
      heightFraction: box.height / height,
      strict: _tracker.current.angle == 'front',
    );
  }

  void _startCountdown() {
    if (_countdownTimer != null || _capturing) return;
    // Short for the turned/tilted poses (they are hard to hold), a bit longer for the front shot.
    var seconds = _tracker.current.angle == 'front' ? 3 : 2;
    setState(() => _countdown = seconds);
    _countdownTimer = Timer.periodic(const Duration(seconds: 1), (timer) {
      seconds--;
      if (seconds > 0) {
        if (mounted) setState(() => _countdown = seconds);
        return;
      }
      timer.cancel();
      _countdownTimer = null;
      if (mounted) setState(() => _countdown = null);
      unawaited(_captureCurrentStep());
    });
  }

  void _cancelCountdown() {
    _countdownTimer?.cancel();
    _countdownTimer = null;
    if (_countdown != null && mounted) setState(() => _countdown = null);
  }

  /// Why a visible, well-framed face is not being captured yet. The 'front' photo needs the head
  /// within 10 degrees of straight both sideways and up/down; a phone held low or high is the usual
  /// reason it never triggers, and the screen used to give no clue.
  String? _poseHint(FacePoseReading r) {
    if (_tracker.isDone || r.faceCount != 1 || r.yaw == null || r.pitch == null) return null;
    if (_tracker.current.angle != 'front') return null;
    if (r.pitch!.abs() > 10) return 'Hold the phone at eye level and look straight ahead';
    if (r.yaw!.abs() > 10) return 'Turn your face straight toward the camera';
    return null;
  }

  Future<void> _captureCurrentStep() async {
    final controller = _camera;
    if (controller == null) return;
    _capturing = true;
    try {
      if (controller.value.isStreamingImages) await controller.stopImageStream();
      final file = await controller.takePicture();
      _photos[_tracker.current.angle] = await readAndDeleteCapture(file);
      HapticFeedback.mediumImpact();
      _tracker.advance();
      if (mounted) {
        setState(() {
          _flash = true;
          _poseGood = false;
          _captureNotice = 'Photo ${_photos.length} of ${facePoseSteps.length} taken';
        });
        Future.delayed(const Duration(milliseconds: 220), () {
          if (mounted) setState(() => _flash = false);
        });
      }
      if (_tracker.isDone) {
        await Future<void>.delayed(const Duration(milliseconds: 600));
        await _stopCamera();
        if (mounted) setState(() => _stage = _Stage.review);
      } else {
        // Give the person a moment to read the confirmation and the next instruction.
        await Future<void>.delayed(const Duration(milliseconds: 1100));
        if (_camera == controller) await controller.startImageStream(_onFrame);
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
    final capturing = _stage == _Stage.capturing;
    return Scaffold(
      backgroundColor: capturing ? Colors.black : null,
      appBar: capturing ? null : AppBar(title: const Text('Set up face attendance')),
      body: SafeArea(
        child: switch (_stage) {
          _Stage.consent => _buildConsent(context),
          _Stage.capturing => _buildCapture(context),
          _Stage.review || _Stage.submitting => _buildReview(context),
        },
      ),
    );
  }

  // ---------------------------------------------------------------------------------------
  // Start page
  // ---------------------------------------------------------------------------------------

  Widget _buildConsent(BuildContext context) {
    final theme = Theme.of(context);
    final scheme = theme.colorScheme;
    Widget tip(IconData icon, String text) => Padding(
          padding: const EdgeInsets.symmetric(vertical: 7),
          child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Container(
              width: 36,
              height: 36,
              decoration: BoxDecoration(color: scheme.primaryContainer, shape: BoxShape.circle),
              child: Icon(icon, size: 19, color: scheme.onPrimaryContainer),
            ),
            const SizedBox(width: 12),
            Expanded(child: Padding(padding: const EdgeInsets.only(top: 8), child: Text(text, style: theme.textTheme.bodyMedium))),
          ]),
        );
    return ListView(
      padding: const EdgeInsets.all(20),
      children: [
        Text('Register your face', style: theme.textTheme.headlineSmall?.copyWith(fontWeight: FontWeight.w700)),
        const SizedBox(height: 6),
        Text(
          'It takes about 30 seconds. Five photos are taken for you, one after another — you only need to follow the on-screen steps.',
          style: theme.textTheme.bodyMedium?.copyWith(color: scheme.onSurfaceVariant),
        ),
        const SizedBox(height: 16),
        Text('Before you start', style: theme.textTheme.titleSmall),
        tip(Icons.wb_sunny_outlined, 'Stand where there is good, even light on your face — not with a window behind you.'),
        tip(Icons.phone_android, 'Hold the phone at eye level, about an arm\'s length away.'),
        tip(Icons.face_retouching_off, 'Take off sunglasses, a cap or a mask. Make sure only you are in view.'),
        tip(Icons.check_circle_outline, 'HR checks your photo before face punching is switched on. You can only do this once; HR has to open it again to redo it.'),
        const SizedBox(height: 8),
        CheckboxListTile(
          value: _consent,
          onChanged: (v) => setState(() => _consent = v ?? false),
          controlAffinity: ListTileControlAffinity.leading,
          contentPadding: EdgeInsets.zero,
          title: const Text('I agree to my face being used to verify my attendance.'),
        ),
        if (_error != null) ...[
          const SizedBox(height: 8),
          Text(_error!, style: TextStyle(color: scheme.error)),
        ],
        const SizedBox(height: 16),
        FilledButton.icon(
          onPressed: _consent ? _startCapture : null,
          icon: const Icon(Icons.camera_front),
          label: const Text('Start'),
        ),
      ],
    );
  }

  // ---------------------------------------------------------------------------------------
  // Capture
  // ---------------------------------------------------------------------------------------

  /// The status line under the instruction: the one thing the person should do (or know) now.
  ({String text, IconData icon, Color color}) _status() {
    if (_captureNotice != null) return (text: _captureNotice!, icon: Icons.check_circle, color: const Color(0xFF34D399));
    if (_countdown != null) return (text: 'Hold still…', icon: Icons.timer_outlined, color: const Color(0xFF34D399));
    if (_hint != null) return (text: _hint!, icon: Icons.info_outline, color: const Color(0xFFFBBF24));
    if (_faceDetected) return (text: 'Looking good — hold still', icon: Icons.face_retouching_natural, color: Colors.white);
    return (text: 'Position your face in the oval', icon: Icons.center_focus_strong_outlined, color: Colors.white);
  }

  Widget _buildCapture(BuildContext context) {
    final controller = _camera;
    final step = _tracker.isDone ? null : _tracker.current;
    final stepNumber = _tracker.isDone ? facePoseSteps.length : _tracker.completedSteps + 1;
    final status = _status();
    final portrait = MediaQuery.orientationOf(context) == Orientation.portrait;
    return Column(
      children: [
        Padding(
          padding: const EdgeInsets.fromLTRB(4, 4, 16, 0),
          child: Row(children: [
            IconButton(onPressed: _cancelCapture, icon: const Icon(Icons.close, color: Colors.white), tooltip: 'Cancel'),
            const Spacer(),
            Text('Step $stepNumber of ${facePoseSteps.length}', style: const TextStyle(color: Colors.white70, fontWeight: FontWeight.w600)),
          ]),
        ),
        Padding(
          padding: const EdgeInsets.fromLTRB(24, 0, 24, 10),
          child: Text(
            step?.instruction ?? 'All done',
            style: const TextStyle(color: Colors.white, fontSize: 22, fontWeight: FontWeight.w700, height: 1.2),
            textAlign: TextAlign.center,
          ),
        ),
        Expanded(
          child: Center(
            child: controller == null || !controller.value.isInitialized
                ? const CircularProgressIndicator(color: Colors.white)
                : AspectRatio(
                    // The preview at its real shape (no stretching), so the oval and the face
                    // detector's coordinates line up with what the person sees.
                    aspectRatio: portrait ? 1 / controller.value.aspectRatio : controller.value.aspectRatio,
                    child: ClipRRect(
                      borderRadius: BorderRadius.circular(20),
                      child: Stack(fit: StackFit.expand, children: [
                        CameraPreview(controller),
                        // Everything outside the oval is blurred and dimmed, so only the face area is sharp.
                        IgnorePointer(
                          child: ClipPath(
                            clipper: _OutsideOvalClipper(),
                            child: BackdropFilter(
                              filter: ui.ImageFilter.blur(sigmaX: 14, sigmaY: 14),
                              child: const ColoredBox(color: Color(0x73000000)),
                            ),
                          ),
                        ),
                        IgnorePointer(
                          child: CustomPaint(
                            painter: _FaceGuidePainter(
                              color: _poseGood ? const Color(0xFF34D399) : (_faceDetected ? const Color(0xFFFBBF24) : Colors.white70),
                            ),
                          ),
                        ),
                        if (_countdown != null)
                          Align(
                            alignment: const Alignment(0, -0.86),
                            child: Container(
                              width: 56,
                              height: 56,
                              alignment: Alignment.center,
                              decoration: const BoxDecoration(color: Color(0xCC000000), shape: BoxShape.circle),
                              child: Text('$_countdown', style: const TextStyle(color: Colors.white, fontSize: 30, fontWeight: FontWeight.bold)),
                            ),
                          ),
                        Align(
                          alignment: const Alignment(0, 0.93),
                          child: Container(
                            margin: const EdgeInsets.symmetric(horizontal: 16),
                            padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 9),
                            decoration: BoxDecoration(color: const Color(0xCC000000), borderRadius: BorderRadius.circular(24)),
                            child: Row(mainAxisSize: MainAxisSize.min, children: [
                              Icon(status.icon, size: 18, color: status.color),
                              const SizedBox(width: 8),
                              Flexible(child: Text(status.text, style: TextStyle(color: status.color, fontWeight: FontWeight.w600), textAlign: TextAlign.center)),
                            ]),
                          ),
                        ),
                        IgnorePointer(
                          child: AnimatedOpacity(
                            opacity: _flash ? 0.85 : 0,
                            duration: const Duration(milliseconds: 150),
                            child: const ColoredBox(color: Colors.white),
                          ),
                        ),
                      ]),
                    ),
                  ),
          ),
        ),
        if (kDebugMode && _debugReading != null) Text(_debugReading!, style: const TextStyle(fontSize: 11, color: Colors.white38)),
        Padding(
          padding: const EdgeInsets.fromLTRB(12, 12, 12, 16),
          child: Row(
            mainAxisAlignment: MainAxisAlignment.spaceEvenly,
            children: [
              for (var i = 0; i < facePoseSteps.length; i++) _StepChip(step: facePoseSteps[i], index: i, current: _tracker.completedSteps, photo: _photos[facePoseSteps[i].angle]),
            ],
          ),
        ),
      ],
    );
  }

  // ---------------------------------------------------------------------------------------
  // Review
  // ---------------------------------------------------------------------------------------

  Widget _buildReview(BuildContext context) {
    final theme = Theme.of(context);
    final submitting = _stage == _Stage.submitting;
    return ListView(
      padding: const EdgeInsets.all(20),
      children: [
        Text('Check your photos', style: theme.textTheme.headlineSmall?.copyWith(fontWeight: FontWeight.w700)),
        const SizedBox(height: 6),
        Text(
          'Make sure your face is clear and well lit in every photo. If one looks wrong, retake them all.',
          style: theme.textTheme.bodyMedium?.copyWith(color: theme.colorScheme.onSurfaceVariant),
        ),
        const SizedBox(height: 14),
        GridView.count(
          crossAxisCount: 3,
          shrinkWrap: true,
          physics: const NeverScrollableScrollPhysics(),
          mainAxisSpacing: 10,
          crossAxisSpacing: 10,
          childAspectRatio: 0.78,
          children: [
            for (final step in facePoseSteps)
              if (_photos[step.angle] != null)
                Column(children: [
                  Expanded(
                    child: ClipRRect(
                      borderRadius: BorderRadius.circular(10),
                      child: SizedBox.expand(child: Image.memory(_photos[step.angle]!, fit: BoxFit.cover)),
                    ),
                  ),
                  const SizedBox(height: 4),
                  Text(step.label, style: theme.textTheme.labelMedium),
                ]),
          ],
        ),
        if (_error != null) ...[
          const SizedBox(height: 14),
          Container(
            padding: const EdgeInsets.all(12),
            decoration: BoxDecoration(color: theme.colorScheme.errorContainer, borderRadius: BorderRadius.circular(10)),
            child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
              Icon(Icons.error_outline, color: theme.colorScheme.onErrorContainer),
              const SizedBox(width: 10),
              Expanded(child: Text(_error!, style: TextStyle(color: theme.colorScheme.onErrorContainer))),
            ]),
          ),
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

IconData _stepIcon(String angle) => switch (angle) {
      'front' => Icons.face_rounded,
      'left' || 'right' => Icons.swap_horiz_rounded,
      'up' => Icons.arrow_upward_rounded,
      _ => Icons.arrow_downward_rounded,
    };

/// One of the five steps along the bottom: the photo itself once taken (so it is obvious it
/// worked), a highlighted icon for the step in progress, a dim icon for what is still to come.
class _StepChip extends StatelessWidget {
  const _StepChip({required this.step, required this.index, required this.current, this.photo});

  final FacePoseStep step;
  final int index;

  /// How many steps are already done (== index of the step in progress).
  final int current;
  final Uint8List? photo;

  @override
  Widget build(BuildContext context) {
    final done = index < current && photo != null;
    final active = index == current;
    const green = Color(0xFF34D399);
    return SizedBox(
      width: 58,
      child: Column(mainAxisSize: MainAxisSize.min, children: [
        Stack(clipBehavior: Clip.none, children: [
          Container(
            width: 48,
            height: 48,
            decoration: BoxDecoration(
              shape: BoxShape.circle,
              color: active ? Colors.white : Colors.white10,
              border: Border.all(color: done ? green : (active ? Colors.white : Colors.white24), width: active || done ? 2.5 : 1),
            ),
            clipBehavior: Clip.antiAlias,
            child: done ? Image.memory(photo!, fit: BoxFit.cover, alignment: const Alignment(0, -0.35)) : Icon(_stepIcon(step.angle), color: active ? Colors.black87 : Colors.white38, size: 24),
          ),
          if (done)
            const Positioned(
              right: -3,
              bottom: -3,
              child: CircleAvatar(radius: 9, backgroundColor: green, child: Icon(Icons.check, size: 13, color: Colors.black)),
            ),
        ]),
        const SizedBox(height: 5),
        Text(step.label, style: TextStyle(fontSize: 11, color: active || done ? Colors.white : Colors.white38, fontWeight: active ? FontWeight.w700 : FontWeight.w500)),
      ]),
    );
  }
}

/// The fixed face oval, centred and slightly above the middle so the head sits naturally in it.
/// Keep in step with `faceGuideCenterY` in `domain/face_framing.dart`.
Rect _guideOval(Size size) => Rect.fromCenter(
      center: Offset(size.width * faceGuideCenterX, size.height * faceGuideCenterY),
      width: size.width * 0.70,
      height: size.height * 0.52,
    );

/// Everything except the face oval (used to blur the background).
class _OutsideOvalClipper extends CustomClipper<Path> {
  @override
  Path getClip(Size size) => Path.combine(
        PathOperation.difference,
        Path()..addRect(Offset.zero & size),
        Path()..addOval(_guideOval(size)),
      );

  @override
  bool shouldReclip(covariant CustomClipper<Path> oldClipper) => false;
}

/// An oval face guide over the camera preview.
class _FaceGuidePainter extends CustomPainter {
  _FaceGuidePainter({required this.color});

  final Color color;

  @override
  void paint(Canvas canvas, Size size) {
    canvas.drawOval(
      _guideOval(size),
      Paint()
        ..color = color
        ..style = PaintingStyle.stroke
        ..strokeWidth = 4,
    );
  }

  @override
  bool shouldRepaint(_FaceGuidePainter oldDelegate) => oldDelegate.color != color;
}
