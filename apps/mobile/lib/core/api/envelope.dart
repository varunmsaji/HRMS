/// Mirrors `apps/web/src/lib/api/types.ts`, which in turn mirrors
/// `apps/api/src/hrms/shared/pagination.py` and `core/errors/envelope.py`.
/// Kept as plain classes (no codegen) so every API integration speaks the
/// same shape without a build_runner step.
library;

class ResponseMeta {
  ResponseMeta({required this.requestId, this.serverTime});

  final String requestId;
  final String? serverTime;

  factory ResponseMeta.fromJson(Map<String, dynamic> json) => ResponseMeta(
        requestId: json['request_id'] as String,
        serverTime: json['server_time'] as String?,
      );
}

/// API-01 pagination contract — 1-indexed `page`, server-capped `per_page` (max 100).
class PaginationMeta {
  PaginationMeta({
    required this.page,
    required this.perPage,
    required this.total,
    required this.totalPages,
    this.nextCursor,
  });

  final int page;
  final int perPage;
  final int total;
  final int totalPages;
  final String? nextCursor;

  factory PaginationMeta.fromJson(Map<String, dynamic> json) => PaginationMeta(
        page: json['page'] as int,
        perPage: json['per_page'] as int,
        total: json['total'] as int,
        totalPages: json['total_pages'] as int,
        nextCursor: json['next_cursor'] as String?,
      );
}

/// A single-resource envelope: `{ data, meta }`.
class DataEnvelope<T> {
  DataEnvelope({required this.data, required this.meta});

  final T data;
  final ResponseMeta meta;

  factory DataEnvelope.fromJson(
    Map<String, dynamic> json,
    T Function(dynamic) fromData,
  ) =>
      DataEnvelope(
        data: fromData(json['data']),
        meta: ResponseMeta.fromJson(json['meta'] as Map<String, dynamic>),
      );
}

/// A list envelope: `{ data: T[], pagination, meta }`.
class ListEnvelope<T> {
  ListEnvelope({required this.data, required this.pagination, required this.meta});

  final List<T> data;
  final PaginationMeta? pagination;
  final ResponseMeta meta;

  factory ListEnvelope.fromJson(
    Map<String, dynamic> json,
    T Function(dynamic) fromItem,
  ) =>
      ListEnvelope(
        data: (json['data'] as List).map(fromItem).toList(),
        pagination: json['pagination'] == null
            ? null
            : PaginationMeta.fromJson(json['pagination'] as Map<String, dynamic>),
        meta: ResponseMeta.fromJson(json['meta'] as Map<String, dynamic>),
      );
}

class ErrorDetail {
  ErrorDetail({this.field, required this.code, required this.message, this.context});

  final String? field;
  final String code;
  final String message;
  final Map<String, dynamic>? context;

  factory ErrorDetail.fromJson(Map<String, dynamic> json) => ErrorDetail(
        field: json['field'] as String?,
        code: json['code'] as String,
        message: json['message'] as String,
        context: json['context'] as Map<String, dynamic>?,
      );
}

class ErrorBody {
  ErrorBody({
    required this.code,
    required this.message,
    required this.details,
    required this.requestId,
    this.documentationUrl,
  });

  final String code;
  final String message;
  final List<ErrorDetail> details;
  final String requestId;
  final String? documentationUrl;

  factory ErrorBody.fromJson(Map<String, dynamic> json) => ErrorBody(
        code: json['code'] as String,
        message: json['message'] as String,
        details: (json['details'] as List? ?? [])
            .map((e) => ErrorDetail.fromJson(e as Map<String, dynamic>))
            .toList(),
        requestId: json['request_id'] as String,
        documentationUrl: json['documentation_url'] as String?,
      );
}
