import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../core/api/api_error.dart';
import '../../../core/widgets/async_list_screen.dart';
import '../../../core/auth/permissions.dart';
import '../../auth/presentation/widgets/auth_form_field.dart';
import '../../auth/state/auth_controller.dart';
import '../data/onboarding_repository.dart';
import 'onboarding_cases_screen.dart' show onboardingRepositoryProvider;
import '../../../core/widgets/ui.dart';

/// Known role codes — mirrors the roles seeded for every company
/// (`apps/api` RBAC bootstrap). Not fetched from an endpoint since there
/// isn't a "list roles" route; these are the fixed built-in roles.
const _roleCodes = ['COMPANY_ADMIN', 'HR_ADMIN', 'REPORTING_MANAGER', 'BRANCH_MANAGER', 'EMPLOYEE'];

/// Role codes shown as words (`HR_ADMIN` -> `HR admin`).
String roleLabel(String code) => code.replaceAll('_', ' ').toLowerCase().replaceFirstMapped(RegExp(r'^.'), (m) => m[0]!.toUpperCase()).replaceAll('Hr ', 'HR ');

/// HR admin and branch manager (without company admin) see only the branches an admin assigns.
bool needsBranches(Iterable<String> roles) {
  final set = roles.toSet();
  return !set.contains('COMPANY_ADMIN') && (set.contains('HR_ADMIN') || set.contains('BRANCH_MANAGER'));
}

/// Checkbox list of active branches; [selected] is edited in place.
class _BranchPicker extends StatelessWidget {
  const _BranchPicker({required this.branches, required this.selected, required this.onChanged});
  final List<({String id, String name})> branches;
  final Set<String> selected;
  final VoidCallback onChanged;

  @override
  Widget build(BuildContext context) {
    return Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
      const SizedBox(height: 12),
      Text('Branches they cover', style: Theme.of(context).textTheme.titleSmall),
      const Text('Choose at least one. They see and manage only these branches.'),
      if (branches.isEmpty) const Padding(padding: EdgeInsets.only(top: 8), child: Text('No active branches yet.')),
      for (final b in branches)
        CheckboxListTile(
          dense: true,
          contentPadding: EdgeInsets.zero,
          title: Text(b.name),
          value: selected.contains(b.id),
          onChanged: (v) {
            (v ?? false) ? selected.add(b.id) : selected.remove(b.id);
            onChanged();
          },
        ),
    ]);
  }
}

class UsersScreen extends ConsumerStatefulWidget {
  const UsersScreen({super.key});

  @override
  ConsumerState<UsersScreen> createState() => _UsersScreenState();
}

class _UsersScreenState extends ConsumerState<UsersScreen> {
  final _listKey = GlobalKey<AsyncListScreenState<UserSummary>>();

  Future<void> _invite() async {
    final emailController = TextEditingController();
    String roleCode = _roleCodes.last;
    final branchIds = <String>{};
    final branches = await ref.read(onboardingRepositoryProvider).listActiveBranches().catchError((_) => <({String id, String name})>[]);
    if (!mounted) return;
    final created = await showDialog<bool>(
      context: context,
      builder: (context) => StatefulBuilder(
        builder: (context, setState) => AlertDialog(
          title: const Text('Invite user'),
          content: SingleChildScrollView(child: Column(mainAxisSize: MainAxisSize.min, children: [
            AuthFormField(label: 'Email', required: true, child: TextField(controller: emailController, keyboardType: TextInputType.emailAddress)),
            const SizedBox(height: 12),
            AuthFormField(
              label: 'Role',
              child: DropdownButtonFormField<String>(
                value: roleCode,
                items: [for (final r in _roleCodes) DropdownMenuItem(value: r, child: Text(roleLabel(r)))],
                onChanged: (v) => setState(() => roleCode = v ?? roleCode),
              ),
            ),
            if (needsBranches([roleCode])) _BranchPicker(branches: branches, selected: branchIds, onChanged: () => setState(() {})),
          ])),
          actions: [
            TextButton(onPressed: () => Navigator.of(context).pop(false), child: const Text('Cancel')),
            FilledButton(
              onPressed: () async {
                if (emailController.text.trim().isEmpty) return;
                final restricted = needsBranches([roleCode]);
                if (restricted && branchIds.isEmpty) {
                  ScaffoldMessenger.of(context).showSnackBar(const SnackBar(content: Text('Choose at least one branch for this role.')));
                  return;
                }
                try {
                  await ref.read(onboardingRepositoryProvider).inviteUser(
                        email: emailController.text.trim(),
                        roleCode: roleCode,
                        branchIds: restricted ? branchIds.toList() : const [],
                      );
                  if (context.mounted) Navigator.of(context).pop(true);
                } catch (error) {
                  if (context.mounted) {
                    ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(error is ApiError ? describeApiError(error) : 'Something went wrong.')));
                  }
                }
              },
              child: const Text('Invite'),
            ),
          ],
        ),
      ),
    );
    if (created == true) _listKey.currentState?.reload();
  }

  Future<void> _editRoles(UserSummary user) async {
    final selected = Set<String>.from(user.roleCodes);
    final branchIds = Set<String>.from(user.branchIds);
    final branches = await ref.read(onboardingRepositoryProvider).listActiveBranches().catchError((_) => <({String id, String name})>[]);
    if (!mounted) return;
    final changed = await showDialog<bool>(
      context: context,
      builder: (context) => StatefulBuilder(
        builder: (context, setState) => AlertDialog(
          title: Text(user.emailLabel),
          content: SingleChildScrollView(child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              for (final role in _roleCodes)
                CheckboxListTile(
                  title: Text(roleLabel(role)),
                  value: selected.contains(role),
                  onChanged: (v) => setState(() => (v ?? false) ? selected.add(role) : selected.remove(role)),
                ),
              if (needsBranches(selected)) _BranchPicker(branches: branches, selected: branchIds, onChanged: () => setState(() {})),
            ],
          )),
          actions: [
            TextButton(onPressed: () => Navigator.of(context).pop(false), child: const Text('Cancel')),
            FilledButton(
              onPressed: () async {
                final restricted = needsBranches(selected);
                if (restricted && branchIds.isEmpty) {
                  ScaffoldMessenger.of(context).showSnackBar(const SnackBar(content: Text('Choose at least one branch for this role.')));
                  return;
                }
                try {
                  await ref.read(onboardingRepositoryProvider).updateUserRoles(user.userId, selected.toList(), branchIds: restricted ? branchIds.toList() : const []);
                  if (context.mounted) Navigator.of(context).pop(true);
                } catch (error) {
                  if (context.mounted) {
                    ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(error is ApiError ? describeApiError(error) : 'Something went wrong.')));
                  }
                }
              },
              child: const Text('Save'),
            ),
          ],
        ),
      ),
    );
    if (changed == true) _listKey.currentState?.reload();
  }

  @override
  Widget build(BuildContext context) {
    final permissions = ref.watch(authControllerProvider).user?.permissions ?? const <String>[];
    final canInvite = permissions.contains(settingsUserManage);
    final canManageRoles = permissions.contains(settingsRoleManage);
    return AsyncListScreen<UserSummary>(
      key: _listKey,
      title: 'Users',
      fetch: () => ref.read(onboardingRepositoryProvider).listUsers(),
      createLabel: 'Invite user',
      onCreate: canInvite ? _invite : null,
      emptyLabel: 'No users yet.',
      itemBuilder: (context, user) {
        final name = [user.firstName, user.lastName].where((s) => s != null && s.isNotEmpty).join(' ').trim();
        final display = name.isEmpty ? user.emailLabel : name;
        return ListRowCard(
          title: display,
          subtitle: [
            user.emailLabel,
            user.roleCodes.isEmpty ? 'No roles' : user.roleCodes.map(roleLabel).join(', '),
            if (needsBranches(user.roleCodes)) user.branchIds.isEmpty ? 'No branches' : '${user.branchIds.length} branch${user.branchIds.length == 1 ? '' : 'es'}',
          ].join(' · '),
          leading: InitialsAvatar(name: display),
          onTap: canManageRoles ? () => _editRoles(user) : null,
        );
      },
    );
  }
}
