import 'package:flutter_test/flutter_test.dart';
import 'package:hrms_mobile/core/api/api_client.dart';
import 'package:hrms_mobile/features/attendance/data/policy_repository.dart';
import 'package:hrms_mobile/features/leave/data/leave_repository.dart';
import 'package:hrms_mobile/features/payroll/data/payroll_repository.dart';

/// Records the path and `ifMatch` of every write. The backend rejects these endpoints with 422
/// when `If-Match` is missing, and the repositories used to accept `ifMatch` and drop it.
class _RecordingClient implements ApiClient {
  final calls = <({String path, String? ifMatch})>[];

  @override
  dynamic noSuchMethod(Invocation invocation) {
    final path = invocation.positionalArguments.isNotEmpty ? invocation.positionalArguments.first as String : '';
    calls.add((path: path, ifMatch: invocation.namedArguments[#ifMatch] as String?));
    throw StateError('recorded');
  }
}

Future<void> _swallow(Future<dynamic> Function() call) async {
  try {
    await call();
  } catch (_) {}
}

void main() {
  late _RecordingClient client;
  setUp(() => client = _RecordingClient());

  void expectSent(String pathEnd) {
    final call = client.calls.single;
    expect(call.path, endsWith(pathEnd));
    expect(call.ifMatch, '7', reason: '${call.path} must send If-Match');
  }

  test('policy version publish sends If-Match', () async {
    await _swallow(() => PolicyRepository(client, 'attendance-policies').publishVersion('p', 'v', ifMatch: '7'));
    expectSent('/attendance-policies/p/versions/v/publish');
  });

  test('leave application decisions send If-Match', () async {
    final repo = LeaveRepository(client);
    final cases = <String, Future<dynamic> Function()>{
      '/leave-applications/a/approve': () => repo.approveLeaveApplication('a', ifMatch: '7'),
      '/leave-applications/a/reject': () => repo.rejectLeaveApplication('a', ifMatch: '7'),
      '/leave-applications/a/cancel': () => repo.cancelLeaveApplication('a', ifMatch: '7'),
    };
    for (final e in cases.entries) {
      client.calls.clear();
      await _swallow(e.value);
      expectSent(e.key);
    }
  });

  test('pay-run transitions and statutory-rate verify send If-Match', () async {
    final repo = PayrollRepository(client);
    final cases = <String, Future<dynamic> Function()>{
      '/payroll/pay-runs/r/lock-inputs': () => repo.lockInputs('r', ifMatch: '7'),
      '/payroll/pay-runs/r/compute': () => repo.compute('r', ifMatch: '7'),
      '/payroll/pay-runs/r/approve': () => repo.approve('r', ifMatch: '7'),
      '/payroll/pay-runs/r/finalise': () => repo.finalise('r', ifMatch: '7'),
      '/payroll/pay-runs/r/mark-paid': () => repo.markPaid('r', ifMatch: '7'),
      '/payroll/statutory-rates/r/verify': () => repo.verifyStatutoryRate('r', ifMatch: '7'),
    };
    for (final e in cases.entries) {
      client.calls.clear();
      await _swallow(e.value);
      expectSent(e.key);
    }
  });
}
