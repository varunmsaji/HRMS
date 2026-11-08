import '../../../core/auth/permissions.dart';
import 'policy_coverage.dart';

/// "Who follows this" for one policy — the pure half of web `use-policy-followers.ts`,
/// `policy-followers-panel.tsx` and `assign-policy-dialog.tsx`.

/// Web `usePolicyFollowers`: one page of this many; more means the list shown is partial.
const followersPageSize = 100;

/// Assignments in force today or starting later, widest scope first, then by start date.
List<Rec> liveFollowers(List<Rec> rows, String today) {
  final live = [
    for (final a in rows)
      if (a['is_active'] != false && (a['effective_to'] == null || '${a['effective_to']}'.compareTo(today) >= 0)) a,
  ];
  live.sort((a, b) {
    final byScope = coverageScopeTypes.indexOf('${a['scope_type']}').compareTo(coverageScopeTypes.indexOf('${b['scope_type']}'));
    return byScope != 0 ? byScope : '${a['effective_from']}'.compareTo('${b['effective_from']}');
  });
  return live;
}

/// Web `assignmentPermissions`: what the server asks for to see and change assignments of a kind.
/// Leave policies need both, like an unfiltered list.
List<String> assignmentPermissionsFor(String kind) {
  if (kind == 'WORK_CALENDAR' || kind == 'WEEKLY_OFF') return const [orgCalendarManage];
  if (kind == 'ATTENDANCE_POLICY' || kind == 'OVERTIME_POLICY' || kind == 'REGULARIZATION_POLICY') return const [attendancePolicyManage];
  return const [orgCalendarManage, attendancePolicyManage];
}

/// Why nobody new can follow the policy right now, in web's words; null when they can.
String? cannotAssignReason({required String kind, required bool isActive, required bool hasPublishedRules}) {
  if (!isActive) {
    final noun = switch (kind) {
      'WORK_CALENDAR' => 'calendar',
      'WEEKLY_OFF' => 'pattern',
      _ => 'policy',
    };
    return 'This $noun is inactive, so nobody new can follow it. Reactivate it to assign it.';
  }
  if (!needsImpactPreview(kind) && !hasPublishedRules) {
    return 'Publish the rules first. A policy can be assigned once it has published rules.';
  }
  return null;
}

/// Web `assign-policy-dialog` checks against what the group follows now (`own` from the coverage
/// row). Null when the assignment can go ahead.
String? assignError({required Rec? own, required String policyId, required String effectiveFrom}) {
  if (own == null) return null;
  if (own['policy_id'] == policyId) return 'They already follow this policy.';
  if (effectiveFrom.compareTo('${own['effective_from']}') <= 0) {
    return 'Must be after ${coverageDate('${own['effective_from']}')}, when their current assignment started.';
  }
  return null;
}
