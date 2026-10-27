import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../core/api/api_client.dart' show ApiClient, PageQuery;
import '../../../core/api/api_error.dart';
import '../../../core/auth/permissions.dart';
import '../../../core/forms/choice_sources.dart';
import '../../../core/forms/form_spec.dart';
import '../../../core/forms/spec_form_screen.dart';
import '../../../core/providers.dart';
import '../../auth/state/auth_controller.dart';
import '../../employees/domain/employee_forms.dart';
import '../../../core/widgets/ui.dart';

enum RecordFormat { text, yesNo, money }

class RecordField {
  const RecordField(this.label, this.key, {this.format = RecordFormat.text});
  final String label;
  final String key;
  final RecordFormat format;
}

/// One read-only tab of the employee record. Mirrors a web panel under
/// `apps/web/src/components/employee/` — same endpoint, fields as returned by
/// the matching `*Read` schema in `apps/api/.../employee/schemas.py`.
class RecordSection {
  const RecordSection({
    required this.title,
    required this.path,
    required this.fields,
    required this.cardTitle,
    this.permission,
    this.single = false,
    this.actions = const [],
    this.rowActions = const [],
  });

  final String title;

  /// Appended to `/employees/{id}`.
  final String path;
  final List<RecordField> fields;
  final String Function(Map<String, dynamic> item) cardTitle;

  /// Null means every viewer of the employee may open the tab.
  final String? permission;

  /// The endpoint returns one object (identity) instead of a list.
  final bool single;

  /// Section-level writes (create / revise / terminate…), shown above the records.
  final List<RecordAction> actions;

  /// Per-record writes (delete…), shown on each card.
  final List<RecordRowAction> rowActions;
}

typedef Items = List<Map<String, dynamic>>;

/// The row that is currently in force: an effective-dated record with no end date.
Map<String, dynamic>? openRow(Items items) {
  for (final i in items) {
    if (i['effective_to'] == null) return i;
  }
  return null;
}

/// A write offered on a section, opened as a spec-driven form. The backend decides; [permission]
/// and [visible] only hide actions that could never succeed.
class RecordAction {
  const RecordAction({
    required this.label,
    required this.spec,
    required this.submit,
    this.permission,
    this.anyOf = const [],
    this.visible,
    this.initial,
    this.defaults = const {},
    this.choiceKeys = const [],
    this.intro,
    this.destructive = false,
    this.specFor,
  });

  /// Shown on the button (and as the form title); may depend on the loaded records.
  final String Function(Items items) label;
  final FormSpec spec;

  /// Overrides [spec] when it depends on who is asking (e.g. which change types they may record).
  final FormSpec Function(List<String> permissions)? specFor;
  final String? permission;

  /// Alternative permissions — any one is enough.
  final List<String> anyOf;
  final bool Function(Items items)? visible;
  final Map<String, dynamic>? Function(Items items)? initial;
  final Map<String, dynamic> defaults;
  final List<String> choiceKeys;
  final String? intro;
  final bool destructive;
  final Future<void> Function(ApiClient client, String employeeId, Items items, Map<String, dynamic> payload, Map<String, dynamic> changed) submit;

  bool allowed(List<String> permissions) =>
      (permission == null && anyOf.isEmpty) || (permission != null && permissions.contains(permission)) || anyOf.any(permissions.contains);
}

class RecordRowAction {
  const RecordRowAction({required this.label, required this.permission, required this.confirm, required this.perform});
  final String label;
  final String permission;
  final String confirm;
  final Future<void> Function(ApiClient client, String employeeId, Map<String, dynamic> row) perform;
}

Map<String, dynamic> _withoutNulls(Map<String, dynamic> m) => {
      for (final e in m.entries)
        if (e.value != null) e.key: e.value,
    };

/// Effective-dated create: `If-Match` is needed only while a current row exists.
Future<void> _createRevision(ApiClient client, String employeeId, String path, Items items, Map<String, dynamic> payload) {
  final current = openRow(items);
  return client.post<Object?>('/employees/$employeeId$path', body: payload, ifMatch: current?['version']?.toString(), parse: (_) => null);
}

Future<void> _deleteRow(ApiClient client, String employeeId, String path, Map<String, dynamic> row) =>
    client.delete<Object?>('/employees/$employeeId$path/${row['id']}', ifMatch: row['version']?.toString(), parse: (_) => null);

Map<String, dynamic>? _active(Items items) {
  for (final i in items) {
    if (i['status'] == 'ACTIVE') return i;
  }
  return null;
}

String _s(Map<String, dynamic> m, String k) => (m[k] ?? '').toString();

String _range(Map<String, dynamic> m, String from, String to) {
  final end = m[to];
  return '${_s(m, from)} → ${end == null ? 'present' : end.toString()}';
}

final employeeRecordSections = <RecordSection>[
  RecordSection(
    title: 'Employment',
    path: '/employments',
    actions: [
      RecordAction(
        label: (items) => items.isEmpty ? 'Create first employment' : 'Rehire',
        permission: employeeCreate,
        visible: (items) => _active(items) == null,
        spec: employmentCreateSpec,
        choiceKeys: const ['legal_entities'],
        intro: "The employee's identity and history are retained — a rehire starts a new employment episode.",
        submit: (client, id, items, payload, _) => client.post<Object?>('/employees/$id/employments', body: payload, parse: (_) => null),
      ),
      RecordAction(
        label: (_) => 'Edit employment',
        permission: employeeUpdate,
        visible: (items) => _active(items) != null,
        spec: employmentEditSpec,
        choiceKeys: const ['legal_entities'],
        initial: _active,
        submit: (client, id, items, payload, changed) {
          final current = _active(items)!;
          return client.patch<Object?>('/employees/$id/employments/${current['id']}', body: changed, ifMatch: current['version'].toString(), parse: (_) => null);
        },
      ),
      RecordAction(
        label: (_) => 'Terminate',
        permission: employeeTerminate,
        visible: (items) => _active(items) != null,
        spec: employmentTerminateSpec,
        destructive: true,
        intro: 'Ends the current employment on the last working day. This cannot be undone.',
        submit: (client, id, items, payload, _) {
          final current = _active(items)!;
          return client.post<Object?>('/employees/$id/employments/${current['id']}/terminate', body: payload, ifMatch: current['version'].toString(), parse: (_) => null);
        },
      ),
    ],
    cardTitle: (m) => 'Joined ${_s(m, 'joining_date')}',
    fields: const [
      RecordField('Status', 'status'),
      RecordField('Pay basis', 'pay_basis'),
      RecordField('Joining date', 'joining_date'),
      RecordField('Probation ends', 'probation_end_date'),
      RecordField('Last working day', 'last_working_day'),
    ],
  ),
  RecordSection(
    title: 'Assignment',
    path: '/assignments',
    actions: [
      RecordAction(
        label: (items) => items.isEmpty ? 'Record initial placement' : 'Record a change',
        anyOf: const [employeeTransfer, employeePromote],
        spec: assignmentSpec(const ['INITIAL', 'TRANSFER', 'PROMOTION', 'MANAGER_CHANGE', 'SHIFT_CHANGE']),
        specFor: (permissions) => assignmentSpec([
          if (permissions.contains(employeeTransfer)) ...const ['INITIAL', 'TRANSFER', 'MANAGER_CHANGE', 'SHIFT_CHANGE'],
          if (permissions.contains(employeePromote)) 'PROMOTION',
        ]),
        choiceKeys: const ['branches', 'departments', 'designations', 'grades', 'employees', 'shifts'],
        intro: 'Anything you leave empty carries forward unchanged from the current assignment.',
        submit: (client, id, items, payload, _) => _createRevision(client, id, '/assignments', items, _withoutNulls(payload)),
      ),
    ],
    cardTitle: (m) => _range(m, 'effective_from', 'effective_to'),
    fields: const [
      RecordField('Work location type', 'work_location_type'),
      RecordField('Change type', 'change_type'),
      RecordField('Change reason', 'change_reason'),
      RecordField('Branch', 'branch_id'),
      RecordField('Department', 'department_id'),
      RecordField('Designation', 'designation_id'),
      RecordField('Grade', 'grade_id'),
      RecordField('Reporting manager', 'reporting_manager_id'),
      RecordField('Shift', 'shift_id'),
    ],
  ),
  RecordSection(
    title: 'Compensation',
    path: '/compensation',
    actions: [
      RecordAction(
        label: (items) => items.isEmpty ? 'Set compensation' : 'Revise compensation',
        permission: employeeUpdateCompensation,
        spec: compensationSpec,
        intro: 'Closes the current compensation and starts a new one on the effective date.',
        submit: (client, id, items, payload, _) => _createRevision(client, id, '/compensation', items, payload),
      ),
    ],
    permission: employeeViewCompensation,
    cardTitle: (m) => _range(m, 'effective_from', 'effective_to'),
    fields: const [
      RecordField('Annual CTC', 'annual_ctc_minor', format: RecordFormat.money),
      RecordField('Currency', 'currency'),
      RecordField('Revision type', 'revision_type'),
      RecordField('Revision reason', 'revision_reason'),
    ],
  ),
  RecordSection(
    title: 'Statutory',
    path: '/statutory',
    actions: [
      RecordAction(
        label: (items) => items.isEmpty ? 'Set statutory profile' : 'Revise statutory profile',
        permission: employeeUpdateSensitive,
        spec: statutorySpec,
        intro: 'Closes the current statutory profile and starts a new one on the effective date.',
        submit: (client, id, items, payload, _) => _createRevision(client, id, '/statutory', items, payload),
      ),
    ],
    permission: employeeViewStatutory,
    cardTitle: (m) => _range(m, 'effective_from', 'effective_to'),
    fields: const [
      RecordField('PF applicable', 'is_pf_applicable', format: RecordFormat.yesNo),
      RecordField('PF number', 'pf_number'),
      RecordField('PF wage-ceiling opt-out', 'pf_wage_ceiling_opt_out', format: RecordFormat.yesNo),
      RecordField('VPF amount', 'vpf_amount'),
      RecordField('VPF %', 'vpf_percentage'),
      RecordField('ESI applicable', 'is_esi_applicable', format: RecordFormat.yesNo),
      RecordField('ESI IP number', 'esi_ip_number'),
      RecordField('PT state', 'pt_state_code'),
      RecordField('LWF applicable', 'is_lwf_applicable', format: RecordFormat.yesNo),
      RecordField('Tax regime', 'tax_regime'),
      RecordField('Director', 'is_director', format: RecordFormat.yesNo),
      RecordField('International worker', 'is_international_worker', format: RecordFormat.yesNo),
    ],
  ),
  RecordSection(
    title: 'Banking',
    path: '/bank',
    actions: [
      RecordAction(
        label: (items) => items.isEmpty ? 'Add bank details' : 'Change bank details',
        permission: employeeUpdateSensitive,
        spec: bankSpec,
        intro: 'Closes the current bank account and starts a new one on the effective date.',
        submit: (client, id, items, payload, _) => _createRevision(client, id, '/bank', items, payload),
      ),
    ],
    permission: employeeViewBanking,
    cardTitle: (m) => _s(m, 'bank_name').isEmpty ? _range(m, 'effective_from', 'effective_to') : _s(m, 'bank_name'),
    fields: const [
      RecordField('Account holder', 'account_holder_name'),
      RecordField('Account number', 'account_number_enc'),
      RecordField('IFSC', 'ifsc'),
      RecordField('Branch', 'branch_name'),
      RecordField('Payment mode', 'payment_mode'),
      RecordField('Primary', 'is_primary', format: RecordFormat.yesNo),
      RecordField('Verification', 'verification_status'),
      RecordField('Effective from', 'effective_from'),
      RecordField('Effective to', 'effective_to'),
    ],
  ),
  RecordSection(
    title: 'Identity',
    path: '/identity',
    actions: [
      RecordAction(
        label: (_) => 'Edit identity',
        permission: employeeUpdateSensitive,
        spec: identitySpec,
        initial: (items) => items.isEmpty ? null : items.first,
        submit: (client, id, items, payload, changed) =>
            client.patch<Object?>('/employees/$id/identity', body: changed, ifMatch: items.first['version'].toString(), parse: (_) => null),
      ),
    ],
    permission: employeeViewSensitive,
    single: true,
    cardTitle: (m) => 'Identity documents',
    fields: const [
      RecordField('PAN', 'pan_number'),
      RecordField('Aadhaar', 'aadhaar_number'),
      RecordField('UAN', 'uan_number'),
      RecordField('Father / husband name', 'father_or_husband_name'),
    ],
  ),
  RecordSection(
    title: 'Experience',
    path: '/experience',
    actions: [
      RecordAction(
        label: (_) => 'Add experience',
        permission: employeeUpdateSensitive,
        spec: experienceSpec,
        submit: (client, id, items, payload, _) => client.post<Object?>('/employees/$id/experience', body: payload, parse: (_) => null),
      ),
    ],
    rowActions: [
      RecordRowAction(
        label: 'Delete',
        permission: employeeUpdateSensitive,
        confirm: 'Delete this experience entry?',
        perform: (client, id, row) => _deleteRow(client, id, '/experience', row),
      ),
    ],
    permission: employeeViewExperience,
    cardTitle: (m) => _s(m, 'company_name'),
    fields: const [
      RecordField('Designation', 'designation'),
      RecordField('From', 'from_date'),
      RecordField('To', 'to_date'),
      RecordField('Last CTC', 'last_ctc_minor', format: RecordFormat.money),
      RecordField('Reason for leaving', 'reason_for_leaving'),
      RecordField('Prior PF membership', 'had_prior_pf_membership', format: RecordFormat.yesNo),
      RecordField('Previous UAN', 'previous_uan'),
      RecordField('Previous PF account', 'previous_pf_account_number'),
      RecordField('Previous ESI IP', 'previous_esi_ip_number'),
    ],
  ),
  RecordSection(
    title: 'Education',
    path: '/education',
    actions: [
      RecordAction(
        label: (_) => 'Add education',
        permission: employeeUpdateSensitive,
        spec: educationSpec,
        submit: (client, id, items, payload, _) => client.post<Object?>('/employees/$id/education', body: payload, parse: (_) => null),
      ),
    ],
    rowActions: [
      RecordRowAction(
        label: 'Delete',
        permission: employeeUpdateSensitive,
        confirm: 'Delete this education entry?',
        perform: (client, id, row) => _deleteRow(client, id, '/education', row),
      ),
    ],
    permission: employeeViewExperience,
    cardTitle: (m) => _s(m, 'qualification'),
    fields: const [
      RecordField('Institution', 'institution_name'),
      RecordField('Year of passing', 'year_of_passing'),
    ],
  ),
  RecordSection(
    title: 'Dependents',
    path: '/dependents',
    actions: [
      RecordAction(
        label: (_) => 'Add dependent / nominee',
        permission: employeeUpdateSensitive,
        spec: dependentSpec,
        submit: (client, id, items, payload, _) => client.post<Object?>('/employees/$id/dependents', body: payload, parse: (_) => null),
      ),
    ],
    rowActions: [
      RecordRowAction(
        label: 'Delete',
        permission: employeeUpdateSensitive,
        confirm: 'Delete this dependent?',
        perform: (client, id, row) => _deleteRow(client, id, '/dependents', row),
      ),
    ],
    permission: employeeViewNominee,
    cardTitle: (m) => '${_s(m, 'full_name')} (${_s(m, 'relationship')})',
    fields: const [
      RecordField('Date of birth', 'date_of_birth'),
      RecordField('Gender', 'gender'),
      RecordField('Minor', 'is_minor', format: RecordFormat.yesNo),
      RecordField('Guardian', 'guardian_name'),
      RecordField('Guardian relationship', 'guardian_relationship'),
      RecordField('Aadhaar', 'aadhaar_number_enc'),
      RecordField('PF nominee', 'is_pf_nominee', format: RecordFormat.yesNo),
      RecordField('PF share %', 'pf_nominee_share_percentage'),
      RecordField('Gratuity nominee', 'is_gratuity_nominee', format: RecordFormat.yesNo),
      RecordField('Gratuity share %', 'gratuity_nominee_share_percentage'),
      RecordField('ESI dependent', 'is_esi_dependent', format: RecordFormat.yesNo),
    ],
  ),
];

String formatRecordValue(RecordField field, dynamic raw) {
  if (raw == null || raw.toString().trim().isEmpty) return 'Not configured';
  switch (field.format) {
    case RecordFormat.yesNo:
      return raw == true ? 'Yes' : 'No';
    case RecordFormat.money:
      final minor = raw is num ? raw : num.tryParse(raw.toString());
      return minor == null ? raw.toString() : (minor / 100).toStringAsFixed(2);
    case RecordFormat.text:
      return raw.toString();
  }
}

/// Loads and renders one [RecordSection] for [employeeId].
class EmployeeRecordPanel extends ConsumerStatefulWidget {
  const EmployeeRecordPanel({super.key, required this.employeeId, required this.section});

  final String employeeId;
  final RecordSection section;

  @override
  ConsumerState<EmployeeRecordPanel> createState() => _EmployeeRecordPanelState();
}

class _EmployeeRecordPanelState extends ConsumerState<EmployeeRecordPanel> {
  bool _loading = true;
  List<Map<String, dynamic>> _items = const [];
  ApiError? _error;

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    setState(() {
      _loading = true;
      _error = null;
    });
    final client = ref.read(apiClientProvider);
    final path = '/employees/${widget.employeeId}${widget.section.path}';
    try {
      final List<Map<String, dynamic>> items;
      if (widget.section.single) {
        final one = await client.get<Map<String, dynamic>>(path, parse: (d) => d as Map<String, dynamic>);
        items = [one];
      } else {
        final env = await client.getList<Map<String, dynamic>>(
          path,
          query: PageQuery(perPage: 100),
          parseItem: (d) => d as Map<String, dynamic>,
        );
        items = env.data;
      }
      if (mounted) setState(() => _items = items);
    } catch (error) {
      if (mounted) {
        setState(() => _error = error is ApiError ? error : ApiError(status: 0, code: 'UNKNOWN_ERROR', message: 'Something went wrong.'));
      }
    } finally {
      if (mounted) setState(() => _loading = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    if (_loading) return const ListSkeleton(count: 3);
    if (_error != null) return StateMessage(icon: Icons.error_outline_rounded, tone: Tone.danger, title: 'Something went wrong', message: _error!.message, actionLabel: 'Retry', onAction: _load);
    final scheme = Theme.of(context).colorScheme;
    final permissions = ref.watch(authControllerProvider).user?.permissions ?? const <String>[];
    final actions = [
      for (final a in widget.section.actions)
        if (a.allowed(permissions) && (a.visible?.call(_items) ?? true)) a,
    ];
    return RefreshIndicator(
      onRefresh: _load,
      child: ListView(
        padding: const EdgeInsets.all(16),
        children: [
          if (actions.isNotEmpty)
            Padding(
              padding: const EdgeInsets.only(bottom: 12),
              child: Wrap(spacing: 8, runSpacing: 8, children: [
                for (final a in actions)
                  (a.destructive ? OutlinedButton.new : FilledButton.new)(
                    style: a.destructive ? OutlinedButton.styleFrom(foregroundColor: scheme.error) : null,
                    onPressed: () => _runAction(a, permissions),
                    child: Text(a.label(_items)),
                  ),
              ]),
            ),
          if (_items.isEmpty)
            SizedBox(height: 280, child: StateMessage(icon: Icons.folder_open_outlined, title: 'Nothing here yet', message: 'No ${widget.section.title.toLowerCase()} records yet.')),
          for (final item in _items) ...[
            _RecordCard(
              section: widget.section,
              item: item,
              rowActions: [for (final r in widget.section.rowActions) if (permissions.contains(r.permission)) r],
              onRowAction: _runRowAction,
            ),
            const SizedBox(height: 12),
          ],
        ],
      ),
    );
  }

  void _toast(String m) => ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(m)));

  Future<void> _runAction(RecordAction a, List<String> permissions) async {
    final client = ref.read(apiClientProvider);
    final saved = await openSpecForm(
      context,
      title: a.label(_items),
      spec: a.specFor?.call(permissions) ?? a.spec,
      initial: a.initial?.call(_items),
      defaults: a.defaults,
      intro: a.intro,
      loadChoices: a.choiceKeys.isEmpty ? null : () => loadChoices(client, a.choiceKeys),
      submitLabel: a.destructive ? a.label(_items) : null,
      onSubmit: (payload, changed) => a.submit(client, widget.employeeId, _items, payload, changed),
    );
    if (saved && mounted) {
      _toast('Saved.');
      await _load();
    }
  }

  Future<void> _runRowAction(RecordRowAction r, Map<String, dynamic> row) async {
    final yes = await showDialog<bool>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: Text(r.label),
        content: Text(r.confirm),
        actions: [
          TextButton(onPressed: () => Navigator.of(ctx).pop(false), child: const Text('Cancel')),
          FilledButton(onPressed: () => Navigator.of(ctx).pop(true), child: Text(r.label)),
        ],
      ),
    );
    if (yes != true) return;
    try {
      await r.perform(ref.read(apiClientProvider), widget.employeeId, row);
      if (mounted) _toast('Done.');
      await _load();
    } catch (e) {
      if (mounted) _toast(e is ApiError ? (e.code == 'STALE_RESOURCE' ? 'This record was changed by someone else. Pull to refresh and try again.' : e.message) : 'Something went wrong.');
    }
  }
}

class _RecordCard extends StatelessWidget {
  const _RecordCard({required this.section, required this.item, this.rowActions = const [], this.onRowAction});

  final RecordSection section;
  final Map<String, dynamic> item;
  final List<RecordRowAction> rowActions;
  final void Function(RecordRowAction action, Map<String, dynamic> row)? onRowAction;

  @override
  Widget build(BuildContext context) {
    final scheme = Theme.of(context).colorScheme;
    return AppCard(
      padding: const EdgeInsets.all(16),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(section.cardTitle(item), style: Theme.of(context).textTheme.titleLarge?.copyWith(fontWeight: FontWeight.w700)),
          const SizedBox(height: 8),
          for (final field in section.fields) KeyValueRow(field.label, formatRecordValue(field, item[field.key])),
          if (rowActions.isNotEmpty)
            Align(
              alignment: Alignment.centerRight,
              child: Wrap(spacing: 8, children: [
                for (final r in rowActions)
                  TextButton(
                    style: TextButton.styleFrom(foregroundColor: scheme.error),
                    onPressed: () => onRowAction?.call(r, item),
                    child: Text(r.label),
                  ),
              ]),
            ),
        ],
      ),
    );
  }
}
