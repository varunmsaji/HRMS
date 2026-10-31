import 'dart:math';

import 'face_liveness_capture.dart' show FaceFrameReading;

/// On-device ACTIVE liveness: a randomized challenge-response (blink twice / turn left / turn
/// right) that must be completed before the frames for a face punch are captured.
///
/// What this is: a raise-the-bar check against static presentation attacks — a printed photo, a
/// photo shown on another screen, a single still image. A still image cannot blink or rotate.
///
/// What this is NOT:
///  * It does not defeat a pre-recorded or replayed video of the genuine employee performing
///    blinks/turns, nor a real-time deepfake / face-swap. Randomizing the challenge makes a
///    pre-recorded clip less likely to match, but it is not a guarantee.
///  * It is evaluated on the client. The server never receives a "liveness passed" flag and is
///    not asked to trust one; the server's own passive liveness model + face match on the
///    uploaded frames remain the security boundary (see [FaceLivenessSession]). A rooted or
///    instrumented client could skip this stage; the server-side checks still apply to it.
///
/// The accurate claim is: active randomized challenge-response increases protection against
/// static-image attacks and basic replay attempts, but does not by itself guarantee protection
/// against all sophisticated presentation attacks.

/// All tunables in one place — nothing here is hard-coded in widgets.
class ActiveLivenessConfig {
  const ActiveLivenessConfig({
    this.enabled = false,
    this.challengesPerAttempt = 2,
    this.maximumLivenessAttempts = 3,
    this.challengeTimeout = const Duration(seconds: 12),
    this.faceWaitTimeout = const Duration(seconds: 20),
    this.blinkCountRequired = 2,
    this.eyeClosedBelow = 0.3,
    this.eyeOpenAbove = 0.6,
    this.minClosedFrames = 2,
    this.minOpenFrames = 2,
    this.maxBlinkDuration = const Duration(milliseconds: 1200),
    this.headTurnThreshold = 20,
    this.headTurnRelease = 12,
    this.headTurnHoldFrames = 3,
    this.neutralFrames = 4,
    this.maxNeutralYaw = 15,
    this.maxNeutralSpread = 6,
    this.maxPitch = 30,
    this.minFaceWidth = 0.28,
    this.maxFaceWidth = 0.85,
    this.userLeftIsPositiveYaw = true,
  })  : assert(challengesPerAttempt >= 1 && challengesPerAttempt <= 3),
        assert(headTurnRelease < headTurnThreshold),
        assert(eyeClosedBelow < eyeOpenAbove);

  /// Master switch. Off by default: turning it on for a deployment is a rollout decision.
  final bool enabled;
  final int challengesPerAttempt;

  /// Challenge sequences a user may be issued before being told to try later.
  final int maximumLivenessAttempts;
  final Duration challengeTimeout;
  final Duration faceWaitTimeout;
  final int blinkCountRequired;

  /// Mean ML Kit eye-open probability at/below which eyes count as closed, and at/above which
  /// as open. Values between the two change nothing (hysteresis).
  final double eyeClosedBelow;
  final double eyeOpenAbove;

  /// Consecutive frames needed to accept a closed / re-opened eye state — one noisy frame is
  /// never a blink.
  final int minClosedFrames;
  final int minOpenFrames;

  /// Eyes shut longer than this are not a blink (eyes closed, or a covered camera).
  final Duration maxBlinkDuration;

  /// Degrees of yaw away from the per-attempt neutral baseline to count as a turn, the lower
  /// level below which a held turn is considered released, and frames it must be held.
  final double headTurnThreshold;
  final double headTurnRelease;
  final int headTurnHoldFrames;

  /// Frames that must agree (within [maxNeutralSpread] degrees, and within [maxNeutralYaw] of
  /// straight ahead) to establish the neutral baseline.
  final int neutralFrames;
  final double maxNeutralYaw;
  final double maxNeutralSpread;
  final double maxPitch;
  final double minFaceWidth;
  final double maxFaceWidth;

  /// Whether a positive ML Kit yaw is the user turning to THEIR left. This depends on the
  /// platform and front-camera mirroring and MUST be confirmed on a real device; if wrong, the
  /// left/right instructions are swapped.
  final bool userLeftIsPositiveYaw;
}

enum LivenessChallenge {
  blinkTwice('Blink twice'),
  turnLeft('Turn your head left'),
  turnRight('Turn your head right');

  const LivenessChallenge(this.instruction);
  final String instruction;
}

/// Draws a fresh sequence of distinct challenges. [previous] (the sequence the user just
/// failed) is never repeated exactly when another ordering is possible.
List<LivenessChallenge> generateChallengeSequence(
  Random random, {
  int length = 2,
  List<LivenessChallenge>? previous,
}) {
  final all = LivenessChallenge.values;
  assert(length >= 1 && length <= all.length);
  List<LivenessChallenge> draw() => (List.of(all)..shuffle(random)).take(length).toList();
  var sequence = draw();
  // Bounded: with 3 challenges there are always several alternatives, so this ends quickly.
  for (var i = 0; i < 20 && previous != null && _sameSequence(sequence, previous); i++) {
    sequence = draw();
  }
  return sequence;
}

bool _sameSequence(List<LivenessChallenge> a, List<LivenessChallenge> b) {
  if (a.length != b.length) return false;
  for (var i = 0; i < a.length; i++) {
    if (a[i] != b[i]) return false;
  }
  return true;
}

/// Counts blinks as open -> closed -> open state transitions with hysteresis and debouncing.
/// Never time-based: nothing completes unless eyes were actually seen to close and reopen.
class BlinkDetector {
  BlinkDetector(this.config);

  final ActiveLivenessConfig config;

  int blinks = 0;
  _EyePhase _phase = _EyePhase.settling;
  int _openStreak = 0;
  int _closedStreak = 0;
  DateTime? _closedSince;

  bool get complete => blinks >= config.blinkCountRequired;

  /// Feeds one reading; returns true once the required blinks have been counted. Readings
  /// without eye probabilities change nothing and can never complete the challenge.
  bool accept(FaceFrameReading r, DateTime at) {
    final left = r.leftEyeOpen;
    final right = r.rightEyeOpen;
    if (left == null || right == null) return complete;
    final mean = (left + right) / 2;
    final isOpen = mean >= config.eyeOpenAbove;
    final isClosed = mean <= config.eyeClosedBelow;

    switch (_phase) {
      case _EyePhase.settling:
        // Must first SEE open eyes: a face that starts with eyes shut counts for nothing.
        if (isOpen) {
          if (++_openStreak >= config.minOpenFrames) _toOpen();
        } else if (isClosed) {
          _openStreak = 0;
        }
      case _EyePhase.open:
        if (isClosed) {
          if (++_closedStreak >= config.minClosedFrames) {
            _phase = _EyePhase.closed;
            _closedSince = at;
            _openStreak = 0;
          }
        } else if (isOpen) {
          _closedStreak = 0;
        }
      case _EyePhase.closed:
        if (at.difference(_closedSince!) > config.maxBlinkDuration) {
          // Held shut: not a blink. Wait to see open eyes again.
          _phase = _EyePhase.settling;
          _openStreak = 0;
          _closedSince = null;
        } else if (isOpen) {
          if (++_openStreak >= config.minOpenFrames) {
            blinks++;
            _toOpen();
          }
        } else if (isClosed) {
          _openStreak = 0;
        }
    }
    return complete;
  }

  void _toOpen() {
    _phase = _EyePhase.open;
    _openStreak = 0;
    _closedStreak = 0;
    _closedSince = null;
  }
}

enum _EyePhase { settling, open, closed }

/// Detects a turn toward [direction] relative to a neutral baseline captured at the start of
/// this challenge, so the user's natural head angle and camera mounting do not matter.
class HeadTurnDetector {
  HeadTurnDetector(this.config, this.direction) : assert(direction != LivenessChallenge.blinkTwice);

  final ActiveLivenessConfig config;
  final LivenessChallenge direction;

  final List<double> _neutral = [];
  double? _baseline;
  bool _armed = false;
  int _hold = 0;

  bool get hasBaseline => _baseline != null;

  /// Feeds one reading; returns true once the turn has been reached and briefly held.
  bool accept(FaceFrameReading r) {
    final yaw = r.yaw;
    final pitch = r.pitch;
    if (yaw == null || pitch == null || pitch.abs() > config.maxPitch) {
      // Unreadable or looking sharply up/down: not a valid turn frame. Also ends any hold.
      if (_baseline != null) _release();
      return false;
    }
    if (_baseline == null) {
      _collectNeutral(yaw);
      return false;
    }
    final sign = (direction == LivenessChallenge.turnLeft) == config.userLeftIsPositiveYaw ? 1.0 : -1.0;
    final toward = (yaw - _baseline!) * sign;
    if (toward >= config.headTurnThreshold) {
      _armed = true;
      _hold++;
    } else if (_armed && toward >= config.headTurnRelease) {
      _hold++; // hysteresis: jitter around the threshold doesn't drop a held turn
    } else {
      _release();
    }
    return _hold >= config.headTurnHoldFrames;
  }

  void _release() {
    _armed = false;
    _hold = 0;
  }

  void _collectNeutral(double yaw) {
    if (yaw.abs() > config.maxNeutralYaw) {
      _neutral.clear(); // still turned (e.g. from the previous challenge): wait for forward
      return;
    }
    _neutral.add(yaw);
    if (_neutral.length > config.neutralFrames) _neutral.removeAt(0);
    if (_neutral.length < config.neutralFrames) return;
    final lo = _neutral.reduce(min);
    final hi = _neutral.reduce(max);
    if (hi - lo > config.maxNeutralSpread) return; // not steady yet; window keeps sliding
    _baseline = _neutral.reduce((a, b) => a + b) / _neutral.length;
  }
}

/// Where an attempt is. The tail (`faceVerification`, `submittingAttendance`, `success`) is
/// owned by the attendance flow; the engine only enters `faceVerification` on request.
enum LivenessState {
  idle,
  initializingCamera,
  waitingForFace,
  challengeActive,
  challengeCompleted,
  nextChallenge,
  livenessPassed,
  faceVerification,
  submittingAttendance,
  success,
  noFaceDetected,
  multipleFacesDetected,
  challengeFailed,
  challengeTimeout,
  cameraError,
  cancelled,
}

const _recoverable = {LivenessState.noFaceDetected, LivenessState.multipleFacesDetected};
const _retryable = {LivenessState.challengeFailed, LivenessState.challengeTimeout, LivenessState.cameraError};

/// Valid transitions. Anything else throws [StateError].
final Map<LivenessState, Set<LivenessState>> livenessTransitions = {
  LivenessState.idle: {LivenessState.initializingCamera, LivenessState.cancelled},
  LivenessState.initializingCamera: {LivenessState.waitingForFace, LivenessState.cameraError, LivenessState.cancelled},
  LivenessState.waitingForFace: {
    LivenessState.challengeActive,
    LivenessState.noFaceDetected,
    LivenessState.multipleFacesDetected,
    LivenessState.challengeTimeout,
    LivenessState.cameraError,
    LivenessState.cancelled,
  },
  LivenessState.challengeActive: {
    LivenessState.challengeCompleted,
    LivenessState.noFaceDetected,
    LivenessState.multipleFacesDetected,
    LivenessState.challengeTimeout,
    LivenessState.challengeFailed,
    LivenessState.cameraError,
    LivenessState.cancelled,
  },
  LivenessState.challengeCompleted: {LivenessState.nextChallenge, LivenessState.livenessPassed, LivenessState.cancelled},
  LivenessState.nextChallenge: {LivenessState.challengeActive, LivenessState.cancelled},
  LivenessState.livenessPassed: {LivenessState.faceVerification, LivenessState.cancelled},
  LivenessState.faceVerification: {LivenessState.submittingAttendance, LivenessState.cameraError, LivenessState.cancelled},
  LivenessState.submittingAttendance: {LivenessState.success, LivenessState.cameraError, LivenessState.cancelled},
  LivenessState.success: {},
  LivenessState.noFaceDetected: {
    LivenessState.waitingForFace,
    LivenessState.challengeActive,
    LivenessState.multipleFacesDetected,
    LivenessState.challengeTimeout,
    LivenessState.cameraError,
    LivenessState.cancelled,
  },
  LivenessState.multipleFacesDetected: {
    LivenessState.waitingForFace,
    LivenessState.challengeActive,
    LivenessState.noFaceDetected,
    LivenessState.challengeTimeout,
    LivenessState.cameraError,
    LivenessState.cancelled,
  },
  // A retry starts a NEW session (and a new sequence) via [ActiveLivenessEngine.retry], which
  // resets to initializingCamera — these states never resume an old one.
  LivenessState.challengeFailed: {LivenessState.initializingCamera, LivenessState.cancelled},
  LivenessState.challengeTimeout: {LivenessState.initializingCamera, LivenessState.cancelled},
  LivenessState.cameraError: {LivenessState.initializingCamera, LivenessState.cancelled},
  LivenessState.cancelled: {},
};

/// What to tell the user right now, independent of wording/localization.
enum LivenessHint { none, positionFace, onlyOnePerson, moveCloser, moveBack, lookForward, doChallenge }

/// Drives one attendance attempt's liveness check. Pure Dart, no timers or I/O: callers feed
/// readings with a timestamp and call [checkTimeout] from a ticker, which keeps it testable
/// and leaves no callbacks to outlive the screen.
///
/// Every [start]/[retry] mints a new [sessionId] and a new random sequence. Readings tagged with
/// any other session id are ignored, so a late result from a previous attempt can never advance
/// or complete the current one. [reset] (also run on [cancel]) destroys all challenge state.
class ActiveLivenessEngine {
  ActiveLivenessEngine({this.config = const ActiveLivenessConfig(), Random? random}) : _random = random ?? Random.secure();

  final ActiveLivenessConfig config;
  final Random _random;

  LivenessState _state = LivenessState.idle;
  LivenessHint _hint = LivenessHint.none;
  int _sessionId = 0;
  int _attempts = 0;
  List<LivenessChallenge> _sequence = const [];
  List<LivenessChallenge>? _lastSequence;
  int _index = 0;
  LivenessState _resumeTo = LivenessState.waitingForFace;
  DateTime? _deadline;
  int _goodFrames = 0;
  BlinkDetector? _blink;
  HeadTurnDetector? _turn;
  final List<LivenessState> _history = [];

  LivenessState get state => _state;
  LivenessHint get hint => _hint;
  int get sessionId => _sessionId;
  int get attemptsUsed => _attempts;
  bool get attemptsExhausted => _attempts >= config.maximumLivenessAttempts;
  List<LivenessChallenge> get sequence => List.unmodifiable(_sequence);
  int get challengeIndex => _index;
  int get challengeCount => _sequence.length;
  LivenessChallenge? get currentChallenge =>
      _state == LivenessState.challengeActive || (_recoverable.contains(_state) && _resumeTo == LivenessState.challengeActive)
          ? _sequence[_index]
          : null;
  bool get passed => _state == LivenessState.livenessPassed;

  /// False once the attempt has ended or passed: callers should then skip frame analysis
  /// altogether rather than burn CPU on frames that will be ignored.
  bool get consumesFrames =>
      _state == LivenessState.waitingForFace || _state == LivenessState.challengeActive || _recoverable.contains(_state);

  /// Every state entered, in order — for tests and diagnostics.
  List<LivenessState> get history => List.unmodifiable(_history);

  /// Begins a fresh attempt: new session id, new random sequence, counted against the limit.
  /// Returns false (and stays put) when the attempt limit is used up.
  bool start() {
    if (_state != LivenessState.idle && !_retryable.contains(_state)) {
      throw StateError('Cannot start liveness from $_state');
    }
    if (attemptsExhausted) return false;
    _attempts++;
    _sessionId++;
    _sequence = generateChallengeSequence(_random, length: config.challengesPerAttempt, previous: _lastSequence);
    _lastSequence = _sequence;
    _index = 0;
    _goodFrames = 0;
    _deadline = null;
    _blink = null;
    _turn = null;
    _hint = LivenessHint.none;
    _resumeTo = LivenessState.waitingForFace;
    _history.clear();
    _go(LivenessState.initializingCamera);
    return true;
  }

  /// Manual retry after a failure: a NEW session and NEW sequence. False when attempts are spent.
  bool retry() => start();

  /// Camera is up and streaming.
  void cameraReady(DateTime now) {
    _go(LivenessState.waitingForFace);
    _deadline = now.add(config.faceWaitTimeout);
  }

  void cameraFailed() {
    if (_state == LivenessState.cancelled || _state == LivenessState.success) return;
    _cancelWork();
    _go(LivenessState.cameraError);
  }

  /// Feeds one analysed frame. Ignored unless [forSession] is the current session and the
  /// engine is in a state that consumes frames.
  LivenessState accept(FaceFrameReading r, DateTime at, {required int forSession}) {
    if (forSession != _sessionId) return _state;
    if (!consumesFrames) return _state;

    if (r.faceCount == 0) return _faceProblem(LivenessState.noFaceDetected, LivenessHint.positionFace);
    if (r.faceCount > 1) return _faceProblem(LivenessState.multipleFacesDetected, LivenessHint.onlyOnePerson);
    final width = r.faceWidthFraction;
    if (width == null || width < config.minFaceWidth) return _qualityProblem(LivenessHint.moveCloser);
    if (width > config.maxFaceWidth) return _qualityProblem(LivenessHint.moveBack);

    if (_recoverable.contains(_state)) {
      // Back to one face. Detectors restart so nothing carries across the interruption.
      _blink = null;
      _turn = null;
      _goodFrames = 0;
      _go(_resumeTo);
    }

    if (_state == LivenessState.waitingForFace) {
      final yaw = r.yaw, pitch = r.pitch;
      if (yaw == null || pitch == null || yaw.abs() > config.maxNeutralYaw || pitch.abs() > config.maxPitch) {
        _goodFrames = 0;
        _hint = LivenessHint.lookForward;
        return _state;
      }
      if (++_goodFrames < config.neutralFrames) {
        _hint = LivenessHint.none;
        return _state;
      }
      _beginChallenge(at);
      return _state;
    }

    // challengeActive
    if (_expired(at)) return _timeout();
    _hint = LivenessHint.doChallenge;
    final done = switch (_sequence[_index]) {
      LivenessChallenge.blinkTwice => (_blink ??= BlinkDetector(config)).accept(r, at),
      LivenessChallenge.turnLeft || LivenessChallenge.turnRight => (_turn ??= HeadTurnDetector(config, _sequence[_index])).accept(r),
    };
    if (done) _completeChallenge(at);
    return _state;
  }

  /// Call from a periodic ticker. Moves to [LivenessState.challengeTimeout] when time is up.
  LivenessState checkTimeout(DateTime now) {
    final waiting = _state == LivenessState.waitingForFace || _state == LivenessState.challengeActive || _recoverable.contains(_state);
    if (waiting && _expired(now)) _timeout();
    return _state;
  }

  /// Marks hand-off to the existing face verification. Only valid after [passed].
  void beginVerification() => _go(LivenessState.faceVerification);
  void beginSubmission() => _go(LivenessState.submittingAttendance);
  void markSuccess() {
    _go(LivenessState.success);
    _reset();
  }

  /// A hard failure of the verification/submission hand-off (not a liveness failure).
  void verificationFailed() {
    _cancelWork();
    _go(LivenessState.cameraError);
  }

  /// User left (closed camera, navigated, logged out, widget disposed). Destroys challenge
  /// state; nothing completed so far survives.
  void cancel() {
    if (_state == LivenessState.cancelled) return;
    if (_state == LivenessState.success) return;
    _cancelWork();
    _state = LivenessState.cancelled;
    _history.add(_state);
    _reset();
  }

  void _beginChallenge(DateTime at) {
    _blink = null;
    _turn = null;
    _hint = LivenessHint.doChallenge;
    _deadline = at.add(config.challengeTimeout);
    _go(LivenessState.challengeActive);
    _resumeTo = LivenessState.challengeActive;
  }

  void _completeChallenge(DateTime at) {
    _go(LivenessState.challengeCompleted);
    _blink = null;
    _turn = null;
    if (_index + 1 >= _sequence.length) {
      _deadline = null;
      _hint = LivenessHint.none;
      _go(LivenessState.livenessPassed);
      // The proof is spent: it cannot be replayed into another attempt.
      _lastSequence = null;
      return;
    }
    _index++;
    _go(LivenessState.nextChallenge);
    _go(LivenessState.challengeActive);
    _deadline = at.add(config.challengeTimeout);
  }

  LivenessState _faceProblem(LivenessState to, LivenessHint hint) {
    _hint = hint;
    _blink = null;
    _turn = null;
    _goodFrames = 0;
    if (_state != to) {
      if (!_recoverable.contains(_state)) _resumeTo = _state;
      _go(to);
    }
    return _state;
  }

  LivenessState _qualityProblem(LivenessHint hint) {
    _hint = hint;
    _goodFrames = 0;
    _blink = null;
    _turn = null;
    return _state;
  }

  bool _expired(DateTime at) => _deadline != null && at.isAfter(_deadline!);

  LivenessState _timeout() {
    _cancelWork();
    _go(LivenessState.challengeTimeout);
    return _state;
  }

  void _go(LivenessState to) {
    if (!(livenessTransitions[_state]?.contains(to) ?? false)) {
      throw StateError('Invalid liveness transition $_state -> $to');
    }
    _state = to;
    _history.add(to);
  }

  /// Stops all detection but keeps the state (for failure screens).
  void _cancelWork() {
    _blink = null;
    _turn = null;
    _deadline = null;
    _goodFrames = 0;
    _hint = LivenessHint.none;
  }

  void _reset() {
    _sequence = const [];
    _lastSequence = null;
    _index = 0;
    _sessionId++; // anything still in flight is now stale
    _cancelWork();
  }
}
