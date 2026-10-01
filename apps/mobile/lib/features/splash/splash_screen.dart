import 'package:flutter/material.dart';

/// Shown only while [AuthController] is resolving a persisted session; the
/// router's redirect sends the user on to `/login` or the authenticated
/// landing route as soon as that resolves.
class SplashScreen extends StatelessWidget {
  const SplashScreen({super.key});

  @override
  Widget build(BuildContext context) {
    return const Scaffold(body: Center(child: CircularProgressIndicator()));
  }
}
