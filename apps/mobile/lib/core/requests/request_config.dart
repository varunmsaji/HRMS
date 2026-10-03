import '../auth/auth_types.dart';
import '../forms/form_spec.dart';

typedef Rec = Map<String, dynamic>;

/// One titled block of a request's detail screen.
class DetailSection {
  const DetailSection(this.title, this.rows, {this.lines = const []});
  final String title;
  final List<(String label, String value)> rows;

  /// Free-text lines (a history entry, a requested punch).
  final List<String> lines;
}

/// A dropdown filter on the list (e.g. request type): [param] is the query parameter name.
class RequestFilter {
  const RequestFilter({required this.param, required this.label, required this.options});
  final String param;
  final String label;
  final List<(String value, String label)> options;
}

/// A request that goes through approval — leave, regularization, overtime. Describes how to list
/// it (the web `[resource]/page.tsx` filters), create it, show it, and decide it, so one pair of
/// screens serves each of them. The server enforces every rule; the hooks here only hide actions
/// that could never succeed (mirroring the web pages).
class RequestConfig {
  const RequestConfig({
    required this.title,
    required this.singular,
    required this.path,
    required this.statuses,
    required this.statusParam,
    required this.approvePermission,
    required this.rowTitle,
    required this.sections,
    required this.isPending,
    this.rowSubtitle,
    this.statusLabels = const {},
    this.filters = const [],
    this.submitPermission,
    this.onBehalfPermission,
    this.createSpec,
    this.createChoiceKeys = const [],
    this.buildCreateBody,
    this.canCancel,
    this.selfApprovalCode,
    this.approverMismatchCode,
    this.cancelLabel = 'Cancel request',
  });

  final String title;
  final String singular;
  final String path;

  final List<String> statuses;
  final Map<String, String> statusLabels;

  /// Query parameter that filters by status (`request_status`, `record_status`).
  final String statusParam;
  final List<RequestFilter> filters;

  final String approvePermission;
  final String? submitPermission;
  final String? onBehalfPermission;

  /// `rowTitle(row, employeeName)` — employeeName is empty on the "Mine" view.
  final String Function(Rec row, String employeeName) rowTitle;
  final String? Function(Rec row)? rowSubtitle;

  /// The creation form, if the user can raise one. Null = system-created (overtime).
  final FormSpec Function(bool onBehalf)? createSpec;
  final List<String> createChoiceKeys;

  /// Turns the form payload into the request body (`zone` is the company timezone).
  final Map<String, dynamic> Function(Map<String, dynamic> payload, String zone)? buildCreateBody;

  /// Detail sections for a record; [zone] is the company timezone.
  final List<DetailSection> Function(Rec row, String zone) sections;

  /// Whether the record is awaiting a decision (so a reviewer may approve/reject it).
  final bool Function(Rec row) isPending;

  /// Whether this user may withdraw the record. Null = cancelling isn't a thing for this request.
  final bool Function(Rec row, UserProfile user)? canCancel;
  final String cancelLabel;

  final String? selfApprovalCode;
  final String? approverMismatchCode;
}
