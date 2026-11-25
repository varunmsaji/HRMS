import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../core/api/api_client.dart';
import '../../../core/api/envelope.dart';
import '../../../core/auth/permissions.dart';
import '../../../core/format.dart';
import '../../../core/providers.dart';
import '../../../core/diagnostics/app_diagnostics.dart';
import '../../../core/time.dart' show formatMinutes;
import '../../attendance/domain/request_resources.dart' show regularizationTypeLabels;
import '../../profile/data/employee_repository.dart' show Employee;

/// The kinds of request the approvals inbox collects, in the order it shows them.
enum ApprovalKind { leave, correction, overtime, onboarding }

/// One request waiting for a decision.
class ApprovalItem {
  const ApprovalItem({required this.kind, required this.id, required this.title, required this.subtitle, required this.at, this.employeeId, this.name});

  final ApprovalKind kind;
  final String id;

  /// Whose request it is; null for an onboarding case (the candidate is not an employee yet).
  final String? employeeId;

  /// The person's name when it is already known (onboarding candidates); employees are looked up.
  final String? name;
  final String title;
  final String subtitle;

  /// When it was raised (ISO), or '' when unknown.
  final String at;

  /// The screen for this one item; the same paths the API puts in notification links.
  String get route => '${listRouteFor(kind)}/$id';
}

/// One kind's waiting requests. [failed] is true when it could not be read: the inbox says so
/// rather than showing it as empty.
class ApprovalQueue {
  const ApprovalQueue({required this.kind, required this.total, required this.items, this.failed = false});
  const ApprovalQueue.failed(this.kind)
      : total = 0,
        items = const [],
        failed = true;

  final ApprovalKind kind;

  /// How many are waiting in all; [items] holds at most a page of them.
  final int total;
  final List<ApprovalItem> items;
  final bool failed;
}

String listRouteFor(ApprovalKind kind) => switch (kind) {
      ApprovalKind.leave => '/app/leave-applications',
      ApprovalKind.correction => '/app/regularizations',
      ApprovalKind.overtime => '/app/overtime',
      ApprovalKind.onboarding => '/app/onboarding',
    };

/// The kinds [permissions] may decide. Onboarding review also needs the read permission, as on the
/// dashboard.
List<ApprovalKind> approvalKindsFor(Iterable<String> permissions) => [
      if (permissions.contains(leaveApplicationApprove)) ApprovalKind.leave,
      if (permissions.contains(attendanceRegularizationApprove)) ApprovalKind.correction,
      if (permissions.contains(attendanceOvertimeApprove)) ApprovalKind.overtime,
      if (permissions.contains(onboardingReview) && permissions.contains(onboardingView)) ApprovalKind.onboarding,
    ];

/// Whether this user approves anything at all (decides whether the inbox and its Home card show).
bool canApproveAnything(Iterable<String> permissions) => approvalKindsFor(permissions).isNotEmpty;

/// Reads the waiting requests across leave, attendance corrections, overtime and onboarding review
/// (MOB-UX-001). Each is the same permission-scoped list read the dashboard and the web use, so the
/// server decides what this user may see. The user's own requests are left out: nobody approves
/// their own, and the server refuses it anyway.
class ApprovalsRepository {
  ApprovalsRepository(this._client);

  final ApiClient _client;

  static const pageSize = 20;

  Future<List<ApprovalQueue>> load(Iterable<String> permissions, {String? myEmployeeId}) async {
    final kinds = approvalKindsFor(permissions);
    final queues = await Future.wait([for (final k in kinds) _queue(k, myEmployeeId)]);
    final ids = {for (final q in queues) for (final i in q.items) if (i.employeeId != null && i.name == null) i.employeeId!};
    final names = await _employeeNames(ids);
    return [
      for (final q in queues)
        ApprovalQueue(
          kind: q.kind,
          total: q.total,
          failed: q.failed,
          items: [
            for (final i in q.items)
              ApprovalItem(kind: i.kind, id: i.id, employeeId: i.employeeId, name: i.name ?? names[i.employeeId], title: i.title, subtitle: i.subtitle, at: i.at),
          ],
        ),
    ];
  }

  /// Just the number waiting, for the Home card.
  Future<int> count(Iterable<String> permissions, {String? myEmployeeId}) async {
    final queues = await Future.wait([for (final k in approvalKindsFor(permissions)) _queue(k, myEmployeeId)]);
    return queues.fold<int>(0, (sum, q) => sum + q.total);
  }

  Future<ApprovalQueue> _queue(ApprovalKind kind, String? me) async {
    try {
      return switch (kind) {
        ApprovalKind.leave => await _leave(me),
        ApprovalKind.correction => await _rows(kind, '/regularizations', {'request_status': 'SUBMITTED'}, 'submitted_at', me, (r) {
            final type = r['request_type'] as String?;
            return (regularizationTypeLabels[type] ?? 'Attendance correction', formatShortDate('${r['attendance_date']}'));
          }),
        ApprovalKind.overtime => await _rows(kind, '/overtime', {'record_status': 'PENDING'}, 'created_at', me, (r) {
            return ('Overtime · ${formatMinutes(r['minutes_detected'] as int?)}', formatShortDate('${r['attendance_date']}'));
          }),
        ApprovalKind.onboarding => await _onboarding(),
      };
    } catch (_) {
      return ApprovalQueue.failed(kind);
    }
  }

  Future<ListEnvelope<Map<String, dynamic>>> _list(String path, Map<String, dynamic> filters) =>
      _client.getList<Map<String, dynamic>>(path, query: PageQuery(page: 1, perPage: pageSize), filters: filters, parseItem: (d) => d as Map<String, dynamic>);

  /// A queue of employee requests. The user's own rows are dropped from the page and from the total.
  Future<ApprovalQueue> _rows(
    ApprovalKind kind,
    String path,
    Map<String, dynamic> filters,
    String timeField,
    String? me,
    (String, String) Function(Map<String, dynamic> row) describe,
  ) async {
    final env = await _list(path, filters);
    final own = env.data.where((r) => me != null && r['employee_id'] == me).length;
    return ApprovalQueue(
      kind: kind,
      total: ((env.pagination?.total ?? env.data.length) - own).clamp(0, 1 << 30),
      items: [
        for (final r in env.data)
          if (me == null || r['employee_id'] != me)
            () {
              final (title, subtitle) = describe(r);
              return ApprovalItem(kind: kind, id: r['id'] as String, employeeId: r['employee_id'] as String?, title: title, subtitle: subtitle, at: (r[timeField] as String?) ?? '');
            }(),
      ],
    );
  }

  Future<ApprovalQueue> _leave(String? me) async {
    // Leave type names are a nicety: without them a row just says "Leave".
    Map<String, String> types = const {};
    try {
      final env = await _client.getList<Map<String, dynamic>>('/leave-types', query: PageQuery(page: 1, perPage: 100), parseItem: (d) => d as Map<String, dynamic>);
      types = {for (final t in env.data) t['id'] as String: (t['name'] as String?) ?? 'Leave'};
    } catch (e, s) { AppDiagnostics.instance.recordHandled(e, s); }
    return _rows(ApprovalKind.leave, '/leave-applications', {'application_status': 'SUBMITTED'}, 'submitted_at', me, (r) {
      final days = r['total_days'];
      final n = days is num ? days : num.tryParse('$days');
      final count = n == null ? '' : ' · ${n == n.roundToDouble() ? n.toInt() : n} ${n == 1 ? 'day' : 'days'}';
      return (types[r['leave_type_id']] ?? 'Leave', '${formatDateRange('${r['start_date']}', '${r['end_date']}')}$count');
    });
  }

  /// Onboarding cases waiting on HR (`SUBMITTED`, `UNDER_REVIEW`). Cases waiting on the candidate
  /// are not decisions and are not counted.
  Future<ApprovalQueue> _onboarding() async {
    final parts = await Future.wait([for (final s in const ['SUBMITTED', 'UNDER_REVIEW']) _list('/onboarding-cases', {'status': s})]);
    final items = <ApprovalItem>[
      for (final env in parts)
        for (final r in env.data)
          ApprovalItem(
            kind: ApprovalKind.onboarding,
            id: r['id'] as String,
            name: ['${r['candidate_first_name'] ?? ''}', '${r['candidate_last_name'] ?? ''}'].where((s) => s.isNotEmpty).join(' '),
            title: 'Onboarding review',
            subtitle: r['status'] == 'UNDER_REVIEW' ? 'Under review' : 'Submitted by the candidate',
            at: (r['updated_at'] as String?) ?? '',
          ),
    ]..sort((a, b) => b.at.compareTo(a.at));
    return ApprovalQueue(kind: ApprovalKind.onboarding, total: parts.fold<int>(0, (s, e) => s + (e.pagination?.total ?? e.data.length)), items: items);
  }

  /// Display names, one `GET /employees/{id}` each; an id that cannot be read is left out.
  Future<Map<String, String>> _employeeNames(Set<String> ids) async {
    final out = <String, String>{};
    await Future.wait([
      for (final id in ids)
        _client.get('/employees/$id', parse: (d) => Employee.fromJson(d as Map<String, dynamic>)).then((e) {
          out[id] = e.fullName.isEmpty ? e.employeeCode : e.fullName;
        }).catchError((Object e, StackTrace s) { AppDiagnostics.instance.recordHandled(e, s); }),
    ]);
    return out;
  }
}

final approvalsRepositoryProvider = Provider<ApprovalsRepository>((ref) => ApprovalsRepository(ref.watch(apiClientProvider)));
