import 'package:flutter/material.dart';
import 'package:go_router/go_router.dart';

/// The entry point into [SettingsHubScreen] from each bottom-nav tab's app
/// bar — everything that doesn't fit the 4-tab bottom nav lives behind it.
class MoreAction extends StatelessWidget {
  const MoreAction({super.key});

  @override
  Widget build(BuildContext context) {
    return IconButton(
      icon: const Icon(Icons.apps_outlined),
      tooltip: 'More',
      onPressed: () => context.push('/app/more'),
    );
  }
}
