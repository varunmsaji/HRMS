import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import 'core/api/api_client.dart';
import 'core/providers.dart';
import 'core/router/app_router.dart';
import 'core/theme/app_theme.dart';
import 'core/time.dart';

Future<void> main() async {
  WidgetsFlutterBinding.ensureInitialized();
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
    return MaterialApp.router(
      title: 'Staff Spectrum HRMS',
      debugShowCheckedModeBanner: false,
      theme: AppTheme.light,
      darkTheme: AppTheme.dark,
      routerConfig: router,
    );
  }
}
