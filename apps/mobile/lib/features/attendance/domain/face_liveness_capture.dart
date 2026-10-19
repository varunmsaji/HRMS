import 'dart:typed_data';

/// On-device capture gating for a face punch. This is a QUALITY gate only — one face, close
/// enough, facing the camera, eyes open, held still — so the frames sent are worth checking.
/// It is NOT liveness and its result is never sent to the server: liveness (photo/screen
/// detection) is decided by the server's own model on the uploaded frames.

/// One ML Kit reading of the live camera stream.
class FaceFrameReading {
  const FaceFrameReading({
    required this.faceCount,
    this.faceWidthFraction,
    this.yaw,
    this.pitch,
    this.leftEyeOpen,
    this.rightEyeOpen,
  });

  final int faceCount;

  /// The face box width as a fraction of the image width.
  final double? faceWidthFraction;
  final double? yaw;
  final double? pitch;

  /// ML Kit eye-open probabilities (null when classification could not run).
  final double? leftEyeOpen;
  final double? rightEyeOpen;
}

enum FaceCaptureHint { noFace, multipleFaces, moveCloser, moveBack, lookStraight, openEyes, holdStill, ready }

String faceCaptureHintText(FaceCaptureHint hint) => switch (hint) {
      FaceCaptureHint.noFace => 'Place your face inside the oval',
      FaceCaptureHint.multipleFaces => 'Make sure only you are in view',
      FaceCaptureHint.moveCloser => 'Move a little closer',
      FaceCaptureHint.moveBack => 'Move a little further away',
      FaceCaptureHint.lookStraight => 'Look straight at the camera',
      FaceCaptureHint.openEyes => 'Keep your eyes open',
      FaceCaptureHint.holdStill => 'Hold still…',
      FaceCaptureHint.ready => 'Capturing…',
    };

/// Becomes [ready] after [stableReadings] consecutive good readings; any bad reading resets it.
class FaceCaptureGate {
  FaceCaptureGate({this.stableReadings = 3});

  final int stableReadings;
  static const minFaceWidth = 0.28;
  static const maxFaceWidth = 0.85;
  static const maxAngle = 15.0;
  static const minEyeOpen = 0.4;

  int _good = 0;

  bool get ready => _good >= stableReadings;

  FaceCaptureHint accept(FaceFrameReading reading) {
    final problem = _problem(reading);
    if (problem != null) {
      _good = 0;
      return problem;
    }
    _good++;
    return ready ? FaceCaptureHint.ready : FaceCaptureHint.holdStill;
  }

  FaceCaptureHint? _problem(FaceFrameReading r) {
    if (r.faceCount == 0) return FaceCaptureHint.noFace;
    if (r.faceCount > 1) return FaceCaptureHint.multipleFaces;
    final width = r.faceWidthFraction;
    if (width == null || width < minFaceWidth) return FaceCaptureHint.moveCloser;
    if (width > maxFaceWidth) return FaceCaptureHint.moveBack;
    if ((r.yaw ?? 99).abs() > maxAngle || (r.pitch ?? 99).abs() > maxAngle) return FaceCaptureHint.lookStraight;
    final left = r.leftEyeOpen;
    final right = r.rightEyeOpen;
    if (left != null && right != null && (left < minEyeOpen || right < minEyeOpen)) return FaceCaptureHint.openEyes;
    return null;
  }
}

/// True while there is still time to capture AND upload before the server-issued challenge
/// expires; [margin] leaves room for the upload itself.
bool challengeStillUsable(DateTime expiresAt, DateTime now, {Duration margin = const Duration(seconds: 15)}) =>
    now.add(margin).isBefore(expiresAt);

/// How a capture attempt ended.
sealed class FaceCaptureOutcome {
  const FaceCaptureOutcome();
}

/// Frames held in memory only; the camera's temporary files are already deleted.
class FaceCaptureFrames extends FaceCaptureOutcome {
  const FaceCaptureFrames(this.frames);
  final List<Uint8List> frames;
}

class FaceCaptureCancelled extends FaceCaptureOutcome {
  const FaceCaptureCancelled();
}

class FaceCapturePermissionDenied extends FaceCaptureOutcome {
  const FaceCapturePermissionDenied();
}

/// The challenge ran out before frames could be captured and uploaded.
class FaceCaptureExpired extends FaceCaptureOutcome {
  const FaceCaptureExpired();
}

/// Camera failure, interruption (app sent to background) or unsupported device.
class FaceCaptureFailed extends FaceCaptureOutcome {
  const FaceCaptureFailed(this.message);
  final String message;
}
