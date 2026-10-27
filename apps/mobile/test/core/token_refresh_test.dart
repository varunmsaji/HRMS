import 'dart:convert';
import 'dart:typed_data';

import 'package:dio/dio.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:hrms_mobile/core/api/api_client.dart';
import 'package:hrms_mobile/core/api/api_error.dart';
import 'package:hrms_mobile/core/auth/token_storage.dart';

/// Answers every request from [handler], recording the paths that were hit.
class _StubAdapter implements HttpClientAdapter {
  _StubAdapter(this.handler);

  final Future<ResponseBody> Function(RequestOptions options) handler;
  final paths = <String>[];

  @override
  Future<ResponseBody> fetch(RequestOptions options, Stream<Uint8List>? requestStream, Future<void>? cancelFuture) {
    paths.add(options.path);
    return handler(options);
  }

  @override
  void close({bool force = false}) {}
}

ResponseBody _json(Object body, int status) => ResponseBody.fromString(
      jsonEncode(body),
      status,
      headers: {
        Headers.contentTypeHeader: [Headers.jsonContentType],
      },
    );

const _unauthorized = {
  'error': {'code': 'INVALID_TOKEN', 'message': 'Token expired', 'details': [], 'request_id': 'req_1'},
};

const _tokenResponse = {
  'data': {
    'access_token': 'new-access',
    'token_type': 'bearer',
    'expires_in_minutes': 15,
    'company_id': 'c-1',
    'companies': [
      {'id': 'c-1', 'name': 'Acme', 'is_primary': true},
    ],
  },
  'meta': {'request_id': 'req_2'},
};

Future<void> _seedSession() => TokenStorage.instance.save(
      StoredSession(
        accessToken: 'old-access',
        companyId: 'c-1',
        companies: const [],
        expiresAt: DateTime.now().millisecondsSinceEpoch + 60000,
      ),
    );

/// A client whose `/things` answers 401 until the access token is refreshed, and whose
/// `/auth/token/refresh` is answered by [refresh].
(ApiClient, _StubAdapter) _client(Future<ResponseBody> Function(RequestOptions) refresh) {
  final adapter = _StubAdapter((o) async {
    if (o.path == '/auth/token/refresh') return refresh(o);
    final bearer = o.headers['Authorization'];
    if (bearer == 'Bearer new-access') {
      return _json({'data': {'ok': true}, 'meta': {'request_id': 'req_3'}}, 200);
    }
    return _json(_unauthorized, 401);
  });
  final dio = Dio(BaseOptions(baseUrl: 'http://api.test/v1'))..httpClientAdapter = adapter;
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
  TestWidgetsFlutterBinding.ensureInitialized();

  setUp(() async {
    FlutterSecureStorage.setMockInitialValues({});
    await _seedSession();
  });

  test('a successful refresh replays the request with the new token', () async {
    final (client, adapter) = _client((_) async => _json(_tokenResponse, 200));

    final ok = await client.get('/things', parse: (d) => (d as Map)['ok'] as bool);

    expect(ok, isTrue);
    expect(adapter.paths, ['/things', '/auth/token/refresh', '/things']);
    expect((await TokenStorage.instance.load())?.accessToken, 'new-access');
  });

  test('a refresh the server rejects ends the session', () async {
    var expired = 0;
    final subscription = TokenStorage.instance.onSessionExpired.listen((_) => expired++);
    final (client, _) = _client((_) async => _json(_unauthorized, 401));

    final error = await _failure(client.get('/things', parse: (d) => d));
    await Future<void>.delayed(Duration.zero);
    await subscription.cancel();

    expect(error, isA<ApiError>().having((e) => e.status, 'status', 401));
    expect(await TokenStorage.instance.load(), isNull);
    expect(expired, 1);
  });

  test('a refresh that cannot reach the server keeps the session and reports a network error', () async {
    var expired = 0;
    final subscription = TokenStorage.instance.onSessionExpired.listen((_) => expired++);
    final (client, _) = _client(
      (o) async => throw DioException(requestOptions: o, type: DioExceptionType.connectionError),
    );

    final error = await _failure(client.get('/things', parse: (d) => d));
    await Future<void>.delayed(Duration.zero);
    await subscription.cancel();

    expect(error, isA<NetworkError>());
    expect((error as NetworkError).requestId, 'req_1');
    expect((await TokenStorage.instance.load())?.accessToken, 'old-access');
    expect(expired, 0);
  });

  test('a refresh that times out keeps the session', () async {
    final (client, _) = _client(
      (o) async => throw DioException(requestOptions: o, type: DioExceptionType.receiveTimeout),
    );

    final error = await _failure(client.get('/things', parse: (d) => d));

    expect(error, isA<NetworkError>());
    expect(await TokenStorage.instance.load(), isNotNull);
  });

  test('a server error during refresh keeps the session', () async {
    final (client, _) = _client((_) async => ResponseBody.fromString('Bad Gateway', 502));

    final error = await _failure(client.get('/things', parse: (d) => d));

    expect(error, isA<NetworkError>());
    expect(await TokenStorage.instance.load(), isNotNull);
  });

  test('concurrent 401s share one refresh call', () async {
    final (client, adapter) = _client((_) async => _json(_tokenResponse, 200));

    await Future.wait([
      client.get('/things', parse: (d) => d),
      client.get('/things', parse: (d) => d),
      client.get('/things', parse: (d) => d),
    ]);

    expect(adapter.paths.where((p) => p == '/auth/token/refresh'), hasLength(1));
  });
}
