import 'package:hrms_mobile/core/api/api_client.dart';
import 'package:hrms_mobile/core/api/envelope.dart';

typedef RecordedCall = ({String method, String path, dynamic body, String? ifMatch});

/// A scripted [ApiClient]: GET lists/objects come from [lists]/[objects] (keyed by path, query
/// ignored), and every write is recorded in [calls] for assertions. A path in [failing] throws its
/// error instead.
class FakeApiClient implements ApiClient {
  FakeApiClient({this.lists = const {}, this.objects = const {}, this.failing = const {}});

  final Map<String, List<Map<String, dynamic>>> lists;
  final Map<String, Map<String, dynamic>> objects;
  final Map<String, Object> failing;
  final calls = <RecordedCall>[];

  /// Every list GET (path and filters) — the writes are in [calls].
  final listCalls = <({String path, Map<String, dynamic>? filters})>[];

  String _p(String path) => path.split('?').first;

  @override
  Future<ListEnvelope<T>> getList<T>(String path, {required T Function(dynamic) parseItem, PageQuery? query, Map<String, dynamic>? filters, bool authenticated = true}) async {
    listCalls.add((path: _p(path), filters: filters));
    if (failing.containsKey(_p(path))) throw failing[_p(path)]!;
    return ListEnvelope(data: (lists[_p(path)] ?? const []).map(parseItem).toList(), pagination: null, meta: ResponseMeta(requestId: 'r'));
  }

  @override
  Future<T> get<T>(String path, {required T Function(dynamic) parse, bool authenticated = true}) async {
    if (failing.containsKey(_p(path))) throw failing[_p(path)]!;
    return parse(objects[_p(path)] ?? const <String, dynamic>{});
  }

  Future<T> _write<T>(String method, String path, dynamic body, String? ifMatch, T Function(dynamic) parse) async {
    calls.add((method: method, path: _p(path), body: body, ifMatch: ifMatch));
    if (failing.containsKey(_p(path))) throw failing[_p(path)]!;
    return parse(objects[_p(path)]);
  }

  @override
  Future<T> post<T>(String path, {dynamic body, required T Function(dynamic) parse, bool authenticated = true, String? ifMatch}) =>
      _write('POST', path, body, ifMatch, parse);

  @override
  Future<T> patch<T>(String path, {dynamic body, required T Function(dynamic) parse, String? ifMatch, bool authenticated = true}) =>
      _write('PATCH', path, body, ifMatch, parse);

  @override
  Future<T> put<T>(String path, {dynamic body, required T Function(dynamic) parse, bool authenticated = true, String? ifMatch}) =>
      _write('PUT', path, body, ifMatch, parse);

  @override
  Future<T> delete<T>(String path, {required T Function(dynamic) parse, String? ifMatch, bool authenticated = true}) =>
      _write('DELETE', path, null, ifMatch, parse);

  @override
  dynamic noSuchMethod(Invocation invocation) => super.noSuchMethod(invocation);
}
