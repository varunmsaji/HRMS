import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../core/api/api_error.dart';
import '../../../core/widgets/async_list_screen.dart';
import '../../auth/presentation/widgets/auth_form_field.dart';
import '../data/onboarding_repository.dart';
import 'onboarding_cases_screen.dart' show onboardingRepositoryProvider;

/// Known role codes — mirrors the roles seeded for every company
/// (`apps/api` RBAC bootstrap). Not fetched from an endpoint since there
/// isn't a "list roles" route; these are the fixed built-in roles.
const _roleCodes = ['COMPANY_ADMIN', 'HR_ADMIN', 'REPORTING_MANAGER', 'EMPLOYEE'];

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
    final created = await showDialog<bool>(
      context: context,
      builder: (context) => StatefulBuilder(
        builder: (context, setState) => AlertDialog(
          title: const Text('Invite user'),
          content: Column(mainAxisSize: MainAxisSize.min, children: [
            AuthFormField(label: 'Email', required: true, child: TextField(controller: emailController, keyboardType: TextInputType.emailAddress)),
            const SizedBox(height: 12),
            AuthFormField(
              label: 'Role',
              child: DropdownButtonFormField<String>(
                value: roleCode,
                items: [for (final r in _roleCodes) DropdownMenuItem(value: r, child: Text(r.replaceAll('_', ' ')))],
                onChanged: (v) => setState(() => roleCode = v ?? roleCode),
              ),
            ),
          ]),
          actions: [
            TextButton(onPressed: () => Navigator.of(context).pop(false), child: const Text('Cancel')),
            FilledButton(
              onPressed: () async {
                if (emailController.text.trim().isEmpty) return;
                try {
                  await ref.read(onboardingRepositoryProvider).inviteUser(email: emailController.text.trim(), roleCode: roleCode);
                  if (context.mounted) Navigator.of(context).pop(true);
                } catch (error) {
                  if (context.mounted) {
                    ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(error is ApiError ? error.message : 'Something went wrong.')));
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
    final changed = await showDialog<bool>(
      context: context,
      builder: (context) => StatefulBuilder(
        builder: (context, setState) => AlertDialog(
          title: Text(user.emailLabel),
          content: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              for (final role in _roleCodes)
                CheckboxListTile(
                  title: Text(role.replaceAll('_', ' ')),
                  value: selected.contains(role),
                  onChanged: (v) => setState(() => (v ?? false) ? selected.add(role) : selected.remove(role)),
                ),
            ],
          ),
          actions: [
            TextButton(onPressed: () => Navigator.of(context).pop(false), child: const Text('Cancel')),
            FilledButton(
              onPressed: () async {
                try {
                  await ref.read(onboardingRepositoryProvider).updateUserRoles(user.userId, selected.toList());
                  if (context.mounted) Navigator.of(context).pop(true);
                } catch (error) {
                  if (context.mounted) {
                    ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(error is ApiError ? error.message : 'Something went wrong.')));
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
    return AsyncListScreen<UserSummary>(
      key: _listKey,
      title: 'Users',
      fetch: () => ref.read(onboardingRepositoryProvider).listUsers(),
      createLabel: 'Invite user',
      onCreate: _invite,
      emptyLabel: 'No users yet.',
      itemBuilder: (context, user) => ListTile(
        title: Text([user.firstName, user.lastName].where((s) => s != null && s.isNotEmpty).join(' ').trim().isEmpty ? user.emailLabel : '${user.firstName ?? ''} ${user.lastName ?? ''}'.trim()),
        subtitle: Text([user.emailLabel, user.roleCodes.join(', ')].join(' · ')),
        onTap: () => _editRoles(user),
      ),
    );
  }
}
