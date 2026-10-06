import 'package:flutter_test/flutter_test.dart';
import 'package:hrms_mobile/features/attendance/data/attendance_repository.dart';

Map<String, dynamic> _body({Object? liveness}) => {
      'punch': {'id': 'p1', 'direction': 'IN', 'punch_time': '2026-10-03T09:00:00Z'},
      'similarity': '0.97',
      'liveness_score': liveness,
    };

void main() {
  test('a punch accepted without a liveness score parses with a null score', () {
    final result = FacePunchResult.fromJson(_body());
    expect(result.livenessScore, isNull);
    expect(result.similarity, closeTo(0.97, 1e-9));
    expect(result.punchId, 'p1');
  });

  test('a numeric or string liveness score still parses', () {
    expect(FacePunchResult.fromJson(_body(liveness: '0.91')).livenessScore, closeTo(0.91, 1e-9));
    expect(FacePunchResult.fromJson(_body(liveness: 0.5)).livenessScore, 0.5);
  });
}
