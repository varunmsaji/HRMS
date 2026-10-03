import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../core/api/api_client.dart' show PageQuery;
import '../../../core/api/api_error.dart';
import '../../../core/auth/permissions.dart';
import '../../../core/providers.dart';

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
    if (_loading) return const Center(child: CircularProgressIndicator());
    if (_error != null) {
      return Center(
        child: Padding(
          padding: const EdgeInsets.all(24),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              Text(_error!.message, textAlign: TextAlign.center),
              const SizedBox(height: 16),
              FilledButton(onPressed: _load, child: const Text('Retry')),
            ],
          ),
        ),
      );
    }
    final scheme = Theme.of(context).colorScheme;
    return RefreshIndicator(
      onRefresh: _load,
      child: _items.isEmpty
          ? ListView(children: [
              Padding(
                padding: const EdgeInsets.all(32),
                child: Text('No ${widget.section.title.toLowerCase()} records yet.', textAlign: TextAlign.center, style: TextStyle(color: scheme.onSurfaceVariant)),
              ),
            ])
          : ListView.separated(
              padding: const EdgeInsets.all(16),
              itemCount: _items.length,
              separatorBuilder: (_, __) => const SizedBox(height: 12),
              itemBuilder: (context, i) => _RecordCard(section: widget.section, item: _items[i]),
            ),
    );
  }
}

class _RecordCard extends StatelessWidget {
  const _RecordCard({required this.section, required this.item});

  final RecordSection section;
  final Map<String, dynamic> item;

  @override
  Widget build(BuildContext context) {
    final scheme = Theme.of(context).colorScheme;
    return Container(
      padding: const EdgeInsets.all(16),
      decoration: BoxDecoration(
        color: scheme.surfaceContainerLowest,
        borderRadius: BorderRadius.circular(12),
        border: Border.all(color: scheme.outlineVariant),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(section.cardTitle(item), style: Theme.of(context).textTheme.headlineSmall),
          const SizedBox(height: 12),
          for (final field in section.fields)
            Padding(
              padding: const EdgeInsets.symmetric(vertical: 5),
              child: Row(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Expanded(flex: 4, child: Text(field.label, style: TextStyle(color: scheme.onSurfaceVariant))),
                  Expanded(flex: 5, child: Text(formatRecordValue(field, item[field.key]), textAlign: TextAlign.end)),
                ],
              ),
            ),
        ],
      ),
    );
  }
}
