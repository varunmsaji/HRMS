import 'dart:collection';

import 'package:flutter/foundation.dart';

import '../api/api_error.dart';

/// One recorded failure. Deliberately *no message text*: exception messages and API messages can
/// carry personal data. What support needs is what failed, where in the code, and the request id
/// the server logged it under.
class DiagnosticEntry {
  DiagnosticEntry({
    required this.at,
    required this.source,
    required this.type,
    this.location,
    this.requestId,
    this.status,
    this.code,
  });

  final DateTime at;

  /// `flutter` (framework/build error), `platform` (uncaught async error) or `api`.
  final String source;
  final String type;

  /// The top frames of the stack — code locations only, never values.
  final String? location;
  final String? requestId;
  final int? status;
  final String? code;

  /// The scrubbed payload for `POST /v1/client-errors`: class, status/code, request id and code
  /// locations — never a message, a token, a body or employee data.
  Map<String, Object?> toReport() => {
    'source': 'mobile',
    'kind': source,
    'error_class': type,
    'frames': location?.split(' < ') ?? const <String>[],
    'request_id': requestId,
    'status': status,
    'code': code,
  };

  String format() => [
    at.toUtc().toIso8601String(),
    source,
    type,
    if (code != null) code!,
    if (status != null) 'HTTP $status',
    if (requestId != null) 'ref $requestId',
    if (location != null) '@ $location',
  ].join(' | ');
}

/// LOG-15 — a small, local, in-memory record of recent failures so an employee can copy a
/// "diagnostics" block into a support message even when the network is down. Nothing is sent
/// anywhere (no crash-reporting service is approved), nothing is persisted to disk, and no
/// tokens, request/response bodies, images or employee data are recorded.
class AppDiagnostics {
  AppDiagnostics._();

  static final AppDiagnostics instance = AppDiagnostics._();

  static const capacity = 20;
  final Queue<DiagnosticEntry> _entries = Queue();

  /// Where reportable entries are sent (`POST /v1/client-errors`). Null until `main` installs it,
  /// and installed unless the build opts out with `--dart-define=CLIENT_ERROR_REPORTING=false`.
  /// Reports go only to our own API and carry no message text.
  void Function(DiagnosticEntry entry)? sink;

  /// At most this many reports per app session, and never the same failure twice, so a render
  /// loop cannot flood the API or the user's data plan.
  static const maxReportsPerSession = 10;
  final Set<String> _reported = {};

  List<DiagnosticEntry> get entries => List.unmodifiable(_entries);

  void _add(DiagnosticEntry entry) {
    _entries.addLast(entry);
    while (_entries.length > capacity) {
      _entries.removeFirst();
    }
    _report(entry);
  }

  void _report(DiagnosticEntry entry) {
    final send = sink;
    if (send == null) return;
    // A request that failed because of the caller (4xx) or connectivity (status 0) is not a defect.
    if (entry.source == 'api' && (entry.status == null || entry.status! < 500)) return;
    final key = '${entry.source}|${entry.type}|${entry.code ?? ''}|${entry.location ?? ''}';
    if (_reported.length >= maxReportsPerSession || !_reported.add(key)) return;
    try {
      send(entry);
    } catch (_) {
      // Reporting must never throw into the failure it is describing.
    }
  }

  /// An error the app caught and chose not to show (a best-effort lookup that failed). Same
  /// scrubbed record as an uncaught one, so a developer can still see it happened.
  void recordHandled(Object error, StackTrace? stack) {
    // An expected API outcome (4xx, no connection) is already recorded by the client when it
    // matters; only a server failure or a real bug is worth a second entry.
    if (error is ApiError && error.status < 500) return;
    recordError(error, stack, source: 'handled');
  }

  /// An uncaught error. Never throws — a broken diagnostics buffer must not mask the error.
  void recordError(Object error, StackTrace? stack, {required String source}) {
    try {
      _add(
        DiagnosticEntry(
          at: DateTime.now(),
          source: source,
          type: error.runtimeType.toString(),
          location: _topFrames(stack),
        ),
      );
    } catch (_) {}
  }

  /// A failed API call — status, stable code and the request id only.
  void recordFailedRequest(ApiError error) {
    try {
      _add(
        DiagnosticEntry(
          at: DateTime.now(),
          source: 'api',
          type: error.runtimeType.toString(),
          requestId: error.requestId,
          status: error.status,
          code: error.code,
        ),
      );
    } catch (_) {}
  }

  /// Text a user can copy into a support request.
  String summary() => _entries.isEmpty ? 'No recent errors.' : _entries.map((e) => e.format()).join('\n');

  @visibleForTesting
  void clear() {
    _entries.clear();
    _reported.clear();
    sink = null;
  }

  static String? _topFrames(StackTrace? stack) {
    if (stack == null) return null;
    // Frame lines look like `#0  Foo.bar (package:hrms_mobile/x.dart:12:3)`; keep only the
    // code location in parentheses.
    final locations =
        stack
            .toString()
            .split('\n')
            .map((line) => RegExp(r'\(([^)]+)\)').firstMatch(line)?.group(1))
            .whereType<String>()
            .take(3)
            .toList();
    return locations.isEmpty ? null : locations.join(' < ');
  }
}
