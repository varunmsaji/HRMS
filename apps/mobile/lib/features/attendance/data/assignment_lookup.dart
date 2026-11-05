import '../../../core/api/api_client.dart';

typedef AssignmentRow = Map<String, dynamic>;

/// The open (no end date) assignment of [policyKind] at one scope, or null when there is none.
/// Asked of the server because a screen only ever holds the pages it has loaded. Replacing an
/// assignment sends this row's `version` as `If-Match`.
Future<AssignmentRow?> findOpenAssignment(
  ApiClient client, {
  required String policyKind,
  required String scopeType,
  String? scopeId,
  String? leaveTypeId,
}) async {
  final found = await client.getList<AssignmentRow>(
    '/policy-assignments',
    query: PageQuery(page: 1),
    filters: {
      'policy_kind': policyKind,
      'scope_type': scopeType,
      if (scopeId != null) 'scope_id': scopeId,
      if (leaveTypeId != null) 'leave_type_id': leaveTypeId,
      'current_only': 'true',
    },
    parseItem: (d) => d as AssignmentRow,
  );
  for (final r in found.data) {
    if (r['effective_to'] == null && r['policy_kind'] == policyKind && r['scope_type'] == scopeType && r['scope_id'] == scopeId && r['leave_type_id'] == leaveTypeId) return r;
  }
  return null;
}
