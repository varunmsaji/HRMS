import 'dart:convert';
import 'dart:typed_data';

import 'package:dio/dio.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:hrms_mobile/core/api/api_client.dart';
import 'package:hrms_mobile/core/api/api_error.dart';
import 'package:hrms_mobile/core/diagnostics/app_diagnostics.dart';

/// Answers every request from [handler], recording what was sent.
class _StubAdapter implements HttpClientAdapter {
  _StubAdapter(this.handler);

  final Future<ResponseBody> Function(RequestOptions options) handler;
  final sent = <RequestOptions>[];

  @override
  Future<ResponseBody> fetch(
    RequestOptions options,
    Stream<Uint8List>? requestStream,
    Future<void>? cancelFuture,
  ) {
    sent.add(options);
    return handler(options);
  }

  @override
  void close({bool force = false}) {}
}

ResponseBody _json(
  Object body,
  int status, {
  Map<String, List<String>> headers = const {},
}) => ResponseBody.fromString(
  jsonEncode(body),
  status,
  headers: {
    Headers.contentTypeHeader: [Headers.jsonContentType],
    ...headers,
  },
);

(ApiClient, _StubAdapter) _client(
  Future<ResponseBody> Function(RequestOptions) handler,
) {
  final adapter = _StubAdapter(handler);
  final dio = Dio(BaseOptions(baseUrl: 'http://api.test/v1'))
    ..httpClientAdapter = adapter;
  return (ApiClient.withDio(dio), adapter);
}

Future<Object> _failure(Future<dynamic> future) async {
  try {
    await future;
  } catch (error) {
    return error;
  }
  fail('expected a failure');
}

void main() {
  setUp(AppDiagnostics.instance.clear);

  test('the production client is configured with timeouts', () {
    expect(connectTimeout, const Duration(seconds: 10));
    expect(receiveTimeout, const Duration(seconds: 30));
    expect(transferTimeout > receiveTimeout, isTrue);
  });

  test(
    'a receive timeout on a write says the outcome is unknown and keeps the sent request id',
    () async {
      final (client, adapter) = _client(
        (o) async =>
            throw DioException(
              requestOptions: o,
              type: DioExceptionType.receiveTimeout,
            ),
      );
      final error = await _failure(
        client.post(
          '/x',
          authenticated: false,
          body: {'a': 1},
          parse: (d) => d,
        ),
      );

      expect(error, isA<NetworkError>());
      final apiError = error as ApiError;
      expect(apiError.code, 'REQUEST_TIMEOUT');
      expect(apiError.message, contains('may or may not have been saved'));
      expect(apiError.requestId, adapter.sent.single.headers['X-Request-Id']);
      expect(adapter.sent, hasLength(1), reason: 'never retried automatically');
    },
  );

  test('a read timeout just asks to try again', () async {
    final (client, _) = _client(
      (o) async =>
          throw DioException(
            requestOptions: o,
            type: DioExceptionType.receiveTimeout,
          ),
    );
    final error =
        await _failure(client.get('/x', authenticated: false, parse: (d) => d))
            as ApiError;
    expect(error.message, isNot(contains('saved')));
  });

  test('connection failures are network errors with the sent id', () async {
    final (client, adapter) = _client(
      (o) async =>
          throw DioException(
            requestOptions: o,
            type: DioExceptionType.connectionError,
          ),
    );
    final error =
        await _failure(client.get('/x', authenticated: false, parse: (d) => d))
            as ApiError;
    expect(error.code, 'NETWORK_ERROR');
    expect(error.status, 0);
    expect(error.requestId, adapter.sent.single.headers['X-Request-Id']);
  });

  test('a proxy 502 without an envelope is readable and referenced', () async {
    final (client, adapter) = _client(
      (o) async => ResponseBody.fromString('<html>bad gateway</html>', 502),
    );
    final error =
        await _failure(client.get('/x', authenticated: false, parse: (d) => d))
            as ApiError;
    expect(error.code, 'SERVICE_UNAVAILABLE');
    expect(error.message, contains('temporarily unavailable'));
    expect(error.requestId, adapter.sent.single.headers['X-Request-Id']);
    expect(describeApiError(error), contains('Reference: ${error.requestId}'));
  });

  test('envelope request id wins; 4xx messages carry no reference', () async {
    final (client, _) = _client(
      (o) async => _json({
        'error': {
          'code': 'CONFLICT',
          'message': 'Already exists',
          'details': <Object>[],
          'request_id': 'srv-409',
        },
      }, 409),
    );
    final error =
        await _failure(client.get('/x', authenticated: false, parse: (d) => d))
            as ApiError;
    expect(error.requestId, 'srv-409');
    expect(describeApiError(error), 'Already exists');
  });

  test(
    'response header id is the fallback for an error without an envelope id',
    () async {
      final (client, _) = _client(
        (o) async => _json(
          <String, Object>{},
          500,
          headers: {
            'x-request-id': ['hdr-500'],
          },
        ),
      );
      final error =
          await _failure(
                client.get('/x', authenticated: false, parse: (d) => d),
              )
              as ApiError;
      expect(error.requestId, 'hdr-500');
    },
  );

  test(
    'failures are recorded in diagnostics without any message text',
    () async {
      final (client, _) = _client(
        (o) async => _json({
          'error': {
            'code': 'INTERNAL_ERROR',
            'message': 'secret detail priya@example.com',
            'details': <Object>[],
            'request_id': 'r-1',
          },
        }, 500),
      );
      await _failure(client.get('/x', authenticated: false, parse: (d) => d));
      final summary = AppDiagnostics.instance.summary();
      expect(summary, contains('INTERNAL_ERROR'));
      expect(summary, contains('ref r-1'));
      expect(summary, isNot(contains('priya')));
      expect(summary, isNot(contains('secret detail')));
    },
  );

  test('diagnostics are bounded and keep code locations only', () {
    for (var i = 0; i < AppDiagnostics.capacity + 5; i++) {
      AppDiagnostics.instance.recordError(
        StateError('token=abc$i'),
        StackTrace.current,
        source: 'platform',
      );
    }
    final entries = AppDiagnostics.instance.entries;
    expect(entries, hasLength(AppDiagnostics.capacity));
    expect(entries.first.type, 'StateError');
    expect(AppDiagnostics.instance.summary(), isNot(contains('token=')));
    expect(entries.first.location, contains('.dart'));
  });

  test(
    'isRetryableError only covers no-response, gateway and rate-limit failures',
    () {
      ApiError make(int s) => ApiError(status: s, code: 'X', message: 'x');
      expect(isRetryableError(NetworkError()), isTrue);
      expect(
        [502, 503, 504, 429].every((s) => isRetryableError(make(s))),
        isTrue,
      );
      expect(
        [400, 401, 403, 409, 422, 500].any((s) => isRetryableError(make(s))),
        isFalse,
      );
    },
  );
}
