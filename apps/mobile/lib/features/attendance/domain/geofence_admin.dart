/// The geofence administration surface (`apps/api/.../attendance/geofence_schemas.py`), with the
/// same wording as the web's `lib/geofence/types.ts`.
class GeofenceWorkplace {
  const GeofenceWorkplace({
    required this.branchId,
    required this.name,
    required this.isActive,
    required this.configured,
    required this.assignedEmployeeCount,
    required this.authorizedEmployeeCount,
    this.latitude,
    this.longitude,
    this.radiusM,
  });

  factory GeofenceWorkplace.fromJson(Map<String, dynamic> json) => GeofenceWorkplace(
        branchId: json['branch_id'] as String,
        name: json['name'] as String,
        isActive: json['is_active'] as bool,
        configured: json['configured'] as bool,
        assignedEmployeeCount: json['assigned_employee_count'] as int,
        authorizedEmployeeCount: json['authorized_employee_count'] as int,
        latitude: (json['latitude'] as num?)?.toDouble(),
        longitude: (json['longitude'] as num?)?.toDouble(),
        radiusM: json['radius_m'] as int?,
      );

  final String branchId;
  final String name;
  final bool isActive;

  /// The branch has coordinates and a radius.
  final bool configured;
  final int assignedEmployeeCount;
  final int authorizedEmployeeCount;
  final double? latitude;
  final double? longitude;
  final int? radiusM;

  /// Only an active branch with coordinates and a radius can act as a geofence.
  bool get usable => isActive && configured;

  String get statusLabel => !configured ? 'Not configured' : (isActive ? 'Active' : 'Inactive');
}

class WorkplaceAuthorization {
  const WorkplaceAuthorization({required this.id, required this.employeeId, required this.branchId});

  factory WorkplaceAuthorization.fromJson(Map<String, dynamic> json) =>
      WorkplaceAuthorization(id: json['id'] as String, employeeId: json['employee_id'] as String, branchId: json['branch_id'] as String);

  final String id;
  final String employeeId;
  final String branchId;
}

class GeofenceAttempt {
  const GeofenceAttempt({
    required this.id,
    required this.employeeId,
    required this.direction,
    required this.mode,
    required this.outcome,
    required this.accepted,
    required this.createdAt,
    this.distanceM,
    this.radiusM,
    this.accuracyM,
    this.clientError,
  });

  factory GeofenceAttempt.fromJson(Map<String, dynamic> json) => GeofenceAttempt(
        id: json['id'] as String,
        employeeId: json['employee_id'] as String,
        direction: json['direction'] as String,
        mode: json['mode'] as String,
        outcome: json['outcome'] as String,
        accepted: json['accepted'] as bool,
        createdAt: json['created_at'] as String,
        distanceM: _decimal(json['distance_m']),
        radiusM: _decimal(json['radius_m']),
        accuracyM: _decimal(json['accuracy_m']),
        clientError: json['client_error'] as String?,
      );

  final String id;
  final String employeeId;
  final String direction;
  final String mode;
  final String outcome;
  final bool accepted;
  final String createdAt;
  final double? distanceM;
  final double? radiusM;
  final double? accuracyM;
  final String? clientError;
}

/// Decimals arrive as strings.
double? _decimal(Object? value) => value == null ? null : double.tryParse('$value');

const _outcomeLabels = {
  'INSIDE': 'Inside the workplace',
  'OUTSIDE_GEOFENCE': 'Outside the workplace',
  'OUTSIDE_GEOFENCE_UNCERTAIN': 'Just outside, GPS too imprecise to be sure',
  'LOCATION_TOO_INACCURATE': 'GPS accuracy too poor',
  'LOCATION_STALE': 'Location reading too old',
  'LOCATION_INVALID': 'Location reading invalid',
  'LOCATION_REQUIRED': 'No location sent',
  'LOCATION_UNAVAILABLE_CLIENT': 'Phone could not provide a location',
  'NO_APPLICABLE_WORKPLACE': 'No approved workplace configured',
  'NOT_PROVIDED': 'No location sent (optional mode)',
};

String geofenceOutcomeLabel(String outcome) => _outcomeLabels[outcome] ?? outcome;

String formatMetres(double? value) => value == null ? '—' : '${value.round()} m';

/// External map link; no mapping library is bundled, as on the web.
Uri workplaceMapLink(double latitude, double longitude) => Uri.parse('https://www.openstreetmap.org/?mlat=$latitude&mlon=$longitude#map=18/$latitude/$longitude');
