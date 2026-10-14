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

  List<DiagnosticEntry> get entries => List.unmodifiable(_entries);

  void _add(DiagnosticEntry entry) {
    _entries.addLast(entry);
    while (_entries.length > capacity) {
      _entries.removeFirst();
    }
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
  void clear() => _entries.clear();

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
