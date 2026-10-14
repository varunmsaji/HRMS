import 'dart:async';
import 'dart:math';

import 'package:cookie_jar/cookie_jar.dart';
import 'package:dio/dio.dart';
import 'package:dio_cookie_manager/dio_cookie_manager.dart';
import 'package:flutter/foundation.dart';
import 'package:path_provider/path_provider.dart';

import '../auth/auth_types.dart';
import '../auth/token_storage.dart';
import '../diagnostics/app_diagnostics.dart';
import 'api_error.dart';
import 'envelope.dart';

/// The mobile equivalent of `NEXT_PUBLIC_API_URL` — pass with
/// `--dart-define=API_BASE_URL=http://10.0.2.2:8000` for the Android emulator
/// (which can't resolve the host's `localhost`), or the real host/port for a
/// physical device or staging/prod build.
const _apiBaseUrl = String.fromEnvironment(
  'API_BASE_URL',
  defaultValue: 'http://localhost:8000',
);

/// Without explicit timeouts dio waits forever, so a punch on a dead network used to spin
/// indefinitely (LOG-15). Uploads and file downloads get longer windows. A timeout is reported,
/// never retried automatically.
const connectTimeout = Duration(seconds: 10);
const receiveTimeout = Duration(seconds: 30);
const sendTimeout = Duration(seconds: 60);
const transferTimeout = Duration(seconds: 120);

/// 1-indexed `page`/`per_page` query params for a paginated list endpoint (API-01).
class PageQuery {
  PageQuery({this.page, this.perPage});

  final int? page;
  final int? perPage;
}

/// A file returned by `ApiClient.download` — the filename comes from
/// `Content-Disposition`.
class DownloadedFile {
  DownloadedFile({required this.bytes, required this.filename});

  final List<int> bytes;
  final String? filename;
}

/// Mirrors `apps/web/src/lib/api/client.ts` end to end: the `/v1` envelope
/// contract, `Authorization` + `X-Company-Id` headers, the 401-refresh-retry
/// path, and `X-Request-Id` tracing. The refresh token itself is never seen
/// here — it lives in `_cookieJar`, attached to requests by `CookieManager`
/// exactly the way the browser attaches the HttpOnly `hrms_refresh` cookie
/// on web (see the SEC-06 note in `token_storage.dart`).
class ApiClient {
  ApiClient._(this._dio, this._cookieJar);

  final Dio _dio;
  // Held for the client's lifetime; the `CookieManager` interceptor does the reads and writes.
  // ignore: unused_field
  final CookieJar _cookieJar;
  Completer<bool>? _refreshInFlight;

  static ApiClient? _instance;

  static Future<ApiClient> getInstance() async {
    if (_instance != null) return _instance!;
    final dir = await getApplicationSupportDirectory();
    final cookieJar = PersistCookieJar(storage: FileStorage('${dir.path}/.cookies/'));
    final dio = Dio(
      BaseOptions(
        baseUrl: '$_apiBaseUrl/v1',
        connectTimeout: connectTimeout,
        receiveTimeout: receiveTimeout,
        sendTimeout: sendTimeout,
      ),
    );
    dio.interceptors.add(CookieManager(cookieJar));
    _instance = ApiClient._(dio, cookieJar);
    return _instance!;
  }

  /// A client over a caller-supplied [Dio] (tests use a stub adapter). No cookie persistence.
  @visibleForTesting
  factory ApiClient.withDio(Dio dio) => ApiClient._(dio, CookieJar());

  /// A fresh `Idempotency-Key` value. Pass the same one when retrying a request after a network
  /// failure so the server runs the mutation once; use a new one for a new request.
  static String newIdempotencyKey() =>
      'idem_${DateTime.now().microsecondsSinceEpoch}_${Random.secure().nextInt(1 << 32).toRadixString(16)}_${Random.secure().nextInt(1 << 32).toRadixString(16)}';

  String _requestId() =>
      'req_${DateTime.now().millisecondsSinceEpoch}_${Random().nextInt(1 << 32).toRadixString(16)}';

  Future<T> _rawRequest<T>(
    String path, {
    required String method,
    dynamic body,
    bool authenticated = true,
    Map<String, String>? headers,
    String? ifMatch,
    T Function(dynamic)? parseData,
    T Function(Map<String, dynamic>)? parseEnvelope,
    ResponseType responseType = ResponseType.json,
  }) async {
    final session = authenticated ? await TokenStorage.instance.load() : null;

    if (authenticated && session == null) {
      throw ApiError(status: 401, code: 'UNAUTHORIZED', message: 'Authentication required');
    }

    final requestHeaders = <String, String>{
      'X-Request-Id': _requestId(),
      ...?headers,
    };
    // The id this attempt is logged under server-side — kept for errors without an envelope.
    final sentRequestId = requestHeaders['X-Request-Id'];
    final isTransfer = body is FormData Function() || responseType == ResponseType.bytes;
    if (ifMatch != null) requestHeaders['If-Match'] = ifMatch;
    if (session != null) {
      requestHeaders['Authorization'] = 'Bearer ${session.accessToken}';
      requestHeaders['X-Company-Id'] = session.companyId;
    }

    Response<dynamic> response;
    try {
      response = await _dio.request<dynamic>(
        path,
        // A FormData can only be sent once, so multipart callers pass a builder and the
        // 401-refresh retry gets a fresh one.
        data: body is FormData Function() ? body() : body,
        options: Options(
          method: method,
          headers: requestHeaders,
          responseType: responseType,
          sendTimeout: isTransfer ? transferTimeout : null,
          receiveTimeout: isTransfer ? transferTimeout : null,
        ),
      );
    } on DioException catch (e) {
      if (e.response == null) {
        final error = switch (e.type) {
          // Connecting never succeeded, so nothing reached the server.
          DioExceptionType.connectionTimeout => NetworkError(requestId: sentRequestId),
          DioExceptionType.sendTimeout || DioExceptionType.receiveTimeout =>
            NetworkError.timeout(isWrite: method != 'GET', requestId: sentRequestId),
          _ => NetworkError(requestId: sentRequestId),
        };
        AppDiagnostics.instance.recordFailedRequest(error);
        throw error;
      }
      response = e.response!;
    }

    if (responseType == ResponseType.bytes) {
      final disposition = response.headers.value('content-disposition') ?? '';
      final match = RegExp('filename="?([^";]+)"?', caseSensitive: false).firstMatch(disposition);
      return DownloadedFile(bytes: response.data as List<int>, filename: match?.group(1)) as T;
    }

    if (response.statusCode == 204) {
      return null as T;
    }

    final payload = response.data;
    final ok = response.statusCode != null && response.statusCode! >= 200 && response.statusCode! < 300;

    if (!ok) {
      final errorPayload = payload is Map<String, dynamic> ? payload['error'] as Map<String, dynamic>? : null;
      // Proxy gateway failures arrive without the API's JSON envelope.
      final unavailable = errorPayload == null && const {502, 503, 504}.contains(response.statusCode);
      final error = ApiError(
        status: response.statusCode ?? 0,
        code: errorPayload?['code'] as String? ?? (unavailable ? 'SERVICE_UNAVAILABLE' : 'UNKNOWN_ERROR'),
        message: errorPayload?['message'] as String? ??
            (unavailable
                ? 'The service is temporarily unavailable. Please try again in a moment.'
                : 'Request failed with status ${response.statusCode}'),
        details: (errorPayload?['details'] as List? ?? [])
            .map((d) => ErrorDetail.fromJson(d as Map<String, dynamic>))
            .toList(),
        // The envelope's id, else the API's response header, else the id this client sent.
        requestId: errorPayload?['request_id'] as String? ?? response.headers.value('x-request-id') ?? sentRequestId,
      );
      AppDiagnostics.instance.recordFailedRequest(error);
      throw error;
    }

    if (parseEnvelope != null) {
      return parseEnvelope(payload as Map<String, dynamic>);
    }
    final envelope = payload as Map<String, dynamic>;
    return parseData!(envelope['data']);
  }

  Future<bool> _refreshSession() async {
    if (await TokenStorage.instance.load() == null) return false;
    try {
      final response = await _dio.request<dynamic>(
        '/auth/token/refresh',
        options: Options(method: 'POST', headers: {'X-Request-Id': _requestId()}),
      );
      if (response.statusCode == null || response.statusCode! < 200 || response.statusCode! >= 300) {
        return false;
      }
      final data = TokenResponseData.fromJson(
        (response.data as Map<String, dynamic>)['data'] as Map<String, dynamic>,
      );
      await TokenStorage.instance.save(StoredSession.fromTokenResponse(data));
      return true;
    } catch (_) {
      return false;
    }
  }

  /// Ensures concurrent 401s during one screen trigger a single refresh call,
  /// not one per request.
  Future<bool> _refreshOnce() {
    if (_refreshInFlight == null) {
      _refreshInFlight = Completer<bool>();
      _refreshSession().then((result) {
        _refreshInFlight!.complete(result);
        _refreshInFlight = null;
      });
    }
    return _refreshInFlight!.future;
  }

  Future<T> _request<T>(
    String path, {
    required String method,
    dynamic body,
    bool authenticated = true,
    Map<String, String>? headers,
    String? ifMatch,
    T Function(dynamic)? parseData,
    T Function(Map<String, dynamic>)? parseEnvelope,
    ResponseType responseType = ResponseType.json,
  }) async {
    try {
      return await _rawRequest<T>(
        path,
        method: method,
        body: body,
        authenticated: authenticated,
        headers: headers,
        ifMatch: ifMatch,
        parseData: parseData,
        parseEnvelope: parseEnvelope,
        responseType: responseType,
      );
    } on ApiError catch (error) {
      final shouldAttemptRefresh = error.status == 401 &&
          authenticated &&
          await TokenStorage.instance.load() != null;

      if (shouldAttemptRefresh) {
        final refreshed = await _refreshOnce();
        if (refreshed) {
          return _rawRequest<T>(
            path,
            method: method,
            body: body,
            authenticated: authenticated,
            headers: headers,
            ifMatch: ifMatch,
            parseData: parseData,
            parseEnvelope: parseEnvelope,
            responseType: responseType,
          );
        }
        await TokenStorage.instance.clear();
        TokenStorage.instance.notifySessionExpired();
      }
      rethrow;
    }
  }

  String _withQuery(String path, Map<String, dynamic>? params) {
    if (params == null || params.isEmpty) return path;
    final query = <String, String>{};
    params.forEach((key, value) {
      if (value != null) query[key] = value.toString();
    });
    if (query.isEmpty) return path;
    final separator = path.contains('?') ? '&' : '?';
    return '$path$separator${Uri(queryParameters: query).query}';
  }

  Future<T> get<T>(String path, {required T Function(dynamic) parse, bool authenticated = true}) =>
      _request<T>(path, method: 'GET', authenticated: authenticated, parseData: parse);

  /// Paginated list endpoints (API-01) — returns the full envelope
  /// (`data` + `pagination`), not just the unwrapped array.
  Future<ListEnvelope<T>> getList<T>(
    String path, {
    required T Function(dynamic) parseItem,
    PageQuery? query,
    Map<String, dynamic>? filters,
    bool authenticated = true,
  }) =>
      _request<ListEnvelope<T>>(
        _withQuery(path, {'page': query?.page, 'per_page': query?.perPage, ...?filters}),
        method: 'GET',
        authenticated: authenticated,
        parseEnvelope: (json) => ListEnvelope.fromJson(json, parseItem),
      );

  Future<T> post<T>(
    String path, {
    dynamic body,
    required T Function(dynamic) parse,
    bool authenticated = true,
    String? ifMatch,
    Map<String, String>? headers,
  }) =>
      _request<T>(path, method: 'POST', body: body, authenticated: authenticated, ifMatch: ifMatch, headers: headers, parseData: parse);

  /// Multipart POST. [buildForm] is called once per attempt (see `_rawRequest`).
  Future<T> postMultipart<T>(
    String path, {
    required FormData Function() buildForm,
    required T Function(dynamic) parse,
    bool authenticated = true,
  }) =>
      _request<T>(path, method: 'POST', body: buildForm, authenticated: authenticated, parseData: parse);

  Future<T> patch<T>(
    String path, {
    dynamic body,
    required T Function(dynamic) parse,
    String? ifMatch,
    bool authenticated = true,
  }) =>
      _request<T>(
        path,
        method: 'PATCH',
        body: body,
        authenticated: authenticated,
        ifMatch: ifMatch,
        parseData: parse,
      );

  Future<T> put<T>(
    String path, {
    dynamic body,
    required T Function(dynamic) parse,
    bool authenticated = true,
    String? ifMatch,
  }) =>
      _request<T>(path, method: 'PUT', body: body, authenticated: authenticated, ifMatch: ifMatch, parseData: parse);

  Future<T> delete<T>(String path, {required T Function(dynamic) parse, String? ifMatch, bool authenticated = true}) =>
      _request<T>(path, method: 'DELETE', ifMatch: ifMatch, authenticated: authenticated, parseData: parse);

  /// GET a file (PDF payslip, CSV export, …) with the usual auth and refresh handling.
  Future<DownloadedFile> download(String path) => _request<DownloadedFile>(
        path,
        method: 'GET',
        responseType: ResponseType.bytes,
      );
}
