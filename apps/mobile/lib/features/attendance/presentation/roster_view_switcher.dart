import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../../core/auth/permissions.dart';
import '../../auth/state/auth_controller.dart';
import 'shift_board_screen.dart';

/// The ways to look at Shift Rosters, in web's order (`SCHEDULE_VIEWS` in
/// `components/shift-roster/roster-nav.tsx`): Coverage, then Week, Month, Day and List.
enum RosterView {
  coverage('Coverage', '/app/schedule'),
  week('Week', '/app/rosters/grid'),
  month('Month', '/app/roster-calendar'),
  day('Day', '/app/rosters/board'),
  list('List', '/app/rosters');

  const RosterView(this.label, this.route);
  final String label;
  final String route;

  /// Whether [permissions] can open this view: the reads its screen makes (UX only, the API stays
  /// the authority). Coverage and List need the roster read grant; Week also reads the employee
  /// directory; Day also needs the shift list its columns come from.
  bool allowedFor(Iterable<String> permissions) {
    final has = permissions.contains;
    return switch (this) {
      RosterView.coverage || RosterView.month || RosterView.list => has(attendanceView),
      RosterView.week => has(attendanceView) && has(employeeViewAll),
      RosterView.day => ShiftBoardScreen.requiredPermissions.every(has),
    };
  }
}

/// The views [permissions] can open, in order.
List<RosterView> rosterViewsFor(Iterable<String> permissions) => [for (final v in RosterView.values) if (v.allowedFor(permissions)) v];

/// One switcher for every Shift Rosters screen, so the five views read as one place (web has a
/// single navigation; the app used to hide three of them behind unlabeled icons). Goes in an
/// `AppBar.bottom`. Choosing a view replaces the current one, so Back still returns to where the
/// user came from, not through every view they tried.
class RosterViewSwitcher extends ConsumerWidget implements PreferredSizeWidget {
  const RosterViewSwitcher({super.key, required this.current});

  final RosterView current;

  @override
  Size get preferredSize => const Size.fromHeight(68); // room for a chip at large text sizes

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final permissions = ref.watch(authControllerProvider).user?.permissions ?? const <String>[];
    final views = rosterViewsFor(permissions);
    return SizedBox(
      height: preferredSize.height,
      child: ListView(
        scrollDirection: Axis.horizontal,
        padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 8),
        children: [
          for (final v in views)
            Padding(
              padding: const EdgeInsets.only(right: 8),
              child: ChoiceChip(
                label: Text(v.label),
                selected: v == current,
                materialTapTargetSize: MaterialTapTargetSize.shrinkWrap,
                // The current view stays enabled (a disabled chip reads as greyed out); tapping it does nothing.
                onSelected: (_) {
                  if (v != current) context.pushReplacement(v.route);
                },
              ),
            ),
        ],
      ),
    );
  }
}
