import 'package:dio/dio.dart';
import 'package:file_picker/file_picker.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:url_launcher/url_launcher.dart';

import '../../../core/api/api_error.dart';
import '../../../core/auth/permissions.dart';
import '../../../core/providers.dart';
import '../../auth/state/auth_controller.dart';
import '../../../core/widgets/ui.dart';

/// Mirrors `EMPLOYEE_DOCUMENT_TYPES` / `_LABELS` in `apps/web/src/lib/employee/types.ts`.
const employeeDocumentTypeLabels = {
  'PHOTO': 'Photo',
  'PAN': 'PAN card',
  'AADHAAR': 'Aadhaar card',
  'ADDRESS_PROOF': 'Address proof',
  'EDUCATION_CERTIFICATE': 'Education certificate',
  'PREVIOUS_EMPLOYMENT_PROOF': 'Previous employment proof',
  'BANK_PROOF': 'Bank proof',
  'OTHER': 'Other',
};

class EmployeeDocument {
  EmployeeDocument.fromJson(Map<String, dynamic> j)
      : id = j['id'] as String,
        documentType = j['document_type'] as String? ?? 'OTHER',
        filename = j['original_filename'] as String? ?? 'document',
        sizeBytes = (j['size_bytes'] as num?)?.toInt() ?? 0,
        status = j['status'] as String? ?? 'PENDING',
        rejectionReason = j['rejection_reason'] as String?,
        downloadUrl = j['download_url'] as String?;

  final String id;
  final String documentType;
  final String filename;
  final int sizeBytes;
  final String status;
  final String? rejectionReason;
  final String? downloadUrl;

  EmployeeDocument withUrl(String? url) => EmployeeDocument.fromJson({
        'id': id,
        'document_type': documentType,
        'original_filename': filename,
        'size_bytes': sizeBytes,
        'status': status,
        'rejection_reason': rejectionReason,
        'download_url': url,
      });
}

String _formatBytes(int b) {
  if (b < 1024) return '$b B';
  if (b < 1024 * 1024) return '${(b / 1024).toStringAsFixed(1)} KB';
  return '${(b / (1024 * 1024)).toStringAsFixed(1)} MB';
}

/// The Documents tab of an employee record — mirrors
/// `apps/web/src/components/employee/document-panel.tsx`: list (SELF-scoped server-side), open via
/// the presigned `download_url`, and — with `EMPLOYEE.UPDATE_SENSITIVE` — upload, verify, reject
/// (with a required reason) and remove.
class EmployeeDocumentsPanel extends ConsumerStatefulWidget {
  const EmployeeDocumentsPanel({super.key, required this.employeeId});
  final String employeeId;

  @override
  ConsumerState<EmployeeDocumentsPanel> createState() => _EmployeeDocumentsPanelState();
}

class _EmployeeDocumentsPanelState extends ConsumerState<EmployeeDocumentsPanel> {
  bool _loading = true;
  bool _busy = false;
  ApiError? _error;
  List<EmployeeDocument> _docs = const [];

  String get _base => '/employees/${widget.employeeId}/documents';

  @override
  void initState() {
    super.initState();
    _load();
  }

  ApiError _asError(Object e) => e is ApiError ? e : ApiError(status: 0, code: 'UNKNOWN_ERROR', message: 'Something went wrong.');

  void _toast(String m) => ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(m)));

  Future<void> _load() async {
    setState(() {
      _loading = true;
      _error = null;
    });
    try {
      final list = await ref.read(apiClientProvider).get<List<EmployeeDocument>>(
            _base,
            parse: (d) => [for (final x in d as List) EmployeeDocument.fromJson(x as Map<String, dynamic>)],
          );
      if (mounted) setState(() => _docs = list);
    } catch (e) {
      if (mounted) setState(() => _error = _asError(e));
    } finally {
      if (mounted) setState(() => _loading = false);
    }
  }

  Future<void> _guard(Future<void> Function() action, String success, String failure) async {
    setState(() => _busy = true);
    try {
      await action();
      if (mounted) _toast(success);
    } catch (e) {
      final err = _asError(e);
      if (mounted) _toast(err.status == 403 ? "You don't have permission to do that." : '$failure: ${err.message}');
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  void _replace(EmployeeDocument updated, EmployeeDocument previous) {
    setState(() => _docs = [for (final d in _docs) d.id == updated.id ? updated.withUrl(previous.downloadUrl) : d]);
  }

  Future<void> _open(EmployeeDocument d) async {
    final url = d.downloadUrl;
    if (url == null) return;
    final ok = await launchUrl(Uri.parse(url), mode: LaunchMode.externalApplication);
    if (!ok && mounted) _toast('Could not open the document.');
  }

  Future<void> _upload() async {
    String? type;
    final chosen = await showDialog<String>(
      context: context,
      builder: (ctx) => StatefulBuilder(
        builder: (ctx, setLocal) => AlertDialog(
          title: const Text('Upload document'),
          content: DropdownButtonFormField<String>(
            value: type,
            decoration: const InputDecoration(labelText: 'Document type'),
            items: [for (final e in employeeDocumentTypeLabels.entries) DropdownMenuItem(value: e.key, child: Text(e.value))],
            onChanged: (v) => setLocal(() => type = v),
          ),
          actions: [
            TextButton(onPressed: () => Navigator.of(ctx).pop(), child: const Text('Cancel')),
            FilledButton(onPressed: type == null ? null : () => Navigator.of(ctx).pop(type), child: const Text('Choose file')),
          ],
        ),
      ),
    );
    if (chosen == null) return;
    final picked = await FilePicker.pickFiles(type: FileType.custom, allowedExtensions: const ['pdf', 'jpg', 'jpeg', 'png']);
    final file = picked?.files.single;
    if (file == null || file.path == null) return;
    await _guard(() async {
      await ref.read(apiClientProvider).postMultipart<Object?>(
            _base,
            buildForm: () => FormData.fromMap({
              'document_type': chosen,
              'file': MultipartFile.fromFileSync(file.path!, filename: file.name),
            }),
            parse: (_) => null,
          );
      await _load();
    }, 'Document uploaded.', 'Could not upload document');
  }

  Future<void> _verify(EmployeeDocument d) => _guard(() async {
        final updated = await ref.read(apiClientProvider).post<EmployeeDocument>(
              '$_base/${d.id}/review',
              body: {'status': 'VERIFIED'},
              parse: (j) => EmployeeDocument.fromJson(j as Map<String, dynamic>),
            );
        _replace(updated, d);
      }, 'Document verified.', 'Could not verify document');

  Future<void> _reject(EmployeeDocument d) async {
    final controller = TextEditingController();
    final reason = await showDialog<String>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: const Text('Reject document'),
        content: TextField(controller: controller, maxLines: 3, decoration: const InputDecoration(labelText: 'Rejection reason')),
        actions: [
          TextButton(onPressed: () => Navigator.of(ctx).pop(), child: const Text('Cancel')),
          FilledButton(
            onPressed: () {
              if (controller.text.trim().isEmpty) return;
              Navigator.of(ctx).pop(controller.text.trim());
            },
            child: const Text('Reject'),
          ),
        ],
      ),
    );
    controller.dispose();
    if (reason == null) return;
    await _guard(() async {
      final updated = await ref.read(apiClientProvider).post<EmployeeDocument>(
            '$_base/${d.id}/review',
            body: {'status': 'REJECTED', 'rejection_reason': reason},
            parse: (j) => EmployeeDocument.fromJson(j as Map<String, dynamic>),
          );
      _replace(updated, d);
    }, 'Document rejected.', 'Could not reject document');
  }

  Future<void> _remove(EmployeeDocument d) async {
    final ok = await showDialog<bool>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: const Text('Remove document?'),
        content: Text(d.filename),
        actions: [
          TextButton(onPressed: () => Navigator.of(ctx).pop(false), child: const Text('Cancel')),
          FilledButton(onPressed: () => Navigator.of(ctx).pop(true), child: const Text('Remove')),
        ],
      ),
    );
    if (ok != true) return;
    await _guard(() async {
      await ref.read(apiClientProvider).delete<Object?>('$_base/${d.id}', parse: (_) => null);
      setState(() => _docs = [for (final x in _docs) if (x.id != d.id) x]);
    }, 'Document removed.', 'Could not remove document');
  }

  Widget _statusChip(BuildContext context, String status) {
    final scheme = Theme.of(context).colorScheme;
    final (label, color) = switch (status) {
      'VERIFIED' => ('Verified', Colors.green.shade700),
      'REJECTED' => ('Rejected', scheme.error),
      _ => ('Pending', scheme.onSurfaceVariant),
    };
    return Text(label, style: TextStyle(color: color, fontWeight: FontWeight.w600, fontSize: 12));
  }

  @override
  Widget build(BuildContext context) {
    final permissions = ref.watch(authControllerProvider).user?.permissions ?? const <String>[];
    final canManage = permissions.contains(employeeUpdateSensitive);
    if (_loading) return const ListSkeleton(count: 3);
    if (_error != null) return StateMessage(icon: Icons.error_outline_rounded, tone: Tone.danger, title: 'Something went wrong', message: _error!.status == 403 ? "You do not have permission to view this employee's documents." : _error!.message, actionLabel: 'Retry', onAction: _load);
    return RefreshIndicator(
      onRefresh: _load,
      child: ListView(
        padding: const EdgeInsets.all(16),
        children: [
          if (canManage)
            Align(
              alignment: Alignment.centerRight,
              child: FilledButton.icon(
                onPressed: _busy ? null : _upload,
                icon: const Icon(Icons.upload_file),
                label: const Text('Upload'),
              ),
            ),
          if (_docs.isEmpty)
            const SizedBox(height: 280, child: StateMessage(icon: Icons.description_outlined, title: 'No documents yet', message: 'No documents on record yet.')),
          for (final d in _docs)
            Padding(
              padding: const EdgeInsets.only(top: 10),
              child: AppCard(
                child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                  Row(children: [
                    const IconBadge(icon: Icons.description_outlined, size: 36),
                    const SizedBox(width: 10),
                    Expanded(child: Text(employeeDocumentTypeLabels[d.documentType] ?? d.documentType, style: const TextStyle(fontWeight: FontWeight.w700))),
                    _statusChip(context, d.status),
                  ]),
                  const SizedBox(height: 4),
                  InkWell(
                    onTap: d.downloadUrl == null ? null : () => _open(d),
                    child: Text('${d.filename} · ${_formatBytes(d.sizeBytes)}', style: const TextStyle(decoration: TextDecoration.underline)),
                  ),
                  if (d.status == 'REJECTED' && d.rejectionReason != null)
                    Padding(
                      padding: const EdgeInsets.only(top: 4),
                      child: Text(d.rejectionReason!, style: TextStyle(fontSize: 12, color: Theme.of(context).colorScheme.onSurfaceVariant)),
                    ),
                  if (canManage)
                    Wrap(spacing: 8, children: [
                      TextButton(onPressed: _busy ? null : () => _verify(d), child: const Text('Verify')),
                      TextButton(onPressed: _busy ? null : () => _reject(d), child: const Text('Reject')),
                      TextButton(onPressed: _busy ? null : () => _remove(d), child: const Text('Remove')),
                    ]),
                ]),
              ),
            ),
        ],
      ),
    );
  }
}
