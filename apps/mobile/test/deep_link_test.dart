import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:go_router/go_router.dart';

/// The deep links declared in AndroidManifest.xml and Info.plist are `hrms://app/<path>`; the
/// router must resolve that URI to the same public routes the web links use.
void main() {
  for (final path in ['onboarding', 'accept-invite', 'reset-password', 'verify-email']) {
    testWidgets('hrms://app/$path/<token> opens /$path/<token>', (tester) async {
      String? seen;
      final router = GoRouter(routes: [
        GoRoute(path: '/', builder: (_, __) => const Text('home')),
        GoRoute(
          path: '/$path/:token',
          builder: (_, state) {
            seen = state.pathParameters['token'];
            return Text('opened $path');
          },
        ),
      ]);
      await tester.pumpWidget(MaterialApp.router(routerConfig: router));
      // What the OS hands Flutter for an incoming link.
      await tester.binding.defaultBinaryMessenger.handlePlatformMessage(
        'flutter/navigation',
        const JSONMethodCodec().encodeMethodCall(MethodCall('pushRouteInformation', {'location': 'hrms://app/$path/tok123'})),
        (_) {},
      );
      await tester.pumpAndSettle();
      expect(find.text('opened $path'), findsOneWidget);
      expect(seen, 'tok123');
    });
  }
}
