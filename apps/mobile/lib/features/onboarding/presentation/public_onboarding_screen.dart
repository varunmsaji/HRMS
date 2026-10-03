import 'package:file_picker/file_picker.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../core/api/api_error.dart';
import '../../../core/providers.dart';
import '../data/public_onboarding_repository.dart';
import '../domain/onboarding_form_spec.dart';
import 'onboarding_record_form.dart';

final publicOnboardingRepositoryProvider = Provider<PublicOnboardingRepository>(
  (ref) => PublicOnboardingRepository(ref.watch(apiClientProvider)),
);

class _Row {
  _Row(this.id, this.values);
  final int id;
  final Map<String, dynamic> values;
}

/// Candidate-facing onboarding wizard — mirrors `apps/web/src/app/onboarding/[token]/page.tsx`:
/// welcome → nine data sections → documents → review & submit, driven by the invite token.
class PublicOnboardingScreen extends ConsumerStatefulWidget {
  const PublicOnboardingScreen({super.key, required this.token});

  final String token;

  @override
  ConsumerState<PublicOnboardingScreen> createState() => _PublicOnboardingScreenState();
}

class _PublicOnboardingScreenState extends ConsumerState<PublicOnboardingScreen> {
  // step 0 = welcome, 1..n = sections, n+1 = documents, n+2 = review
  int _step = 0;
  bool _loading = true;
  bool _saving = false;
  bool _submitted = false;
  ApiError? _loadError;
  PublicOnboardingCase? _case;
  List<OnboardingDocument> _documents = const [];
  final _rows = <String, List<_Row>>{};
  Map<String, Map<String, String>> _errors = {};
  String? _sectionError;
  int _rowSeq = 0;

  int get _sectionCount => onboardingSections.length;
  int get _documentsStep => _sectionCount + 1;
  int get _reviewStep => _sectionCount + 2;
  int get _lastStep => _reviewStep;

  PublicOnboardingRepository get _repo => ref.read(publicOnboardingRepositoryProvider);

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    setState(() {
      _loading = true;
      _loadError = null;
    });
    try {
      final data = await _repo.getCase(widget.token);
      List<OnboardingDocument> docs;
      try {
        docs = await _repo.listDocuments(widget.token);
      } catch (_) {
        docs = const [];
      }
      if (!mounted) return;
      setState(() {
        _case = data;
        _documents = docs;
        _hydrate(data);
      });
    } catch (e) {
      if (mounted) setState(() => _loadError = e is ApiError ? e : ApiError(status: 0, code: 'UNKNOWN_ERROR', message: 'Something went wrong.'));
    } finally {
      if (mounted) setState(() => _loading = false);
    }
  }

  void _hydrate(PublicOnboardingCase data) {
    for (final spec in onboardingSections) {
      final wire = data.sections[spec.name] ?? const {};
      if (spec.repeatable) {
        final items = (wire['items'] as List?) ?? const [];
        _rows[spec.name] = [for (final i in items) _Row(_rowSeq++, rowFromWire(spec, Map<String, dynamic>.from(i as Map)))];
      } else {
        _rows[spec.name] = [_Row(_rowSeq++, rowFromWire(spec, Map<String, dynamic>.from(wire)))];
      }
    }
  }

  bool _isLocked(String section) => _case?.reviewFor(section)?.status == 'VERIFIED';

  void _toast(String message) => ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(message)));

  String _errMessage(Object e) => e is ApiError ? e.message : 'Something went wrong.';

  /// Validates and PATCHes the section at [_step]; returns whether it's safe to move on.
  Future<bool> _saveCurrent() async {
    final spec = onboardingSections[_step - 1];
    if (_isLocked(spec.name)) return true;
    final rows = _rows[spec.name]!;
    final errors = <String, Map<String, String>>{};
    for (final r in rows) {
      final e = validateRow(spec, r.values);
      if (e.isNotEmpty) errors['${r.id}'] = e;
    }
    String? sectionError;
    if (errors.isEmpty && spec.name == 'nominee_info') {
      sectionError = validateNomineeTotals([for (final r in rows) r.values]);
    }
    setState(() {
      _errors = errors;
      _sectionError = sectionError ?? (errors.isNotEmpty ? 'Please fix the highlighted fields.' : null);
    });
    if (errors.isNotEmpty || sectionError != null) return false;

    final payload = spec.repeatable
        ? {'items': [for (final r in rows) rowToPayload(spec, r.values)]}
        : rowToPayload(spec, rows.first.values);
    setState(() => _saving = true);
    try {
      final updated = await _repo.saveSection(widget.token, spec.name, payload);
      if (mounted) setState(() => _case = updated);
      return true;
    } catch (e) {
      _toast('Could not save: ${_errMessage(e)}');
      return false;
    } finally {
      if (mounted) setState(() => _saving = false);
    }
  }

  void _goTo(int step) => setState(() {
        _step = step;
        _errors = {};
        _sectionError = null;
      });

  Future<void> _next() async {
    if (_step >= 1 && _step <= _sectionCount) {
      if (!await _saveCurrent()) return;
    }
    if (_step < _lastStep) _goTo(_step + 1);
  }

  Future<void> _submit() async {
    setState(() => _saving = true);
    try {
      final updated = await _repo.submit(widget.token);
      if (mounted) {
        setState(() {
          _case = updated;
          _submitted = true;
        });
      }
    } catch (e) {
      _toast('Could not submit: ${_errMessage(e)}');
    } finally {
      if (mounted) setState(() => _saving = false);
    }
  }

  // ---- build ------------------------------------------------------------------------------------

  @override
  Widget build(BuildContext context) {
    if (_loading) return const Scaffold(body: Center(child: CircularProgressIndicator()));
    if (_loadError != null || _case == null) {
      return _Terminal(
        icon: Icons.warning_amber_rounded,
        title: 'Link not available',
        message: _loadError?.status == 404
            ? 'This onboarding link is invalid or has expired. Please contact HR for a new one.'
            : (_loadError?.message ?? 'Something went wrong.'),
        onRetry: _loadError?.status == 404 ? null : _load,
      );
    }
    final c = _case!;
    if (_submitted || c.status == 'SUBMITTED' || !c.writable) {
      final activated = c.status == 'ACTIVATED';
      final submitted = _submitted || c.status == 'SUBMITTED';
      return _Terminal(
        icon: submitted || activated ? Icons.check_circle_outline : Icons.info_outline,
        title: activated
            ? "You're all set, ${c.candidateFirstName}!"
            : submitted
                ? 'Thanks, ${c.candidateFirstName}!'
                : 'This link is no longer active',
        message: activated
            ? 'Your onboarding is complete and your employee record has been created. Contact HR if anything needs updating.'
            : submitted
                ? 'Your details have been submitted for review. HR will be in touch if anything needs a correction.'
                : 'Current status: ${c.status}. Please contact HR if you have questions.',
      );
    }

    final title = _step == 0
        ? 'Welcome'
        : _step <= _sectionCount
            ? onboardingSections[_step - 1].label
            : _step == _documentsStep
                ? 'Document Upload'
                : 'Review & Submit';
    return Scaffold(
      appBar: AppBar(title: Text(title)),
      body: SafeArea(
        child: Column(
          children: [
            LinearProgressIndicator(value: _step / _lastStep),
            Padding(
              padding: const EdgeInsets.fromLTRB(16, 8, 16, 0),
              child: Align(alignment: Alignment.centerLeft, child: Text('Step ${_step + 1} of ${_lastStep + 1}', style: Theme.of(context).textTheme.bodySmall)),
            ),
            Expanded(child: _body(c)),
            _footer(),
          ],
        ),
      ),
    );
  }

  Widget _body(PublicOnboardingCase c) {
    if (_step == 0) {
      return ListView(padding: const EdgeInsets.all(20), children: [
        Text('Hi ${c.candidateFirstName}, welcome aboard!', style: Theme.of(context).textTheme.headlineMedium),
        const SizedBox(height: 12),
        Text('Your proposed joining date is ${c.proposedJoiningDate}. This takes about 10 minutes — fill in each section, upload your documents, then submit for HR to review. Your progress is saved as you go.'),
      ]);
    }
    if (_step <= _sectionCount) return _sectionStep(onboardingSections[_step - 1], c);
    if (_step == _documentsStep) {
      return _DocumentsStep(
        token: widget.token,
        documents: _documents,
        onChanged: (docs) => setState(() => _documents = docs),
      );
    }
    return _reviewBody();
  }

  Widget _sectionStep(OnboardingSectionSpec spec, PublicOnboardingCase c) {
    final review = c.reviewFor(spec.name);
    final locked = review?.status == 'VERIFIED';
    final rows = _rows[spec.name]!;
    final scheme = Theme.of(context).colorScheme;
    return ListView(
      padding: const EdgeInsets.all(16),
      children: [
        Text(spec.description, style: TextStyle(color: scheme.onSurfaceVariant)),
        const SizedBox(height: 12),
        if (locked) _Banner(color: Colors.green, icon: Icons.verified_outlined, text: 'This section has been verified by HR — no changes needed.'),
        if (review?.status == 'REJECTED')
          _Banner(
            color: scheme.error,
            icon: Icons.warning_amber_rounded,
            text: 'HR requested changes to this section${review?.rejectionReason != null ? ': ${review!.rejectionReason}' : '.'}',
          ),
        if (_sectionError != null) _Banner(color: scheme.error, icon: Icons.error_outline, text: _sectionError!),
        for (var i = 0; i < rows.length; i++) ...[
          Container(
            margin: const EdgeInsets.only(bottom: 16),
            padding: spec.repeatable ? const EdgeInsets.all(12) : EdgeInsets.zero,
            decoration: spec.repeatable ? BoxDecoration(border: Border.all(color: scheme.outlineVariant), borderRadius: BorderRadius.circular(12)) : null,
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.stretch,
              children: [
                if (spec.repeatable)
                  Row(
                    children: [
                      Expanded(child: Text('${spec.itemNoun[0].toUpperCase()}${spec.itemNoun.substring(1)} ${i + 1}', style: Theme.of(context).textTheme.titleSmall)),
                      if (!locked)
                        IconButton(
                          tooltip: 'Remove',
                          icon: const Icon(Icons.delete_outline),
                          onPressed: () => setState(() => rows.removeAt(i)),
                        ),
                    ],
                  ),
                OnboardingRecordForm(
                  key: ValueKey('${spec.name}-${rows[i].id}'),
                  spec: spec,
                  values: rows[i].values,
                  errors: _errors['${rows[i].id}'] ?? const {},
                  readOnly: locked,
                  onChanged: () => setState(() {}),
                ),
              ],
            ),
          ),
        ],
        if (spec.repeatable && !locked)
          OutlinedButton.icon(
            icon: const Icon(Icons.add),
            label: Text('Add ${spec.itemNoun}'),
            onPressed: () => setState(() => rows.add(_Row(_rowSeq++, rowFromWire(spec, const {})))),
          ),
        if (spec.repeatable && rows.isEmpty) Padding(padding: const EdgeInsets.only(top: 8), child: Text('Nothing added — you can skip this step if it does not apply.', style: TextStyle(color: scheme.onSurfaceVariant))),
      ],
    );
  }

  String _summary(OnboardingSectionSpec spec) {
    final rows = _rows[spec.name]!;
    if (spec.repeatable) return rows.isEmpty ? 'None added' : '${rows.length} ${spec.itemNoun}${rows.length == 1 ? '' : 's'}';
    final filled = rowToPayload(spec, rows.first.values).values.where((v) => v != null && v != false && v != '').length;
    return filled == 0 ? 'Not filled in yet' : '$filled field${filled == 1 ? '' : 's'} filled';
  }

  Widget _reviewBody() {
    return ListView(
      padding: const EdgeInsets.all(16),
      children: [
        const Text('Check everything below before you submit. Once submitted, HR will verify each section — you will be notified if anything needs a correction.'),
        const SizedBox(height: 12),
        for (var i = 0; i < onboardingSections.length; i++)
          Card(
            child: ListTile(
              title: Text(onboardingSections[i].label),
              subtitle: Text(_summary(onboardingSections[i])),
              trailing: TextButton(onPressed: () => _goTo(i + 1), child: const Text('Edit')),
            ),
          ),
        Card(
          child: ListTile(
            title: const Text('Documents'),
            subtitle: Text(_documents.isEmpty ? 'None uploaded' : '${_documents.length} uploaded'),
            trailing: TextButton(onPressed: () => _goTo(_documentsStep), child: const Text('Edit')),
          ),
        ),
      ],
    );
  }

  Widget _footer() {
    final last = _step == _lastStep;
    return Padding(
      padding: const EdgeInsets.all(16),
      child: Row(
        children: [
          if (_step > 0) OutlinedButton(onPressed: _saving ? null : () => _goTo(_step - 1), child: const Text('Back')),
          const Spacer(),
          FilledButton(
            onPressed: _saving ? null : (last ? _submit : _next),
            child: Text(_saving ? (last ? 'Submitting…' : 'Saving…') : (last ? 'Submit' : (_step == 0 ? 'Get started' : 'Save & continue'))),
          ),
        ],
      ),
    );
  }
}

class _Banner extends StatelessWidget {
  const _Banner({required this.color, required this.icon, required this.text});
  final Color color;
  final IconData icon;
  final String text;

  @override
  Widget build(BuildContext context) => Container(
        margin: const EdgeInsets.only(bottom: 12),
        padding: const EdgeInsets.all(12),
        decoration: BoxDecoration(color: color.withValues(alpha: 0.08), border: Border.all(color: color), borderRadius: BorderRadius.circular(8)),
        child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Icon(icon, size: 18, color: color),
          const SizedBox(width: 8),
          Expanded(child: Text(text)),
        ]),
      );
}

class _Terminal extends StatelessWidget {
  const _Terminal({required this.icon, required this.title, required this.message, this.onRetry});
  final IconData icon;
  final String title;
  final String message;
  final VoidCallback? onRetry;

  @override
  Widget build(BuildContext context) => Scaffold(
        body: Center(
          child: Padding(
            padding: const EdgeInsets.all(24),
            child: Column(mainAxisSize: MainAxisSize.min, children: [
              Icon(icon, size: 48),
              const SizedBox(height: 16),
              Text(title, style: Theme.of(context).textTheme.headlineSmall, textAlign: TextAlign.center),
              const SizedBox(height: 8),
              Text(message, textAlign: TextAlign.center),
              if (onRetry != null) ...[const SizedBox(height: 16), FilledButton(onPressed: onRetry, child: const Text('Retry'))],
            ]),
          ),
        ),
      );
}

class _DocumentsStep extends ConsumerStatefulWidget {
  const _DocumentsStep({required this.token, required this.documents, required this.onChanged});
  final String token;
  final List<OnboardingDocument> documents;
  final ValueChanged<List<OnboardingDocument>> onChanged;

  @override
  ConsumerState<_DocumentsStep> createState() => _DocumentsStepState();
}

class _DocumentsStepState extends ConsumerState<_DocumentsStep> {
  String? _type;
  bool _busy = false;

  String _size(int b) => b < 1024 ? '$b B' : b < 1024 * 1024 ? '${(b / 1024).toStringAsFixed(1)} KB' : '${(b / (1024 * 1024)).toStringAsFixed(1)} MB';

  Future<void> _upload() async {
    final messenger = ScaffoldMessenger.of(context);
    if (_type == null) {
      messenger.showSnackBar(const SnackBar(content: Text('Choose a document type first')));
      return;
    }
    final picked = await FilePicker.pickFiles(type: FileType.custom, allowedExtensions: const ['pdf', 'jpg', 'jpeg', 'png']);
    final file = picked?.files.single;
    if (file == null || file.path == null) return;
    setState(() => _busy = true);
    try {
      final repo = ref.read(publicOnboardingRepositoryProvider);
      final created = await repo.uploadDocument(widget.token, documentType: _type!, path: file.path!, filename: file.name);
      widget.onChanged([...widget.documents, created]);
      if (mounted) setState(() => _type = null);
      messenger.showSnackBar(const SnackBar(content: Text('Document uploaded')));
    } catch (e) {
      messenger.showSnackBar(SnackBar(content: Text('Could not upload: ${e is ApiError ? e.message : 'Something went wrong.'}')));
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  Future<void> _delete(OnboardingDocument d) async {
    final messenger = ScaffoldMessenger.of(context);
    setState(() => _busy = true);
    try {
      await ref.read(publicOnboardingRepositoryProvider).deleteDocument(widget.token, d.id);
      widget.onChanged(widget.documents.where((x) => x.id != d.id).toList());
    } catch (e) {
      messenger.showSnackBar(SnackBar(content: Text('Could not delete: ${e is ApiError ? e.message : 'Something went wrong.'}')));
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final scheme = Theme.of(context).colorScheme;
    return ListView(
      padding: const EdgeInsets.all(16),
      children: [
        Text('Upload your ID and any other requested documents (PDF, JPG or PNG).', style: TextStyle(color: scheme.onSurfaceVariant)),
        const SizedBox(height: 12),
        DropdownButtonFormField<String>(
          value: _type,
          items: [for (final e in onboardingDocumentTypes.entries) DropdownMenuItem(value: e.key, child: Text(e.value))],
          onChanged: _busy ? null : (v) => setState(() => _type = v),
          decoration: const InputDecoration(labelText: 'Document type'),
        ),
        const SizedBox(height: 12),
        FilledButton.icon(
          icon: const Icon(Icons.upload_file),
          label: Text(_busy ? 'Working…' : 'Choose file & upload'),
          onPressed: _busy ? null : _upload,
        ),
        const SizedBox(height: 16),
        if (widget.documents.isEmpty) Text('No documents uploaded yet.', style: TextStyle(color: scheme.onSurfaceVariant)),
        for (final d in widget.documents)
          Card(
            child: ListTile(
              leading: const Icon(Icons.description_outlined),
              title: Text(onboardingDocumentTypes[d.documentType] ?? d.documentType),
              subtitle: Text('${d.originalFilename} · ${_size(d.sizeBytes)} · ${d.status}${d.rejectionReason != null ? '\nRejected: ${d.rejectionReason}' : ''}'),
              isThreeLine: d.rejectionReason != null,
              trailing: IconButton(icon: const Icon(Icons.delete_outline), onPressed: _busy ? null : () => _delete(d)),
            ),
          ),
      ],
    );
  }
}
