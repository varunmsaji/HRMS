import 'package:flutter/material.dart';

import '../../../core/api/api_error.dart';
import '../../auth/presentation/widgets/auth_form_field.dart';
import '../data/policy_repository.dart';

/// Shared chrome for a "new draft version" form — each policy kind only
/// supplies its own curated field list (the full version schemas run
/// 15-30 fields each; these forms cover the common, load-bearing ones and
/// leave the rest at the server's defaults, editable in full on web).
class _VersionFormScaffold extends StatefulWidget {
  const _VersionFormScaffold({
    super.key,
    required this.title,
    required this.repository,
    required this.policyId,
    required this.fields,
    required this.buildBody,
  });

  final String title;
  final PolicyRepository repository;
  final String policyId;
  final Map<String, TextEditingController> fields;
  final Widget Function(BuildContext context, bool submitting) buildBody;

  @override
  State<_VersionFormScaffold> createState() => VersionFormScaffoldState();
}

class VersionFormScaffoldState extends State<_VersionFormScaffold> {
  bool submitting = false;
  String? formError;

  Future<void> submit(Map<String, dynamic> body) async {
    setState(() {
      submitting = true;
      formError = null;
    });
    try {
      await widget.repository.createVersion(widget.policyId, body);
      if (mounted) Navigator.of(context).pop(true);
    } catch (error) {
      setState(() => formError = error is ApiError ? error.message : 'Something went wrong.');
    } finally {
      if (mounted) setState(() => submitting = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: Text(widget.title)),
      body: ListView(
        padding: const EdgeInsets.all(16),
        children: [
          if (formError != null) ...[InlineAlert(message: formError!), const SizedBox(height: 16)],
          widget.buildBody(context, submitting),
        ],
      ),
    );
  }
}

DateTime? _parseDate(String text) => DateTime.tryParse(text.trim());

Widget _dateField(TextEditingController controller, bool enabled, {String label = 'Effective from', bool required = true}) {
  return AuthFormField(
    label: label,
    required: required,
    description: 'YYYY-MM-DD',
    child: TextField(controller: controller, enabled: enabled, decoration: const InputDecoration(hintText: '2026-10-01')),
  );
}

Widget _numberField(TextEditingController controller, bool enabled, String label, {String? description}) {
  return AuthFormField(
    label: label,
    description: description,
    child: TextField(controller: controller, enabled: enabled, keyboardType: TextInputType.number),
  );
}

class AttendancePolicyVersionForm extends StatefulWidget {
  const AttendancePolicyVersionForm({super.key, required this.repository, required this.policyId});
  final PolicyRepository repository;
  final String policyId;

  @override
  State<AttendancePolicyVersionForm> createState() => _AttendancePolicyVersionFormState();
}

class _AttendancePolicyVersionFormState extends State<AttendancePolicyVersionForm> {
  final _effectiveFrom = TextEditingController();
  final _graceIn = TextEditingController(text: '0');
  final _graceOut = TextEditingController(text: '0');
  final _halfDayBoundary = TextEditingController();
  final _key = GlobalKey<VersionFormScaffoldState>();

  @override
  Widget build(BuildContext context) {
    return _VersionFormScaffold(
      key: _key,
      title: 'New attendance policy draft',
      repository: widget.repository,
      policyId: widget.policyId,
      fields: const {},
      buildBody: (context, submitting) => Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          _dateField(_effectiveFrom, !submitting),
          const SizedBox(height: 16),
          Row(children: [
            Expanded(child: _numberField(_graceIn, !submitting, 'Grace in (minutes)')),
            const SizedBox(width: 12),
            Expanded(child: _numberField(_graceOut, !submitting, 'Grace out (minutes)')),
          ]),
          const SizedBox(height: 16),
          _numberField(_halfDayBoundary, !submitting, 'Half-day boundary (minutes)', description: 'Optional'),
          const SizedBox(height: 20),
          PrimaryButton(
            label: 'Create draft',
            loading: submitting,
            onPressed: () {
              if (_parseDate(_effectiveFrom.text) == null) return;
              _key.currentState?.submit({
                'effective_from': _effectiveFrom.text.trim(),
                'grace_in_minutes': int.tryParse(_graceIn.text.trim()) ?? 0,
                'grace_out_minutes': int.tryParse(_graceOut.text.trim()) ?? 0,
                if (_halfDayBoundary.text.trim().isNotEmpty) 'half_day_boundary_minutes': int.tryParse(_halfDayBoundary.text.trim()),
              });
            },
          ),
        ],
      ),
    );
  }
}

class OvertimePolicyVersionForm extends StatefulWidget {
  const OvertimePolicyVersionForm({super.key, required this.repository, required this.policyId});
  final PolicyRepository repository;
  final String policyId;

  @override
  State<OvertimePolicyVersionForm> createState() => _OvertimePolicyVersionFormState();
}

class _OvertimePolicyVersionFormState extends State<OvertimePolicyVersionForm> {
  final _effectiveFrom = TextEditingController();
  final _minOtMinutes = TextEditingController(text: '0');
  final _dailyCap = TextEditingController();
  final _weeklyCap = TextEditingController();
  final _monthlyCap = TextEditingController();
  bool _requiresPreApproval = false;
  bool _requiresPostApproval = true;
  final _key = GlobalKey<VersionFormScaffoldState>();

  @override
  Widget build(BuildContext context) {
    return _VersionFormScaffold(
      key: _key,
      title: 'New overtime policy draft',
      repository: widget.repository,
      policyId: widget.policyId,
      fields: const {},
      buildBody: (context, submitting) => Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          _dateField(_effectiveFrom, !submitting),
          const SizedBox(height: 16),
          _numberField(_minOtMinutes, !submitting, 'Minimum OT (minutes)'),
          const SizedBox(height: 16),
          Row(children: [
            Expanded(child: _numberField(_dailyCap, !submitting, 'Daily cap (min)', description: 'Optional')),
            const SizedBox(width: 12),
            Expanded(child: _numberField(_weeklyCap, !submitting, 'Weekly cap (min)', description: 'Optional')),
          ]),
          const SizedBox(height: 16),
          _numberField(_monthlyCap, !submitting, 'Monthly cap (minutes)', description: 'Optional'),
          const SizedBox(height: 8),
          SwitchListTile(
            contentPadding: EdgeInsets.zero,
            title: const Text('Requires pre-approval'),
            value: _requiresPreApproval,
            onChanged: submitting ? null : (v) => setState(() => _requiresPreApproval = v),
          ),
          SwitchListTile(
            contentPadding: EdgeInsets.zero,
            title: const Text('Requires post-approval'),
            value: _requiresPostApproval,
            onChanged: submitting ? null : (v) => setState(() => _requiresPostApproval = v),
          ),
          const SizedBox(height: 12),
          PrimaryButton(
            label: 'Create draft',
            loading: submitting,
            onPressed: () {
              if (_parseDate(_effectiveFrom.text) == null) return;
              _key.currentState?.submit({
                'effective_from': _effectiveFrom.text.trim(),
                'min_ot_minutes': int.tryParse(_minOtMinutes.text.trim()) ?? 0,
                'requires_pre_approval': _requiresPreApproval,
                'requires_post_approval': _requiresPostApproval,
                if (_dailyCap.text.trim().isNotEmpty) 'daily_cap_minutes': int.tryParse(_dailyCap.text.trim()),
                if (_weeklyCap.text.trim().isNotEmpty) 'weekly_cap_minutes': int.tryParse(_weeklyCap.text.trim()),
                if (_monthlyCap.text.trim().isNotEmpty) 'monthly_cap_minutes': int.tryParse(_monthlyCap.text.trim()),
              });
            },
          ),
        ],
      ),
    );
  }
}

class ShiftVersionForm extends StatefulWidget {
  const ShiftVersionForm({super.key, required this.repository, required this.policyId});
  final PolicyRepository repository;
  final String policyId;

  @override
  State<ShiftVersionForm> createState() => _ShiftVersionFormState();
}

class _ShiftVersionFormState extends State<ShiftVersionForm> {
  final _effectiveFrom = TextEditingController();
  final _timezone = TextEditingController(text: 'Asia/Kolkata');
  final _startTime = TextEditingController(text: '09:00');
  final _endTime = TextEditingController(text: '18:00');
  String _shiftType = 'FIXED';
  final _key = GlobalKey<VersionFormScaffoldState>();

  @override
  Widget build(BuildContext context) {
    return _VersionFormScaffold(
      key: _key,
      title: 'New shift timing draft',
      repository: widget.repository,
      policyId: widget.policyId,
      fields: const {},
      buildBody: (context, submitting) => Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          _dateField(_effectiveFrom, !submitting),
          const SizedBox(height: 16),
          AuthFormField(
            label: 'Shift type',
            child: DropdownButtonFormField<String>(
              value: _shiftType,
              items: const [
                DropdownMenuItem(value: 'FIXED', child: Text('Fixed')),
                DropdownMenuItem(value: 'FLEXIBLE', child: Text('Flexible')),
                DropdownMenuItem(value: 'SPLIT', child: Text('Split')),
              ],
              onChanged: submitting ? null : (v) => setState(() => _shiftType = v ?? _shiftType),
            ),
          ),
          const SizedBox(height: 16),
          Row(children: [
            Expanded(child: AuthFormField(label: 'Start time', description: 'HH:MM', child: TextField(controller: _startTime, enabled: !submitting))),
            const SizedBox(width: 12),
            Expanded(child: AuthFormField(label: 'End time', description: 'HH:MM', child: TextField(controller: _endTime, enabled: !submitting))),
          ]),
          const SizedBox(height: 16),
          AuthFormField(label: 'Timezone', child: TextField(controller: _timezone, enabled: !submitting)),
          const SizedBox(height: 20),
          PrimaryButton(
            label: 'Create draft',
            loading: submitting,
            onPressed: () {
              if (_parseDate(_effectiveFrom.text) == null) return;
              _key.currentState?.submit({
                'effective_from': _effectiveFrom.text.trim(),
                'shift_type': _shiftType,
                'timezone': _timezone.text.trim(),
                'start_time': _startTime.text.trim(),
                'end_time': _endTime.text.trim(),
              });
            },
          ),
        ],
      ),
    );
  }
}

class RegularizationPolicyVersionForm extends StatefulWidget {
  const RegularizationPolicyVersionForm({super.key, required this.repository, required this.policyId});
  final PolicyRepository repository;
  final String policyId;

  @override
  State<RegularizationPolicyVersionForm> createState() => _RegularizationPolicyVersionFormState();
}

class _RegularizationPolicyVersionFormState extends State<RegularizationPolicyVersionForm> {
  final _effectiveFrom = TextEditingController();
  final _maxBackdatedDays = TextEditingController();
  final _maxRequestsPerMonth = TextEditingController();
  bool _allowEmployeeRequest = true;
  bool _allowManagerRequest = true;
  bool _allowHrRequest = true;
  bool _reasonRequired = true;
  bool _attachmentRequired = false;
  final _key = GlobalKey<VersionFormScaffoldState>();

  @override
  Widget build(BuildContext context) {
    return _VersionFormScaffold(
      key: _key,
      title: 'New regularization policy draft',
      repository: widget.repository,
      policyId: widget.policyId,
      fields: const {},
      buildBody: (context, submitting) => Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          _dateField(_effectiveFrom, !submitting),
          const SizedBox(height: 16),
          Row(children: [
            Expanded(child: _numberField(_maxBackdatedDays, !submitting, 'Max backdated days', description: 'Optional')),
            const SizedBox(width: 12),
            Expanded(child: _numberField(_maxRequestsPerMonth, !submitting, 'Max requests/month', description: 'Optional')),
          ]),
          const SizedBox(height: 8),
          SwitchListTile(contentPadding: EdgeInsets.zero, title: const Text('Employees can request'), value: _allowEmployeeRequest, onChanged: submitting ? null : (v) => setState(() => _allowEmployeeRequest = v)),
          SwitchListTile(contentPadding: EdgeInsets.zero, title: const Text('Managers can request on behalf'), value: _allowManagerRequest, onChanged: submitting ? null : (v) => setState(() => _allowManagerRequest = v)),
          SwitchListTile(contentPadding: EdgeInsets.zero, title: const Text('HR can request on behalf'), value: _allowHrRequest, onChanged: submitting ? null : (v) => setState(() => _allowHrRequest = v)),
          SwitchListTile(contentPadding: EdgeInsets.zero, title: const Text('Reason required'), value: _reasonRequired, onChanged: submitting ? null : (v) => setState(() => _reasonRequired = v)),
          SwitchListTile(contentPadding: EdgeInsets.zero, title: const Text('Attachment required'), value: _attachmentRequired, onChanged: submitting ? null : (v) => setState(() => _attachmentRequired = v)),
          const SizedBox(height: 12),
          PrimaryButton(
            label: 'Create draft',
            loading: submitting,
            onPressed: () {
              if (_parseDate(_effectiveFrom.text) == null) return;
              _key.currentState?.submit({
                'effective_from': _effectiveFrom.text.trim(),
                'allow_employee_request': _allowEmployeeRequest,
                'allow_manager_request': _allowManagerRequest,
                'allow_hr_request': _allowHrRequest,
                'reason_required': _reasonRequired,
                'attachment_required': _attachmentRequired,
                if (_maxBackdatedDays.text.trim().isNotEmpty) 'max_backdated_days': int.tryParse(_maxBackdatedDays.text.trim()),
                if (_maxRequestsPerMonth.text.trim().isNotEmpty) 'max_requests_per_month': int.tryParse(_maxRequestsPerMonth.text.trim()),
              });
            },
          ),
        ],
      ),
    );
  }
}
