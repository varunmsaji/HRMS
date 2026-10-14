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

/// No HTTP response at all (status 0). [code] says why:
/// - `NETWORK_ERROR` — the server could not be reached;
/// - `REQUEST_TIMEOUT` — no response in time. For a write the outcome is unknown (the server may
///   have applied it), so callers must not resubmit blindly.
/// [requestId] is the id this client sent, so support can still find the attempt in server logs.
class NetworkError extends ApiError {
  NetworkError({String? code, String? message, super.requestId})
      : super(
          status: 0,
          code: code ?? 'NETWORK_ERROR',
          message: message ?? 'Could not reach the server. Check your connection and try again.',
        );

  factory NetworkError.timeout({required bool isWrite, String? requestId}) => NetworkError(
        code: 'REQUEST_TIMEOUT',
        message: isWrite
            ? 'The server took too long to respond. Your change may or may not have been saved — refresh to check before trying again.'
            : 'The server took too long to respond. Please try again.',
        requestId: requestId,
      );
}

/// The support reference for a failure the user cannot fix (a server error or no response):
/// the request id the API logged it under. Null for ordinary 4xx outcomes.
String? errorReference(Object error) {
  if (error is! ApiError || error.requestId == null) return null;
  return error.status == 0 || error.status >= 500 ? error.requestId : null;
}

/// True when repeating the *same read* is reasonable. Never use it to resubmit a write.
bool isRetryableError(Object error) {
  if (error is! ApiError) return false;
  return error.status == 0 || error.status == 429 || const {502, 503, 504}.contains(error.status);
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
/// (snackbars, banners). Server and connectivity failures carry their support reference.
String describeApiError(Object error) {
  if (error is ApiError) {
    final reference = errorReference(error);
    return reference == null ? error.message : '${error.message} (Reference: $reference)';
  }
  return 'Something went wrong. Please try again.';
}
