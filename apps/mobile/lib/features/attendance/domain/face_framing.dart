/// Where the detected face sits in the camera frame, judged against the on-screen oval so the
/// automatic photo is only taken once the face fills it properly (all values are fractions of the
/// upright camera frame, 0..1).
enum FaceFraming { ok, tooFar, tooClose, offCenter }

/// The oval's centre and the face-height range that fills it. The oval is drawn at the same spot
/// (see `_guideOval` in the enrollment screen), so "centred in the oval" == "close to this point".
const faceGuideCenterX = 0.5;
const faceGuideCenterY = 0.46;

/// [heightFraction] is the detected face box's height over the frame's height; [centerX] and
/// [centerY] are the box centre. Turned and tilted poses shift and shrink the box, so they get
/// more room than the straight-ahead photo ([strict] = true).
FaceFraming judgeFraming({
  required double centerX,
  required double centerY,
  required double heightFraction,
  required bool strict,
}) {
  final minHeight = strict ? 0.30 : 0.24;
  const maxHeight = 0.62;
  if (heightFraction < minHeight) return FaceFraming.tooFar;
  if (heightFraction > maxHeight) return FaceFraming.tooClose;
  final dx = strict ? 0.16 : 0.24;
  final dy = strict ? 0.14 : 0.20;
  if ((centerX - faceGuideCenterX).abs() > dx || (centerY - faceGuideCenterY).abs() > dy) return FaceFraming.offCenter;
  return FaceFraming.ok;
}

/// The short instruction for a framing problem, or null when the framing is fine.
String? framingHint(FaceFraming framing) => switch (framing) {
      FaceFraming.ok => null,
      FaceFraming.tooFar => 'Move a little closer',
      FaceFraming.tooClose => 'Move back a little',
      FaceFraming.offCenter => 'Center your face in the oval',
    };
