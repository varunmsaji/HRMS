import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../api/api_client.dart';
import '../api/api_error.dart';
import '../forms/choice_sources.dart';
import '../forms/form_spec.dart';
import '../forms/spec_form_screen.dart';
import '../providers.dart';
import '../../features/auth/state/auth_controller.dart';
import '../../features/shell/more_action.dart';
import '../theme/employee_theme_scope.dart';
import '../widgets/ui.dart';
import 'resource_config.dart';
import 'versions_section.dart';

typedef Rec = Map<String, dynamic>;

List<String> _choiceKeys(FormSpec spec) => choiceSourcesOf(spec);

/// A record's value as text, resolving select labels and choice ids to names.
String displayValue(FieldSpec f, dynamic raw, Map<String, Map<String, String>> names) {
  if (raw == null || (raw is String && raw.trim().isEmpty) || (raw is List && raw.isEmpty)) return '—';
  switch (f.kind) {
    case FieldKind.toggle:
      return raw == true ? 'Yes' : 'No';
    case FieldKind.money:
      return raw is num ? (raw / 100).toStringAsFixed(2) : raw.toString();
    case FieldKind.select:
      return f.optionLabels[raw.toString()] ?? prettyEnum(raw.toString());
    case FieldKind.choice:
      return names[f.choiceKey]?[raw.toString()] ?? raw.toString();
    case FieldKind.multiChoice:
      return (raw as List).map((v) => names[f.choiceKey]?[v.toString()] ?? v.toString()).join(', ');
    default:
      return raw.toString();
  }
}

/// One line per row of a `FieldKind.rows` value: `Label: value · Label: value`.
List<String> rowLines(FieldSpec f, dynamic raw, Map<String, Map<String, String>> names) {
  final rows = (raw is List ? raw : const []).whereType<Map>().toList();
  return [
    for (final r in rows)
      [
        for (final sf in f.rowSpec!.fields)
          if (sf.kind != FieldKind.hidden && r[sf.key] != null && r[sf.key] != '') '${sf.label}: ${displayValue(sf, r[sf.key], names)}',
      ].join(' · '),
  ];
}

/// Mirrors the web list pages (`apps/web/src/app/app/<resource>/page.tsx`): every record, an
/// active/inactive badge, and a create form for users who may manage the resource.
class ResourceListScreen extends ConsumerStatefulWidget {
  const ResourceListScreen({super.key, required this.config, this.createScreen});
  final ResourceConfig config;

  /// A purpose-built create screen (templates, one-step publish) used instead of the generic form.
  /// It pops `true` once something was saved.
  final Widget Function()? createScreen;

  @override
  ConsumerState<ResourceListScreen> createState() => _ResourceListScreenState();
}

class _ResourceListScreenState extends ConsumerState<ResourceListScreen> {
  bool _loading = true;
  ApiError? _error;
  List<Rec> _rows = const [];
  bool _showInactive = false;

  ResourceConfig get _c => widget.config;
  ApiClient get _client => ref.read(apiClientProvider);

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
    try {
      final rows = <Rec>[];
      for (var page = 1; page <= 20; page++) {
        final env = await _client.getList<Rec>(_c.path, query: PageQuery(page: page, perPage: 100), filters: _c.listFilters, parseItem: (d) => d as Rec);
        rows.addAll(env.data);
        if (!(env.pagination?.hasNext ?? false)) break;
      }
      if (mounted) setState(() => _rows = rows);
    } catch (e) {
      if (mounted) setState(() => _error = e is ApiError ? e : ApiError(status: 0, code: 'UNKNOWN_ERROR', message: 'Something went wrong.'));
    } finally {
      if (mounted) setState(() => _loading = false);
    }
  }

  Future<void> _create() async {
    final custom = widget.createScreen;
    if (custom != null) {
      final saved = await pushKeepingTheme<bool>(context, (_) => custom());
      if (saved == true && mounted) _load();
      return;
    }
    final saved = await openSpecForm(
      context,
      title: 'New ${_c.singular.toLowerCase()}',
      spec: _c.spec,
      loadChoices: _choiceKeys(_c.spec).isEmpty ? null : () => loadChoices(_client, _choiceKeys(_c.spec)),
      onSubmit: (payload, _) async => _client.post<Object?>(_c.path, body: payload, parse: (_) => null),
    );
    if (saved && mounted) {
      ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text('${_c.singular} created.')));
      _load();
    }
  }

  @override
  Widget build(BuildContext context) {
    final permissions = ref.watch(authControllerProvider).user?.permissions ?? const <String>[];
    final canManage = _c.manage == null || permissions.contains(_c.manage);
    final visible = _rows.where((r) => !_c.hasActive || _showInactive || r['is_active'] != false).toList();
    final inactiveCount = _rows.where((r) => r['is_active'] == false).length;
    return Scaffold(
      appBar: AppBar(title: Text(_c.title), actions: [if (canManage && _c.listActions != null) ..._c.listActions!(context, _rows, _load), const MoreAction()]),
      floatingActionButton: canManage ? FloatingActionButton.extended(onPressed: _create, icon: const Icon(Icons.add), label: Text('New ${_c.singular.toLowerCase()}')) : null,
      body: _loading
          ? const ListSkeleton()
          : _error != null
              ? StateMessage(
                  icon: _error!.status == 403 ? Icons.lock_outline_rounded : Icons.cloud_off_rounded,
                  tone: _error!.status == 403 ? Tone.warning : Tone.danger,
                  title: _error!.status == 403 ? 'No access' : 'Couldn\'t load this',
                  message: _error!.status == 403 ? 'You do not have permission to view ${_c.title.toLowerCase()}.' : _error!.message,
                  actionLabel: _error!.status == 403 ? null : 'Try again',
                  onAction: _load,
                )
              : RefreshIndicator(
                  onRefresh: _load,
                  child: visible.isEmpty
                      ? ListView(children: [
                          if (_c.listHeader != null) Padding(padding: const EdgeInsets.fromLTRB(16, 4, 16, 0), child: _c.listHeader!(context)),
                          SizedBox(
                            height: MediaQuery.sizeOf(context).height * 0.6,
                            child: StateMessage(
                              icon: Icons.inbox_outlined,
                              title: _c.emptyLabel ?? 'No ${_c.title.toLowerCase()} yet',
                              message: canManage ? 'Tap "New ${_c.singular.toLowerCase()}" to add the first one.' : null,
                            ),
                          ),
                        ])
                      : ListView(
                          padding: const EdgeInsets.fromLTRB(16, 4, 16, 96),
                          children: [
                            if (_c.listHeader != null) _c.listHeader!(context),
                            if (_c.hasActive && inactiveCount > 0)
                              Padding(
                                padding: const EdgeInsets.only(bottom: 10),
                                child: AppCard(
                                  padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 2),
                                  child: SwitchListTile(
                                    dense: true,
                                    contentPadding: EdgeInsets.zero,
                                    title: Text('Show inactive ($inactiveCount)'),
                                    value: _showInactive,
                                    onChanged: (v) => setState(() => _showInactive = v),
                                  ),
                                ),
                              ),
                            for (final row in visible)
                              Padding(
                                padding: const EdgeInsets.only(bottom: 10),
                                child: ListRowCard(
                                  title: _c.rowTitle(row),
                                  subtitle: _c.rowSubtitle == null ? null : _c.rowSubtitle!(row),
                                  leading: IconBadge(
                                    icon: Icons.folder_outlined,
                                    tone: _c.hasActive && row['is_active'] == false ? Tone.neutral : Tone.accent,
                                  ),
                                  trailing: _c.hasActive && row['is_active'] == false ? const StatusChip(label: 'Inactive') : null,
                                  onTap: () async {
                                    await Navigator.of(context).push(MaterialPageRoute(builder: (_) => ResourceDetailScreen(config: _c, initial: row)));
                                    _load();
                                  },
                                ),
                              ),
                          ],
                        ),
                ),
    );
  }
}

/// One record — mirrors the web `[id]` pages: the fields, Edit (PATCH with the record's version),
/// Deactivate/Reactivate, and any sub-resources the config adds.
class ResourceDetailScreen extends ConsumerStatefulWidget {
  const ResourceDetailScreen({super.key, required this.config, required this.initial});
  final ResourceConfig config;
  final Rec initial;

  @override
  ConsumerState<ResourceDetailScreen> createState() => _ResourceDetailScreenState();
}

class _ResourceDetailScreenState extends ConsumerState<ResourceDetailScreen> {
  late Rec _row = widget.initial;
  Map<String, Map<String, String>> _names = const {};
  bool _busy = false;

  ResourceConfig get _c => widget.config;
  ApiClient get _client => ref.read(apiClientProvider);
  String get _url => '${_c.path}/${_row['id']}';

  @override
  void initState() {
    super.initState();
    _loadNames();
    _reload();
  }

  Future<void> _loadNames() async {
    final keys = _choiceKeys(_c.spec);
    if (keys.isEmpty) return;
    try {
      final choices = await loadChoices(_client, keys);
      if (mounted) setState(() => _names = {for (final e in choices.entries) e.key: {for (final c in e.value) c.value: c.label}});
    } catch (_) {}
  }

  Future<void> _reload() async {
    try {
      final latest = await _client.get<Rec>(_url, parse: (d) => d as Rec);
      if (mounted) setState(() => _row = latest);
    } catch (_) {}
  }

  void _toast(String m) => ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(m)));

  String _explain(Object e) {
    if (e is ApiError) {
      if (e.code == 'STALE_RESOURCE') return 'This ${_c.singular.toLowerCase()} was changed by someone else. Reload and try again.';
      if (e.status == 403) return "You don't have permission to do that.";
      return e.message;
    }
    return 'Something went wrong.';
  }

  Future<void> _edit() async {
    final saved = await openSpecForm(
      context,
      title: 'Edit ${_c.singular.toLowerCase()}',
      spec: _c.spec,
      initial: _row,
      loadChoices: _choiceKeys(_c.spec).isEmpty ? null : () => loadChoices(_client, _choiceKeys(_c.spec)),
      onSubmit: (payload, changed) async {
        final reviewed = await _c.reviewEdit?.call(context, _row, changed);
        if (reviewed == false) throw const SubmitCancelled();
        if (reviewed == true) return _reload();
        final updated = await _client.patch<Rec>(_url, body: changed, ifMatch: _row['version'].toString(), parse: (d) => d as Rec);
        if (mounted) setState(() => _row = updated);
      },
    );
    if (saved && mounted) _toast('${_c.singular} saved.');
  }

  Future<void> _hardDelete() async {
    final yes = await showDialog<bool>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: Text('Delete ${_c.singular.toLowerCase()}?'),
        content: const Text('This cannot be undone.'),
        actions: [
          TextButton(onPressed: () => Navigator.of(ctx).pop(false), child: const Text('Cancel')),
          FilledButton(style: FilledButton.styleFrom(backgroundColor: Theme.of(ctx).colorScheme.error), onPressed: () => Navigator.of(ctx).pop(true), child: const Text('Delete')),
        ],
      ),
    );
    if (yes != true) return;
    setState(() => _busy = true);
    try {
      await _client.delete<Object?>(_url, ifMatch: _row['version']?.toString(), parse: (_) => null);
      if (mounted) {
        _toast('${_c.singular} deleted.');
        Navigator.of(context).pop();
      }
    } catch (e) {
      _toast(_explain(e));
      if (mounted) setState(() => _busy = false);
    }
  }

  Future<void> _guardedDelete() async {
    final result = await _c.guardedDelete!(context, _row);
    if (!mounted || result == null) return;
    if (result) {
      _toast('${_c.singular} deleted.');
      Navigator.of(context).pop();
    } else {
      _toast('This ${_c.singular.toLowerCase()} was changed by someone else. It has been reloaded.');
      _reload();
    }
  }

  Future<void> _toggleActive() async {
    final deactivating = _row['is_active'] != false;
    final yes = await showDialog<bool>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: Text(deactivating ? 'Deactivate ${_c.singular.toLowerCase()}?' : 'Reactivate ${_c.singular.toLowerCase()}?'),
        content: Text(deactivating ? 'It will no longer be offered for new use. You can reactivate it later.' : 'It will be available again.'),
        actions: [
          TextButton(onPressed: () => Navigator.of(ctx).pop(false), child: const Text('Cancel')),
          FilledButton(
            style: deactivating ? FilledButton.styleFrom(backgroundColor: Theme.of(ctx).colorScheme.error) : null,
            onPressed: () => Navigator.of(ctx).pop(true),
            child: Text(deactivating ? 'Deactivate' : 'Reactivate'),
          ),
        ],
      ),
    );
    if (yes != true) return;
    setState(() => _busy = true);
    try {
      final version = _row['version'].toString();
      final updated = deactivating
          ? await _client.delete<Rec>(_url, ifMatch: version, parse: (d) => d as Rec)
          : await _client.patch<Rec>(_url, body: {'is_active': true}, ifMatch: version, parse: (d) => d as Rec);
      if (mounted) setState(() => _row = updated);
      _toast(deactivating ? '${_c.singular} deactivated.' : '${_c.singular} reactivated.');
    } catch (e) {
      _toast(_explain(e));
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final permissions = ref.watch(authControllerProvider).user?.permissions ?? const <String>[];
    final canManage = _c.manage == null || permissions.contains(_c.manage);
    final scheme = Theme.of(context).colorScheme;
    final active = _row['is_active'] != false;
    return Scaffold(
      appBar: AppBar(title: Text(_c.rowTitle(_row))),
      body: RefreshIndicator(
        onRefresh: _reload,
        child: ListView(
          padding: const EdgeInsets.all(16),
          children: [
            if (_c.hasActive)
              Align(
                alignment: Alignment.centerLeft,
                child: Chip(
                  label: Text(active ? 'Active' : 'Inactive'),
                  backgroundColor: (active ? Colors.green : scheme.onSurfaceVariant).withValues(alpha: 0.12),
                  visualDensity: VisualDensity.compact,
                ),
              ),
            if (canManage)
              Padding(
                padding: const EdgeInsets.only(top: 8, bottom: 8),
                child: Wrap(spacing: 8, runSpacing: 8, children: [
                  if (_c.editable) FilledButton.icon(icon: const Icon(Icons.edit_outlined), label: const Text('Edit'), onPressed: _busy ? null : _edit),
                  if (_c.hardDelete) OutlinedButton(style: OutlinedButton.styleFrom(foregroundColor: Theme.of(context).colorScheme.error), onPressed: _busy ? null : _hardDelete, child: const Text('Delete')),
                  if (_c.hasActive && _c.canDeactivate) OutlinedButton(onPressed: _busy ? null : _toggleActive, child: Text(active ? 'Deactivate' : 'Reactivate')),
                  if (_c.guardedDelete != null) OutlinedButton(style: OutlinedButton.styleFrom(foregroundColor: Theme.of(context).colorScheme.error), onPressed: _busy ? null : _guardedDelete, child: const Text('Delete')),
                ]),
              ),
            Container(
              padding: const EdgeInsets.all(14),
              decoration: BoxDecoration(border: Border.all(color: scheme.outlineVariant), borderRadius: BorderRadius.circular(12)),
              child: Column(children: [
                for (final f in _c.spec.fields)
                  if (f.kind == FieldKind.rows)
                    Padding(
                      padding: const EdgeInsets.symmetric(vertical: 6),
                      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                        Text('${f.label} (${rowLines(f, _row[f.key], _names).length})', style: const TextStyle(fontWeight: FontWeight.w600)),
                        for (final line in rowLines(f, _row[f.key], _names)) Padding(padding: const EdgeInsets.only(left: 8, top: 2), child: Text(line, style: TextStyle(color: scheme.onSurfaceVariant, fontSize: 13))),
                      ]),
                    )
                  else if (f.kind != FieldKind.hidden && !f.editOnly)
                    Padding(
                      padding: const EdgeInsets.symmetric(vertical: 5),
                      child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
                        Expanded(flex: 4, child: Text(f.label, style: TextStyle(color: scheme.onSurfaceVariant))),
                        Expanded(flex: 5, child: Text(displayValue(f, _row[f.key], _names), textAlign: TextAlign.end)),
                      ]),
                    ),
              ]),
            ),
            if (_c.detailExtras != null) _c.detailExtras!(context, _row, _reload),
            if (_c.versions != null) VersionsSection(config: _c, parent: _row),
          ],
        ),
      ),
    );
  }
}
