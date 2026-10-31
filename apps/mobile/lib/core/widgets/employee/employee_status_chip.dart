import 'package:flutter/material.dart';

import 'status_map.dart';

/// Pill with the status word and a dot: colour is never the only signal. 24 high.
class EmployeeStatusChip extends StatelessWidget {
  const EmployeeStatusChip({super.key, required this.status});

  /// From [statusForAttendanceBucket] or [statusForRequest].
  final EmployeeStatus status;

  @override
  Widget build(BuildContext context) {
    final c = statusColors(context, status.kind);
    return Semantics(
      label: 'Status: ${status.label}',
      excludeSemantics: true,
      child: Container(
        constraints: const BoxConstraints(minHeight: 24),
        padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 3),
        decoration: BoxDecoration(color: c.fill, borderRadius: BorderRadius.circular(999)),
        child: Row(
          mainAxisSize: MainAxisSize.min,
          children: [
            Container(width: 6, height: 6, decoration: BoxDecoration(color: c.glyph, shape: BoxShape.circle)),
            const SizedBox(width: 6),
            Flexible(
              child: Text(
                status.label,
                maxLines: 1,
                overflow: TextOverflow.ellipsis,
                style: Theme.of(context).textTheme.labelSmall?.copyWith(color: c.text, fontWeight: FontWeight.w600),
              ),
            ),
          ],
        ),
      ),
    );
  }
}
