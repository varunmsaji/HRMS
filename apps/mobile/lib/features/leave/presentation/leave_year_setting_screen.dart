import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../core/api/api_error.dart';
import '../../auth/presentation/widgets/auth_form_field.dart';
import '../data/leave_repository.dart' show leaveRepositoryProvider;

const _leaveYearTypes = ['CALENDAR', 'FINANCIAL', 'CUSTOM', 'ANNIVERSARY'];

/// `GET/PUT /leave-year-setting` — a singleton, not a list. `start_month`/
/// `start_day` only apply (and are required) when type is CUSTOM.
class LeaveYearSettingScreen extends ConsumerStatefulWidget {
  const LeaveYearSettingScreen({super.key});

  @override
  ConsumerState<LeaveYearSettingScreen> createState() => _LeaveYearSettingScreenState();
}

class _LeaveYearSettingScreenState extends ConsumerState<LeaveYearSettingScreen> {
  bool _loading = true;
  String _leaveYearType = 'CALENDAR';
  final _startMonth = TextEditingController();
  final _startDay = TextEditingController();
  bool _submitting = false;
  String? _message;

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    try {
      final setting = await ref.read(leaveRepositoryProvider).getLeaveYearSetting();
      if (mounted) {
        setState(() {
          _leaveYearType = setting.leaveYearType;
          _startMonth.text = setting.startMonth?.toString() ?? '';
          _startDay.text = setting.startDay?.toString() ?? '';
        });
      }
    } catch (_) {
      // Not configured yet — leave the CALENDAR default.
    } finally {
      if (mounted) setState(() => _loading = false);
    }
  }

  Future<void> _save() async {
    setState(() {
      _submitting = true;
      _message = null;
    });
    try {
      await ref.read(leaveRepositoryProvider).putLeaveYearSetting({
        'leave_year_type': _leaveYearType,
        if (_leaveYearType == 'CUSTOM') 'start_month': int.tryParse(_startMonth.text.trim()),
        if (_leaveYearType == 'CUSTOM') 'start_day': int.tryParse(_startDay.text.trim()),
      });
      if (mounted) setState(() => _message = 'Saved.');
    } catch (error) {
      setState(() => _message = error is ApiError ? error.message : 'Something went wrong.');
    } finally {
      if (mounted) setState(() => _submitting = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('Leave Year')),
      body: _loading
          ? const Center(child: CircularProgressIndicator())
          : ListView(
              padding: const EdgeInsets.all(16),
              children: [
                if (_message != null) ...[InlineAlert(message: _message!), const SizedBox(height: 16)],
                AuthFormField(
                  label: 'Leave year type',
                  child: DropdownButtonFormField<String>(
                    value: _leaveYearType,
                    items: [for (final t in _leaveYearTypes) DropdownMenuItem(value: t, child: Text(t))],
                    onChanged: _submitting ? null : (v) => setState(() => _leaveYearType = v ?? _leaveYearType),
                  ),
                ),
                if (_leaveYearType == 'CUSTOM') ...[
                  const SizedBox(height: 16),
                  Row(children: [
                    Expanded(child: AuthFormField(label: 'Start month', required: true, child: TextField(controller: _startMonth, keyboardType: TextInputType.number, enabled: !_submitting))),
                    const SizedBox(width: 12),
                    Expanded(child: AuthFormField(label: 'Start day', required: true, child: TextField(controller: _startDay, keyboardType: TextInputType.number, enabled: !_submitting))),
                  ]),
                ] else
                  Padding(
                    padding: const EdgeInsets.only(top: 8),
                    child: Text(
                      _leaveYearType == 'ANNIVERSARY'
                          ? 'Each employee\'s leave year starts on their date of joining — no company-wide date.'
                          : 'Uses a fixed built-in start for this type.',
                      style: Theme.of(context).textTheme.bodySmall,
                    ),
                  ),
                const SizedBox(height: 20),
                PrimaryButton(label: 'Save', loading: _submitting, onPressed: _save),
              ],
            ),
    );
  }
}
