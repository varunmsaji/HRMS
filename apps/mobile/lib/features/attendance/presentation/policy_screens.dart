import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../core/api/api_error.dart';
import '../../../core/providers.dart';
import '../../../core/widgets/async_list_screen.dart';
import '../../auth/presentation/widgets/auth_form_field.dart';
import '../data/policy_repository.dart';

/// Generic list+detail+publish UI shared by Attendance/Overtime/
/// Regularization Policies — identical shape (identity + versions +
/// publish/discard) across all three, per
/// `apps/api/src/hrms/modules/attendance/{router,schemas}.py`. Each kind
/// only differs in what a *new version*'s fields are, so version creation is
/// injected via [versionFormBuilder] rather than built in here.
class PolicyListScreen extends ConsumerStatefulWidget {
  const PolicyListScreen({
    super.key,
    required this.title,
    required this.basePath,
    required this.versionFormBuilder,
  });

  final String title;
  final String basePath;
  final Widget Function(BuildContext context, PolicyRepository repository, String policyId) versionFormBuilder;

  @override
  ConsumerState<PolicyListScreen> createState() => _PolicyListScreenState();
}

class _PolicyListScreenState extends ConsumerState<PolicyListScreen> {
  late final _repository = PolicyRepository(ref.read(apiClientProvider), widget.basePath);
  final _listKey = GlobalKey<AsyncListScreenState<PolicyIdentity>>();

  Future<void> _create() async {
    final nameController = TextEditingController();
    final codeController = TextEditingController();
    final created = await showDialog<bool>(
      context: context,
      builder: (context) => AlertDialog(
        title: Text('New ${widget.title.toLowerCase()}'),
        content: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            AuthFormField(label: 'Name', required: true, child: TextField(controller: nameController)),
            const SizedBox(height: 12),
            AuthFormField(label: 'Code', description: 'Optional', child: TextField(controller: codeController)),
          ],
        ),
        actions: [
          TextButton(onPressed: () => Navigator.of(context).pop(false), child: const Text('Cancel')),
          FilledButton(
            onPressed: () async {
              if (nameController.text.trim().isEmpty) return;
              try {
                await _repository.createPolicy(name: nameController.text.trim(), code: codeController.text.trim());
                if (context.mounted) Navigator.of(context).pop(true);
              } catch (error) {
                if (context.mounted) {
                  ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(error is ApiError ? error.message : 'Something went wrong.')));
                }
              }
            },
            child: const Text('Create'),
          ),
        ],
      ),
    );
    if (created == true) _listKey.currentState?.reload();
  }

  @override
  Widget build(BuildContext context) {
    return AsyncListScreen<PolicyIdentity>(
      key: _listKey,
      title: widget.title,
      fetch: _repository.listPolicies,
      createLabel: 'New policy',
      onCreate: _create,
      emptyLabel: 'No policies yet.',
      itemBuilder: (context, policy) => ListTile(
        title: Text(policy.name),
        subtitle: Text([if (policy.code != null) policy.code!, if (!policy.isActive) 'Inactive'].join(' · ')),
        trailing: const Icon(Icons.chevron_right, size: 20),
        onTap: () async {
          await Navigator.of(context).push(
            MaterialPageRoute(
              builder: (_) => PolicyDetailScreen(
                title: policy.name,
                repository: _repository,
                policyId: policy.id,
                versionFormBuilder: widget.versionFormBuilder,
              ),
            ),
          );
        },
      ),
    );
  }
}

class PolicyDetailScreen extends StatefulWidget {
  const PolicyDetailScreen({
    super.key,
    required this.title,
    required this.repository,
    required this.policyId,
    required this.versionFormBuilder,
  });

  final String title;
  final PolicyRepository repository;
  final String policyId;
  final Widget Function(BuildContext context, PolicyRepository repository, String policyId) versionFormBuilder;

  @override
  State<PolicyDetailScreen> createState() => _PolicyDetailScreenState();
}

class _PolicyDetailScreenState extends State<PolicyDetailScreen> {
  bool _loading = true;
  List<PolicyVersion> _versions = const [];
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
    try {
      final versions = await widget.repository.listVersions(widget.policyId);
      versions.sort((a, b) => b.versionNumber.compareTo(a.versionNumber));
      if (mounted) setState(() => _versions = versions);
    } catch (error) {
      if (mounted) setState(() => _error = error is ApiError ? error : ApiError(status: 0, code: 'UNKNOWN_ERROR', message: 'Something went wrong.'));
    } finally {
      if (mounted) setState(() => _loading = false);
    }
  }

  Future<void> _publish(PolicyVersion version) async {
    try {
      await widget.repository.publishVersion(widget.policyId, version.id, ifMatch: version.versionNumber.toString());
      _load();
    } catch (error) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(error is ApiError ? error.message : 'Something went wrong.')));
      }
    }
  }

  Future<void> _newDraft() async {
    final created = await Navigator.of(context).push<bool>(
      MaterialPageRoute(builder: (context) => widget.versionFormBuilder(context, widget.repository, widget.policyId)),
    );
    if (created == true) _load();
  }

  @override
  Widget build(BuildContext context) {
    Widget body;
    if (_loading) {
      body = const Center(child: CircularProgressIndicator());
    } else if (_error != null) {
      body = Center(
        child: Padding(
          padding: const EdgeInsets.all(24),
          child: Column(mainAxisSize: MainAxisSize.min, children: [
            Text(_error!.message, textAlign: TextAlign.center),
            const SizedBox(height: 16),
            FilledButton(onPressed: _load, child: const Text('Retry')),
          ]),
        ),
      );
    } else if (_versions.isEmpty) {
      body = const Center(child: Padding(padding: EdgeInsets.all(24), child: Text('No versions yet.')));
    } else {
      body = RefreshIndicator(
        onRefresh: _load,
        child: ListView.separated(
          padding: const EdgeInsets.all(16),
          itemCount: _versions.length,
          separatorBuilder: (_, __) => const SizedBox(height: 12),
          itemBuilder: (context, index) => _VersionCard(version: _versions[index], onPublish: () => _publish(_versions[index])),
        ),
      );
    }

    return Scaffold(
      appBar: AppBar(title: Text(widget.title)),
      body: body,
      floatingActionButton: FloatingActionButton.extended(onPressed: _newDraft, icon: const Icon(Icons.add), label: const Text('New draft')),
    );
  }
}

class _VersionCard extends StatelessWidget {
  const _VersionCard({required this.version, required this.onPublish});
  final PolicyVersion version;
  final VoidCallback onPublish;

  @override
  Widget build(BuildContext context) {
    final scheme = Theme.of(context).colorScheme;
    final fields = version.raw.entries.where((e) =>
        !['id', 'company_id', 'policy_id', 'status', 'version', 'created_at', 'updated_at'].contains(e.key) &&
        e.value != null &&
        e.value is! List &&
        e.value is! Map);
    return Container(
      padding: const EdgeInsets.all(16),
      decoration: BoxDecoration(color: scheme.surfaceContainerLowest, borderRadius: BorderRadius.circular(12), border: Border.all(color: scheme.outlineVariant)),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Container(
                padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 2),
                decoration: BoxDecoration(
                  color: version.isDraft ? scheme.secondaryContainer : scheme.primaryContainer.withValues(alpha: 0.3),
                  borderRadius: BorderRadius.circular(4),
                ),
                child: Text(version.status, style: const TextStyle(fontSize: 11, fontWeight: FontWeight.w600)),
              ),
              const SizedBox(width: 8),
              Text('v${version.versionNumber}', style: TextStyle(color: scheme.onSurfaceVariant)),
              const Spacer(),
              if (version.isDraft) TextButton(onPressed: onPublish, child: const Text('Publish')),
            ],
          ),
          if (version.effectiveFrom != null) Padding(padding: const EdgeInsets.only(top: 4), child: Text('Effective from ${version.effectiveFrom}')),
          const Divider(height: 20),
          for (final field in fields)
            Padding(
              padding: const EdgeInsets.symmetric(vertical: 3),
              child: Row(
                mainAxisAlignment: MainAxisAlignment.spaceBetween,
                children: [
                  Expanded(child: Text(field.key.replaceAll('_', ' '), style: TextStyle(color: scheme.onSurfaceVariant, fontSize: 13))),
                  Text('${field.value}', style: const TextStyle(fontSize: 13)),
                ],
              ),
            ),
        ],
      ),
    );
  }
}
