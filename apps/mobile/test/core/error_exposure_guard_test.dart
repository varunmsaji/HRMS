import 'dart:io';

import 'package:flutter_test/flutter_test.dart';

/// CI guard: a raw error must not reach a user-facing surface, and a failure must not vanish.
///
/// Dart has no analyzer package available to the test run here, so this is a targeted,
/// line-level scan of `lib/` (not a text search of the whole repo: tests, comments, strings in
/// docs and `lib/core/api/` - where an ApiError's text is first read - are not scanned). Each rule
/// matches a pattern with no legitimate use in a screen; every exception is in [allowed], with the
/// reason, and an entry that matches nothing fails the run.
///
/// M1  `.message` read off an error variable (`e`, `err`, `error`, `_error`, `?.message`): it
///     skips the support reference and, for anything that is not an ApiError, would show
///     internals. Use `describeApiError` / `describeError`.
/// M2  An error interpolated into text or `.toString()`-ed (`$e`, `${error}`, `e.toString()`).
/// M3  A swallowed failure: `catch (_) {}`, a comment-only catch, or `catchError((_) {})`. Record
///     it with `AppDiagnostics.instance.recordHandled`.
class Finding {
  Finding(this.file, this.line, this.rule, this.text);
  final String file;
  final int line;
  final String rule;
  final String text;
  @override
  String toString() => '$file:$line [$rule] $text';
}

class Allowed {
  const Allowed(this.file, this.rule, this.contains, this.reason);
  final String file;
  final String rule;
  final String contains;
  final String reason;
}

const allowed = <Allowed>[
  Allowed('lib/main.dart', 'M2', r'$error',
      'Debug builds only (guarded by `if (debug)`); a release build never prints it.'),
  Allowed('lib/features/notifications/push/push_messaging.dart', 'M2', r'$e',
      'A debugPrint explaining why push is off in a build without Firebase config; developer console only.'),
  Allowed('lib/core/forms/form_spec.dart', 'M2', 'e.toString()',
      '`e` is an item of a list of form values being compared as text, not a caught error.'),
  Allowed('lib/core/forms/spec_form.dart', 'M2', 'e.toString()',
      '`e` is an item of a list of selected form values, not a caught error.'),
  Allowed('lib/core/widgets/employee/today_status_panel.dart', 'M2', r'$e',
      '`e` is the formatted end time of a shift in this function, not a caught error.'),
  Allowed('lib/core/diagnostics/app_diagnostics.dart', 'M3', 'Reporting must never throw',
      'The reporting hook of the diagnostics buffer: a failing report must never raise into the failure it describes.'),
  Allowed('lib/features/attendance/presentation/camera_input_image.dart', 'M3', 'Already gone',
      'Deleting a temporary camera frame: if the file is already gone there is nothing to do and nothing to tell anyone.'),
  Allowed('lib/features/attendance/presentation/face_enrollment_screen.dart', 'M3',
      'A dropped frame is harmless',
      'On-device analysis of one camera frame failed; the next frame is analysed instead, and no server call is involved.'),
  Allowed('lib/features/attendance/presentation/face_liveness_capture_screen.dart', 'M3',
      'A dropped frame is harmless',
      'On-device analysis of one camera frame failed; the next frame is analysed instead, and no server call is involved.'),
  Allowed('lib/main.dart', 'M3', 'catchError((Object _) {})',
      'The error reporter itself: a failed report must never raise or report again.'),
  Allowed('lib/core/diagnostics/app_diagnostics.dart', 'M3', 'catch (_) {}',
      'The diagnostics buffer must never throw into the failure it is describing.'),
  Allowed('lib/features/notifications/presentation/notifications_screen.dart', 'M3',
      'navigation must not depend on it',
      'Marking a notification read is a courtesy; opening its screen must not wait on or fail with it.'),
  Allowed('lib/features/notifications/state/notification_popups.dart', 'M3',
      'opening the screen must not depend on it',
      'Same as above: a read-marker failure must not block navigation.'),
];

final _errName = r'(?:e|err|error|exception|_error|_loadError|_workError)';
final _rules = <String, RegExp>{
  'M1': RegExp('\\b$_errName!?\\??\\.message\\b|\\?\\.message\\b'),
  'M2': RegExp('\\\$(?:\\{$_errName\\}|$_errName(?!\\w))|\\b$_errName\\.toString\\(\\)'),
  // An empty catch, or one whose body is only comments; or a catchError handler that does nothing.
  'M3': RegExp(
    r'catch \(_\) \{(?:\s*(?://[^\n]*|/\*.*?\*/))*\s*\}|catchError\(\((?:Object )?_\) \{\s*\}\)',
    dotAll: true,
  ),
};

List<Finding> scanSource(String source, String file) {
  final out = <Finding>[];
  final lines = source.split('\n');
  _rules.forEach((rule, pattern) {
    for (final match in pattern.allMatches(source)) {
      final index = '\n'.allMatches(source.substring(0, match.start)).length;
      final line = lines[index];
      if (line.trimLeft().startsWith('//')) continue; // a comment line is not code
      out.add(Finding(file, index + 1, rule, match.group(0)!.replaceAll(RegExp(r'\s+'), ' ')));
    }
  });
  return out;
}

void main() {
  group('prohibited patterns are rejected', () {
    List<String> rulesOf(String code) => scanSource(code, 'lib/x.dart').map((f) => f.rule).toList();

    test('M1: the message of an error', () {
      expect(rulesOf('Text(e.message)'), ['M1']);
      expect(rulesOf('Text(error.message)'), ['M1']);
      expect(rulesOf('Text(_error!.message)'), ['M1']);
      expect(rulesOf("message: _loadError?.message ?? 'x'"), ['M1']);
    });
    test('M2: an error interpolated or stringified', () {
      expect(rulesOf(r"showSnackBar(SnackBar(content: Text('Failed: $e')))"), ['M2']);
      expect(rulesOf(r"Text('Failed: ${error}')"), ['M2']);
      expect(rulesOf('Text(e.toString())'), ['M2']);
    });
    test('M3: a swallowed failure', () {
      expect(rulesOf('} catch (_) {}'), ['M3']);
      expect(rulesOf('} catch (_) {/* ignored */}'), ['M3']);
      expect(rulesOf('} catch (_) {\n  // nothing\n}'), ['M3']);
      expect(rulesOf('f().catchError((_) {});'), ['M3']);
      expect(rulesOf('f().catchError((Object _) {});'), ['M3']);
    });
  });

  group('permitted patterns are accepted', () {
    List<String> rulesOf(String code) => scanSource(code, 'lib/x.dart').map((f) => f.rule).toList();

    test('the safe helpers', () {
      expect(rulesOf('Text(describeApiError(e))'), isEmpty);
      expect(rulesOf("message: describeError(_error, 'Not found.')"), isEmpty);
    });
    test('recording a handled failure', () {
      expect(rulesOf('} catch (e, s) { AppDiagnostics.instance.recordHandled(e, s); }'), isEmpty);
      expect(rulesOf('f().catchError((Object e, StackTrace s) { record(e, s); });'), isEmpty);
    });
    test('.message of things that are not errors, and dates named e', () {
      expect(rulesOf('Text(issue.message)'), isEmpty);
      expect(rulesOf('Text(detail.message)'), isEmpty);
      expect(rulesOf(r"Text('${e.day} ${e.month}')"), isEmpty);
      expect(rulesOf(r"key: 'b-${e.id}'"), isEmpty);
    });
    test('commented-out code is not code', () {
      expect(rulesOf('// Text(e.message);'), isEmpty);
    });
  });

  test('every allowlist entry is justified', () {
    for (final a in allowed) {
      expect(a.reason.trim().length, greaterThan(30), reason: '${a.file} ${a.rule}');
    }
  });

  test('lib/ has no unlisted raw error exposure or swallowed failure, and no stale allowlist entry', () {
    final root = Directory('lib');
    expect(root.existsSync(), isTrue);
    final findings = <Finding>[];
    for (final entity in root.listSync(recursive: true)) {
      if (entity is! File || !entity.path.endsWith('.dart')) continue;
      final path = entity.path.replaceAll(r'\', '/');
      // `lib/core/api/` is where an ApiError's text is defined and first read.
      if (path.startsWith('lib/core/api/')) continue;
      findings.addAll(scanSource(entity.readAsStringSync(), path));
    }
    final used = <Allowed>{};
    final remaining = findings.where((f) {
      final match = allowed.where((a) => a.file == f.file && a.rule == f.rule && f.text.contains(a.contains));
      used.addAll(match);
      return match.isEmpty;
    }).toList();
    expect(remaining.map((f) => f.toString()).toList(), isEmpty);
    expect(allowed.where((a) => !used.contains(a)).map((a) => '${a.file} ${a.rule} ${a.contains}').toList(), isEmpty);
  });
}
