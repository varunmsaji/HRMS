import 'dart:math';

import 'package:flutter_test/flutter_test.dart';
import 'package:hrms_mobile/features/attendance/domain/active_liveness.dart';
import 'package:hrms_mobile/features/attendance/domain/face_liveness_capture.dart';

final _t0 = DateTime(2026, 10, 31, 9);
DateTime _at(int ms) => _t0.add(Duration(milliseconds: ms));

FaceFrameReading _r({int faces = 1, double width = 0.45, double? yaw = 0, double? pitch = 0, double? eyes = 0.9}) =>
    FaceFrameReading(faceCount: faces, faceWidthFraction: width, yaw: yaw, pitch: pitch, leftEyeOpen: eyes, rightEyeOpen: eyes);

const _cfg = ActiveLivenessConfig(enabled: true);

/// Feeds frames 100 ms apart starting at [from]; returns the next free timestamp (ms).
class _Feeder {
  _Feeder(this.engine);
  final ActiveLivenessEngine engine;
  int ms = 0;

  void feed(FaceFrameReading r, {int times = 1, int? session}) {
    for (var i = 0; i < times; i++) {
      engine.accept(r, _at(ms), forSession: session ?? engine.sessionId);
      ms += 100;
    }
  }

  /// One genuine blink: open frames, closed frames, open frames.
  void blink() {
    feed(_r(eyes: 0.9), times: 2);
    feed(_r(eyes: 0.05), times: 2);
    feed(_r(eyes: 0.9), times: 2);
  }

  void turn(double yaw) => feed(_r(yaw: yaw), times: 4);
}

ActiveLivenessEngine _engine({ActiveLivenessConfig config = _cfg, int seed = 1}) => ActiveLivenessEngine(config: config, random: Random(seed));

/// Engine already past the neutral-face stage with a known sequence.
(ActiveLivenessEngine, _Feeder) _active(List<LivenessChallenge> wanted) {
  for (var seed = 0; seed < 500; seed++) {
    final e = _engine(seed: seed)..start();
    if (_sameStart(e.sequence, wanted)) {
      e.cameraReady(_at(0));
      final f = _Feeder(e);
      f.feed(_r(), times: 4);
      expect(e.state, LivenessState.challengeActive);
      return (e, f);
    }
  }
  throw StateError('no seed found');
}

bool _sameStart(List<LivenessChallenge> a, List<LivenessChallenge> b) {
  for (var i = 0; i < b.length; i++) {
    if (a[i] != b[i]) return false;
  }
  return true;
}

void main() {
  group('challenge generation', () {
    test('no duplicate challenge within a sequence', () {
      final random = Random(7);
      for (var i = 0; i < 200; i++) {
        final s = generateChallengeSequence(random);
        expect(s.toSet().length, s.length);
        expect(s.length, 2);
      }
    });

    test('is random: every challenge appears first, across many draws', () {
      final random = Random(3);
      final firsts = {for (var i = 0; i < 200; i++) generateChallengeSequence(random).first};
      expect(firsts, LivenessChallenge.values.toSet());
    });

    test('a retry never reissues the failed sequence', () {
      final random = Random(5);
      for (var i = 0; i < 200; i++) {
        final first = generateChallengeSequence(random);
        final second = generateChallengeSequence(random, previous: first);
        expect(second, isNot(first));
      }
    });

    test('engine mints a new session id and a different sequence on retry and on a new engine', () {
      final e = _engine()..start();
      final firstSession = e.sessionId;
      final firstSeq = e.sequence;
      e.cameraReady(_at(0));
      e.checkTimeout(_at(60000));
      expect(e.state, LivenessState.challengeTimeout);
      expect(e.retry(), isTrue);
      expect(e.sessionId, isNot(firstSession));
      expect(e.sequence, isNot(firstSeq));
      expect(e.state, LivenessState.initializingCamera);
    });
  });

  group('BlinkDetector', () {
    test('open -> closed -> open is one blink; two complete the challenge', () {
      final d = BlinkDetector(_cfg);
      var ms = 0;
      bool feed(double eyes) => d.accept(_r(eyes: eyes), _at(ms += 100));
      feed(0.9); feed(0.9);
      feed(0.05); feed(0.05);
      feed(0.9);
      expect(d.blinks, 0, reason: 'reopening must be confirmed over several frames');
      feed(0.9);
      expect(d.blinks, 1);
      expect(d.complete, isFalse);
      feed(0.05); feed(0.05);
      feed(0.9);
      expect(feed(0.9), isTrue);
      expect(d.blinks, 2);
    });

    test('single-frame noise is never a blink', () {
      final d = BlinkDetector(_cfg);
      var ms = 0;
      for (var i = 0; i < 10; i++) {
        d.accept(_r(eyes: 0.9), _at(ms += 100));
        d.accept(_r(eyes: 0.9), _at(ms += 100));
        d.accept(_r(eyes: 0.05), _at(ms += 100)); // lone closed frame
      }
      expect(d.blinks, 0);
    });

    test('hysteresis: mid-range readings neither close nor open', () {
      final d = BlinkDetector(_cfg);
      var ms = 0;
      for (final e in [0.9, 0.9, 0.45, 0.45, 0.45, 0.45, 0.9, 0.9]) {
        d.accept(_r(eyes: e), _at(ms += 100));
      }
      expect(d.blinks, 0);
    });

    test('eyes held shut are not a blink; open eyes must be seen again first', () {
      final d = BlinkDetector(_cfg);
      var ms = 0;
      for (var i = 0; i < 2; i++) { d.accept(_r(eyes: 0.9), _at(ms += 100)); }
      for (var i = 0; i < 20; i++) { d.accept(_r(eyes: 0.05), _at(ms += 100)); }
      for (var i = 0; i < 2; i++) { d.accept(_r(eyes: 0.9), _at(ms += 100)); }
      expect(d.blinks, 0);
    });

    test('a face that starts with eyes shut does not count its first opening', () {
      final d = BlinkDetector(_cfg);
      var ms = 0;
      for (var i = 0; i < 3; i++) { d.accept(_r(eyes: 0.05), _at(ms += 100)); }
      for (var i = 0; i < 3; i++) { d.accept(_r(eyes: 0.9), _at(ms += 100)); }
      expect(d.blinks, 0);
    });

    test('a static open-eyed image never completes, however long it is shown', () {
      final d = BlinkDetector(_cfg);
      for (var i = 0; i < 500; i++) {
        expect(d.accept(_r(eyes: 0.95), _at(i * 100)), isFalse);
      }
    });

    test('missing eye probabilities never complete', () {
      final d = BlinkDetector(_cfg);
      for (var i = 0; i < 50; i++) {
        d.accept(const FaceFrameReading(faceCount: 1, faceWidthFraction: 0.4, yaw: 0, pitch: 0), _at(i * 100));
      }
      expect(d.blinks, 0);
    });
  });

  group('HeadTurnDetector', () {
    bool run(HeadTurnDetector d, List<double> yaws) {
      var done = false;
      for (final y in yaws) { done = d.accept(_r(yaw: y)); }
      return done;
    }

    test('left turn relative to the baseline completes (positive yaw = user left by default)', () {
      final d = HeadTurnDetector(_cfg, LivenessChallenge.turnLeft);
      expect(run(d, [0, 0, 0, 0]), isFalse);
      expect(d.hasBaseline, isTrue);
      expect(run(d, [25, 26, 27]), isTrue);
    });

    test('right turn is the opposite sign', () {
      final d = HeadTurnDetector(_cfg, LivenessChallenge.turnRight);
      run(d, [0, 0, 0, 0]);
      expect(run(d, [25, 26, 27, 28]), isFalse, reason: 'turning the wrong way must not count');
      expect(run(d, [0, -25, -26, -27]), isTrue);
    });

    test('mapping can be inverted for platforms with the opposite yaw sign', () {
      const inverted = ActiveLivenessConfig(userLeftIsPositiveYaw: false);
      final d = HeadTurnDetector(inverted, LivenessChallenge.turnLeft);
      run(d, [0, 0, 0, 0]);
      expect(run(d, [-25, -26, -27]), isTrue);
    });

    test('is relative to the neutral baseline, not absolute yaw', () {
      final d = HeadTurnDetector(_cfg, LivenessChallenge.turnLeft);
      run(d, [-10, -10, -10, -10]); // naturally tilted right of centre
      expect(run(d, [5, 6, 7, 8]), isFalse, reason: '15 degrees from baseline is below the threshold');
      expect(run(d, [12, 12, 12]), isTrue);
    });

    test('minor movement does not complete', () {
      final d = HeadTurnDetector(_cfg, LivenessChallenge.turnLeft);
      run(d, [0, 0, 0, 0]);
      expect(run(d, [5, 8, 10, 12, 9, 15, 18, 19, 18, 19]), isFalse);
    });

    test('hysteresis: jitter between release and threshold keeps the hold', () {
      final d = HeadTurnDetector(_cfg, LivenessChallenge.turnLeft);
      run(d, [0, 0, 0, 0]);
      expect(run(d, [21, 15, 21]), isTrue);
    });

    test('dropping below the release level resets the hold', () {
      final d = HeadTurnDetector(_cfg, LivenessChallenge.turnLeft);
      run(d, [0, 0, 0, 0]);
      expect(run(d, [25, 25, 5, 25, 25]), isFalse);
    });

    test('does not start while the head is still turned; waits for neutral', () {
      final d = HeadTurnDetector(_cfg, LivenessChallenge.turnRight);
      run(d, [30, 30, 30, 30, 30]);
      expect(d.hasBaseline, isFalse);
      run(d, [0, 0, 0, 0]);
      expect(d.hasBaseline, isTrue);
    });

    test('a moving head does not establish a baseline', () {
      final d = HeadTurnDetector(_cfg, LivenessChallenge.turnLeft);
      run(d, [0, 8, -8, 8, -8, 8]);
      expect(d.hasBaseline, isFalse);
    });

    test('extreme pitch frames do not count', () {
      final d = HeadTurnDetector(_cfg, LivenessChallenge.turnLeft);
      run(d, [0, 0, 0, 0]);
      var done = false;
      for (var i = 0; i < 6; i++) { done = d.accept(_r(yaw: 30, pitch: 50)); }
      expect(done, isFalse);
    });
  });

  group('state machine', () {
    test('full happy path: blink then left, through every state, to livenessPassed', () {
      final (e, f) = _active([LivenessChallenge.blinkTwice, LivenessChallenge.turnLeft]);
      f.blink(); f.blink();
      expect(e.state, LivenessState.challengeActive);
      expect(e.currentChallenge, LivenessChallenge.turnLeft);
      f.turn(0);
      f.feed(_r(yaw: 25), times: 4);
      expect(e.state, LivenessState.livenessPassed);
      expect(e.passed, isTrue);
      expect(e.history, [
        LivenessState.initializingCamera,
        LivenessState.waitingForFace,
        LivenessState.challengeActive,
        LivenessState.challengeCompleted,
        LivenessState.nextChallenge,
        LivenessState.challengeActive,
        LivenessState.challengeCompleted,
        LivenessState.livenessPassed,
      ]);
    });

    test('a static frame fed forever never passes', () {
      final e = _engine()..start();
      e.cameraReady(_at(0));
      final f = _Feeder(e);
      // 9 s: inside the face-wait budget, longer than any single challenge needs.
      f.feed(_r(), times: 90);
      expect(e.passed, isFalse);
      f.feed(_r(), times: 200);
      expect(e.state, isNot(LivenessState.livenessPassed));
      expect(e.state, LivenessState.challengeTimeout);
    });

    test('no face and multiple faces are blocking, and recover', () {
      final (e, f) = _active([LivenessChallenge.turnLeft, LivenessChallenge.blinkTwice]);
      f.feed(_r(faces: 0));
      expect(e.state, LivenessState.noFaceDetected);
      expect(e.hint, LivenessHint.positionFace);
      f.feed(_r(faces: 2));
      expect(e.state, LivenessState.multipleFacesDetected);
      expect(e.hint, LivenessHint.onlyOnePerson);
      f.feed(_r(yaw: 0));
      expect(e.state, LivenessState.challengeActive);
    });

    test('a second face mid-turn discards progress', () {
      final (e, f) = _active([LivenessChallenge.turnLeft, LivenessChallenge.blinkTwice]);
      f.turn(0);
      f.feed(_r(yaw: 25), times: 2);
      f.feed(_r(faces: 2));
      f.feed(_r(yaw: 25), times: 3); // new baseline needed first: this is "turned", so no baseline
      expect(e.state, LivenessState.challengeActive);
      expect(e.currentChallenge, LivenessChallenge.turnLeft);
    });

    test('timeout moves to challengeTimeout; frames after it are ignored', () {
      final (e, f) = _active([LivenessChallenge.blinkTwice, LivenessChallenge.turnLeft]);
      e.checkTimeout(_at(f.ms + 13000));
      expect(e.state, LivenessState.challengeTimeout);
      f.blink(); f.blink();
      expect(e.state, LivenessState.challengeTimeout);
    });

    test('waiting for a face times out too', () {
      final e = _engine()..start();
      e.cameraReady(_at(0));
      e.checkTimeout(_at(21000));
      expect(e.state, LivenessState.challengeTimeout);
    });

    test('maximum attempts is enforced and never silently bypassed', () {
      final e = _engine(config: const ActiveLivenessConfig(enabled: true, maximumLivenessAttempts: 2))..start();
      e.cameraReady(_at(0));
      e.checkTimeout(_at(30000));
      expect(e.retry(), isTrue);
      e.cameraReady(_at(0));
      e.checkTimeout(_at(30000));
      expect(e.attemptsExhausted, isTrue);
      expect(e.retry(), isFalse);
      expect(e.passed, isFalse);
      expect(e.state, LivenessState.challengeTimeout);
    });

    test('frames tagged with an old session id are ignored', () {
      final (e, f) = _active([LivenessChallenge.blinkTwice, LivenessChallenge.turnLeft]);
      final old = e.sessionId;
      e.checkTimeout(_at(f.ms + 13000));
      e.retry();
      e.cameraReady(_at(0));
      final f2 = _Feeder(e);
      f2.feed(_r(), times: 6, session: old);
      expect(e.state, LivenessState.waitingForFace);
      expect(e.challengeIndex, 0);
    });

    test('a completed attempt cannot be completed again by stale frames after cancel', () {
      final (e, f) = _active([LivenessChallenge.blinkTwice, LivenessChallenge.turnLeft]);
      final session = e.sessionId;
      e.cancel();
      expect(e.state, LivenessState.cancelled);
      expect(e.sequence, isEmpty);
      f.feed(_r(), times: 20, session: session);
      f.blink();
      expect(e.state, LivenessState.cancelled);
      expect(e.passed, isFalse);
    });

    test('cancel after pass destroys the result', () {
      final (e, f) = _active([LivenessChallenge.blinkTwice, LivenessChallenge.turnLeft]);
      f.blink(); f.blink(); f.turn(0); f.feed(_r(yaw: 25), times: 4);
      expect(e.passed, isTrue);
      e.cancel();
      expect(e.passed, isFalse);
      expect(e.sequence, isEmpty);
    });

    test('frames after a pass cannot restart the challenge or clear the pass', () {
      final (e, f) = _active([LivenessChallenge.blinkTwice, LivenessChallenge.turnLeft]);
      f.blink();
      f.blink();
      f.turn(0);
      f.feed(_r(yaw: 25), times: 4);
      expect(e.passed, isTrue);
      final session = e.sessionId;
      f.feed(_r(faces: 0), times: 5, session: session);
      f.blink();
      expect(e.state, LivenessState.livenessPassed);
      expect(e.passed, isTrue);
      expect(e.challengeIndex, 1);
    });

    test('verification hand-off is only reachable from livenessPassed', () {
      final e = _engine()..start();
      expect(e.beginVerification, throwsStateError);
      expect(e.beginSubmission, throwsStateError);
      expect(e.markSuccess, throwsStateError);
    });

    test('verification hand-off after pass', () {
      final (e, f) = _active([LivenessChallenge.turnLeft, LivenessChallenge.turnRight]);
      f.turn(0); f.feed(_r(yaw: 25), times: 4);
      f.turn(0); f.feed(_r(yaw: -25), times: 4);
      expect(e.passed, isTrue);
      e.beginVerification();
      e.beginSubmission();
      e.markSuccess();
      expect(e.state, LivenessState.success);
    });

    test('transition table: terminal states are closed, nothing re-enters idle', () {
      expect(livenessTransitions[LivenessState.success], isEmpty);
      expect(livenessTransitions[LivenessState.cancelled], isEmpty);
      for (final to in livenessTransitions.values) {
        expect(to, isNot(contains(LivenessState.idle)));
      }
      // Liveness can only be passed from a completed challenge.
      final into = livenessTransitions.entries.where((e) => e.value.contains(LivenessState.livenessPassed)).map((e) => e.key);
      expect(into, [LivenessState.challengeCompleted]);
    });

    test('camera error is retryable with a new session', () {
      final e = _engine()..start();
      final s = e.sessionId;
      e.cameraFailed();
      expect(e.state, LivenessState.cameraError);
      expect(e.retry(), isTrue);
      expect(e.sessionId, isNot(s));
    });

    test('face quality hints: too small / too big', () {
      final e = _engine()..start();
      e.cameraReady(_at(0));
      e.accept(_r(width: 0.1), _at(0), forSession: e.sessionId);
      expect(e.hint, LivenessHint.moveCloser);
      e.accept(_r(width: 0.95), _at(100), forSession: e.sessionId);
      expect(e.hint, LivenessHint.moveBack);
      e.accept(_r(yaw: 40), _at(200), forSession: e.sessionId);
      expect(e.hint, LivenessHint.lookForward);
      expect(e.state, LivenessState.waitingForFace);
    });
  });
}
