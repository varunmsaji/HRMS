import 'package:flutter_test/flutter_test.dart';
import 'package:hrms_mobile/features/attendance/domain/face_framing.dart';

FaceFraming strict(double cx, double cy, double h) => judgeFraming(centerX: cx, centerY: cy, heightFraction: h, strict: true);

void main() {
  test('a face of the right size in the middle of the oval is fine', () {
    expect(strict(0.5, 0.46, 0.4), FaceFraming.ok);
  });

  test('too small means move closer, too big means move back', () {
    expect(strict(0.5, 0.46, 0.2), FaceFraming.tooFar);
    expect(strict(0.5, 0.46, 0.7), FaceFraming.tooClose);
    expect(framingHint(FaceFraming.tooFar), 'Move a little closer');
    expect(framingHint(FaceFraming.tooClose), 'Move back a little');
  });

  test('a face away from the oval centre must be centred', () {
    expect(strict(0.2, 0.46, 0.4), FaceFraming.offCenter);
    expect(strict(0.5, 0.8, 0.4), FaceFraming.offCenter);
    expect(framingHint(FaceFraming.ok), isNull);
  });

  test('turned and tilted poses get more room than the straight-ahead photo', () {
    // Off-centre and smallish: refused for the front photo, fine for a turned one.
    expect(strict(0.34, 0.46, 0.27), FaceFraming.tooFar);
    expect(judgeFraming(centerX: 0.34, centerY: 0.46, heightFraction: 0.27, strict: false), FaceFraming.ok);
  });
}
