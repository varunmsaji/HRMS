import 'envelope.dart';

/// Thrown for every non-2xx API response and for network failures.
/// Mirrors `apps/web/src/lib/api/errors.ts`.
class ApiError implements Exception {
  ApiError({
    required this.status,
    required this.code,
    required this.message,
    this.details = const [],
    this.requestId,
  });

  final int status;
  final String code;
  final String message;
  final List<ErrorDetail> details;
  final String? requestId;

  @override
  String toString() => message;
}

class NetworkError extends ApiError {
  NetworkError()
      : super(
          status: 0,
          code: 'NETWORK_ERROR',
          message: 'Could not reach the server. Check your connection and try again.',
        );
}

/// FastAPI's `RequestValidationError` handler joins Pydantic's `loc` tuple with "."
/// (e.g. "body.admin_password"), while `AppError`s raised directly from service code
/// use the bare field name. Matching on the last dot-segment handles both.
String? getFieldError(List<ErrorDetail> details, String field) {
  for (final detail in details) {
    if (detail.field == null) continue;
    final segments = detail.field!.split('.');
    if (segments.last == field) return detail.message;
  }
  return null;
}

/// A human-readable fallback for surfaces that just need one line of text
/// (snackbars, banners).
String describeApiError(Object error) {
  if (error is ApiError) return error.message;
  return 'Something went wrong. Please try again.';
}
