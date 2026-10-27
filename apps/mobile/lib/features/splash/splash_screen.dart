import 'package:flutter/material.dart';

import '../../core/theme/app_theme.dart' show AppBrand;

/// Shown only while [AuthController] is resolving a persisted session; the
/// router's redirect sends the user on to `/login` or the authenticated
/// landing route as soon as that resolves.
class SplashScreen extends StatelessWidget {
  const SplashScreen({super.key});

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: AppBrand.navy,
      body: Center(
        child: Column(mainAxisSize: MainAxisSize.min, children: const [
          Image(image: AssetImage('assets/brand/krewoxa-mark.png'), height: 72),
          SizedBox(height: 16),
          Image(image: AssetImage('assets/brand/krewoxa-wordmark-white.png'), height: 26),
          SizedBox(height: 6),
          Text('Your people, organized.', style: TextStyle(color: Colors.white70)),
          SizedBox(height: 28),
          SizedBox(width: 26, height: 26, child: CircularProgressIndicator(strokeWidth: 2.5, color: Colors.white)),
        ]),
      ),
    );
  }
}
