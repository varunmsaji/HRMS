import 'package:flutter/foundation.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:hrms_mobile/core/api/api_error.dart';
import 'package:hrms_mobile/core/diagnostics/app_diagnostics.dart';
import 'package:hrms_mobile/core/widgets/ui.dart';
import 'package:hrms_mobile/main.dart';

const placeholder = 'This part of the screen could not be displayed. Go back and try again.';

class _Crashes extends StatelessWidget {
  const _Crashes();
  @override
  Widget build(BuildContext context) => throw StateError('secret salary_minor=9999999 at /srv/hrms/x.dart');
}

void main() {
  late FlutterExceptionHandler? originalOnError;
  late ErrorWidgetBuilder originalBuilder;
  late bool Function(Object, StackTrace)? originalPlatformOnError;

  setUp(() {
    originalOnError = FlutterError.onError;
    originalBuilder = ErrorWidget.builder;
    originalPlatformOnError = PlatformDispatcher.instance.onError;
    AppDiagnostics.instance.clear();
  });
  tearDown(() {
    FlutterError.onError = originalOnError;
    ErrorWidget.builder = originalBuilder;
    PlatformDispatcher.instance.onError = originalPlatformOnError;
    AppDiagnostics.instance.clear();
  });

  group('release-mode placeholder', () {
    testWidgets('a widget that fails to build shows fixed text, never the exception', (tester) async {
      installGlobalErrorHandlers(release: true, debug: false);
      FlutterError.onError = (details) =>
          AppDiagnostics.instance.recordError(details.exception, details.stack, source: 'flutter');

      await tester.pumpWidget(const MaterialApp(home: Scaffold(body: _Crashes())));

      expect(find.text(placeholder), findsOneWidget);
      expect(find.textContaining('secret'), findsNothing);
      expect(find.textContaining('StateError'), findsNothing);
      expect(find.textContaining('.dart'), findsNothing);
      // The failure is still recorded for the developer, without its message.
      expect(AppDiagnostics.instance.entries.single.type, 'StateError');
      expect(AppDiagnostics.instance.summary(), isNot(contains('secret')));
      expect(AppDiagnostics.instance.summary(), isNot(contains('9999999')));
    });

    testWidgets('installGlobalErrorHandlers only swaps the builder in a release build', (tester) async {
      final before = ErrorWidget.builder;
      installGlobalErrorHandlers(release: false, debug: false);
      expect(ErrorWidget.builder, same(before));
      installGlobalErrorHandlers(release: true, debug: false);
      expect(ErrorWidget.builder, same(releaseErrorPlaceholder));
    });

    test('an uncaught async error is recorded, handled, and its text is not kept', () {
      installGlobalErrorHandlers(release: true, debug: false);
      final handled = PlatformDispatcher.instance.onError!(StateError('token=abc123'), StackTrace.current);
      expect(handled, isTrue);
      expect(AppDiagnostics.instance.entries.single.source, 'platform');
      expect(AppDiagnostics.instance.summary(), isNot(contains('abc123')));
    });
  });

  group('what a user is shown for a failed request', () {
    Widget screen(ApiError error) =>
        MaterialApp(home: Scaffold(body: StateMessage(icon: Icons.error_outline, title: "Couldn't load", message: describeApiError(error))));

    testWidgets('a server failure shows the generic text and the ERR reference', (tester) async {
      await tester.pumpWidget(screen(ApiError(
        status: 500,
        code: 'INTERNAL_ERROR',
        message: 'An unexpected error occurred',
        requestId: 'uuid-1',
        reference: 'ERR-1A2B3C4D',
      )));
      expect(find.text('An unexpected error occurred (Reference: ERR-1A2B3C4D)'), findsOneWidget);
    });

    testWidgets('a business or validation message stays useful and has no reference', (tester) async {
      await tester.pumpWidget(screen(ApiError(
        status: 422,
        code: 'VALIDATION_ERROR',
        message: 'End date cannot be before the start date.',
        requestId: 'uuid-2',
        reference: 'ERR-SHOULDNOT',
      )));
      expect(find.text('End date cannot be before the start date.'), findsOneWidget);
      expect(find.textContaining('Reference'), findsNothing);
    });

    test('anything that is not an ApiError gets the fixed fallback', () {
      expect(describeApiError(StateError('SELECT * FROM salary')), 'Something went wrong. Please try again.');
      expect(describeError(null, 'Pay run not found.'), 'Pay run not found.');
    });
  });

  group('what the developer is told, and what is kept out of it', () {
    test('the report carries class, locations, status, code and references - nothing else', () {
      final sent = <DiagnosticEntry>[];
      AppDiagnostics.instance.sink = sent.add;
      AppDiagnostics.instance.recordFailedRequest(ApiError(
        status: 500,
        code: 'INTERNAL_ERROR',
        message: 'salary of Priya is 9999999',
        requestId: 'uuid-1',
        reference: 'ERR-1A2B3C4D',
      ));
      final report = sent.single.toReport();
      expect(report.keys.toSet(), {'source', 'kind', 'error_class', 'frames', 'request_id', 'reference', 'status', 'code'});
      expect(report['reference'], 'ERR-1A2B3C4D');
      expect(report.toString(), isNot(contains('Priya')));
      expect(report.toString(), isNot(contains('9999999')));
      expect(AppDiagnostics.instance.summary(), contains('ref ERR-1A2B3C4D'));
    });

    test('a handled error with a sensitive message is reported without it', () {
      final sent = <DiagnosticEntry>[];
      AppDiagnostics.instance.sink = sent.add;
      AppDiagnostics.instance.recordHandled(
        StateError('Bearer eyJhbGciOiJIUzI1NiJ9.payload.sig for aadhaar 2345 6789 0123'),
        StackTrace.current,
      );
      final text = sent.single.toReport().toString();
      for (final secret in ['Bearer', 'eyJ', 'aadhaar', '2345', 'payload']) {
        expect(text, isNot(contains(secret)));
      }
    });
  });
}
