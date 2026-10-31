import 'package:flutter/foundation.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import 'core/api/api_client.dart';
import 'core/diagnostics/app_diagnostics.dart';
import 'core/providers.dart';
import 'core/router/app_router.dart';
import 'core/theme/theme_selection.dart';
import 'features/auth/state/auth_controller.dart';
import 'core/auth/surface.dart';
import 'core/time.dart';

Future<void> main() async {
  WidgetsFlutterBinding.ensureInitialized();
  installGlobalErrorHandlers();
  initTimeZones();
  final apiClient = await ApiClient.getInstance();
  runApp(
    ProviderScope(
      overrides: [apiClientProvider.overrideWithValue(apiClient)],
      child: const HrmsApp(),
    ),
  );
}

class HrmsApp extends ConsumerWidget {
  const HrmsApp({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final router = ref.watch(appRouterProvider);
    // Only the employee/administrator split matters here, so rebuild on that, not on every
    // profile refresh. Administrators and signed-out screens keep the system-themed app.
    final employee = ref.watch(authControllerProvider.select((s) => usesEmployeeSurface(s.user)));
    final selection = themeSelectionFor(employee ? ref.read(authControllerProvider).user : null);
    return MaterialApp.router(
      title: 'Krewoxa',
      debugShowCheckedModeBanner: false,
      theme: selection.theme,
      darkTheme: selection.darkTheme,
      themeMode: selection.themeMode,
      routerConfig: router,
    );
  }
}

/// LOG-15 — before this nothing caught uncaught errors: async failures vanished and a build
/// error in a release build showed a grey box. Errors are recorded locally (`AppDiagnostics`,
/// no message text, nothing sent off-device), still printed in debug, and a broken widget shows
/// a readable placeholder instead of a blank or grey screen.
void installGlobalErrorHandlers() {
  final previousOnError = FlutterError.onError;
  FlutterError.onError = (details) {
    AppDiagnostics.instance.recordError(details.exception, details.stack, source: 'flutter');
    if (kDebugMode) {
      (previousOnError ?? FlutterError.presentError)(details);
    }
  };
  PlatformDispatcher.instance.onError = (error, stack) {
    AppDiagnostics.instance.recordError(error, stack, source: 'platform');
    if (kDebugMode) debugPrint('Uncaught error: $error');
    return true; // handled: do not crash the app over an unawaited failure
  };
  if (kReleaseMode) {
    ErrorWidget.builder = (details) => const Material(
          child: Center(
            child: Padding(
              padding: EdgeInsets.all(24),
              child: Text(
                'This part of the screen could not be displayed. Go back and try again.',
                textAlign: TextAlign.center,
              ),
            ),
          ),
        );
  }
}
