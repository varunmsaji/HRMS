import 'dart:typed_data';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../core/api/api_error.dart';
import '../../../core/time.dart';
import '../../auth/state/auth_controller.dart';
import '../data/attendance_repository.dart';
import 'holiday_calendars_screen.dart' show attendanceRepositoryProvider;

/// HR side of face enrollment — mirrors `apps/web/src/components/attendance/face-enrollment-card.tsx`:
/// open a one-time self-enrollment window (the employee captures their face in the app), then
/// approve or reject what they submitted, or revoke an enrolled profile. Shown only to callers
/// holding `ATTENDANCE.FACE_ENROLLMENT_MANAGE`; the server still enforces scope.
class FaceEnrollmentAdminCard extends ConsumerStatefulWidget {
  const FaceEnrollmentAdminCard({super.key, required this.employeeId, required this.employeeLabel});

  final String employeeId;
  final String employeeLabel;

  @override
  ConsumerState<FaceEnrollmentAdminCard> createState() => _FaceEnrollmentAdminCardState();
}

class _FaceEnrollmentAdminCardState extends ConsumerState<FaceEnrollmentAdminCard> {
  bool _loading = true;
  bool _busy = false;
  String? _loadError;
  Map<String, dynamic>? _profile;
  Map<String, dynamic>? _window;
  Uint8List? _reviewPhoto;

  AttendanceRepository get _repo => ref.read(attendanceRepositoryProvider);
  String get _tz => ref.read(authControllerProvider).user?.companyTimezone ?? 'Asia/Kolkata';

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    setState(() {
      _loading = true;
      _loadError = null;
      _reviewPhoto = null;
    });
    try {
      final status = await _repo.getFaceProfileStatus(widget.employeeId);
      final profile = status['profile'] as Map<String, dynamic>?;
      final window = status['open_window'] as Map<String, dynamic>?;
      if (mounted) {
        setState(() {
          _profile = profile;
          _window = window;
        });
      }
      if (profile?['status'] == 'PENDING_APPROVAL' && profile?['has_review_photo'] == true) {
        try {
          final file = await _repo.downloadFaceReviewPhoto(widget.employeeId);
          if (mounted) setState(() => _reviewPhoto = Uint8List.fromList(file.bytes));
        } catch (_) {}
      }
    } catch (e) {
      if (mounted) setState(() => _loadError = e is ApiError ? e.message : 'Something went wrong.');
    } finally {
      if (mounted) setState(() => _loading = false);
    }
  }

  Future<bool> _act(Future<void> Function() run, String success, String failure) async {
    setState(() => _busy = true);
    try {
      await run();
      if (mounted) ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(success)));
      await _load();
      return true;
    } catch (e) {
      if (mounted) ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text('$failure ${e is ApiError ? e.message : ''}'.trim())));
      return false;
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  Future<void> _reject() async {
    final note = TextEditingController();
    final ok = await showDialog<bool>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: const Text('Reject face enrollment?'),
        content: Column(mainAxisSize: MainAxisSize.min, crossAxisAlignment: CrossAxisAlignment.start, children: [
          Text('The submitted face is deleted from the verification service. You can open enrollment again for ${widget.employeeLabel} afterwards.'),
          const SizedBox(height: 12),
          TextField(controller: note, maxLength: 500, maxLines: 3, decoration: const InputDecoration(labelText: 'Reason (shown to the employee, optional)')),
        ]),
        actions: [
          TextButton(onPressed: () => Navigator.of(ctx).pop(false), child: const Text('Cancel')),
          FilledButton(style: FilledButton.styleFrom(backgroundColor: Theme.of(ctx).colorScheme.error), onPressed: () => Navigator.of(ctx).pop(true), child: const Text('Reject')),
        ],
      ),
    );
    if (ok == true) {
      await _act(() => _repo.rejectFaceProfile(widget.employeeId, note: note.text.trim()), 'Face profile rejected.', 'Could not reject.');
    }
  }

  Future<void> _revoke() async {
    final ok = await showDialog<bool>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: const Text('Revoke face profile?'),
        content: Text('${widget.employeeLabel} will no longer be able to punch with their face until they enrol again. The face record is deleted from the verification service.'),
        actions: [
          TextButton(onPressed: () => Navigator.of(ctx).pop(false), child: const Text('Cancel')),
          FilledButton(style: FilledButton.styleFrom(backgroundColor: Theme.of(ctx).colorScheme.error), onPressed: () => Navigator.of(ctx).pop(true), child: const Text('Revoke')),
        ],
      ),
    );
    if (ok == true) await _act(() => _repo.revokeFaceProfile(widget.employeeId), 'Face profile revoked.', 'Could not revoke.');
  }

  @override
  Widget build(BuildContext context) {
    final scheme = Theme.of(context).colorScheme;
    final profile = _profile;
    final pending = profile?['status'] == 'PENDING_APPROVAL';
    String badge;
    Color badgeColor;
    String description;
    List<Widget> actions;
    String? at(String key) => profile?[key] as String?;

    if (profile?['status'] == 'ENROLLED') {
      badge = 'Enrolled';
      badgeColor = Colors.green;
      description = 'Approved ${formatDateTime(at('reviewed_at') ?? at('enrolled_at'), _tz)} · ${profile?['reference_photo_count']} reference angles';
      actions = [OutlinedButton(onPressed: _busy ? null : _revoke, child: const Text('Revoke'))];
    } else if (pending) {
      badge = 'Awaiting approval';
      badgeColor = Colors.orange;
      description = 'Submitted ${formatDateTime(at('enrolled_at'), _tz)} from the mobile app. Check that this is ${widget.employeeLabel} before approving.';
      actions = [
        OutlinedButton(onPressed: _busy ? null : _reject, child: const Text('Reject')),
        FilledButton(onPressed: _busy ? null : () => _act(() => _repo.approveFaceProfile(widget.employeeId), 'Face profile approved.', 'Could not approve.'), child: const Text('Approve')),
      ];
    } else if (_window != null) {
      badge = 'Enrollment open';
      badgeColor = Colors.blue;
      description = '${widget.employeeLabel} can set up face attendance in the mobile app until ${formatDateTime(_window!['expires_at'] as String?, _tz)}. The link closes once they finish.';
      actions = [OutlinedButton(onPressed: _busy ? null : () => _act(() => _repo.cancelFaceEnrollmentWindow(widget.employeeId), 'Face enrollment cancelled.', 'Could not cancel.'), child: const Text('Cancel enrollment'))];
    } else {
      if (profile?['status'] == 'REJECTED') {
        badge = 'Rejected';
        badgeColor = scheme.error;
        description = 'Rejected ${formatDateTime(at('reviewed_at'), _tz)}. Open enrollment again to let them retry.${at('review_note') != null ? ' Reason: ${at('review_note')}' : ''}';
      } else if (profile?['status'] == 'REVOKED') {
        badge = 'Revoked';
        badgeColor = Colors.orange;
        description = 'Revoked ${formatDateTime(at('revoked_at'), _tz)}. The face record was deleted from the verification service.';
      } else {
        badge = 'Not enrolled';
        badgeColor = scheme.onSurfaceVariant;
        description = 'Open a one-time enrollment so ${widget.employeeLabel} can register their face from the mobile app.';
      }
      actions = [FilledButton(onPressed: _busy ? null : () => _act(() => _repo.openFaceEnrollmentWindow(widget.employeeId), 'Face enrollment opened.', 'Could not open face enrollment.'), child: const Text('Open face enrollment'))];
    }

    return Container(
      margin: const EdgeInsets.only(bottom: 12),
      padding: const EdgeInsets.all(14),
      decoration: BoxDecoration(border: Border.all(color: scheme.outlineVariant), borderRadius: BorderRadius.circular(12)),
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Row(children: [
          const Icon(Icons.face_retouching_natural, size: 20),
          const SizedBox(width: 8),
          Text('Face attendance', style: Theme.of(context).textTheme.titleSmall),
          const SizedBox(width: 8),
          if (!_loading && _loadError == null)
            Container(
              padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 2),
              decoration: BoxDecoration(color: badgeColor.withValues(alpha: 0.12), borderRadius: BorderRadius.circular(4)),
              child: Text(badge, style: TextStyle(color: badgeColor, fontSize: 11, fontWeight: FontWeight.w600)),
            ),
        ]),
        const SizedBox(height: 6),
        Text(_loading ? 'Loading…' : (_loadError ?? description), style: TextStyle(color: scheme.onSurfaceVariant)),
        if (!_loading && _loadError == null && pending) ...[
          const SizedBox(height: 8),
          if (_reviewPhoto != null)
            ClipRRect(borderRadius: BorderRadius.circular(8), child: Image.memory(_reviewPhoto!, height: 220, fit: BoxFit.contain))
          else
            Text('Loading submitted photo…', style: TextStyle(color: scheme.onSurfaceVariant)),
        ],
        if (!_loading && _loadError == null) ...[
          const SizedBox(height: 10),
          Wrap(spacing: 8, runSpacing: 8, children: actions),
        ],
      ]),
    );
  }
}
