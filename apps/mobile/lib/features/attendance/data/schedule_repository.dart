import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../core/api/api_client.dart';
import '../../../core/providers.dart';
import '../domain/weekly_schedule.dart';

/// Weekly schedule and shift-swap calls. Employees raise, agree to and withdraw swaps themselves;
/// a roster manager approves or declines (the API enforces who may do what).
class ScheduleRepository {
  ScheduleRepository(this._client);
  final ApiClient _client;

  Future<WeeklySchedule> weeklySchedule({required String weekStart, String? branchId, String? departmentId}) => _client.get(
        _path('/rosters/weekly-schedule', {'week_start': weekStart, if (branchId != null && branchId.isNotEmpty) 'branch_id': branchId, if (departmentId != null && departmentId.isNotEmpty) 'department_id': departmentId}),
        parse: (d) => WeeklySchedule.fromJson(d as Map<String, dynamic>),
      );

  Future<List<SwapRequest>> listSwaps({String? status}) async => (await _client.getList<SwapRequest>(
        '/rosters/swap-requests',
        filters: {if (status != null) 'status': status},
        parseItem: (d) => SwapRequest.fromJson(d as Map<String, dynamic>),
      ))
          .data;

  Future<List<SwapCandidate>> candidates(String date) async => (await _client.getList<SwapCandidate>(
        '/rosters/swap-candidates',
        filters: {'swap_date': date},
        parseItem: (d) => SwapCandidate.fromJson(d as Map<String, dynamic>),
      ))
          .data;

  Future<SwapRequest> requestSwap({required String counterpartEmployeeId, required String date, String? reason}) => _client.post(
        '/rosters/swap-requests/mine',
        body: {'counterpart_employee_id': counterpartEmployeeId, 'swap_date': date, if (reason != null && reason.trim().isNotEmpty) 'reason': reason.trim()},
        parse: (d) => SwapRequest.fromJson(d as Map<String, dynamic>),
      );

  Future<SwapRequest> consent(String id) => _act(id, 'consent');
  Future<SwapRequest> withdraw(String id) => _act(id, 'withdraw');
  Future<SwapRequest> approve(String id) => _act(id, 'approve');
  Future<SwapRequest> decline(String id) => _act(id, 'decline');

  Future<SwapRequest> _act(String id, String action) => _client.post(
        '/rosters/swap-requests/$id/$action',
        body: const <String, dynamic>{},
        parse: (d) => SwapRequest.fromJson(d as Map<String, dynamic>),
      );

  static String _path(String base, Map<String, String> query) => '$base?${Uri(queryParameters: query).query}';
}

final scheduleRepositoryProvider = Provider<ScheduleRepository>((ref) => ScheduleRepository(ref.watch(apiClientProvider)));
