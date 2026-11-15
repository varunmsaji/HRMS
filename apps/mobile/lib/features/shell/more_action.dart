import 'package:flutter/material.dart';
import 'package:go_router/go_router.dart';

/// The entry point into [SettingsHubScreen] from every bottom-nav tab's app bar — everything that
/// doesn't fit the 4-tab bottom nav lives behind it, including everyday employee tasks (leave
/// balances, corrections, payslips).
///
/// A labelled "More" pill, not a gear: a gear reads as "settings", so employees never looked there
/// for their payslips (audit MOB-UX-004). The pill keeps a 48 dp touch target. [onDark] is for the
/// navy headers (dashboard, Home).
class MoreAction extends StatelessWidget {
  const MoreAction({super.key, this.onDark = false});

  final bool onDark;

  static const tooltip = 'More: settings and tools';

  @override
  Widget build(BuildContext context) {
    final scheme = Theme.of(context).colorScheme;
    final fg = onDark ? Colors.white : scheme.primary;
    final bg = onDark ? Colors.white.withValues(alpha: 0.18) : scheme.primary.withValues(alpha: 0.10);
    final border = onDark ? Colors.white.withValues(alpha: 0.45) : scheme.primary.withValues(alpha: 0.35);
    // On a narrow phone at large text the word would push the app bar past the screen edge: the
    // pill then shows the icon alone (still announced as "More", with its tooltip).
    final scale = MediaQuery.textScalerOf(context).scale(1);
    final showLabel = scale <= 1.3 || MediaQuery.sizeOf(context).width >= 420;
    return Padding(
      padding: const EdgeInsets.symmetric(horizontal: 6),
      child: Tooltip(
        message: tooltip,
        child: Semantics(
          button: true,
          label: 'More',
          excludeSemantics: true,
          child: ConstrainedBox(
            constraints: const BoxConstraints(minHeight: 48),
            child: Center(
              child: Material(
                color: bg,
                shape: StadiumBorder(side: BorderSide(color: border, width: 1.2)),
                child: InkWell(
                  customBorder: const StadiumBorder(),
                  onTap: () => context.push('/app/more'),
                  child: Padding(
                    padding: showLabel ? const EdgeInsets.fromLTRB(10, 8, 14, 8) : const EdgeInsets.all(10),
                    child: Row(mainAxisSize: MainAxisSize.min, children: [
                      Icon(Icons.apps_rounded, color: fg, size: 20),
                      if (showLabel) ...[
                        const SizedBox(width: 6),
                        // Capped like the tab labels, so the bar does not grow without limit.
                        MediaQuery.withClampedTextScaling(
                          maxScaleFactor: 1.3,
                          child: Text('More', style: TextStyle(color: fg, fontWeight: FontWeight.w700, fontSize: 14)),
                        ),
                      ],
                    ]),
                  ),
                ),
              ),
            ),
          ),
        ),
      ),
    );
  }
}
