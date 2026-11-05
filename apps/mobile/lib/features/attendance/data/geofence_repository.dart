import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../core/api/api_client.dart';
import '../../../core/providers.dart';
import '../domain/geofence_admin.dart';

class GeofenceRepository {
  GeofenceRepository(this._client);

  final ApiClient _client;

  Future<List<GeofenceWorkplace>> listWorkplaces() =>
      _client.getList('/attendance/geofences', parseItem: (d) => GeofenceWorkplace.fromJson(d as Map<String, dynamic>)).then((e) => e.data);

  /// Every authorisation, a page at a time (the API caps a page at 100).
  Future<List<WorkplaceAuthorization>> listAuthorizations() async {
    final all = <WorkplaceAuthorization>[];
    for (var page = 1; page <= 20; page++) {
      final env = await _client.getList('/attendance/workplace-authorizations', query: PageQuery(page: page, perPage: 100), parseItem: (d) => WorkplaceAuthorization.fromJson(d as Map<String, dynamic>));
      all.addAll(env.data);
      if (!(env.pagination?.hasNext ?? false)) break;
    }
    return all;
  }

  Future<void> authorize({required String employeeId, required String branchId}) =>
      _client.post<Object?>('/attendance/workplace-authorizations', body: {'employee_id': employeeId, 'branch_id': branchId}, parse: (_) => null);

  Future<void> removeAuthorization(String id) => _client.delete<Object?>('/attendance/workplace-authorizations/$id', parse: (_) => null);

  Future<({List<GeofenceAttempt> rows, bool hasNext})> listAttempts({required bool onlyRejected, int page = 1}) async {
    final env = await _client.getList(
      '/attendance/geofence-attempts',
      query: PageQuery(page: page, perPage: 50),
      filters: {if (onlyRejected) 'accepted': 'false'},
      parseItem: (d) => GeofenceAttempt.fromJson(d as Map<String, dynamic>),
    );
    return (rows: env.data, hasNext: env.pagination?.hasNext ?? false);
  }

  /// A workplace is a branch, so its centre and radius are saved on the branch, against the
  /// version read just now.
  Future<void> setWorkplaceLocation({required String branchId, required double latitude, required double longitude, required int radiusM}) async {
    final branch = await _client.get<Map<String, dynamic>>('/branches/$branchId', parse: (d) => d as Map<String, dynamic>);
    await _client.patch<Object?>(
      '/branches/$branchId',
      body: {'latitude': latitude.toStringAsFixed(6), 'longitude': longitude.toStringAsFixed(6), 'geofence_radius_m': radiusM},
      ifMatch: branch['version'].toString(),
      parse: (_) => null,
    );
  }
}

final geofenceRepositoryProvider = Provider<GeofenceRepository>((ref) => GeofenceRepository(ref.watch(apiClientProvider)));
