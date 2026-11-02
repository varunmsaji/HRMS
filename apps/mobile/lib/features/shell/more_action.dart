import 'package:flutter/material.dart';
import 'package:go_router/go_router.dart';

/// The entry point into [SettingsHubScreen] from each bottom-nav tab's app
/// bar — everything that doesn't fit the 4-tab bottom nav lives behind it.
///
/// Drawn as a filled, bordered gear button (44dp, above the 48dp-ish touch target once padded) so it
/// reads as a button rather than a faint glyph. [onDark] is for the navy dashboard header, where the
/// default dark icon was nearly invisible.
class MoreAction extends StatelessWidget {
  const MoreAction({super.key, this.onDark = false});

  final bool onDark;

  @override
  Widget build(BuildContext context) {
    final scheme = Theme.of(context).colorScheme;
    final fg = onDark ? Colors.white : scheme.primary;
    final bg = onDark ? Colors.white.withValues(alpha: 0.18) : scheme.primary.withValues(alpha: 0.10);
    final border = onDark ? Colors.white.withValues(alpha: 0.45) : scheme.primary.withValues(alpha: 0.35);
    return Padding(
      padding: const EdgeInsets.symmetric(horizontal: 6),
      child: Tooltip(
        message: 'Settings & more',
        child: Semantics(
          button: true,
          label: 'Settings and more',
          child: Material(
            color: bg,
            shape: CircleBorder(side: BorderSide(color: border, width: 1.2)),
            child: InkWell(
              customBorder: const CircleBorder(),
              onTap: () => context.push('/app/more'),
              child: SizedBox(width: 44, height: 44, child: Icon(Icons.settings_rounded, color: fg, size: 24)),
            ),
          ),
        ),
      ),
    );
  }
}
