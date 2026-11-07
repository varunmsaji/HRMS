import 'policy_assignment_form.dart';

/// "Set policies" for one group — the pure half of web's `set-policies-panel.tsx` and
/// `lib/policy-assignment/types.ts`: what is set at a scope and what applies today
/// (`GET /policy-assignments/coverage`), which picks are real changes, the date rule, and the body
/// for `POST /policy-assignments/batch`.

typedef Rec = Map<String, dynamic>;

/// Web `SCOPE_TYPES` order.
const coverageScopeTypes = ['COMPANY', 'LEGAL_ENTITY', 'BRANCH', 'DEPARTMENT', 'GRADE', 'DESIGNATION', 'SHIFT', 'EMPLOYEE'];

/// Where each scope's choices come from (web `SCOPE_LIST_PATH`); employees use the picker.
const scopeListPaths = {
  'LEGAL_ENTITY': '/legal-entities',
  'BRANCH': '/branches',
  'DEPARTMENT': '/departments',
  'GRADE': '/grades',
  'DESIGNATION': '/designations',
  'SHIFT': '/shifts',
};

/// Each kind's policy list (web `POLICY_KIND_LIST_PATH`).
const policyKindListPaths = {
  'WORK_CALENDAR': '/work-calendars',
  'WEEKLY_OFF': '/weekly-off-patterns',
  'ATTENDANCE_POLICY': '/attendance-policies',
  'OVERTIME_POLICY': '/overtime-policies',
  'REGULARIZATION_POLICY': '/regularization-policies',
  'LEAVE_POLICY': '/leave-policies',
};

/// Work Calendar / Weekly-Off changes alter day types, so they go through the impact preview.
bool needsImpactPreview(String kind) => kind == 'WORK_CALENDAR' || kind == 'WEEKLY_OFF';

/// The four versioned kinds can only be assigned once published; the API filters them.
Map<String, String> assignableQuery(String kind) => needsImpactPreview(kind) ? const {} : const {'assignable': 'true'};

/// Query for `GET /policy-assignments/coverage`.
Map<String, String> coverageQuery(String scopeType, String? scopeId, String asOf) => {
      'scope_type': scopeType,
      'as_of': asOf,
      if (scopeId != null) 'scope_id': scopeId,
    };

/// One row of the coverage: a kind (per leave type for leave), what is set at this scope (`own`)
/// and what applies on the day (`applied`, possibly inherited from a wider scope).
class CoverageRow {
  const CoverageRow(this.raw);
  final Rec raw;

  String get kind => '${raw['policy_kind']}';
  String? get leaveTypeId => raw['leave_type_id'] as String?;
  String? get leaveTypeName => raw['leave_type_name'] as String?;
  Rec? get own => raw['own'] as Rec?;
  Rec? get applied => raw['applied'] as Rec?;

  /// Web `coverageRowKey`.
  String get key => leaveTypeId != null ? '$kind:$leaveTypeId' : kind;

  /// Web `coverageRowLabel`.
  String get label => leaveTypeName != null ? 'Leave Policy — $leaveTypeName' : (policyKindLabels[kind] ?? kind);
}

List<CoverageRow> coverageRows(Rec coverage) => [for (final r in (coverage['rows'] as List? ?? const [])) CoverageRow(r as Rec)];

/// A policy the user may pick for a row.
class PolicyOption {
  const PolicyOption(this.id, this.name, {this.leaveTypeId});
  final String id;
  final String name;
  final String? leaveTypeId;

  factory PolicyOption.fromJson(Rec m) => PolicyOption('${m['id']}', '${m['name'] ?? m['title'] ?? m['id']}', leaveTypeId: m['leave_type_id'] as String?);
}

/// Active options, as web drops `is_active: false` ones.
List<PolicyOption> activeOptions(List<Rec> list) => [for (final m in list) if (m['is_active'] != false) PolicyOption.fromJson(m)];

/// What a row offers (web `rowOptions`): the kind's policies, only the row's leave type for leave,
/// and the current policy first when it is no longer in the list (e.g. since deactivated).
List<PolicyOption> rowOptions(CoverageRow row, List<PolicyOption> ofKind) {
  final all = [for (final o in ofKind) if (row.leaveTypeId == null || o.leaveTypeId == row.leaveTypeId) o];
  final own = row.own;
  if (own != null && !all.any((o) => o.id == own['policy_id'])) {
    return [PolicyOption('${own['policy_id']}', (own['policy_name'] as String?) ?? 'Current policy'), ...all];
  }
  return all;
}

/// A pick that differs from what is set at this scope.
class CoverageChange {
  const CoverageChange(this.row, this.policyId, this.policyName);
  final CoverageRow row;
  final String policyId;
  final String policyName;
}

List<CoverageChange> pendingChanges(List<CoverageRow> rows, Map<String, String> picks, Map<String, List<PolicyOption>> optionsByKind) => [
      for (final row in rows)
        if (picks[row.key] != null && picks[row.key]!.isNotEmpty && picks[row.key] != row.own?['policy_id'])
          CoverageChange(
            row,
            picks[row.key]!,
            (optionsByKind[row.kind] ?? const []).where((o) => o.id == picks[row.key]).map((o) => o.name).firstOrNull ?? 'Selected policy',
          ),
    ];

const _months = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];

/// "9 Sep 2026".
String coverageDate(String iso) => '${int.parse(iso.substring(8, 10))} ${_months[int.parse(iso.substring(5, 7)) - 1]} ${iso.substring(0, 4)}';

/// Web's date check before the review: a change must start after the current assignment here did.
String? effectiveFromError(String? effectiveFrom, List<CoverageChange> changes) {
  if (effectiveFrom == null || effectiveFrom.isEmpty) return 'Effective from is required.';
  for (final c in changes) {
    final own = c.row.own;
    if (own != null && effectiveFrom.compareTo('${own['effective_from']}') <= 0) {
      return '${c.row.label} must start after ${coverageDate('${own['effective_from']}')}, when its current assignment started.';
    }
  }
  return null;
}

/// Where an applied policy comes from, in words (web `appliedSourceLabel`).
String appliedSourceLabel(Rec applied) {
  final label = scopeTypeLabels[applied['scope_type']] ?? '${applied['scope_type']}';
  return applied['scope_name'] != null ? '$label: ${applied['scope_name']}' : label;
}

/// The line under what applies today: set at this scope (until when) or inherited from where.
String appliedNote(Rec applied, String scopeType) {
  if (applied['scope_type'] != scopeType) return 'Inherited from ${appliedSourceLabel(applied)}';
  final to = applied['effective_to'] as String?;
  return to != null ? 'Set here until ${coverageDate(to)}, then inherited' : 'Set here since ${coverageDate('${applied['effective_from']}')}';
}

/// "Return to inherited" is offered where an assignment can be ended (web `canEndAssignment`).
bool canReturnToInherited(CoverageRow row, String scopeType) => row.own != null && canEndAssignment(row.kind, scopeType, null);

/// `POST /policy-assignments/batch` for the changes that do not need an impact preview.
Rec batchBody({required String scopeType, required String? scopeId, required String effectiveFrom, required String reason, required List<CoverageChange> changes}) => {
      'scope_type': scopeType,
      'scope_id': scopeId,
      'effective_from': effectiveFrom,
      'reason': reason.trim().isEmpty ? null : reason.trim(),
      'changes': [
        for (final c in changes)
          {'policy_kind': c.row.kind, 'policy_id': c.policyId, 'leave_type_id': c.row.leaveTypeId, 'expected_version': c.row.own?['version']},
      ],
    };

/// The impact-preview change for a calendar or weekly-off pick (web `impactFor`).
Rec impactChange({required CoverageChange change, required String scopeType, required String? scopeId, required String effectiveFrom, required String reason}) => {
      'change_type': 'ASSIGNMENT_CREATE',
      if (change.row.own?['version'] != null) 'expected_version': change.row.own!['version'],
      'body': {
        'policy_kind': change.row.kind,
        'policy_id': change.policyId,
        'scope_type': scopeType,
        'scope_id': scopeId,
        'effective_from': effectiveFrom,
        'reason': reason.trim().isEmpty ? null : reason.trim(),
      },
    };

/// Which change failed, from a refused batch's first error detail (`policy_kind`, `leave_type_id`).
CoverageChange? failedChange(List<CoverageChange> changes, Map<String, dynamic>? context) {
  if (context == null) return null;
  for (final c in changes) {
    if (c.row.kind == context['policy_kind'] && c.row.leaveTypeId == context['leave_type_id']) return c;
  }
  return null;
}
