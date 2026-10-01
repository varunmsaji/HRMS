import 'package:flutter_test/flutter_test.dart';
import 'package:hrms_mobile/features/attendance/domain/face_pose_tracker.dart';

FacePoseReading face(double yaw, double pitch) => FacePoseReading(faceCount: 1, yaw: yaw, pitch: pitch);

/// Feeds [reading] until the tracker reports ready (or gives up), then captures.
bool hold(FacePoseTracker tracker, FacePoseReading reading) {
  for (var i = 0; i < tracker.requiredStableReadings; i++) {
    if (tracker.accept(reading)) {
      tracker.advance();
      return true;
    }
  }
  return false;
}

void main() {
  test('walks front, both turns and both tilts in order', () {
    final tracker = FacePoseTracker();
    expect(tracker.current.angle, 'front');
    expect(hold(tracker, face(2, -3)), isTrue);
    expect(tracker.current.angle, 'left');
    expect(hold(tracker, face(30, 0)), isTrue);
    expect(tracker.current.angle, 'right');
    expect(hold(tracker, face(-30, 0)), isTrue);
    expect(tracker.current.angle, 'up');
    expect(hold(tracker, face(0, 20)), isTrue);
    expect(tracker.current.angle, 'down');
    expect(hold(tracker, face(0, -20)), isTrue);
    expect(tracker.isDone, isTrue);
  });

  test('the second turn must go the opposite way from the first', () {
    final tracker = FacePoseTracker();
    hold(tracker, face(0, 0));
    hold(tracker, face(-28, 0));
    expect(hold(tracker, face(-28, 0)), isFalse, reason: 'same side as the first turn');
    expect(hold(tracker, face(28, 0)), isTrue);
  });

  test('the second tilt must go the opposite way from the first', () {
    final tracker = FacePoseTracker();
    hold(tracker, face(0, 0));
    hold(tracker, face(30, 0));
    hold(tracker, face(-30, 0));
    hold(tracker, face(0, -18));
    expect(hold(tracker, face(0, -18)), isFalse);
    expect(hold(tracker, face(0, 18)), isTrue);
  });

  test('front rejects a turned or tilted head', () {
    final tracker = FacePoseTracker();
    expect(hold(tracker, face(15, 0)), isFalse);
    expect(hold(tracker, face(0, 15)), isFalse);
    expect(tracker.current.angle, 'front');
  });

  test('turns outside 20-45 degrees do not count', () {
    final tracker = FacePoseTracker();
    hold(tracker, face(0, 0));
    expect(hold(tracker, face(12, 0)), isFalse, reason: 'too little');
    expect(hold(tracker, face(70, 0)), isFalse, reason: 'too far — face no longer matchable');
    expect(hold(tracker, face(35, 0)), isTrue);
  });

  test('needs several consecutive qualifying readings', () {
    final tracker = FacePoseTracker(requiredStableReadings: 3);
    expect(tracker.accept(face(0, 0)), isFalse);
    expect(tracker.accept(face(0, 0)), isFalse);
    expect(tracker.accept(face(20, 0)), isFalse, reason: 'a bad reading resets the count');
    expect(tracker.accept(face(0, 0)), isFalse);
    expect(tracker.accept(face(0, 0)), isFalse);
    expect(tracker.accept(face(0, 0)), isTrue);
  });

  test('no face or several faces never qualify, with a hint', () {
    final tracker = FacePoseTracker(requiredStableReadings: 1);
    const none = FacePoseReading(faceCount: 0);
    const two = FacePoseReading(faceCount: 2, yaw: 0, pitch: 0);
    expect(tracker.accept(none), isFalse);
    expect(tracker.accept(two), isFalse);
    expect(tracker.hintFor(none), contains('into the frame'));
    expect(tracker.hintFor(two), contains('only you'));
    expect(tracker.hintFor(face(0, 0)), isNull);
  });
}
