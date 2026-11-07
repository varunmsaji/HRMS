import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../core/api/api_error.dart';
import '../../../core/providers.dart';



/// The reason must be at least this long (API `ShiftDeleteRequest.reason`, web dialog).
const shiftDeleteMinReason = 10;

/// Opens the permanent shift delete (web `components/shift/shift-delete-dialog.tsx`). Resolves
/// true once deleted, false when the shift changed meanwhile (the caller reloads it), null when
/// cancelled. For [ResourceConfig.guardedDelete].
Future<bool?> openShiftDelete(BuildContext context, Map<String, dynamic> shift) =>
    Navigator.of(context).push<bool>(MaterialPageRoute(fullscreenDialog: true, builder: (_) => ShiftDeleteScreen(shift: shift)));

/// Permanent removal with web's layered safeguards. The server is authoritative and re-checks
/// everything when deleting; this screen makes the consequences explicit:
/// 1. a live check lists every blocker (Delete stays disabled while any exist),
/// 2. the shift's exact name must be typed back,
/// 3. a written reason (kept in the audit log) is required,
/// 4. an explicit "cannot be undone from the app" acknowledgement is required.
class ShiftDeleteScreen extends ConsumerStatefulWidget {
  const ShiftDeleteScreen({super.key, required this.shift});
  final Map<String, dynamic> shift;

  @override
  ConsumerState<ShiftDeleteScreen> createState() => _ShiftDeleteScreenState();
}

class _ShiftDeleteScreenState extends ConsumerState<ShiftDeleteScreen> {
  final _name = TextEditingController();
  final _reason = TextEditingController();
  Map<String, dynamic>? _check;
  String? _checkError;
  bool _acknowledged = false;
  bool _deleting = false;
  String? _nameError;
  String? _error;

  String get _shiftName => '${widget.shift['name']}';

  @override
  void initState() {
    super.initState();
    _loadCheck();
  }

  @override
  void dispose() {
    _name.dispose();
    _reason.dispose();
    super.dispose();
  }

  Future<void> _loadCheck() async {
    try {
      final check = await ref.read(apiClientProvider).get<Map<String, dynamic>>('/shifts/${widget.shift['id']}/deletion-check', parse: (d) => d as Map<String, dynamic>);
      if (mounted) setState(() => _check = check);
    } catch (e) {
      if (mounted) setState(() => _checkError = describeApiError(e));
    }
  }

  bool get _canDelete => _check?['can_delete'] == true;

  bool get _canSubmit => _canDelete && _name.text == _shiftName && _reason.text.trim().length >= shiftDeleteMinReason && _acknowledged && !_deleting;

  Future<void> _delete() async {
    setState(() {
      _deleting = true;
      _error = null;
      _nameError = null;
    });
    try {
      await ref.read(apiClientProvider).post<Object?>(
            '/shifts/${widget.shift['id']}/delete',
            body: {'confirm_name': _name.text, 'reason': _reason.text.trim(), 'acknowledge_irreversible': true},
            ifMatch: '${widget.shift['version']}',
            parse: (_) => null,
          );
      if (mounted) Navigator.of(context).pop(true);
      return;
    } on ApiError catch (e) {
      if (!mounted) return;
      if (e.status == 409 && e.code == 'STALE_RESOURCE') {
        Navigator.of(context).pop(false);
        return;
      }
      if (e.status == 409 && e.code == 'SHIFT_DELETE_BLOCKED') {
        // Something changed since the check (e.g. it was assigned meanwhile): show the new blockers.
        setState(() => _check = {
              'can_delete': false,
              'blockers': [for (final d in e.details) {'code': d.code, 'message': d.message}],
            });
      } else {
        setState(() {
          if (e.status == 422) _nameError = getFieldError(e.details, 'confirm_name');
          _error = describeApiError(e);
        });
      }
    } catch (e) {
      if (mounted) setState(() => _error = describeApiError(e));
    }
    if (mounted) setState(() => _deleting = false);
  }

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final scheme = theme.colorScheme;
    final check = _check;
    final published = (check?['published_version_count'] as num?)?.toInt() ?? 0;
    final drafts = (check?['draft_version_count'] as num?)?.toInt() ?? 0;
    return PopScope(
      canPop: !_deleting,
      child: Scaffold(
        appBar: AppBar(title: Text('Delete shift “$_shiftName”?')),
        body: ListView(padding: const EdgeInsets.all(16), children: [
          Text(
            'Deleting removes the shift and its schedule versions from every list and picker. It is only allowed for a shift '
            'that has never been used. Anything that has been assigned, rostered or used in attendance must be kept — deactivate it instead.',
            style: TextStyle(color: scheme.onSurfaceVariant),
          ),
          const SizedBox(height: 16),
          if (check == null && _checkError == null)
            const Row(children: [
              SizedBox(width: 18, height: 18, child: CircularProgressIndicator(strokeWidth: 2)),
              SizedBox(width: 10),
              Text('Checking whether this shift is in use…'),
            ]),
          if (_checkError != null) Text(_checkError!, style: TextStyle(color: scheme.error)),
          if (check != null && !_canDelete)
            Semantics(
              liveRegion: true,
              child: Container(
                padding: const EdgeInsets.all(12),
                decoration: BoxDecoration(color: scheme.errorContainer.withValues(alpha: 0.4), border: Border.all(color: scheme.error.withValues(alpha: 0.4)), borderRadius: BorderRadius.circular(8)),
                child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                  Text('This shift can’t be deleted yet', style: TextStyle(fontWeight: FontWeight.w600, color: scheme.error)),
                  const SizedBox(height: 6),
                  for (final b in (check['blockers'] as List? ?? const []))
                    Padding(padding: const EdgeInsets.only(top: 2), child: Text('• ${(b as Map)['message']}')),
                ]),
              ),
            ),
          if (_canDelete) ...[
            Container(
              padding: const EdgeInsets.all(12),
              decoration: BoxDecoration(color: scheme.surfaceContainerLow, border: Border.all(color: scheme.outlineVariant), borderRadius: BorderRadius.circular(8)),
              child: Text(
                'Not assigned to any employee, roster or attendance record. '
                '${published > 0 ? '$published published schedule version(s) and ' : ''}'
                '${drafts > 0 ? '$drafts draft(s) ' : ''}'
                'will be removed with it. The deletion is recorded in the audit log.',
                style: TextStyle(color: scheme.onSurfaceVariant),
              ),
            ),
            const SizedBox(height: 16),
            TextField(
              controller: _name,
              autocorrect: false,
              enableSuggestions: false,
              decoration: InputDecoration(labelText: 'Type “$_shiftName” to confirm', errorText: _nameError, border: const OutlineInputBorder()),
              onChanged: (_) => setState(() {}),
            ),
            const SizedBox(height: 12),
            TextField(
              controller: _reason,
              minLines: 2,
              maxLines: 4,
              maxLength: 500,
              decoration: const InputDecoration(labelText: 'Reason for deletion', helperText: 'At least $shiftDeleteMinReason characters. Saved in the audit log.', border: OutlineInputBorder()),
              onChanged: (_) => setState(() {}),
            ),
            CheckboxListTile(
              contentPadding: EdgeInsets.zero,
              controlAffinity: ListTileControlAffinity.leading,
              value: _acknowledged,
              onChanged: (v) => setState(() => _acknowledged = v ?? false),
              title: const Text('I understand this cannot be undone from the app.'),
            ),
          ],
          if (_error != null) Padding(padding: const EdgeInsets.only(top: 8), child: Text(_error!, style: TextStyle(color: scheme.error))),
          const SizedBox(height: 16),
          Row(mainAxisAlignment: MainAxisAlignment.end, children: [
            TextButton(onPressed: _deleting ? null : () => Navigator.of(context).pop(), child: const Text('Cancel')),
            const SizedBox(width: 8),
            FilledButton(
              style: FilledButton.styleFrom(backgroundColor: scheme.error, foregroundColor: scheme.onError),
              onPressed: _canSubmit ? _delete : null,
              child: Text(_deleting ? 'Deleting…' : 'Delete permanently'),
            ),
          ]),
        ]),
      ),
    );
  }
}
