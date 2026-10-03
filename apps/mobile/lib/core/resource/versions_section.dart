import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../api/api_client.dart';
import '../api/api_error.dart';
import '../forms/choice_sources.dart';
import '../forms/form_spec.dart';
import '../forms/spec_form_screen.dart';
import '../providers.dart';
import '../../features/auth/state/auth_controller.dart';
import 'resource_config.dart';
import 'resource_screens.dart' show displayValue;

typedef Rec = Map<String, dynamic>;

List<String> _versionChoiceKeys(FormSpec spec) => choiceSourcesOf(spec);

/// The versions of a policy/shift, with the draft workflow — mirrors the web `[id]` pages
/// (`apps/web/src/app/app/attendance-policies/[id]/page.tsx` and siblings):
///
///  * **Create draft** — `POST …/versions` with `{}`; the server seeds it.
///  * **Edit draft** — the full version form, `PATCH …/versions/{id}` with the draft's version.
///  * **Discard draft** — `DELETE …/versions/{id}`.
///  * **Publish** — `POST …/versions/{id}/publish` with an optional reason; published versions
///    are immutable (a correction needs a new draft).
class VersionsSection extends ConsumerStatefulWidget {
  const VersionsSection({super.key, required this.config, required this.parent});

  final ResourceConfig config;
  final Rec parent;

  @override
  ConsumerState<VersionsSection> createState() => _VersionsSectionState();
}

class _VersionsSectionState extends ConsumerState<VersionsSection> {
  bool _loading = true;
  bool _busy = false;
  ApiError? _error;
  List<Rec> _versions = const [];
  Map<String, Map<String, String>> _names = const {};

  VersionsConfig get _v => widget.config.versions!;
  ApiClient get _client => ref.read(apiClientProvider);
  String get _base => '${widget.config.path}/${widget.parent['id']}/versions';

  @override
  void initState() {
    super.initState();
    _load();
    _loadNames();
  }

  Future<void> _loadNames() async {
    final keys = _versionChoiceKeys(_v.spec);
    if (keys.isEmpty) return;
    try {
      final choices = await loadChoices(_client, keys);
      if (mounted) setState(() => _names = {for (final e in choices.entries) e.key: {for (final c in e.value) c.value: c.label}});
    } catch (_) {}
  }

  Future<void> _load() async {
    setState(() {
      _loading = true;
      _error = null;
    });
    try {
      final env = await _client.getList<Rec>(_base, query: PageQuery(perPage: 100), parseItem: (d) => d as Rec);
      final rows = [...env.data]..sort((a, b) => (b['version'] as int).compareTo(a['version'] as int));
      if (mounted) setState(() => _versions = rows);
    } catch (e) {
      if (mounted) setState(() => _error = e is ApiError ? e : ApiError(status: 0, code: 'UNKNOWN_ERROR', message: 'Something went wrong.'));
    } finally {
      if (mounted) setState(() => _loading = false);
    }
  }

  void _toast(String m) => ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(m)));

  String _explain(Object e) {
    if (e is ApiError) {
      if (e.code == 'STALE_RESOURCE') return 'This ${_v.noun} was changed by someone else. Reloading.';
      if (e.status == 403) return "You don't have permission to do that.";
      return e.message;
    }
    return 'Something went wrong.';
  }

  Rec? get _draft {
    for (final v in _versions) {
      if (v['status'] == 'DRAFT') return v;
    }
    return null;
  }

  Rec? get _current {
    for (final v in _versions) {
      if (v['status'] == 'PUBLISHED' && v['effective_to'] == null) return v;
    }
    return null;
  }

  Future<void> _guard(Future<void> Function() action, String success) async {
    setState(() => _busy = true);
    try {
      await action();
      _toast(success);
    } catch (e) {
      _toast(_explain(e));
    } finally {
      if (mounted) setState(() => _busy = false);
      await _load();
    }
  }

  Future<void> _createDraft() async {
    setState(() => _busy = true);
    try {
      final created = await _client.post<Rec>(_base, body: const {}, parse: (d) => d as Rec);
      await _load();
      if (!mounted) return;
      setState(() => _busy = false);
      await _editDraft(created);
    } catch (e) {
      _toast(_explain(e));
      if (mounted) setState(() => _busy = false);
    }
  }

  Future<void> _editDraft(Rec draft) async {
    final saved = await openSpecForm(
      context,
      title: 'Edit draft',
      spec: _v.spec,
      initial: draft,
      loadChoices: _versionChoiceKeys(_v.spec).isEmpty ? null : () => loadChoices(_client, _versionChoiceKeys(_v.spec)),
      onSubmit: (payload, changed) async =>
          _client.patch<Object?>('$_base/${draft['id']}', body: changed, ifMatch: draft['version'].toString(), parse: (_) => null),
    );
    if (saved && mounted) {
      _toast('Draft saved.');
      _load();
    }
  }

  Future<void> _discard(Rec draft) async {
    final yes = await _confirm('Discard draft?', 'The draft and everything you entered in it will be deleted.', 'Discard', destructive: true);
    if (yes) await _guard(() async => _client.delete<Object?>('$_base/${draft['id']}', ifMatch: draft['version'].toString(), parse: (_) => null), 'Draft discarded.');
  }

  Future<void> _publish(Rec draft) async {
    final current = _current;
    final reason = TextEditingController();
    final yes = await showDialog<bool>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: const Text('Publish this draft?'),
        content: Column(mainAxisSize: MainAxisSize.min, crossAxisAlignment: CrossAxisAlignment.start, children: [
          Text(current != null
              ? 'This closes the version currently effective from ${current['effective_from'] ?? '—'} and makes this one effective from ${draft['effective_from'] ?? 'the date set in the draft'}. Published versions are immutable.'
              : 'This makes it live from the effective date set in the draft. Published versions are immutable — a correction requires a new draft.'),
          const SizedBox(height: 12),
          TextField(controller: reason, decoration: const InputDecoration(labelText: 'Reason (optional)')),
        ]),
        actions: [
          TextButton(onPressed: () => Navigator.of(ctx).pop(false), child: const Text('Cancel')),
          FilledButton(onPressed: () => Navigator.of(ctx).pop(true), child: const Text('Publish')),
        ],
      ),
    );
    if (yes != true) return;
    final text = reason.text.trim();
    await _guard(
      () async => _client.post<Object?>('$_base/${draft['id']}/publish', body: {'publish_reason': text.isEmpty ? null : text}, ifMatch: draft['version'].toString(), parse: (_) => null),
      'Published.',
    );
  }

  Future<bool> _confirm(String title, String body, String label, {bool destructive = false}) async {
    final yes = await showDialog<bool>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: Text(title),
        content: Text(body),
        actions: [
          TextButton(onPressed: () => Navigator.of(ctx).pop(false), child: const Text('Cancel')),
          FilledButton(
            style: destructive ? FilledButton.styleFrom(backgroundColor: Theme.of(ctx).colorScheme.error) : null,
            onPressed: () => Navigator.of(ctx).pop(true),
            child: Text(label),
          ),
        ],
      ),
    );
    return yes == true;
  }

  List<Widget> _details(Rec version) {
    final scheme = Theme.of(context).colorScheme;
    final out = <Widget>[];
    for (final f in _v.spec.fields) {
      if (f.kind == FieldKind.hidden) continue;
      if (f.kind == FieldKind.rows) {
        final rows = (version[f.key] as List?)?.cast<Rec>() ?? const <Rec>[];
        out.add(Padding(padding: const EdgeInsets.only(top: 8), child: Text('${f.label} (${rows.length})', style: const TextStyle(fontWeight: FontWeight.w600))));
        for (final r in rows) {
          out.add(Padding(
            padding: const EdgeInsets.only(left: 8, top: 2),
            child: Text(
              [for (final sf in f.rowSpec!.fields) if (sf.kind != FieldKind.hidden && r[sf.key] != null && r[sf.key] != '') '${sf.label}: ${displayValue(sf, r[sf.key], _names)}'].join(' · '),
              style: TextStyle(color: scheme.onSurfaceVariant, fontSize: 13),
            ),
          ));
        }
        continue;
      }
      out.add(Padding(
        padding: const EdgeInsets.symmetric(vertical: 3),
        child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Expanded(flex: 5, child: Text(f.label, style: TextStyle(color: scheme.onSurfaceVariant))),
          Expanded(flex: 4, child: Text(displayValue(f, version[f.key], _names), textAlign: TextAlign.end)),
        ]),
      ));
    }
    if (version['publish_reason'] != null) out.add(Padding(padding: const EdgeInsets.only(top: 8), child: Text('Published: ${version['publish_reason']}')));
    return out;
  }

  @override
  Widget build(BuildContext context) {
    final permissions = ref.watch(authControllerProvider).user?.permissions ?? const <String>[];
    final manage = _v.manage ?? widget.config.manage;
    final canManage = manage == null || permissions.contains(manage);
    final scheme = Theme.of(context).colorScheme;
    final draft = _draft;
    return Container(
      margin: const EdgeInsets.only(top: 16),
      padding: const EdgeInsets.all(14),
      decoration: BoxDecoration(border: Border.all(color: scheme.outlineVariant), borderRadius: BorderRadius.circular(12)),
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Text('Versions', style: Theme.of(context).textTheme.titleSmall),
        const SizedBox(height: 4),
        Text('A published ${_v.noun} is immutable. Make changes in a draft, then publish it.', style: TextStyle(fontSize: 12, color: scheme.onSurfaceVariant)),
        if (canManage)
          Padding(
            padding: const EdgeInsets.only(top: 10),
            child: Wrap(spacing: 8, runSpacing: 8, children: [
              if (draft == null && !_loading) FilledButton.icon(onPressed: _busy ? null : _createDraft, icon: const Icon(Icons.add, size: 18), label: const Text('Create draft')),
              if (draft != null) FilledButton(onPressed: _busy ? null : () => _editDraft(draft), child: const Text('Edit draft')),
              if (draft != null) FilledButton.tonal(onPressed: _busy ? null : () => _publish(draft), child: const Text('Publish')),
              if (draft != null) OutlinedButton(onPressed: _busy ? null : () => _discard(draft), child: const Text('Discard draft')),
            ]),
          ),
        const SizedBox(height: 8),
        if (_loading)
          const Padding(padding: EdgeInsets.all(16), child: Center(child: CircularProgressIndicator()))
        else if (_error != null)
          Column(children: [Text(_error!.message), TextButton(onPressed: _load, child: const Text('Retry'))])
        else if (_versions.isEmpty)
          Text('No versions yet.', style: TextStyle(color: scheme.onSurfaceVariant))
        else
          for (final v in _versions)
            ExpansionTile(
              tilePadding: EdgeInsets.zero,
              childrenPadding: const EdgeInsets.only(bottom: 8),
              title: Row(children: [
                Text('v${v['version']}', style: const TextStyle(fontWeight: FontWeight.w700)),
                const SizedBox(width: 8),
                Chip(
                  label: Text(v['status'] == 'DRAFT' ? 'Draft' : (v['effective_to'] == null ? 'Current' : 'Past')),
                  visualDensity: VisualDensity.compact,
                  backgroundColor: (v['status'] == 'DRAFT' ? Colors.orange : (v['effective_to'] == null ? Colors.green : scheme.onSurfaceVariant)).withValues(alpha: 0.14),
                ),
              ]),
              subtitle: Text([
                '${v['effective_from'] ?? 'no effective date'} → ${v['effective_to'] ?? 'open'}',
                if (_v.summary?.call(v) != null) _v.summary!(v)!,
              ].join('\n')),
              children: _details(v),
            ),
      ]),
    );
  }
}
