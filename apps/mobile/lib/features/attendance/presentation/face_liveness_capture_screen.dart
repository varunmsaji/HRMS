import 'dart:async';
import 'dart:io';

import 'package:camera/camera.dart';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:google_mlkit_face_detection/google_mlkit_face_detection.dart';

import '../data/attendance_repository.dart' show FaceLivenessSession;
import '../domain/face_liveness_capture.dart';
import 'camera_input_image.dart';

/// Captures the frames for one server-issued liveness challenge: live camera + on-device
/// quality gating (one face, close, facing the camera, eyes open), then [FaceLivenessSession
/// .framesRequired] photos in quick succession. Pops with a [FaceCaptureOutcome].
///
/// Frames live in memory only (each camera temp file is deleted as soon as it is read) and are
/// handed straight to the caller. No liveness decision is made here — the server makes it.
class FaceLivenessCaptureScreen extends StatefulWidget {
  const FaceLivenessCaptureScreen({super.key, required this.session});

  final FaceLivenessSession session;

  @override
  State<FaceLivenessCaptureScreen> createState() => _FaceLivenessCaptureScreenState();
}

class _FaceLivenessCaptureScreenState extends State<FaceLivenessCaptureScreen> with WidgetsBindingObserver {
  CameraController? _camera;
  CameraDescription? _cameraDescription;
  FaceDetector? _detector;
  final FaceCaptureGate _gate = FaceCaptureGate();
  Timer? _expiryTimer;
  bool _processingFrame = false;
  bool _capturing = false;
  bool _finished = false;
  FaceCaptureHint _hint = FaceCaptureHint.noFace;

  /// The gap between consecutive shots, so the frames are distinct moments.
  static const _frameGap = Duration(milliseconds: 200);

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addObserver(this);
    _expiryTimer = Timer.periodic(const Duration(seconds: 1), (_) {
      if (!challengeStillUsable(widget.session.expiresAt, DateTime.now())) _finish(const FaceCaptureExpired());
    });
    _start();
  }

  @override
  void dispose() {
    WidgetsBinding.instance.removeObserver(this);
    _expiryTimer?.cancel();
    _stopCamera();
    super.dispose();
  }

  @override
  void didChangeAppLifecycleState(AppLifecycleState state) {
    // Leaving the app mid-capture (call, app switch) abandons this attempt; a new one gets a
    // fresh challenge. Not `inactive`, and not before the camera runs: the system camera
    // permission prompt itself makes the app inactive.
    if (state == AppLifecycleState.paused && _camera != null) {
      _finish(const FaceCaptureFailed('The camera was interrupted. Please try again.'));
    }
  }

  Future<void> _start() async {
    try {
      final cameras = await availableCameras();
      if (cameras.isEmpty) {
        _finish(const FaceCaptureFailed('No camera is available on this device.'));
        return;
      }
      _cameraDescription = cameras.firstWhere(
        (c) => c.lensDirection == CameraLensDirection.front,
        orElse: () => cameras.first,
      );
      // `medium` is 480p (3:4 portrait on most phones): enough face detail for the server's
      // liveness model and Face++, and comfortably under the server's 1 MB per-frame limit.
      final controller = CameraController(
        _cameraDescription!,
        ResolutionPreset.medium,
        enableAudio: false,
        imageFormatGroup: Platform.isAndroid ? ImageFormatGroup.nv21 : ImageFormatGroup.bgra8888,
      );
      await controller.initialize();
      _detector ??= FaceDetector(
        options: FaceDetectorOptions(performanceMode: FaceDetectorMode.fast, enableClassification: true, minFaceSize: 0.2),
      );
      if (!mounted || _finished) {
        await controller.dispose();
        return;
      }
      setState(() => _camera = controller);
      await controller.startImageStream(_onFrame);
    } on CameraException catch (e) {
      _finish(e.code.contains('AccessDenied') || e.code.contains('Restricted')
          ? const FaceCapturePermissionDenied()
          : const FaceCaptureFailed('Could not start the camera. Please try again.'));
    } catch (_) {
      _finish(const FaceCaptureFailed('Face attendance is not supported on this device.'));
    }
  }

  Future<void> _stopCamera() async {
    final controller = _camera;
    _camera = null;
    if (controller != null) {
      try {
        if (controller.value.isStreamingImages) await controller.stopImageStream();
      } catch (_) {}
      await controller.dispose();
    }
    await _detector?.close();
    _detector = null;
  }

  void _finish(FaceCaptureOutcome outcome) {
    if (_finished) return;
    _finished = true;
    _expiryTimer?.cancel();
    _stopCamera();
    if (mounted) Navigator.of(context).pop(outcome);
  }

  Future<void> _onFrame(CameraImage image) async {
    if (_processingFrame || _capturing || _finished) return;
    final camera = _cameraDescription;
    final controller = _camera;
    final detector = _detector;
    if (camera == null || controller == null || detector == null) return;
    final input = cameraFrameToInputImage(image, camera, controller);
    if (input == null) return;
    _processingFrame = true;
    try {
      final faces = await detector.processImage(input);
      final face = faces.length == 1 ? faces.first : null;
      final hint = _gate.accept(FaceFrameReading(
        faceCount: faces.length,
        faceWidthFraction: face == null ? null : face.boundingBox.width / uprightWidth(input),
        yaw: face?.headEulerAngleY,
        pitch: face?.headEulerAngleX,
        leftEyeOpen: face?.leftEyeOpenProbability,
        rightEyeOpen: face?.rightEyeOpenProbability,
      ));
      if (mounted && hint != _hint) setState(() => _hint = hint);
      if (_gate.ready) await _captureFrames();
    } catch (_) {
      // A dropped frame is harmless; the next one is analysed instead.
    } finally {
      _processingFrame = false;
    }
  }

  Future<void> _captureFrames() async {
    final controller = _camera;
    if (controller == null || _capturing) return;
    _capturing = true;
    final frames = <Uint8List>[];
    try {
      await controller.stopImageStream();
      for (var i = 0; i < widget.session.framesRequired; i++) {
        if (_finished) return;
        if (i > 0) await Future<void>.delayed(_frameGap);
        frames.add(await readAndDeleteCapture(await controller.takePicture()));
      }
      HapticFeedback.mediumImpact();
      if (!challengeStillUsable(widget.session.expiresAt, DateTime.now(), margin: const Duration(seconds: 5))) {
        frames.clear();
        _finish(const FaceCaptureExpired());
        return;
      }
      _finish(FaceCaptureFrames(frames));
    } catch (_) {
      frames.clear();
      _finish(const FaceCaptureFailed('Could not take the photos. Please try again.'));
    }
  }

  @override
  Widget build(BuildContext context) {
    final controller = _camera;
    final scheme = Theme.of(context).colorScheme;
    return Scaffold(
      appBar: AppBar(
        title: Text(widget.session.direction == 'IN' ? 'Face punch in' : 'Face punch out'),
        leading: IconButton(
          icon: const Icon(Icons.close),
          tooltip: 'Cancel',
          onPressed: () => _finish(const FaceCaptureCancelled()),
        ),
      ),
      body: SafeArea(
        child: Column(children: [
          Padding(
            padding: const EdgeInsets.fromLTRB(20, 16, 20, 8),
            child: Column(children: [
              Text(
                'Hold the phone yourself and look straight at the camera.',
                style: Theme.of(context).textTheme.titleMedium,
                textAlign: TextAlign.center,
              ),
              const SizedBox(height: 4),
              Semantics(
                liveRegion: true,
                child: Text(
                  faceCaptureHintText(_hint),
                  style: TextStyle(color: scheme.onSurfaceVariant),
                  textAlign: TextAlign.center,
                ),
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
                        IgnorePointer(child: CustomPaint(painter: _OvalGuidePainter(color: scheme.primary))),
                      ]),
                    ),
            ),
          ),
          const Padding(
            padding: EdgeInsets.all(16),
            child: Text(
              'Photos are taken automatically and are not saved on your phone.',
              textAlign: TextAlign.center,
            ),
          ),
        ]),
      ),
    );
  }
}

class _OvalGuidePainter extends CustomPainter {
  _OvalGuidePainter({required this.color});

  final Color color;

  @override
  void paint(Canvas canvas, Size size) {
    canvas.drawOval(
      Rect.fromCenter(center: size.center(Offset.zero), width: size.width * 0.62, height: size.height * 0.62),
      Paint()
        ..color = color
        ..style = PaintingStyle.stroke
        ..strokeWidth = 3,
    );
  }

  @override
  bool shouldRepaint(_OvalGuidePainter oldDelegate) => oldDelegate.color != color;
}
