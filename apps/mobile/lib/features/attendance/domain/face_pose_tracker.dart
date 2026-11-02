/// Guides the five-angle self-enrollment from live face-detection readings.
///
/// Turn and tilt directions are checked by *opposite sign* rather than by absolute sign: whether
/// a positive head yaw means "left" depends on camera mirroring and platform, so the second turn
/// just has to go the other way from the first (likewise for the two tilts). The angle names sent
/// to the server ("left", "right", "up", "down") are therefore capture-order labels; the server
/// only verifies that every capture is the same person as the front one.
library;

class FacePoseReading {
  const FacePoseReading({required this.faceCount, this.yaw, this.pitch});

  final int faceCount;

  /// Degrees; ML Kit `headEulerAngleY`.
  final double? yaw;

  /// Degrees; ML Kit `headEulerAngleX`.
  final double? pitch;
}

class FacePoseStep {
  const FacePoseStep(this.angle, this.instruction);

  /// Form field name the capture is submitted under.
  final String angle;
  final String instruction;
}

const facePoseSteps = [
  FacePoseStep('front', 'Look straight at the camera'),
  FacePoseStep('left', 'Slowly turn your head to one side'),
  FacePoseStep('right', 'Now turn your head to the other side'),
  FacePoseStep('up', 'Tilt your head up a little'),
  FacePoseStep('down', 'Now tilt your head down a little'),
];

class FacePoseTracker {
  FacePoseTracker({this.requiredStableReadings = 3});

  /// Consecutive qualifying readings needed before a step is captured, so a passing glance
  /// doesn't trigger the shutter.
  final int requiredStableReadings;

  static const _frontMax = 10.0;
  static const _turnMin = 15.0;
  static const _turnMax = 30.0;
  static const _tiltMin = 10.0;
  static const _tiltMax = 25.0;

  int _index = 0;
  int _stable = 0;
  double? _firstTurnSign;
  double? _firstTiltSign;
  double? _pendingSign;

  bool get isDone => _index >= facePoseSteps.length;
  FacePoseStep get current => facePoseSteps[_index];
  int get completedSteps => _index;

  /// Hint for the user when the current reading doesn't qualify, or null when it does.
  String? hintFor(FacePoseReading reading) {
    if (reading.faceCount == 0) return 'Move your face into the frame';
    if (reading.faceCount > 1) return 'Make sure only you are in the frame';
    return null;
  }

  /// Feeds one reading; returns true once the current step has been held long enough to capture.
  bool accept(FacePoseReading reading) {
    if (isDone) return false;
    final sign = _qualifyingSign(reading);
    if (sign == null) {
      _stable = 0;
      _pendingSign = null;
      return false;
    }
    if (_pendingSign != null && _pendingSign != sign) _stable = 0;
    _pendingSign = sign;
    _stable++;
    return _stable >= requiredStableReadings;
  }

  /// Call after the current step's photo was captured.
  void advance() {
    final angle = current.angle;
    if (angle == 'left') _firstTurnSign = _pendingSign;
    if (angle == 'up') _firstTiltSign = _pendingSign;
    _index++;
    _stable = 0;
    _pendingSign = null;
  }

  /// Returns a sign (1 / -1, or 0 for the front step) when [reading] satisfies the current step.
  double? _qualifyingSign(FacePoseReading reading) {
    if (reading.faceCount != 1 || reading.yaw == null || reading.pitch == null) return null;
    final yaw = reading.yaw!;
    final pitch = reading.pitch!;
    switch (current.angle) {
      case 'front':
        return yaw.abs() <= _frontMax && pitch.abs() <= _frontMax ? 0 : null;
      case 'left':
      case 'right':
        if (yaw.abs() < _turnMin || yaw.abs() > _turnMax || pitch.abs() > _tiltMax) return null;
        final sign = yaw.sign;
        if (current.angle == 'right' && sign == _firstTurnSign) return null;
        return sign;
      case 'up':
      case 'down':
        if (pitch.abs() < _tiltMin || pitch.abs() > _tiltMax || yaw.abs() > _turnMin) return null;
        final sign = pitch.sign;
        if (current.angle == 'down' && sign == _firstTiltSign) return null;
        return sign;
    }
    return null;
  }
}
