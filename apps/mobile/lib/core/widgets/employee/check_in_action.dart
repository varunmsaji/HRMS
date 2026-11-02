import 'package:flutter/material.dart';

import '../../../features/attendance/domain/today_state.dart';
import '../../theme/employee_tokens.dart';

/// What the punch control should do, decided by its owner from the shared `PunchController`
/// state and the face status. The control only presents it; it never punches by itself.
class CheckInAction extends StatelessWidget {
  const CheckInAction({
    super.key,
    required this.likely,
    required this.faceRequired,
    required this.busy,
    required this.ready,
    required this.onPunch,
    this.busyLabel,
    this.showIcons = true,
  });

  /// Which direction is primary ([TodayState.likely]). Both stay reachable: the server accepts
  /// either, and a forgotten punch-out must not trap the employee.
  final LikelyPunch likely;

  /// Server says this employee must punch with their face: labels say so, and the owner routes
  /// the tap to the face flow.
  final bool faceRequired;

  /// A punch is in flight. Both buttons are disabled; the label says what is happening.
  final bool busy;

  /// False until the face status is known, so a plain punch is never offered and then refused.
  final bool ready;

  /// `'IN'` or `'OUT'`.
  final void Function(String direction) onPunch;

  final String? busyLabel;

  /// Home shows plain text buttons; the Attendance tab keeps its glyphs.
  final bool showIcons;

  @override
  Widget build(BuildContext context) {
    final enabled = ready && !busy;
    String label(String direction) => '${faceRequired && direction == 'IN' ? 'Face punch' : 'Punch'} ${direction == 'IN' ? 'in' : 'out'}';

    // Minimum, not fixed, heights: at large text the label wraps and the button grows with it.
    Widget primary(String direction) => ConstrainedBox(
          constraints: const BoxConstraints(minWidth: double.infinity, minHeight: EmployeeTokens.minTarget),
          child: !showIcons && !busy
              ? FilledButton(onPressed: enabled ? () => onPunch(direction) : null, child: Text(label(direction)))
              : FilledButton.icon(
                  onPressed: enabled ? () => onPunch(direction) : null,
                  icon: busy
                      ? const SizedBox(width: 18, height: 18, child: CircularProgressIndicator(strokeWidth: 2))
                      : Icon(direction == 'IN' ? Icons.login_rounded : Icons.logout_rounded),
                  label: Text(label(direction)),
                ),
        );

    Widget secondary(String direction) => ConstrainedBox(
          constraints: const BoxConstraints(minWidth: double.infinity, minHeight: EmployeeTokens.minTarget),
          child: TextButton(
            onPressed: enabled ? () => onPunch(direction) : null,
            child: Text('${label(direction)} instead'),
          ),
        );

    Widget equal() => Row(children: [
          Expanded(
            child: ConstrainedBox(
              constraints: const BoxConstraints(minHeight: EmployeeTokens.minTarget),
              child: FilledButton.icon(
                onPressed: enabled ? () => onPunch('IN') : null,
                icon: const Icon(Icons.login_rounded),
                label: Text(label('IN')),
              ),
            ),
          ),
          const SizedBox(width: 12),
          Expanded(
            child: ConstrainedBox(
              constraints: const BoxConstraints(minHeight: EmployeeTokens.minTarget),
              child: OutlinedButton.icon(
                onPressed: enabled ? () => onPunch('OUT') : null,
                icon: const Icon(Icons.logout_rounded),
                label: Text(label('OUT')),
              ),
            ),
          ),
        ]);

    final body = switch (likely) {
      LikelyPunch.equal => equal(),
      LikelyPunch.punchIn => Column(mainAxisSize: MainAxisSize.min, children: [primary('IN'), secondary('OUT')]),
      LikelyPunch.punchOut => Column(mainAxisSize: MainAxisSize.min, children: [primary('OUT'), secondary('IN')]),
    };
    // Both directions stay on screen (disabled) while a punch is in flight, with a plain-words
    // caption; nothing says the punch happened until the server has confirmed it.
    return Semantics(
      container: true,
      child: Column(mainAxisSize: MainAxisSize.min, children: [
        body,
        if (busy && busyLabel != null) ...[
          const SizedBox(height: 8),
          Semantics(liveRegion: true, child: Text(busyLabel!, style: Theme.of(context).textTheme.bodySmall?.copyWith(color: EmployeeTokens.of(context).inkSecondary))),
        ],
        if (!ready) ...[
          const SizedBox(height: 8),
          Text('Checking your punch options…', style: Theme.of(context).textTheme.bodySmall?.copyWith(color: EmployeeTokens.of(context).inkSecondary)),
        ],
      ]),
    );
  }
}
